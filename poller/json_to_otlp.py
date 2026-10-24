"""Convert Salesforce Agentforce Session Trace OTel JSON -> OTLP Protobuf.

Zerobus Ingest rejects OTLP/HTTP JSON (Content-Type: application/json).
Salesforce returns OTLP ResourceSpans as JSON with **hex** trace/span IDs
(OTLP/JSON encoding). `google.protobuf.json_format.ParseDict` expects **base64**
for bytes fields, so we normalize IDs before parsing.
"""

from __future__ import annotations

import base64
import copy
import re
from typing import Any

from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def _as_resource_spans_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "resourceSpans" in payload:
        return list(payload["resourceSpans"] or [])
    if "resource_spans" in payload:
        return list(payload["resource_spans"] or [])
    if "scopeSpans" in payload or "scope_spans" in payload:
        return [payload]
    raise ValueError(
        "OTel payload missing resourceSpans; got keys: " + ", ".join(sorted(payload))
    )


def _hex_or_raw_to_b64(value: Any, expected_bytes: int) -> Any:
    """Convert OTLP/JSON hex IDs to protobuf-JSON base64 bytes strings."""
    if not isinstance(value, str) or not value:
        return value
    # Already looks like base64 of the right length? leave alone if not hex
    if _HEX_RE.fullmatch(value) and len(value) == expected_bytes * 2:
        return base64.b64encode(bytes.fromhex(value)).decode("ascii")
    return value


def _normalize_ids(payload: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(payload)
    # Ensure camelCase resourceSpans key for ParseDict
    if "resource_spans" in data and "resourceSpans" not in data:
        data = {"resourceSpans": data["resource_spans"]}
    elif "resourceSpans" not in data:
        data = {"resourceSpans": _as_resource_spans_list(data)}

    for rs in data.get("resourceSpans") or []:
        scopes = rs.get("scopeSpans") or rs.get("scope_spans") or []
        if "scope_spans" in rs and "scopeSpans" not in rs:
            rs["scopeSpans"] = rs.pop("scope_spans")
            scopes = rs["scopeSpans"]
        for scope in scopes:
            for span in scope.get("spans") or []:
                if "traceId" in span:
                    span["traceId"] = _hex_or_raw_to_b64(span["traceId"], 16)
                if "trace_id" in span:
                    span["traceId"] = _hex_or_raw_to_b64(span.pop("trace_id"), 16)
                if "spanId" in span:
                    span["spanId"] = _hex_or_raw_to_b64(span["spanId"], 8)
                if "span_id" in span:
                    span["spanId"] = _hex_or_raw_to_b64(span.pop("span_id"), 8)
                if "parentSpanId" in span and span["parentSpanId"]:
                    span["parentSpanId"] = _hex_or_raw_to_b64(span["parentSpanId"], 8)
                if "parent_span_id" in span and span["parent_span_id"]:
                    span["parentSpanId"] = _hex_or_raw_to_b64(
                        span.pop("parent_span_id"), 8
                    )
                # Links
                for link in span.get("links") or []:
                    if "traceId" in link:
                        link["traceId"] = _hex_or_raw_to_b64(link["traceId"], 16)
                    if "spanId" in link:
                        link["spanId"] = _hex_or_raw_to_b64(link["spanId"], 8)
    return data


def stamp_demo_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    data = _normalize_ids(payload)
    for rs in data.get("resourceSpans") or []:
        resource = rs.setdefault("resource", {})
        attrs = resource.setdefault("attributes", [])
        existing = {a.get("key") for a in attrs if isinstance(a, dict)}
        for key, value in (
            ("service.name", "salesforce.agentforce"),
            ("demo.customer", "suncorp"),
            ("telemetry.source", "agentforce.session_trace_otel_api"),
        ):
            if key in existing:
                continue
            attrs.append({"key": key, "value": {"stringValue": value}})
    return data


def to_export_trace_request_bytes(payload: dict[str, Any]) -> bytes:
    normalized = stamp_demo_attributes(payload)
    req = ExportTraceServiceRequest()
    ParseDict(normalized, req, ignore_unknown_fields=True)
    if not req.resource_spans:
        raise ValueError("No resource_spans after protobuf conversion")
    # Validate ID lengths (OTLP: trace=16 bytes, span=8 bytes)
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            for span in ss.spans:
                if len(span.trace_id) != 16:
                    raise ValueError(
                        f"Invalid trace_id length {len(span.trace_id)} "
                        f"(hex={span.trace_id.hex()})"
                    )
                if len(span.span_id) != 8:
                    raise ValueError(
                        f"Invalid span_id length {len(span.span_id)} "
                        f"(hex={span.span_id.hex()})"
                    )
    return req.SerializeToString()


def span_count(payload: dict[str, Any]) -> int:
    count = 0
    for rs in _as_resource_spans_list(payload):
        for scope in rs.get("scopeSpans") or rs.get("scope_spans") or []:
            count += len(scope.get("spans") or [])
    return count
