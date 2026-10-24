# salesforce-otel

**Suncorp demo:** ingest Salesforce **Agentforce** OpenTelemetry session traces into **Databricks on AWS** via **Zerobus Ingest** (native OTLP) — no Kafka / Kinesis.

```
Agentforce → Session Trace OTel API (JSON)
         → Poller (JSON→Protobuf)
         → OpenTelemetry Collector (OAuth refresh)
         → Zerobus Ingest OTLP
         → Unity Catalog Delta (VARIANT)
```

## Live demo environment

| Component | Value |
|-----------|-------|
| GitHub | `pravinva/salesforce-otel` |
| Salesforce | `https://orgfarm-91850b6147-dev-ed.develop.my.salesforce.com` |
| Databricks | `https://fevm-ot-pdm-semi.cloud.databricks.com` (FEVM AWS, **us-east-1**) |
| Workspace ID | `7474651137949483` |
| Catalog / schema | `ot_pdm_semi_catalog.agentforce_otel` |
| Tables | `agentforce_otel_spans`, `_logs`, `_metrics` |
| Service principal | `agentforce-zerobus-otel` |

Secrets live in `~/.vibe/salesforce-otel/demo.env` (not in git).

## Architecture

See [docs/architecture.md](docs/architecture.md). Salesforce setup: [docs/salesforce-setup.md](docs/salesforce-setup.md).

Collector deployment choice for this demo: **Docker locally** (same YAML works on **EC2**; for EKS wrap as a Deployment + ConfigMap).

## Quick start

### 1. Link secrets

```bash
cd salesforce-otel
ln -sf ~/.vibe/salesforce-otel/demo.env .env
```

### 2. Start the OTel Collector

```bash
cd otel-collector
docker compose up -d
docker compose logs -f
```

### 3. Smoke-test Zerobus (synthetic Agentforce-like spans)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r poller/requirements.txt
python3 scripts/send_synthetic_spans.py
```

### 4. Query Delta

```sql
SELECT time, service_name, name, status.code, trace_id, attributes
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
ORDER BY time DESC
LIMIT 20;
```

Warehouse tip: start **Suncorp Pilot SQL** (`4c66e7da442d0341`) on the FEVM workspace.

### 5. Poll real Agentforce sessions

1. Complete [docs/salesforce-setup.md](docs/salesforce-setup.md)
2. Chat with an **activated** agent
3. Run:

```bash
# Dry-run discovery / fetch only
DRY_RUN=true python3 poller/poll_agentforce.py

# Forward Protobuf to local collector → Zerobus
python3 poller/poll_agentforce.py
```

## Repo layout

```
sql/                 UC DDL + demo queries
otel-collector/      Collector YAML + docker-compose (EC2/EKS-ready)
poller/              Salesforce Session Trace poller (JSON→Protobuf)
scripts/             Synthetic spans + Zerobus token mint
docs/                Architecture + Salesforce setup
```

## Production notes

- Prefer Collector on **EKS** for HA; **EC2** is fine for PoC.
- Grant the SP **table-level** `MODIFY` + `SELECT` (schema inheritance is not enough for Zerobus `authorization_details`).
- Zerobus accepts **Protobuf only** on OTLP/HTTP — never post Salesforce’s JSON body directly to Zerobus.
- Optional next step: Zero-Copy share curated span aggregates back to Salesforce Data Cloud.

## References

- [Ingest OpenTelemetry with Zerobus](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
- [Configure OTLP clients](https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure)
- [Export Agentforce Session Tracing Data](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
