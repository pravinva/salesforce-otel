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

kubectl -n "$NS" create configmap session-poller-code \
  --from-file="$ROOT/poller/poll_agentforce.py" \
  --from-file="$ROOT/poller/json_to_otlp.py" \
  --from-file="$ROOT/poller/requirements.txt" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f "$ROOT/otel-collector/k8s/poller.yaml"

if [[ -n "${SALESFORCE_CLIENT_ID:-}" && -n "${SALESFORCE_CLIENT_SECRET:-}" ]]; then
  kubectl -n "$NS" create secret generic sf-poller \
    --from-literal=SALESFORCE_INSTANCE_URL="${SALESFORCE_INSTANCE_URL:?}" \
    --from-literal=SALESFORCE_CLIENT_ID="$SALESFORCE_CLIENT_ID" \
    --from-literal=SALESFORCE_CLIENT_SECRET="$SALESFORCE_CLIENT_SECRET" \
    --from-literal=SALESFORCE_API_VERSION="${SALESFORCE_API_VERSION:-v66.0}" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo
  echo "In-cluster poller (CronJob suspended until you unsuspend or run a Job):"
  echo "  kubectl -n $NS create job session-poller-once --from=cronjob/session-poller"
  echo "  kubectl -n $NS logs -l app=session-poller --tail=50"
  echo "  kubectl -n $NS patch cronjob session-poller -p '{\"spec\":{\"suspend\":false}}'"
else
  echo
  echo "CronJob session-poller is applied but Jobs fail until sf-poller exists."
  echo "Set SALESFORCE_CLIENT_ID and SALESFORCE_CLIENT_SECRET (External Client App) in"
  echo "$ENV_FILE, then re-run this script."
  echo "Laptop fallback:"
  echo "  kubectl -n $NS port-forward svc/otel-collector 4318:4318"
  echo "  OTEL_COLLECTOR_TRACES_URL=http://127.0.0.1:4318/v1/traces python3 poller/poll_agentforce.py"
fi

kubectl -n "$NS" get pods,svc,cronjob
