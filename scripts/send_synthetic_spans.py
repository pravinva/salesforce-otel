#!/usr/bin/env python3
"""Send a synthetic Agentforce-like OTLP protobuf trace to the local Collector.

Use this to validate Zerobus + UC tables before Salesforce Session Tracing is
fully provisioned / before an agent conversation exists.
"""

from __future__ import annotations

import os
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


def _hex_id(nbytes: int) -> str:
    """Return lowercase hex for nbytes of randomness (OTLP/JSON ID encoding)."""
    return uuid.uuid4().bytes[:nbytes].hex()


def build_payload() -> dict:
    now_ns = time.time_ns()
    trace_id = _hex_id(16)
    root_span = _hex_id(8)
    llm_span = _hex_id(8)
    tool_span = _hex_id(8)
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "salesforce.agentforce"}},
                        {"key": "demo.customer", "value": {"stringValue": "suncorp"}},
                        {
                            "key": "agentforce.agent.name",
                            "value": {"stringValue": "Databricks Ingest Tester"},
                        },
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "agentforce.session_trace",
                            "version": "demo-1.0",
                        },
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": root_span,
                                "name": "GeneralFAQ",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns - 250_000_000),
                                "endTimeUnixNano": str(now_ns),
                                "status": {"code": 1},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "invoke_agent"},
                                    },
                                    {
                                        "key": "agent.topic",
                                        "value": {"stringValue": "GeneralFAQ"},
                                    },
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": llm_span,
                                "parentSpanId": root_span,
                                "name": "agent_router",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns - 200_000_000),
                                "endTimeUnixNano": str(now_ns - 50_000_000),
                                "status": {"code": 1},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "chat"},
                                    },
                                    {
                                        "key": "gen_ai.request.model",
                                        "value": {"stringValue": "atlas-reasoning-engine"},
                                    },
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": tool_span,
                                "parentSpanId": root_span,
                                "name": "InstructionAdherence",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns - 40_000_000),
                                "endTimeUnixNano": str(now_ns - 5_000_000),
                                "status": {"code": 1},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "execute_tool"},
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
    url = os.environ.get(
        "OTEL_COLLECTOR_TRACES_URL", "http://127.0.0.1:4318/v1/traces"
    ).strip()
    payload = build_payload()
    body = to_export_trace_request_bytes(payload)
    print(f"POST {url} ({len(body)} protobuf bytes, 3 spans)")
    resp = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/x-protobuf"},
        timeout=60,
    )
    print(f"HTTP {resp.status_code}")
    if resp.text:
        print(resp.text[:500])
    if not resp.ok:
        raise SystemExit(1)
    print("OK — query ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans in ~seconds")


if __name__ == "__main__":
    main()
