"""Convert Salesforce Agentforce Session Trace OTel JSON -> OTLP Protobuf.

Zerobus Ingest rejects OTLP/HTTP JSON (Content-Type: application/json).
Salesforce returns OTLP ResourceSpans as JSON. This module wraps / normalizes
that payload into an ExportTraceServiceRequest protobuf bytes blob suitable for
POST to an OTel Collector (or Zerobus) at /v1/traces with
Content-Type: application/x-protobuf.
"""

from __future__ import annotations

from typing import Any

from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)


def _as_resource_spans_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept common Salesforce / OTLP JSON shapes and return resourceSpans[]."""
    if "resourceSpans" in payload:
        return list(payload["resourceSpans"] or [])
    if "resource_spans" in payload:
        return list(payload["resource_spans"] or [])
    # Single ResourceSpans object
    if "scopeSpans" in payload or "scope_spans" in payload:
        return [payload]
    raise ValueError(
        "OTel payload missing resourceSpans; got keys: " + ", ".join(sorted(payload))
    )


def stamp_demo_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """Add demo resource attributes without mutating caller's original unnecessarily."""
    import copy

    data = copy.deepcopy(payload)
    for rs in _as_resource_spans_list(data):
        resource = rs.setdefault("resource", {})
        attrs = resource.setdefault("attributes", [])
        existing = {
            a.get("key")
            for a in attrs
            if isinstance(a, dict)
        }
        for key, value in (
            ("service.name", "salesforce.agentforce"),
            ("demo.customer", "suncorp"),
            ("telemetry.source", "agentforce.session_trace_otel_api"),
        ):
            if key in existing:
                continue
            attrs.append({"key": key, "value": {"stringValue": value}})
        # Ensure ExportTraceServiceRequest shape
    if "resourceSpans" not in data and "resource_spans" not in data:
        data = {"resourceSpans": _as_resource_spans_list(data)}
    elif "resource_spans" in data and "resourceSpans" not in data:
        data = {"resourceSpans": data["resource_spans"]}
    return data


def to_export_trace_request_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize Salesforce OTel JSON to ExportTraceServiceRequest protobuf bytes."""
    normalized = stamp_demo_attributes(payload)
    # ParseDict expects camelCase proto JSON mapping
    req = ExportTraceServiceRequest()
    ParseDict(normalized, req, ignore_unknown_fields=True)
    if not req.resource_spans:
        raise ValueError("No resource_spans after protobuf conversion")
    return req.SerializeToString()


def span_count(payload: dict[str, Any]) -> int:
    count = 0
    for rs in _as_resource_spans_list(payload):
        for scope in rs.get("scopeSpans") or rs.get("scope_spans") or []:
            count += len(scope.get("spans") or [])
    return count
