#!/usr/bin/env python3
"""Poll Salesforce Agentforce Session Trace OTel API and forward to OTel Collector.

Architecture (demo):
  Agentforce session
    -> Data 360 Session Tracing
    -> GET /services/data/v66.0/einstein/audit/otel/{sessionId}  (OTLP JSON)
    -> this poller (JSON -> Protobuf)
    -> OTel Collector :4318/v1/traces
    -> Databricks Zerobus Ingest
    -> Unity Catalog Delta tables (VARIANT)

Salesforce does NOT push OTLP outbound today — polling is required (beta API).
Zerobus rejects application/json — Protobuf conversion is mandatory.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from json_to_otlp import span_count, to_export_trace_request_bytes

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path.home() / ".vibe" / "salesforce-otel" / "demo.env")

API_VERSION = os.environ.get("SALESFORCE_API_VERSION", "v66.0").strip() or "v66.0"
WINDOW_DAYS = int(os.environ.get("DISCOVERY_WINDOW_DAYS", "3") or "3")
DISCOVERY_LIMIT = int(os.environ.get("DISCOVERY_LIMIT", "20") or "20")
IDLE_SECONDS = int(os.environ.get("SESSION_IDLE_SECONDS", "120") or "120")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60") or "60")
MAX_PASSES = int(os.environ.get("MAX_PASSES", "1") or "1")
EXPORTED_FILE = Path(
    os.environ.get("EXPORTED_FILE", str(ROOT / ".agentforce-exported.json"))
)


class HttpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} in .env or ~/.vibe/salesforce-otel/demo.env")
    return value


def dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def http_json(method: str, url: str, headers: dict | None = None, **kwargs):
    response = requests.request(method, url, headers=headers or {}, timeout=120, **kwargs)
    if not response.ok:
        if response.text:
            print(response.text[:1000])
        raise HttpError(response.status_code, f"{method} {url} failed: HTTP {response.status_code}")
    if not response.content:
        return {}
    return response.json()


def salesforce_token(instance: str) -> str:
    """Prefer External Client App client_credentials; fall back to sf CLI session."""
    client_id = os.environ.get("SALESFORCE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SALESFORCE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        payload = http_json(
            "POST",
            f"{instance}/services/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        token = payload.get("access_token")
        if not token:
            raise SystemExit("no access_token from Salesforce client_credentials")
        return str(token)

    # Fallback: reuse sf CLI auth (orgfarm918)
    alias = os.environ.get("SALESFORCE_ALIAS", "orgfarm918").strip() or "orgfarm918"
    import subprocess

    out = subprocess.check_output(
        ["sf", "org", "display", "-o", alias, "--json"],
        text=True,
    )
    # sf may print warnings before JSON
    start = out.find("{")
    data = json.loads(out[start:])
    token = data.get("result", {}).get("accessToken")
    if not token:
        raise SystemExit(
            "No SALESFORCE_CLIENT_ID/SECRET and sf org display returned no accessToken. "
            "Create an External Client App or run: sf org login web -a orgfarm918"
        )
    print(f"Using sf CLI session token for alias={alias}")
    return str(token)


def discovery_soql(window_days: int, limit: int) -> str:
    where = ""
    if window_days > 0:
        where = f"WHERE ssot__StartTimestamp__c = LAST_N_DAYS:{window_days} "
    return (
        "SELECT ssot__Id__c, ssot__StartTimestamp__c, ssot__EndTimestamp__c "
        "FROM ssot__AiAgentSession__dlm "
        f"{where}"
        "ORDER BY ssot__StartTimestamp__c DESC NULLS LAST "
        f"LIMIT {limit}"
    )


def discover_sessions(instance: str, headers: dict) -> list[dict]:
    query = http_json(
        "GET",
        f"{instance}/services/data/{API_VERSION}/query/",
        headers,
        params={"q": discovery_soql(WINDOW_DAYS, DISCOVERY_LIMIT)},
    )
    records = query.get("records")
    if not isinstance(records, list):
        return []
    return [r for r in records if isinstance(r, dict) and r.get("ssot__Id__c")]


def fetch_otel(instance: str, headers: dict, session_id: str) -> dict:
    payload = http_json(
        "GET",
        f"{instance}/services/data/{API_VERSION}/einstein/audit/otel/{quote(session_id, safe='')}",
        {**headers, "Accept": "application/json"},
    )
    if not isinstance(payload, dict):
        raise SystemExit(f"OTel response for {session_id} was not an object")
    return payload


def latest_span_end_unix(payload: dict) -> int:
    latest = 0
    for rs in payload.get("resourceSpans") or payload.get("resource_spans") or []:
        for scope in rs.get("scopeSpans") or rs.get("scope_spans") or []:
            for span in scope.get("spans") or []:
                try:
                    end_ns = int(span.get("endTimeUnixNano") or 0)
                except (TypeError, ValueError):
                    continue
                if end_ns > latest:
                    latest = end_ns
    return latest


def session_is_complete(session: dict, payload: dict) -> bool:
    end_timestamp = session.get("ssot__EndTimestamp__c")
    if isinstance(end_timestamp, str) and end_timestamp.strip():
        return True
    latest_ns = latest_span_end_unix(payload)
    if latest_ns <= 0:
        return False
    return (time.time() - (latest_ns / 1_000_000_000)) >= IDLE_SECONDS


def parse_sf_timestamp(value) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def past_72h(record: dict) -> bool:
    start = parse_sf_timestamp(record.get("ssot__StartTimestamp__c"))
    if start is None:
        return False
    return (time.time() - start) >= 72 * 3600


def load_exported(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def save_exported(path: Path, exported: set[str]) -> None:
    path.write_text(json.dumps(sorted(exported), indent=2), encoding="utf-8")


def post_protobuf_traces(url: str, protobuf_bytes: bytes) -> None:
    response = requests.post(
        url,
        data=protobuf_bytes,
        headers={"Content-Type": "application/x-protobuf"},
        timeout=60,
    )
    if not response.ok:
        print(response.text[:1000])
        raise HttpError(response.status_code, f"OTLP POST failed: HTTP {response.status_code}")


def process_session(
    record: dict,
    *,
    instance: str,
    sf_headers: dict,
    otlp_url: str,
    pin: bool,
    preview: bool,
    exported: set[str],
) -> bool:
    session_id = str(record["ssot__Id__c"])
    try:
        payload = fetch_otel(instance, sf_headers, session_id)
    except HttpError as exc:
        print(f"Skip {session_id}: {exc}")
        return False

    count = span_count(payload)
    complete = pin or session_is_complete(record, payload)
    if count == 0:
        if not pin and past_72h(record):
            print(f"Skip {session_id}: no spans and start is past 72 hours")
        else:
            print(f"Skip {session_id}: no spans yet (Data 360 catch-up)")
        return False
    if not complete:
        print(f"Skip {session_id}: in-progress ({count} spans so far)")
        return False

    if preview:
        print(f"Would export {count} span(s) for {session_id}")
        return False

    protobuf = to_export_trace_request_bytes(payload)
    try:
        post_protobuf_traces(otlp_url, protobuf)
    except HttpError as exc:
        print(f"Collector/Zerobus POST failed for {session_id}: {exc}")
        return False

    print(f"Exported {count} span(s) for {session_id} ({len(protobuf)} protobuf bytes)")
    exported.add(session_id)
    save_exported(EXPORTED_FILE, exported)
    return True


def run_pass(*, instance: str, otlp_url: str, only: str, preview: bool, exported: set[str]) -> None:
    token = salesforce_token(instance)
    sf_headers = {"Authorization": f"Bearer {token}"}
    pin = bool(only)
    if pin:
        sessions = [{"ssot__Id__c": only}]
    else:
        sessions = discover_sessions(instance, sf_headers)

    pending = [r for r in sessions if pin or str(r["ssot__Id__c"]) not in exported]
    print(f"Discovered {len(sessions)} session(s), {len(pending)} pending")
    for record in pending:
        process_session(
            record,
            instance=instance,
            sf_headers=sf_headers,
            otlp_url=otlp_url,
            pin=pin,
            preview=preview,
            exported=exported,
        )


def main() -> None:
    instance = env("SALESFORCE_INSTANCE_URL").rstrip("/")
    if not instance.startswith("https://"):
        raise SystemExit("SALESFORCE_INSTANCE_URL must start with https://")
    preview = dry_run()
    otlp_url = os.environ.get(
        "OTEL_COLLECTOR_TRACES_URL", "http://127.0.0.1:4318/v1/traces"
    ).strip()
    only = os.environ.get("SALESFORCE_SESSION_ID", "").strip()
    exported: set[str] = set() if preview else load_exported(EXPORTED_FILE)

    print(f"Salesforce: {instance}")
    print(f"OTLP sink:  {otlp_url} (DRY_RUN={preview})")

    passes = 0
    while True:
        try:
            run_pass(
                instance=instance,
                otlp_url=otlp_url,
                only=only,
                preview=preview,
                exported=exported,
            )
        except HttpError as exc:
            raise SystemExit(str(exc)) from exc
        passes += 1
        if MAX_PASSES != 0 and passes >= MAX_PASSES:
            break
        print(f"Sleeping {POLL_INTERVAL}s")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
