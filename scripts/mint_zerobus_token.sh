#!/usr/bin/env bash
# Mint a short-lived Zerobus OAuth token (expires ~1h). Prefer the Collector for demos.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
elif [[ -f "$HOME/.vibe/salesforce-otel/demo.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$HOME/.vibe/salesforce-otel/demo.env"
  set +a
fi

: "${DATABRICKS_CLIENT_ID:?}"
: "${DATABRICKS_CLIENT_SECRET:?}"
: "${WORKSPACE_URL:?}"
: "${WORKSPACE_ID:?}"
: "${CATALOG:?}"
: "${SCHEMA:?}"
: "${TABLE_PREFIX:?}"

TABLE_NAME="${CATALOG}.${SCHEMA}.${TABLE_PREFIX}_otel_spans"

authorization_details=$(cat <<EOF
[{
  "type": "unity_catalog_privileges",
  "privileges": ["USE CATALOG"],
  "object_type": "CATALOG",
  "object_full_path": "$CATALOG"
},
{
  "type": "unity_catalog_privileges",
  "privileges": ["USE SCHEMA"],
  "object_type": "SCHEMA",
  "object_full_path": "$CATALOG.$SCHEMA"
},
{
  "type": "unity_catalog_privileges",
  "privileges": ["SELECT", "MODIFY"],
  "object_type": "TABLE",
  "object_full_path": "$TABLE_NAME"
}]
EOF
)

curl -sS -X POST \
  -u "$DATABRICKS_CLIENT_ID:$DATABRICKS_CLIENT_SECRET" \
  -d "grant_type=client_credentials" \
  -d "scope=all-apis" \
  -d "resource=api://databricks/workspaces/$WORKSPACE_ID/zerobusDirectWriteApi" \
  --data-urlencode "authorization_details=$authorization_details" \
  "https://$WORKSPACE_URL/oidc/v1/token" | python3 -m json.tool
