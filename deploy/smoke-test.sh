#!/usr/bin/env bash
# In-cluster smoke test for the Precog chart.
#
# Assumes the image is already built and loaded into the cluster, e.g.:
#   podman build --format docker -t precog-api:local .
#   podman save precog-api:local | sudo k3s ctr images import -   # k3s
#   kind load docker-image precog-api:local                       # kind
#
# Usage:
#   KUBECONFIG=... deploy/smoke-test.sh
#   CLEANUP=false KUBECONFIG=... deploy/smoke-test.sh
set -euo pipefail

NAMESPACE="${NAMESPACE:-precog-smoke}"
RELEASE="${RELEASE:-precog}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-localhost/precog-api}"
IMAGE_TAG="${IMAGE_TAG:-local}"
CLEANUP="${CLEANUP:-true}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">> installing release '$RELEASE' in namespace '$NAMESPACE'"
helm upgrade --install "$RELEASE" "$ROOT/deploy/helm/precog" \
  --namespace "$NAMESPACE" --create-namespace \
  --set "image.repository=$IMAGE_REPOSITORY" \
  --set "image.tag=$IMAGE_TAG" \
  --set image.pullPolicy=Never \
  --wait --timeout 5m

POD="$(kubectl -n "$NAMESPACE" get pod -l app.kubernetes.io/name=precog -o jsonpath='{.items[0].metadata.name}')"
echo ">> pod: $POD"

echo ">> forecast through the API"
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "
import json, urllib.request
payload = {'mode': 'univariate', 'horizon': 3,
           'series': [{'id': 's', 'target': [100, 102, 101, 105, 107, 106, 108, 109, 112, 111]}]}
req = urllib.request.Request('http://127.0.0.1:8000/v1/forecast',
                             data=json.dumps(payload).encode(),
                             headers={'content-type': 'application/json'})
result = json.load(urllib.request.urlopen(req))
print('model:', result['model'], '| forecast:', [round(v, 2) for v in result['results'][0]['forecast']])
"

echo ">> /readyz"
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "
import urllib.request
print('status', urllib.request.urlopen('http://127.0.0.1:8000/readyz').status)
"

if [ "$CLEANUP" = "true" ]; then
  echo ">> uninstalling"
  helm uninstall "$RELEASE" -n "$NAMESPACE"
  kubectl delete namespace "$NAMESPACE" --wait=false >/dev/null 2>&1 || true
fi

echo ">> smoke test passed"
