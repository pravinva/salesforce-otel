# Salesforce Agentforce setup (OrgFarm / Developer Edition)

Org used for this demo:

- Login URL: `https://orgfarm-91850b6147-dev-ed.develop.my.salesforce.com`
- Username: `pravin.varmadbrx.24b133d4e353@agentforce.com`
- Alias (sf CLI): `orgfarm918`
- Agent used for live traces: **Agentforce (Default)** / `Copilot_for_Salesforce`

## Current org status (24 Oct 2026)

| Check | Result |
|-------|--------|
| sf CLI login | Connected (`orgfarm918`) |
| Data Cloud | **Enabled**; Data Space `default` (`0vhaj000001VLKXAA4`) **ACTIVE** |
| Einstein Audit dataspace | **Bound to `default`** (Setup UI only — not Metadata API) |
| Agentforce Session Tracing | On |
| Agent Platform Tracing | On |
| Audit and Feedback | On (`enableAIFeedbackWithDC = true`) |
| Session Trace OTel API | **Healthy** — dummy UUID returns `404 session not found` |
| `ssot__AiAgentSession__dlm` | **Mapped and queryable** |
| `GenAIFeedback__dlm` | **Mapped and queryable** |
| SSOT entities | **153** after tracing semantic model finished |
| Live session ingested | `01a16cb0-5079-71ce-a37e-9aee0cb3c332` → 8 spans in Delta |

CLI cannot set the Einstein Audit Data Space picker. After Data Cloud shows
**Enabled**, open:

`sf org open -o orgfarm918 -p lightning/setup/EinsteinAuditAnalyticsMonitoring/home`

Hard-refresh, choose **default**, Save. Until that bind exists, OTel returns
`No selected dataspace for Einstein Audit`.

Provisioning after the bind is sequential. OTel may 500 on missing
`ssot__AiAgentSession__dlm` then `GenAIFeedback__dlm` for 15–60+ minutes.

## 1. Enable Agentforce

1. Setup → Quick Find → **Agentforce Settings**
2. Toggle **Enable Agentforce** → On (Default agent cannot be `sf agent activate`’d)

## 2. Enable Data 360 + Session Tracing + Audit

1. Setup → **Data Cloud Setup Home** — turn on Data 360 and wait until **Enabled**
2. Setup → **Einstein Audit, Analytics, and Monitoring Setup** (not the Agentforce model page)
3. Select Data Space **`default`** and Save
4. Confirm:
   - **Agentforce Session Tracing**
   - **Audit and Feedback**
   - **Agent Platform Tracing** if listed

Useful permsets on the running user: `GenieAdmin` (Data Cloud Architect),
`CopilotSalesforceUser`, `CopilotSalesforceAdmin`. `CDPAdmin` may fail on DE
(`CdpPsl` disabled); Genie starter PSL is the DE licence.

## 3. Activate Data 360 streams

In **Data Cloud → Data Streams**, ensure these are Active and refresh each:

- `AiAgentSession`
- `AiAgentInteraction`
- `AiAgentInteractionMessage`
- `AiAgentInteractionStep`

Until streams are mapped, OTel can 500 (`table does not exist`) or 404 even
after chats. Data Cloud catch-up after a conversation was **~6 minutes** in this lab.

## 4. Generate a traced session (CLI)

Default Agentforce agent is enough; a custom service agent is optional.

```bash
# One-off test spec → org (see /tmp or a local specs/ file)
sf agent test create --spec specs/OTel_Demo_Test.yaml \
  --api-name OTel_Demo_Test --target-org orgfarm918 --force-overwrite

sf agent test run --api-name OTel_Demo_Test --target-org orgfarm918 --wait 10 --verbose
```

Utterance used in the lab: `Hello, what can you do?`  
Expected topic: `GeneralCRM`  
Session id is in `generatedData.sessionId`.

Alternatively chat in Agent Builder / Copilot panel. Draft-only preview on an
**inactive** custom bot often never lands in Session Tracing.

## 5. Poll OTel

```
GET /services/data/v66.0/einstein/audit/otel/{session-id}
```

- One session ID per request (no bulk yet)
- Sessions must have `StartTimestamp` within the prior **72 hours**
- Dummy UUID → `404 session not found` means the API is enabled
- Empty `spanId` on evaluation spans (`TaskResolution`, `InstructionAdherence`)
  is handled in `poller/json_to_otlp.py`

The poller **pulls** this JSON, converts to Protobuf, then **pushes** to the
Collector (`OTEL_COLLECTOR_TRACES_URL`, default `http://127.0.0.1:4318/v1/traces`
after `kubectl port-forward` to EKS).

```bash
sf org display -o orgfarm918
DRY_RUN=true python3 poller/poll_agentforce.py
# Pin a session and push Protobuf to the Collector:
SALESFORCE_SESSION_ID=01a16cb0-5079-71ce-a37e-9aee0cb3c332 \
  OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces \
  python3 poller/poll_agentforce.py
```

## 6. External Client App (recommended for unattended poller)

1. Setup → External Client Apps / App Manager
2. Enable **Client Credentials Flow**
3. API scope: **Manage user data via APIs (`api`)**  
   Using only `full` can fail with `invalid_grant: no valid scopes defined`
4. Set **Run As** to a user with Data Cloud + Einstein Audit access
5. Copy Consumer Key / Secret into `SALESFORCE_CLIENT_ID` / `SALESFORCE_CLIENT_SECRET`

Until the ECA exists, the poller falls back to the `sf` CLI session for `orgfarm918`.
