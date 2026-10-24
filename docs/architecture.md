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
them, then shows where Private Link attaches. End-to-end delay follows
Salesforce Data 360 catch-up and the poll interval (typically tens of
seconds to a few minutes after the session is readable). Zerobus writes
Delta when the Protobuf POST arrives.

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

**OTLP** (OpenTelemetry Protocol) is the wire format for traces, metrics,
and logs over HTTP or gRPC (`/v1/traces`, `/v1/metrics`, `/v1/logs`).
Zerobus Ingest OTLP speaks that protocol. The Salesforce API returns
OTLP-shaped **JSON** on GET; Zerobus accepts OTLP **Protobuf** on POST.

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
**OpenTelemetry Collector** (Zerobus client). Phase A1 posted Protobuf
from the poller straight to Zerobus. The Collector is the standing
Databricks client when you want token refresh, batching, and Private Link
egress from a VPC. This lab hosted it on EKS Fargate. Production can use
EKS, ECS, a small VM, or a scheduled function. EKS is a host for that
process. Zerobus only needs a client that POSTs Protobuf.

## 5. Architecture, hop by hop

**Salesforce Agentforce.** The Default agent runs. Session Tracing writes
into Data 360. The poller calls
`GET /services/data/v66.0/einstein/audit/otel/{sessionId}`. On the figure:
*PULL GET OTel JSON*.

**AWS VPC — telemetry bridge.** This lab runs the Collector in account
`332745928618`, region `ap-southeast-2`, EKS cluster `agentforce-otel`
(Fargate).

- **Poller** calls Salesforce, converts JSON to Protobuf, and POSTs to the
  Collector ClusterIP `http://otel-collector.agentforce-otel.svc.cluster.local:4318/v1/traces`.
  On EKS that is CronJob `session-poller` in the same namespace (manifest
  `otel-collector/k8s/poller.yaml`). A one-shot Job is
  `kubectl -n agentforce-otel create job session-poller-once --from=cronjob/session-poller`.
  The pod needs an External Client App (`SALESFORCE_CLIENT_ID` /
  `SALESFORCE_CLIENT_SECRET`). Until that secret exists, the same poller
  runs on a laptop through `kubectl port-forward`.
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

A1 posted Protobuf from the laptop to public Zerobus. A2 runs the Collector
in a VPC on the same public hostname. FEVM `fevm-ot-pdm-semi` is a public
workspace. Suncorp copies the Collector-in-VPC pattern onto Private Link;
the lab host can be EKS, ECS, or an equivalent small process.

Poller on EKS (same VPC as the Collector; needs External Client App in
`sf-poller`):

```bash
export AWS_PROFILE=unity-gateway-demo
otel-collector/k8s/deploy.sh
kubectl -n agentforce-otel create job session-poller-once --from=cronjob/session-poller
kubectl -n agentforce-otel logs -l app=session-poller --tail=80
```

Laptop fallback (sf CLI session, no ECA):

```bash
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
| Poller | EKS CronJob `session-poller` (laptop + port-forward until ECA exists) | Same namespace as the Collector |
| Catalog | `ot_pdm_semi_catalog.agentforce_otel` | Suncorp UC names, same DDL |
| Auth | SP `agentforce-zerobus-otel` | Suncorp SP, table-level `SELECT` and `MODIFY` |

Phase B checks (private DNS, VPC endpoint connectivity, POST 200, SQL rows)
are in [suncorp-test-setup.md](suncorp-test-setup.md).
Org enablement is in [salesforce-setup.md](salesforce-setup.md).

## 8. Produce traces and inspect tables

Catalog `ot_pdm_semi_catalog.agentforce_otel`. Warehouse used in the lab:
**Suncorp Pilot SQL**. DDL is in `sql/01_create_otel_tables.sql`. Repeatable
queries are in `sql/02_demo_queries.sql`.

### 8.1 Produce an Agentforce session

1. Confirm Session Tracing, Einstein Audit (dataspace `default`), and Agent
   Platform Tracing are on (`docs/salesforce-setup.md`).
2. Chat with **Agentforce (Default)** in Agent Builder, or run:

```bash
sf agent test run --api-name OTel_Demo_Test --target-org orgfarm918 --wait 10 --verbose
```

Lab utterance: `Hello, what can you do?` Expected topic: `GeneralCRM`.
Copy `generatedData.sessionId`.

3. Wait for Data 360 catch-up (often several minutes). Then:

```bash
DRY_RUN=true python3 poller/poll_agentforce.py
```

Observe: a session id, span count greater than zero, status complete. Empty
spans means Data 360 is still catching up; wait and repeat.

### 8.2 POST to Zerobus

Direct (Phase A1):

```bash
SALESFORCE_SESSION_ID=<session-id> \
  OTEL_COLLECTOR_TRACES_URL="https://${WORKSPACE_ID}.zerobus.${REGION}.cloud.databricks.com:443/v1/traces" \
  python3 poller/poll_agentforce.py
```

Via Collector on EKS (Phase A2, poller in-cluster):

```bash
kubectl -n agentforce-otel create job session-poller-once --from=cronjob/session-poller
kubectl -n agentforce-otel logs -l app=session-poller --tail=80
```

The CronJob posts to
`http://otel-collector.agentforce-otel.svc.cluster.local:4318/v1/traces`.
Unsuspend for a 2-minute schedule:
`kubectl -n agentforce-otel patch cronjob session-poller -p '{"spec":{"suspend":false}}'`.

Laptop fallback if `sf-poller` is missing:

```bash
kubectl -n agentforce-otel port-forward svc/otel-collector 4318:4318
SALESFORCE_SESSION_ID=<session-id> \
  OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces \
  python3 poller/poll_agentforce.py
```

Observe on the client: `Exported N span(s)` and HTTP 200. Synthetic check:
`python3 scripts/send_direct_zerobus.py`.

### 8.3 Tables and what to look for

| Table | When it grows | What to look for |
|-------|---------------|------------------|
| `agentforce_otel_spans` | Every successful trace POST | New `time`; `name` values such as `GeneralCRM_*`, `AiCopilot__ReactInitialPrompt`, `CLOSED_USER_REQUEST`, `TaskResolution`, `InstructionAdherence`; non-empty `trace_id` and `span_id`; `status.code`; `attributes` VARIANT with prompt/tool payload |
| `agentforce_otel_logs` | When the session export includes log records | Rows sharing the same `trace_id`; `body` / `severity_text` |
| `agentforce_otel_metrics` | When the session export includes metrics | Rows for the same window; `name` and points in VARIANT |

A short Agentforce chat often fills **spans** first. Empty logs or metrics
with populated spans is a valid session.

```sql
SELECT time, service_name, name, status.code, trace_id, span_id
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
ORDER BY time DESC
LIMIT 20;
```

```sql
SELECT name, COUNT(*) AS spans
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
WHERE time > current_timestamp() - INTERVAL 1 DAYS
GROUP BY name
ORDER BY spans DESC;
```

Lab session `01a16cb0-5079-71ce-a37e-9aee0cb3c332` produced **8 spans** and
Zerobus HTTP **200**. Match a new run by `time` descending and by `name`.

## 9. Design consequences

- The Salesforce contract is a **session GET of OTLP JSON**. The poller
  implements that client.
- The Databricks contract is a **Protobuf POST** with Unity Catalog
  authorization. The poller or the Collector performs that POST.
- Zerobus OTLP on TCP 443 is the Private Link attachment point. A Collector
  (or equivalent client) in Suncorp’s VPC sits on that hop.
- `VARIANT` columns keep prompt and tool payloads for eval on the lakehouse.
- Delta Sharing can return curated aggregates to Data Cloud after traces
  already land in Delta.

## 10. References

- [Export Agentforce Session Tracing Data](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
- [Zerobus OTLP overview](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
- [Configure OTLP clients](https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure)
- [OTLP table reference](https://docs.databricks.com/aws/en/ingestion/opentelemetry/table-reference)
- [Zerobus networking / front-end Private Link](https://docs.databricks.com/aws/en/ingestion/zerobus-networking)
- [Inbound PrivateLink for performance-intensive services](https://docs.databricks.com/aws/en/security/network/front-end/service-direct-privatelink)
