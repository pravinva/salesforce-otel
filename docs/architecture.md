# Architecture — Agentforce OTel → Databricks Zerobus (Suncorp demo)

## Production target (four layers)

```
[ Salesforce / Agentforce ]
       │  Session Trace OTel REST API (OTLP JSON, beta)
       │  GET /services/data/v66.0/einstein/audit/otel/{sessionId}
       ▼
[ Telemetry bridge: poller + OpenTelemetry Collector ]
       │  Poller: discover sessions, JSON→Protobuf
       │  Collector (EC2 / EKS): oauth2clientauthextension token refresh
       │  Standard OTLP over gRPC or HTTP Protobuf
       ▼
[ Databricks Zerobus Ingest OTLP Gateway ]   ← Unity Catalog authz
       │  Header: x-databricks-zerobus-table-name
       │  Direct managed write (no Kafka / Kinesis)
       ▼
[ Delta Lake tables (VARIANT attributes) ]
       │  Flat, query-ready spans / logs / metrics
       ▼
[ Lakehouse AI observability / eval / Zero-Copy back to SFDC ]
```

## Why a Collector?

Databricks OAuth tokens for Zerobus expire about every **60 minutes**. The
Collector’s `oauth2clientauthextension` mints and refreshes tokens from a
service principal without changing producer code.

## Why a Poller?

Agentforce does **not** push OTLP to an external endpoint today. The beta
Session Trace OTel API returns one session as OTLP JSON. Production path is:

1. Agentforce writes session/LLM/tool data into Data 360 Session Tracing
2. Poller discovers `ssot__AiAgentSession__dlm` rows
3. Poller fetches each session’s OTel payload
4. Poller converts JSON → Protobuf (Zerobus rejects `application/json`)
5. Poller posts to Collector → Zerobus → Delta

## Demo environment (this repo)

| Layer | Choice |
|-------|--------|
| Salesforce | OrgFarm Dev Edition `orgfarm-91850b6147-dev-ed` |
| Databricks | FEVM AWS Serverless `fevm-ot-pdm-semi` (us-east-1) |
| Catalog | `ot_pdm_semi_catalog.agentforce_otel` |
| Tables | `agentforce_otel_{spans,logs,metrics}` |
| Collector | Docker locally (stand-in for EC2/EKS) |
| Auth | Databricks SP `agentforce-zerobus-otel` |

## Key advantages for Suncorp

1. **No message bus** — no Kafka/MSK/Kinesis for lakehouse-bound telemetry
2. **Unified AI eval** — LLM-as-judge / RAG evals on live conversation traces
3. **Zero-Copy optionality** — share curated analytics back to Salesforce Data Cloud
4. **VARIANT columns** — preserve high-cardinality Agentforce prompt/tool metadata

## References

- [Zerobus OTLP overview](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
- [Configure OTLP clients](https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure)
- [OTLP table reference](https://docs.databricks.com/aws/en/ingestion/opentelemetry/table-reference)
- [Agentforce Session Trace OTel API](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
