# Salesforce Agentforce setup (OrgFarm / Developer Edition)

Org used for this demo:

- Login URL: `https://orgfarm-91850b6147-dev-ed.develop.my.salesforce.com`
- Username: `pravin.varmadbrx.24b133d4e353@agentforce.com`
- Alias (sf CLI): `orgfarm918`

## Current org status (checked during scaffold)

Against `orgfarm-91850b6147-dev-ed`:

| Check | Result |
|-------|--------|
| sf CLI login | Connected (`orgfarm918`) |
| `AiAgent` sObject | Present |
| Session Trace OTel API | **`FUNCTIONALITY_NOT_ENABLED`** (`EinsteinAuditResourceFamily`) |
| `ssot__AiAgentSession__dlm` | **Not available** (Data 360 Session Tracing DMOs not provisioned) |

Until Einstein Audit / Session Tracing is enabled, the poller cannot fetch live
Agentforce OTel. The Databricks Zerobus path is already validated with synthetic spans.

## 1. Enable Agentforce

1. Setup → Quick Find → **Agentforce Settings**
2. Toggle **Enable Agentforce** → On

## 2. Enable Data 360 + Session Tracing + Audit

1. Setup → **Data Cloud Setup Home** — turn on Data 360 and wait until live
2. Setup → **Einstein Audit, Analytics, and Monitoring Setup**
3. Confirm a dataspace is selected (often `default`)
4. Turn on:
   - **Agentforce Session Tracing** (Data model can take ~10 minutes)
   - **Audit and Feedback**
   - **Agent Platform Tracing** if listed

If the OTel API still returns `FUNCTIONALITY_NOT_ENABLED`, the org edition may
lack Einstein Audit entitlements — use a **Data Cloud & Agentforce Developer Trial**
from [Salesforce free trials](https://www.salesforce.com/form/developer-signup/) rather than a plain OrgFarm.

## 3. Activate Data 360 streams

In **Data Cloud → Data Streams**, ensure these are Active and refresh each:

- `AiAgentSession`
- `AiAgentInteraction`
- `AiAgentInteractionMessage`
- `AiAgentInteractionStep`

Until streams are active, the OTel API can return `404` even after chats.

## 4. Create / activate a test agent

1. Setup → **Agents** → New Agent → Service Agent  
   Name example: `Databricks Ingest Tester`
2. **Activate / publish** the agent  
   Draft-only preview sessions often do **not** appear in Session Tracing.

## 5. Generate telemetry

In Agentforce Builder Preview (or the published channel), run a multi-turn chat:

> Hello, what can you do? Can you help me look up a standard tool?

Wait a few minutes for Data 360 catch-up, then run the poller.

## 6. External Client App (recommended for the poller)

For unattended polling, create an **External Client App**:

1. Setup → External Client Apps / App Manager
2. Enable **Client Credentials Flow**
3. API scope: **Manage user data via APIs (`api`)**  
   Using only `full` can fail with `invalid_grant: no valid scopes defined`
4. Set **Run As** to a user with Data Cloud + Einstein Audit access
5. Copy Consumer Key / Secret into:

```bash
SALESFORCE_CLIENT_ID=...
SALESFORCE_CLIENT_SECRET=...
```

Until the ECA exists, the poller falls back to the `sf` CLI session for `orgfarm918`.

## 7. OTel API (beta) limits

```
GET /services/data/v66.0/einstein/audit/otel/{session-id}
```

- One session ID per request (no bulk yet)
- Sessions must have `StartTimestamp` within the prior **72 hours**
- Data 360 required for the beta
- Connect API rate limits apply

## 8. Verify from CLI

```bash
sf org display -o orgfarm918
# After a conversation + Data 360 catch-up:
cd poller && DRY_RUN=true python3 poll_agentforce.py
```
