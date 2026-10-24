# Suncorp — Agentforce session traces on Databricks

Field Engineering demonstration readout  
24 October 2026

This note walks the integration: Salesforce’s session-trace API, Zerobus
Ingest, and the bridge that moves data between them. The figure is the
visual companion. The test plan is [suncorp-test-setup.md](suncorp-test-setup.md).

![Suncorp Agentforce OpenTelemetry to Databricks Lakehouse](diagrams/suncorp_agentforce_otel_zerobus.png)

## 1. Background

Suncorp runs customer-facing work on **Salesforce Agentforce** (LLM, tools,
CRM actions). The same traces need to land in **Databricks** so platform and
risk teams can query conversations, run evals, and retain them with the rest
of the lakehouse. Target workspaces use **AWS front-end Private Link**. The
ingest path is **Zerobus Ingest OTLP** into Delta.

The two products already publish the APIs this design uses. This demo wires
them, then shows where Private Link attaches.

## 2. Salesforce session tracing

With Agentforce Session Tracing, Einstein Audit, and Agent Platform Tracing
enabled, **Data 360** stores the session: prompts, tool calls, evaluation
spans, metrics, and logs.

Salesforce’s
[Export Agentforce Session Tracing Data API](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
returns that payload over REST:

```
GET /services/data/v66.0/einstein/audit/otel/{session-id}
```

A client authenticates with OAuth 2.0 (External Client App), supplies **one
session id**, and receives **JSON** that follows the OTLP schema
(`ResourceSpans`, plus metrics and logs). Sessions must have started within
the prior **72 hours**. Throughput follows Connect API rate limits.
Salesforce’s developer guidance is to take this JSON and POST it to the
observability backend you operate.

You can also query Data 360 DMOs with SOQL (for example
`ssot__TelemetryTraceSpan__dlm`). That is a second read path into the same
stored traces.

In OpenTelemetry terms, an **exporter** is a process that POSTs OTLP to a
URL you configure. The Salesforce API is a **session export GET**: the
integration calls Salesforce and receives OTLP-shaped JSON.

## 3. Databricks Zerobus Ingest

[Zerobus Ingest OTLP](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
is a managed gateway. A client POSTs OTLP to
`{workspaceId}.zerobus.{region}.cloud.databricks.com` with Unity Catalog
authorization and the header `x-databricks-zerobus-table-name`. Zerobus
writes **Delta** tables and stores attributes as **VARIANT**.

On this gateway:

- The content type is **Protobuf** (`application/x-protobuf`).
- The client initiates the POST.
- The **OTLP** interface is a documented front-end Private Link service on
  **TCP 443**. MQTT and Kafka-compatible Zerobus APIs stay on their own
  networking model.
- Databricks OAuth tokens last about **60 minutes**, so the client refreshes
  them.

## 4. The telemetry bridge

Salesforce holds the session and serves it on GET. Zerobus accepts a
Protobuf POST and writes Delta. The **bridge** is the client of both APIs.

| | Salesforce API | Zerobus OTLP |
|--|--|--|
| Job | Session system of record | Lakehouse ingest |
| Call | Integration `GET`s JSON | Integration `POST`s Protobuf |
| Unit | One session id, 72-hour window | Batches of spans, logs, metrics |

The bridge does three things:

1. **Discover and read** finished sessions (`ssot__AiAgentSession__dlm`, then
   the OTel GET).
2. **Translate** OTLP JSON to OTLP Protobuf. Where Salesforce sends an empty
   `spanId`, the converter writes a deterministic 8-byte id so the batch is
   valid OTLP.
3. **POST** to Zerobus and **refresh** the Databricks service-principal
   token.

We implement that as a **poller** (Salesforce client) plus an
**OpenTelemetry Collector** (Zerobus client). The poller is the OTLP
exporter Salesforce leaves for you to run. The Collector is the long-lived
push process in the VPC.

## 5. Architecture, hop by hop

**Salesforce Agentforce.** The Default agent runs. Session Tracing writes
into Data 360. The poller calls
`GET /services/data/v66.0/einstein/audit/otel/{sessionId}`. On the figure:
*PULL GET OTel JSON*.

**AWS VPC — telemetry bridge on EKS.** This lab runs the bridge in account
`332745928618`, region `ap-southeast-2`, EKS cluster `agentforce-otel`
(Fargate).

- **Poller** calls Salesforce, converts JSON to Protobuf, and POSTs to the
  Collector at `:4318/v1/traces`. In this lab it runs on a laptop and uses
  `kubectl port-forward`. At Suncorp, run it in the same VPC as the
  Collector.
- **OpenTelemetry Collector** receives Protobuf, batches, sets source
  attributes, refreshes OAuth, and POSTs to Zerobus. On the figure: *PUSH
  OTLP Protobuf to Zerobus*.

The Collector service is ClusterIP **4317** (gRPC) and **4318** (HTTP)
inside the VPC. Traffic from poller to Collector to Zerobus stays on OTLP.

**Path to Databricks.** Today the Collector POSTs over **public HTTPS** to
FEVM Zerobus in **us-east-1**. That is Phase A ingest. Phase B keeps the
same Collector and Protobuf and points the hostname at a **VPC endpoint**
(front-end / service-direct Private Link, TCP 443, private DNS).

**Databricks.** Zerobus writes
`ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_{spans,logs,metrics}`.
Unity Catalog grants the service principal table-level `SELECT` and
`MODIFY`. SQL and MLflow evals read those Delta tables. A later option is
Delta Sharing of curated aggregates back to Salesforce Data Cloud.

The Salesforce GET to `/einstein/audit/otel/{id}` uses Salesforce’s network
path. Databricks Private Link covers Collector → Zerobus. If the Salesforce
GET also has to stay on a private path, that is **Salesforce Private
Connect** (or an approved egress allowlist), as a separate control.

## 6. What the lab has demonstrated

| Phase | Work | Status |
|-------|------|--------|
| **A1** | Live Agentforce session `01a16cb0-5079-71ce-a37e-9aee0cb3c332`: 8 spans, public Zerobus HTTP 200, rows in Delta | **Done** 24 Oct 2026 |
| **A2** | Collector on EKS Fargate in this AWS VPC, POSTing to public Zerobus | **Done** 24 Oct 2026 |
| **B** | Same Collector with Private Link: private DNS, VPC endpoint, POST and SQL from the VPC | Suncorp network build |

A1 posted Protobuf directly while local Docker was down. A2 is the pattern
to copy: Collector in a VPC. FEVM `fevm-ot-pdm-semi` is a public workspace,
so A2 still uses the public Zerobus hostname.

From a laptop:

```bash
export AWS_PROFILE=unity-gateway-demo
kubectl -n agentforce-otel port-forward svc/otel-collector 4318:4318
OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces python3 poller/poll_agentforce.py
```

Manifests: [`otel-collector/k8s/`](../otel-collector/k8s/). Tear down:
`eksctl delete cluster -f otel-collector/k8s/cluster.yaml`.

## 7. This lab and Suncorp production

| | This repo | Suncorp production (Phase B) |
|--|-----------|------------------------------|
| Salesforce | OrgFarm DE `orgfarm918` | Suncorp Agentforce + Data Cloud |
| Databricks | Public FEVM `fevm-ot-pdm-semi` us-east-1 | Private Link workspace, same region as the VPC |
| VPC | Demo VPC, EKS `agentforce-otel`, ap-southeast-2 | Suncorp VPC; Collector uses the Private Link hostname |
| Collector | Running on Fargate | Same pattern, private DNS and PL |
| Poller | Laptop + port-forward | Same VPC as the Collector |
| Catalog | `ot_pdm_semi_catalog.agentforce_otel` | Suncorp UC names, same DDL |
| Auth | SP `agentforce-zerobus-otel` | Suncorp SP, table-level `SELECT` and `MODIFY` |

Phase B checks (private DNS, VPC endpoint connectivity, POST 200, SQL rows)
are in [suncorp-test-setup.md](suncorp-test-setup.md).
Org enablement is in [salesforce-setup.md](salesforce-setup.md).

## 8. Design consequences

- The Salesforce contract is a **session GET of OTLP JSON**. The poller
  implements that client.
- The Databricks contract is a **Protobuf POST** with Unity Catalog
  authorization. The Collector implements that client.
- Zerobus OTLP on TCP 443 is the Private Link attachment point. The
  Collector is the process that sits on that hop.
- `VARIANT` columns keep prompt and tool payloads for eval on the lakehouse.
- Delta Sharing can return curated aggregates to Data Cloud after traces
  already land in Delta.

## References

- [Export Agentforce Session Tracing Data](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
- [Zerobus OTLP overview](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
- [Configure OTLP clients](https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure)
- [OTLP table reference](https://docs.databricks.com/aws/en/ingestion/opentelemetry/table-reference)
- [Zerobus networking / front-end Private Link](https://docs.databricks.com/aws/en/ingestion/zerobus-networking)
- [Inbound PrivateLink for performance-intensive services](https://docs.databricks.com/aws/en/security/network/front-end/service-direct-privatelink)
