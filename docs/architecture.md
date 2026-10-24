# Architecture — Agentforce OTel → Databricks Zerobus (Suncorp demo)

Bricksmith / Databricks-branded figure (EKS collector in an AWS VPC, poll vs push arrows, Phase B Private Link):

![Suncorp Agentforce OpenTelemetry to Databricks Lakehouse](diagrams/suncorp_agentforce_otel_zerobus.png)

Prompt: [suncorp_agentforce_otel_zerobus.txt](suncorp_agentforce_otel_zerobus.txt).

## Direction of traffic

Salesforce **does not push** OTLP to Databricks. The [Export Agentforce Session Tracing Data API](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html) is a **pull**: one session as OTLP JSON over REST. **Zerobus is push**: the Collector POSTs OTLP Protobuf.

```
Salesforce Agentforce
        |  write session / LLM / tool traces
        v
Data 360 Session Tracing  (72-hour window)
        ^
        |  PULL  GET /services/data/v66.0/einstein/audit/otel/{sessionId}
        |  OTLP JSON
        |
[ AWS VPC  ap-southeast-2 ]
  Session poller  (JSON → Protobuf)
        |  PUSH  application/x-protobuf  :4318/v1/traces
        v
  OpenTelemetry Collector on EKS Fargate
        |  PUSH  OTLP Protobuf + OAuth refresh
        v
Zerobus Ingest  (public today / Private Link in Phase B)
        v
Unity Catalog Delta  VARIANT span / log / metric tables
```

There is no Kafka, Kinesis, or MSK on this path.

## Live collector (this account)

| | |
|--|--|
| AWS account | `332745928618` (IAM Identity Center `d-92670d081f`, profile `unity-gateway-demo`) |
| Region | `ap-southeast-2` |
| Cluster | EKS `agentforce-otel` (Kubernetes 1.32, Fargate) |
| Workload | `otel/opentelemetry-collector-contrib:0.114.0` in namespace `agentforce-otel` |
| Service | ClusterIP `4317` (gRPC) and `4318` (HTTP) |
| Manifests | [`otel-collector/k8s/`](../otel-collector/k8s/) |
| Databricks sink | Public Zerobus on FEVM **us-east-1** (not Private Link) |

Laptop poller reaches the ClusterIP with:

```bash
export AWS_PROFILE=unity-gateway-demo
kubectl -n agentforce-otel port-forward svc/otel-collector 4318:4318
OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces python3 poller/poll_agentforce.py
```

Tear down: `AWS_PROFILE=unity-gateway-demo eksctl delete cluster -f otel-collector/k8s/cluster.yaml`.

## Why a Collector?

Databricks OAuth tokens for Zerobus expire about every **60 minutes**. The
Collector’s `oauth2clientauthextension` mints and refreshes tokens from a
service principal. It is also the process that **pushes** into Zerobus, so it
belongs in the VPC (and, in Phase B, on the Private Link hop).

## Why a Poller?

Agentforce has no outbound OTLP exporter. Production loop:

1. Agentforce writes into Data 360 Session Tracing
2. Poller discovers `ssot__AiAgentSession__dlm` rows
3. Poller **pulls** each session’s OTel JSON
4. Poller converts JSON → Protobuf (Zerobus rejects `application/json`)
5. Poller **pushes** Protobuf to the Collector; Collector **pushes** to Zerobus → Delta

Salesforce evaluation spans may arrive with an **empty `spanId`**. The converter
fills a deterministic 8-byte ID so Zerobus accepts the batch.

## Lab vs production

| | This repo now | Suncorp production (Phase B) |
|--|----------------|------------------------------|
| Databricks | Public FEVM `fevm-ot-pdm-semi` us-east-1 | PL-enforced workspace, same region as the VPC |
| Zerobus URL | `{workspaceId}.zerobus.us-east-1.cloud.databricks.com` (public) | Front-end / service-direct Private Link, TCP 443 |
| VPC | Demo VPC created with the EKS cluster in **ap-southeast-2** | Suncorp VPC; no public route to Zerobus |
| Collector | **Running** on EKS Fargate `agentforce-otel` | Same pattern, private DNS + PL |
| Poller | Laptop via `kubectl port-forward` | In the VPC next to the Collector |
| Salesforce | OrgFarm DE `orgfarm918` | Suncorp Agentforce + Data Cloud org |
| Proven | Live 8-span ingest (direct POST) + Collector on EKS | Not yet — needs Suncorp network build |

## Demo environment (this repo)

| Layer | Choice |
|-------|--------|
| Salesforce | OrgFarm Dev Edition `orgfarm-91850b6147-dev-ed` |
| Databricks | FEVM AWS Serverless `fevm-ot-pdm-semi` (us-east-1) |
| Catalog | `ot_pdm_semi_catalog.agentforce_otel` |
| Tables | `agentforce_otel_{spans,logs,metrics}` |
| Collector | EKS Fargate in ap-southeast-2; local Docker Compose still available |
| Auth | Databricks SP `agentforce-zerobus-otel` (table-level `SELECT`+`MODIFY`) |
| Live session | `01a16cb0-5079-71ce-a37e-9aee0cb3c332` (24 Oct 2026) |

## Key advantages for Suncorp

1. **No message bus** — no Kafka/MSK/Kinesis for lakehouse-bound telemetry
2. **Private Link compatible** — OTLP is a supported Zerobus PL interface
3. **Unified AI eval** — LLM-as-judge / RAG evals on live conversation traces
4. **Zero-Copy optionality** — share curated analytics back to Salesforce Data Cloud
5. **VARIANT columns** — preserve high-cardinality Agentforce prompt/tool metadata

## References

- [Zerobus OTLP overview](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
- [Configure OTLP clients](https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure)
- [OTLP table reference](https://docs.databricks.com/aws/en/ingestion/opentelemetry/table-reference)
- [Zerobus networking / front-end Private Link](https://docs.databricks.com/aws/en/ingestion/zerobus-networking)
- [Inbound PrivateLink for performance-intensive services](https://docs.databricks.com/aws/en/security/network/front-end/service-direct-privatelink)
- [Export Agentforce Session Tracing Data](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
