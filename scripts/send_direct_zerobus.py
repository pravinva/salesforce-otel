#!/usr/bin/env python3
"""Send synthetic OTLP Protobuf spans directly to Zerobus (no local Collector).

Useful when Docker is unavailable. For long-running demos prefer the Collector
so OAuth tokens refresh automatically.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poller"))
load_dotenv(ROOT / ".env")
load_dotenv(Path.home() / ".vibe" / "salesforce-otel" / "demo.env")

from json_to_otlp import to_export_trace_request_bytes  # noqa: E402


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


def mint_token() -> str:
    catalog = env("CATALOG")
    schema = env("SCHEMA")
    prefix = env("TABLE_PREFIX")
    table = f"{catalog}.{schema}.{prefix}_otel_spans"
    authorization_details = json.dumps(
        [
            {
                "type": "unity_catalog_privileges",
                "privileges": ["USE CATALOG"],
                "object_type": "CATALOG",
                "object_full_path": catalog,
            },
            {
                "type": "unity_catalog_privileges",
                "privileges": ["USE SCHEMA"],
                "object_type": "SCHEMA",
                "object_full_path": f"{catalog}.{schema}",
            },
            {
                "type": "unity_catalog_privileges",
                "privileges": ["SELECT", "MODIFY"],
                "object_type": "TABLE",
                "object_full_path": table,
            },
        ]
    )
    resp = requests.post(
        f"https://{env('WORKSPACE_URL')}/oidc/v1/token",
        auth=(env("DATABRICKS_CLIENT_ID"), env("DATABRICKS_CLIENT_SECRET")),
        data={
            "grant_type": "client_credentials",
            "scope": "all-apis",
            "resource": f"api://databricks/workspaces/{env('WORKSPACE_ID')}/zerobusDirectWriteApi",
            "authorization_details": authorization_details,
        },
        timeout=60,
    )
    if not resp.ok:
        print(resp.text[:1000])
        raise SystemExit(f"token mint failed: HTTP {resp.status_code}")
    token = resp.json().get("access_token")
    if not token:
        raise SystemExit(f"no access_token: {resp.text[:500]}")
    return token, table


def build_payload() -> dict:
    now_ns = time.time_ns()
    trace_id = uuid.uuid4().hex
    root = uuid.uuid4().hex[:16]
    child = uuid.uuid4().hex[:16]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "salesforce.agentforce"}},
                        {"key": "demo.customer", "value": {"stringValue": "suncorp"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agentforce.session_trace", "version": "demo-1.0"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": root,
                                "name": "GeneralFAQ",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns - 100_000_000),
                                "endTimeUnixNano": str(now_ns),
                                "status": {"code": 1},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "invoke_agent"},
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": child,
                                "parentSpanId": root,
                                "name": "agent_router",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns - 80_000_000),
                                "endTimeUnixNano": str(now_ns - 20_000_000),
                                "status": {"code": 1},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "chat"},
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
    }


def main() -> None:
    token, table = mint_token()
    endpoint = (
        f"https://{env('WORKSPACE_ID')}.zerobus.{env('REGION')}.cloud.databricks.com:443/v1/traces"
    )
    body = to_export_trace_request_bytes(build_payload())
    print(f"POST {endpoint}")
    print(f"table={table} bytes={len(body)}")
    resp = requests.post(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-protobuf",
            "x-databricks-zerobus-table-name": table,
        },
        timeout=60,
    )
    print(f"HTTP {resp.status_code}")
    if resp.text:
        print(resp.text[:800])
    if not resp.ok:
        raise SystemExit(1)
    print("OK — query agentforce_otel_spans shortly")


if __name__ == "__main__":
    main()
