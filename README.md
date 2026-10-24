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

See [docs/architecture.md](docs/architecture.md), [docs/salesforce-setup.md](docs/salesforce-setup.md), and [docs/suncorp-test-setup.md](docs/suncorp-test-setup.md) (Phase A vs Private Link Phase B). Architecture figure: [docs/diagrams/suncorp_agentforce_otel_zerobus.png](docs/diagrams/suncorp_agentforce_otel_zerobus.png).

**Live ingest (24 Oct 2026):** Agentforce session `01a16cb0-5079-71ce-a37e-9aee0cb3c332` → 8 OTel spans → Zerobus HTTP 200 → rows in `agentforce_otel_spans`. That was on the **public** FEVM workspace. Private Link is a **separate Suncorp network build**, not something this lab can prove.

Collector YAML is the production path (EC2 or EKS in a Suncorp VPC). This lab ingested **direct OTLP Protobuf to Zerobus** when Docker was unavailable.

## Quick start

### 1. Link secrets

```bash
cd salesforce-otel
ln -sf ~/.vibe/salesforce-otel/demo.env .env
```

### 2. Start the OTel Collector (optional for local demos)

Requires Docker daemon running (`colima start` or Docker Desktop):

```bash
cd otel-collector
docker-compose up -d
docker-compose logs -f
```

If Docker is unavailable, skip to the **direct Zerobus** smoke test below
(Collector is still the recommended production path for OAuth refresh).

### 3. Smoke-test Zerobus (synthetic Agentforce-like spans)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r poller/requirements.txt

# A) Direct to Zerobus (no Collector) — verified on this FEVM workspace
python3 scripts/send_direct_zerobus.py

# B) Via local Collector (when Docker is up)
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
2. Generate a session (`sf agent test run` or an Agent Builder chat)
3. Wait for Data Cloud catch-up (several minutes), then:

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
docs/                Architecture, Salesforce setup, Suncorp test plan, PDF/DOCX readout
```

## Production notes

- Prefer Collector on **EKS** in the Suncorp VPC for HA and Private Link; **EC2** is fine for PoC.
- Grant the SP **table-level** `MODIFY` + `SELECT` (schema inheritance is not enough for Zerobus `authorization_details`).
- Zerobus accepts **Protobuf only** on OTLP/HTTP — never post Salesforce’s JSON body directly to Zerobus.
- **Private Link:** OTLP is supported; MQTT/Kafka Zerobus APIs are not. Test plan is in [docs/suncorp-test-setup.md](docs/suncorp-test-setup.md).
- Optional next step: Zero-Copy share curated span aggregates back to Salesforce Data Cloud.

## References

- [Ingest OpenTelemetry with Zerobus](https://docs.databricks.com/aws/en/ingestion/opentelemetry/)
- [Configure OTLP clients](https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure)
- [Zerobus networking / Private Link](https://docs.databricks.com/aws/en/ingestion/zerobus-networking)
- [Export Agentforce Session Tracing Data](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api.html)
