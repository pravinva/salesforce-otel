#!/usr/bin/env bash
# Deploy the OTel Collector onto EKS cluster agentforce-otel (ap-southeast-2).
# Secrets are read from ~/.vibe/salesforce-otel/demo.env and never written to git.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-unity-gateway-demo}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
CLUSTER="${CLUSTER:-agentforce-otel}"
NS=agentforce-otel
ENV_FILE="${ENV_FILE:-$HOME/.vibe/salesforce-otel/demo.env}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${DATABRICKS_CLIENT_ID:?}"
: "${DATABRICKS_CLIENT_SECRET:?}"
: "${WORKSPACE_URL:?}"
: "${WORKSPACE_ID:?}"
: "${REGION:?}"
: "${CATALOG:?}"
: "${SCHEMA:?}"
: "${TABLE_PREFIX:?}"

aws eks update-kubeconfig --name "$CLUSTER" --region "$AWS_REGION" --profile "$AWS_PROFILE"

kubectl apply -f "$ROOT/otel-collector/k8s/collector.yaml"

kubectl -n "$NS" create secret generic otel-zerobus \
  --from-literal=DATABRICKS_CLIENT_ID="$DATABRICKS_CLIENT_ID" \
  --from-literal=DATABRICKS_CLIENT_SECRET="$DATABRICKS_CLIENT_SECRET" \
  --from-literal=WORKSPACE_URL="$WORKSPACE_URL" \
  --from-literal=WORKSPACE_ID="$WORKSPACE_ID" \
  --from-literal=REGION="$REGION" \
  --from-literal=CATALOG="$CATALOG" \
  --from-literal=SCHEMA="$SCHEMA" \
  --from-literal=TABLE_PREFIX="$TABLE_PREFIX" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$NS" rollout restart deployment/otel-collector
kubectl -n "$NS" rollout status deployment/otel-collector --timeout=180s
kubectl -n "$NS" get pods,svc
echo
echo "Port-forward for the laptop poller:"
echo "  kubectl -n $NS port-forward svc/otel-collector 4318:4318"
echo "Then: OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces python3 poller/poll_agentforce.py"
