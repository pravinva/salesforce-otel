# Suncorp — recommended test setup

![Suncorp Agentforce OpenTelemetry to Databricks Lakehouse](diagrams/suncorp_agentforce_otel_zerobus.png)

Background and architecture are in [architecture.md](architecture.md). This
page is the test plan only.

Suncorp workspaces use **AWS front-end Private Link**. The ingest path is
Zerobus Ingest OTLP into Delta. Split the proof across two environments.
The Field Engineering FEVM lab is a public workspace, so Private Link
checks run on a Suncorp PL workspace.

| Phase | Where | What it proves | Status |
|-------|--------|----------------|--------|
| **A1 — Functional ingest** | FEVM `fevm-ot-pdm-semi` | Session GET → Protobuf POST → public Zerobus → Delta | **Done** (24 Oct 2026) |
| **A2 — Collector in a VPC** | EKS `agentforce-otel` in AWS `332745928618` / `ap-southeast-2` | OTel Collector on Fargate **pushes** to public Zerobus | **Done** (24 Oct 2026) |
| **B — Private path** | Suncorp PL workspace, same region as the VPC | Collector POSTs through the VPC endpoint and private DNS | **Needs Suncorp networking** |

The Salesforce session API is a **GET** of OTLP JSON for one session.
Zerobus ingest is a **POST** of OTLP Protobuf. The poller is the Salesforce
client; the Collector (or the poller in A1) is the Zerobus client. Phase B
keeps those contracts and sends the POST through a VPC endpoint and private
DNS.

## Phase A — already demonstrated (FEVM ingest + EKS Collector)

Live session `01a16cb0-5079-71ce-a37e-9aee0cb3c332` (utterance: *Hello, what can
you do?*) produced **8 spans**. Zerobus returned HTTP **200**. Rows in
`ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans` included
`GeneralCRM_16jaj000003iyMv`, `AiCopilot__ReactInitialPrompt`,
`CLOSED_USER_REQUEST`, `TaskResolution`, `InstructionAdherence`.

Repeat on FEVM (direct push, no Collector):

```bash
python3 scripts/send_direct_zerobus.py
DRY_RUN=true python3 poller/poll_agentforce.py
OTEL_COLLECTOR_TRACES_URL="https://${WORKSPACE_ID}.zerobus.${REGION}.cloud.databricks.com:443/v1/traces" \
  python3 poller/poll_agentforce.py
```

Repeat via **EKS in the demo VPC** (poller CronJob GETs Salesforce, POSTs
Protobuf to the Collector ClusterIP; Collector POSTs to Zerobus):

```bash
export AWS_PROFILE=unity-gateway-demo
aws eks update-kubeconfig --name agentforce-otel --region ap-southeast-2
otel-collector/k8s/deploy.sh
kubectl -n agentforce-otel create job session-poller-once --from=cronjob/session-poller
kubectl -n agentforce-otel logs -l app=session-poller --tail=80
```

The CronJob needs secret `sf-poller` (External Client App). Until that exists,
use the laptop fallback: `kubectl port-forward svc/otel-collector 4318:4318`
and `OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces python3 poller/poll_agentforce.py`.

```sql
SELECT time, service_name, name
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
ORDER BY time DESC
LIMIT 20;
```

## Phase B — Private Link test (Suncorp must provision)

Zerobus OTLP is a documented front-end Private Link service on **TCP 443**.
MQTT and Kafka-compatible Zerobus APIs use a separate networking model. See [Zerobus networking](https://docs.databricks.com/aws/en/ingestion/zerobus-networking)
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
5. Collector + poller in a **Suncorp VPC**. The Collector POSTs to the
   Private Link Zerobus hostname.
6. If Delta storage is firewalled: allowlist Databricks **serverless outbound
   IPs** for that region (Zerobus → table storage is a second hop).
7. Unity Catalog tables + table-level `SELECT`/`MODIFY` on a Suncorp catalog
   (same DDL as `sql/01_create_otel_tables.sql`, different three-part names).

The Salesforce GET to `/einstein/audit/otel/{id}` uses Salesforce’s network
path. Databricks Private Link covers Collector → Zerobus. Private Salesforce
egress is **Salesforce Private Connect** (or an approved allowlist), as a
separate control.

### Phase B test cases (run from the VPC)

| ID | Test | Pass criteria |
|----|------|----------------|
| PL-1 | `dig` / `nslookup` of the service-direct / Zerobus PL hostname | Returns **private** VPC endpoint IP |
| PL-2 | `nc -vz <pl-hostname> 443` from the collector subnet | Connects |
| PL-3 | Same check against the **public** `*.zerobus.*.cloud.databricks.com` name from that subnet | **Fails** (no public route) |
| PL-4 | OTLP Protobuf POST `/v1/traces` through the collector | HTTP 200 |
| PL-5 | SQL on the Suncorp UC span table | New rows for the test session |
| PL-6 | (Optional) Salesforce poller to OTel API | 200 with spans **or** documented Salesforce Private Connect path |

Phase B is complete when PL-1, PL-2, PL-4, and PL-5 pass, and PL-3 shows
the public hostname is unreachable from that subnet.

### Suggested owners

| Work | Owner |
|------|--------|
| VPC endpoint, DNS, SG, no public Zerobus route | Suncorp network / cloud |
| Workspace PL registration, serverless IP allowlist | Suncorp Databricks admin + Databricks SA |
| Collector + poller on EKS in the Suncorp VPC | Suncorp platform (pattern already on FE EKS `agentforce-otel`) |
| Agentforce session + Data Cloud tracing | Suncorp Salesforce admin |
| Repeat ingest + SQL readout | Joint |

## Recommended sequence for Suncorp

1. Accept Phase A1 (direct ingest) and A2 (Collector in a VPC) as the
   functional proof: session GET, Protobuf POST, Zerobus, Delta.
2. Book a Phase B window on a **non-prod PL workspace** in the producer region.
3. Reuse [`otel-collector/k8s/`](../otel-collector/k8s/) in the Suncorp VPC
   (swap catalog/schema/workspace ID; keep Protobuf + `x-databricks-zerobus-table-name`).
4. Run PL-1 … PL-5 with a synthetic span first, then one live Agentforce chat.
5. Only then discuss HA replicas, logs/metrics tables, and MLflow eval on VARIANT.

## Out of scope until Phase B exists

- Proving “denied public Zerobus” from this laptop or FEVM
- Changing FEVM to Private Link
- End-to-end private Salesforce **and** Databricks in one hop without Salesforce
  Private Connect
