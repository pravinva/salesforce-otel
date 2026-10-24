# Suncorp — recommended test setup

![Suncorp Agentforce OpenTelemetry to Databricks Lakehouse](diagrams/suncorp_agentforce_otel_zerobus.png)

Suncorp wants Agentforce OTel traces in Databricks for centralised AI
observability, on workspaces with **AWS Private Link enforced end-to-end**.

Split the proof into two environments. Do **not** try to prove Private Link on
the Field Engineering FEVM lab — that workspace is public.

| Phase | Where | What it proves | Status |
|-------|--------|----------------|--------|
| **A — Functional ingest** | FEVM `fevm-ot-pdm-semi` (this repo) | Agentforce → poll OTel JSON → Protobuf → Zerobus → Delta, no Kafka | **Done** (24 Oct 2026) |
| **B — Private path** | Suncorp PL workspace, same region as producers | Traffic never uses the public Zerobus hostname | **Needs Suncorp networking** |

Phase B is extra network work. It does not require re-enabling Salesforce
Session Tracing if Suncorp already has a Data Cloud + Agentforce org; it
requires VPC endpoints, private DNS, and a collector in a Suncorp VPC.

## Phase A — already demonstrated (FEVM)

Live session `01a16cb0-5079-71ce-a37e-9aee0cb3c332` (utterance: *Hello, what can
you do?*) produced **8 spans**. Zerobus returned HTTP **200**. Rows in
`ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans` included
`GeneralCRM_16jaj000003iyMv`, `AiCopilot__ReactInitialPrompt`,
`CLOSED_USER_REQUEST`, `TaskResolution`, `InstructionAdherence`.

Repeat on FEVM:

```bash
# Synthetic contract check
python3 scripts/send_direct_zerobus.py

# After a chat / sf agent test run (Data Cloud catch-up can take several minutes)
DRY_RUN=true python3 poller/poll_agentforce.py
OTEL_COLLECTOR_TRACES_URL="https://${WORKSPACE_ID}.zerobus.${REGION}.cloud.databricks.com:443/v1/traces" \
  python3 poller/poll_agentforce.py   # or scripts/send_direct_zerobus.py-style POST
```

```sql
SELECT time, service_name, name
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
ORDER BY time DESC
LIMIT 20;
```

## Phase B — Private Link test (Suncorp must provision)

Zerobus OTLP **does** support front-end Private Link. MQTT and Kafka-compatible
Zerobus APIs **do not**. See [Zerobus networking](https://docs.databricks.com/aws/en/ingestion/zerobus-networking)
and [inbound PrivateLink for performance-intensive services](https://docs.databricks.com/aws/en/security/network/front-end/service-direct-privatelink)
(Zerobus listed on **TCP 443**).

### What Suncorp networking needs to stand up

1. Workspace with **front-end Private Link** (existing Suncorp posture).
2. AWS **VPC endpoint** for workspace front-end and/or **inbound PL for
   performance-intensive services** in the **same region** as the workspace
   (Zerobus is regional).
3. **Private DNS** so
   `{region}.service-direct.privatelink.cloud.databricks.com` (and Zerobus
   names) resolve to the **VPC endpoint IP**, not public anycast.
4. Subnet security group: inbound **TCP 443** from the collector/poller
   security group.
5. Collector + poller in a **Suncorp VPC** with **no public route** to
   `*.zerobus.*.cloud.databricks.com`.
6. If Delta storage is firewalled: allowlist Databricks **serverless outbound
   IPs** for that region (Zerobus → table storage is a second hop).
7. Unity Catalog tables + table-level `SELECT`/`MODIFY` on a Suncorp catalog
   (same DDL as `sql/01_create_otel_tables.sql`, different three-part names).

Salesforce REST to `/einstein/audit/otel/{id}` is **not** covered by Databricks
Private Link. Privatise that hop separately with **Salesforce Private Connect**
(or an approved egress to Salesforce API hostnames).

### Phase B test cases (run from the VPC)

| ID | Test | Pass criteria |
|----|------|----------------|
| PL-1 | `dig` / `nslookup` of the service-direct / Zerobus PL hostname | Returns **private** VPC endpoint IP |
| PL-2 | `nc -vz <pl-hostname> 443` from the collector subnet | Connects |
| PL-3 | Same check against the **public** `*.zerobus.*.cloud.databricks.com` name from that subnet | **Fails** (no public route) |
| PL-4 | OTLP Protobuf POST `/v1/traces` through the collector | HTTP 200 |
| PL-5 | SQL on the Suncorp UC span table | New rows for the test session |
| PL-6 | (Optional) Salesforce poller to OTel API | 200 with spans **or** documented Salesforce Private Connect path |

Do not call Phase B complete unless **PL-3** fails and **PL-4/PL-5** succeed.
That is the evidence Suncorp’s “full Private Link” control is doing work.

### Suggested owners

| Work | Owner |
|------|--------|
| VPC endpoint, DNS, SG, no public Zerobus route | Suncorp network / cloud |
| Workspace PL registration, serverless IP allowlist | Suncorp Databricks admin + Databricks SA |
| Collector + poller on EKS/EC2 in the VPC | Suncorp platform / FE overlay |
| Agentforce session + Data Cloud tracing | Suncorp Salesforce admin |
| Repeat ingest + SQL readout | Joint |

## Recommended sequence for Suncorp

1. Accept Phase A (this repo) as the **functional** proof — no message bus.
2. Book a Phase B window on a **non-prod PL workspace** in the producer region.
3. Deploy this repo’s Collector YAML in the VPC (swap catalog/schema/workspace
   ID; keep Protobuf + `x-databricks-zerobus-table-name`).
4. Run PL-1 … PL-5 with a synthetic span first, then one live Agentforce chat.
5. Only then discuss HA (EKS), logs/metrics tables, and MLflow eval on VARIANT.

## Out of scope until Phase B exists

- Proving “denied public Zerobus” from this laptop or FEVM
- Changing FEVM to Private Link
- End-to-end private Salesforce **and** Databricks in one hop without Salesforce
  Private Connect
