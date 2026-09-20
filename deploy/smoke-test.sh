#!/usr/bin/env bash
# In-cluster smoke test for a PUBLISHED Precog Helm chart.
#
# Installs the chart from the published OCI registry (never from this source
# tree) with the fake engine and verifies the canonical execution contract.
#
# Usage:
#   APP_VERSION=0.21.1 deploy/smoke-test.sh
#   APP_VERSION=0.21.1 CHART_VERSION=0.21.1 CLEANUP=false deploy/smoke-test.sh
set -euo pipefail

NAMESPACE="${NAMESPACE:-precog-smoke}"
RELEASE="${RELEASE:-precog}"
APP_VERSION="${APP_VERSION:?set APP_VERSION to the released application version, e.g. 0.21.1}"
TAG="${TAG:-v$APP_VERSION}"
CHART_VERSION="${CHART_VERSION:-$APP_VERSION}"
CHART="${CHART:-oci://ghcr.io/albe83/precog-charts/precog}"
API_REPOSITORY="${API_REPOSITORY:-ghcr.io/albe83/precog-api}"
MCP_REPOSITORY="${MCP_REPOSITORY:-ghcr.io/albe83/precog-mcp}"
CLEANUP="${CLEANUP:-true}"

echo ">> installing published chart $CHART --version $CHART_VERSION (images $TAG)"
helm upgrade --install "$RELEASE" "$CHART" \
  --version "$CHART_VERSION" \
  --namespace "$NAMESPACE" --create-namespace \
  --set "image.repository=$API_REPOSITORY" \
  --set "image.tag=$TAG" \
  --set "mcp.enabled=true" \
  --set "mcp.image.repository=$MCP_REPOSITORY" \
  --set "mcp.image.tag=$TAG" \
  --set "mcp.service.enabled=true" \
  --set "mcp.allowedHosts=*" \
  --set config.engine=fake \
  --wait --timeout 5m

POD="$(kubectl -n "$NAMESPACE" get pod -l app.kubernetes.io/name=precog -o jsonpath='{.items[0].metadata.name}')"
echo ">> pod: $POD"

echo ">> canonical forecast through the API"
kubectl -n "$NAMESPACE" exec "$POD" -c api -- python -c '
import json, urllib.request
payload = {
    "horizon": 3,
    "targets": [{"id": "s", "values": [100, 102, 101, 105, 107, 106, 108, 109, 112, 111]}],
    "quantiles": [0.1, 0.9],
}
req = urllib.request.Request(
    "http://127.0.0.1:8000/v1/forecast",
    data=json.dumps(payload).encode(),
    headers={"content-type": "application/json"},
)
result = json.load(urllib.request.urlopen(req))
assert "results" not in result and "mode" not in result, result
target = result["targets"][0]
assert len(target["forecast"]) == 3, target
assert {q["level"] for q in target["quantiles"]} == {0.1, 0.9}, target
print("model:", result["model"], "| forecast:", [round(v, 2) for v in target["forecast"]])
'

echo ">> /readyz"
kubectl -n "$NAMESPACE" exec "$POD" -c api -- python -c '
import urllib.request
print("status", urllib.request.urlopen("http://127.0.0.1:8000/readyz").status)
'

echo ">> helm test"
helm test "$RELEASE" -n "$NAMESPACE" --timeout 2m

if [ "$CLEANUP" = "true" ]; then
  echo ">> uninstalling"
  helm uninstall "$RELEASE" -n "$NAMESPACE"
  kubectl delete namespace "$NAMESPACE" --wait=false >/dev/null 2>&1 || true
fi

echo ">> smoke test passed"
