# Deploy

The Precog API ships as a CPU-only container with the TimesFM-3 weights baked
in, so it runs offline once built. **Nothing is published**: build the image
locally and load it into your runtime.

> The baked weights are under the TimesFM Non-Commercial License v1.0. Do not
> publish the resulting image (see `THIRD_PARTY_NOTICES.md`).

## Build the image

```bash
podman build --format docker -t precog-api:local .        # or: docker build
```

Behind a TLS-inspecting proxy, inject the corporate CA so pip and
Hugging Face can reach the network during the build:

```bash
podman build --format docker \
  --build-arg CA_CERT="$(cat /path/to/corp-root.crt)" \
  -t precog-api:local .
```

The build downloads torch (CPU wheel), the Precog packages and the pinned
model revision (`43046b85…`), producing a ~2.5 GB image.

## Standalone (docker compose)

```bash
cd deploy/compose
docker compose up --build        # or: podman-compose up --build
curl -s localhost:8000/v1/forecast -H 'content-type: application/json' -d \
  '{"mode":"univariate","horizon":4,"series":[{"id":"a","target":[1,2,3,4,5]}]}'
```

## Kubernetes (Helm, recommended)

Load the local image into your cluster, e.g. with kind or k3d:

```bash
kind load docker-image precog-api:local
```

Then install the chart:

```bash
helm install precog deploy/helm/precog \
  --set image.repository=precog-api --set image.tag=local
kubectl port-forward svc/precog 8000:80
```

Key values: `resources`, `autoscaling.enabled`, `podDisruptionBudget.enabled`,
`config.*` (env), `config.apiKey` (enables bearer auth).

The chart sets non-root security contexts, readiness on `/readyz` and liveness
on `/healthz`.

## Kubernetes (Kustomize)

```bash
kubectl apply -k deploy/kustomize/overlays/dev
kubectl apply -k deploy/kustomize/overlays/prod
```

## In-cluster smoke test

After loading the image into the cluster, verify the chart end-to-end:

```bash
CLEANUP=false deploy/smoke-test.sh      # installs, checks /readyz and a forecast
```

## Configuration

All runtime settings use the `PRECOG_` prefix; see
`apps/api/src/precog_api/config.py`. Model location is baked in
(`PRECOG_CACHE_DIR=/opt/precog/hf`, `HF_HUB_OFFLINE=1`), no volume required.
An optional `PRECOG_API_KEY` enables bearer auth.
