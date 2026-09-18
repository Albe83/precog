# Deploy

The Precog API ships as a CPU-only container. By default the TimesFM-3 weights
are **not baked into the image**: the entrypoint downloads them at startup into
`PRECOG_CACHE_DIR` (`/opt/precog/hf`) if they are not already there, and reuses
them on subsequent starts. The cache directory can be an ephemeral directory, a
named volume, a bind mount or a Kubernetes PVC.

> The weights are under the TimesFM Non-Commercial License v1.0. Because the
> image does not contain them, the image itself does not redistribute them. Once
> downloaded, the non-commercial restriction applies. See
> `THIRD_PARTY_NOTICES.md`.

## Build the image

```bash
podman build --format docker -t precog-api:local .        # or: docker build
```

Behind a TLS-inspecting proxy, inject the corporate CA so the runtime download
can reach Hugging Face:

```bash
podman build --format docker \
  --build-arg CA_CERT="$(cat /path/to/corp-root.crt)" \
  -t precog-api:local .
```

For air-gapped clusters, bake the weights (larger image, no runtime download):

```bash
podman build --format docker --build-arg PRECOG_BAKE_WEIGHTS=true -t precog-api:local .
```

## Standalone (docker compose)

```bash
cd deploy/compose
docker compose up --build        # or: podman-compose up --build
```

The service mounts the named volume `precog-models` at `/opt/precog/hf`. The
first start downloads ~1.3 GB (a couple of minutes); later starts are fast.
Swap the volume for an anonymous volume or a bind mount if you prefer.

```bash
curl -s localhost:8000/v1/forecast -H 'content-type: application/json' -d \
  '{"mode":"univariate","horizon":4,"series":[{"id":"a","target":[1,2,3,4,5]}]}'
```

## Kubernetes (Helm, recommended)

Load the local image into your cluster, e.g. with kind or k3s:

```bash
kind load docker-image precog-api:local
```

Install the chart:

```bash
helm install precog deploy/helm/precog \
  --set image.repository=precog-api --set image.tag=local
```

Defaults are conservative: an **ephemeral `emptyDir`** cache and a single
replica, so no StorageClass or RWX support is assumed. A `startupProbe` allows
the cold start (download + model load) before liveness runs.

To persist the cache, enable a PVC (created by the chart):

```bash
helm install precog deploy/helm/precog \
  --set modelCache.persistence.enabled=true \
  --set modelCache.persistence.size=5Gi
```

Use `modelCache.persistence.existingClaim` to bring your own claim. For more
than one replica sharing a single cache, use `ReadWriteMany`:

```bash
--set modelCache.persistence.accessModes[0]=ReadWriteMany --set replicaCount=2
```

Other useful values: `modelCache.preload` (`auto`/`always`/`never`),
`modelCache.revision`, `modelCache.hfTokenSecret` (Secret name; token in key
`hf-token`).

```bash
kubectl port-forward svc/precog 8000:80
```

## Kubernetes (Kustomize)

```bash
kubectl apply -k deploy/kustomize/overlays/dev
kubectl apply -k deploy/kustomize/overlays/prod
```

The base uses an `emptyDir` for the cache; patch it with a PVC or `hostPath` if
you want the weights to persist.

## In-cluster smoke test

After loading the image into the cluster, verify the chart end-to-end:

```bash
CLEANUP=false deploy/smoke-test.sh      # installs, checks /readyz and a forecast
```

## Configuration

All runtime settings use the `PRECOG_` prefix; see
`apps/api/src/precog_api/config.py`. Model-related settings:

| Variable | Meaning | Default |
| -------- | ------- | ------- |
| `PRECOG_MODEL_ID` | Hugging Face repo | `google/timesfm-3.0-pytorch` |
| `PRECOG_MODEL_REVISION` | Pinned revision | `43046b85…` |
| `PRECOG_CACHE_DIR` | Where weights live | `/opt/precog/hf` |
| `PRECOG_PRELOAD` | `auto` / `always` / `never` | `auto` |
| `PRECOG_HF_TOKEN` | Token for gated repos | unset |
| `PRECOG_LOCAL_FILES_ONLY` | Avoid network lookups | `true` in the image |

An optional `PRECOG_API_KEY` enables bearer auth.
