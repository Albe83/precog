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

## Published images

Weight-free images are published to GHCR on each release (and via manual
dispatch):

```bash
docker pull ghcr.io/albe83/precog-api:latest   # downloads weights at runtime
docker pull ghcr.io/albe83/precog-mcp:latest   # no weights at all
```

The Helm chart is published per release as an OCI chart
(`oci://ghcr.io/albe83/precog-charts/precog`, pin with `--version`) and as a
`.tgz` asset on the GitHub release. See
[`deploy/helm/precog/README.md`](../deploy/helm/precog/README.md).

The CI verifies that no weights are embedded before pushing. **Never** publish
an image built with `PRECOG_BAKE_WEIGHTS=true`: that variant embeds the
non-commercial weights and is intended only for local, air-gapped builds.

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
  '{"horizon":4,"targets":[{"id":"a","values":[1,2,3,4,5]}],"quantiles":[0.1,0.9]}'
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
replica, so no StorageClass is assumed. A `startupProbe` allows the cold start
(download + model load) before liveness runs.

To persist the cache, enable a PVC (created by the chart). The claim defaults to
**`ReadWriteMany`** so scaling up reuses the same volume instead of recreating
it:

```bash
helm install precog deploy/helm/precog \
  --set modelCache.persistence.enabled=true \
  --set modelCache.persistence.size=5Gi
```

If your StorageClass only supports `ReadWriteOnce`, override it (keep a single
replica in that case):

```bash
--set modelCache.persistence.accessModes[0]=ReadWriteOnce
```

Use `modelCache.persistence.existingClaim` to bring your own claim. Other useful
values: `modelCache.preload` (`auto`/`always`/`never`), `modelCache.revision`,
`modelCache.hfTokenSecret` (Secret name; token in key `hf-token`),
`modelCache.downloadInitContainer.enabled` and `modelCache.downloadJob.enabled`.

```bash
kubectl port-forward svc/precog 8000:80
```

Full value reference and more install scenarios (published images, persistence,
download Job/initContainer, MCP, autoscaling):
[`deploy/helm/precog/README.md`](../deploy/helm/precog/README.md).

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

## Multi-replica: who downloads the model

Each pod ensures the model is available at startup (entrypoint) or in an
initContainer. Behaviour depends on the cache volume:

- **`emptyDir` (default)** — per-pod volume. Every replica downloads its own
  copy; nothing is shared, and each new pod downloads again. Simple, no
  StorageClass needed.
- **PVC `ReadWriteMany` (recommended for scaling)** — shared cache. The first pod
  that starts downloads; the others find the files and skip. Concurrent
  downloads are serialized by the Hugging Face cache lock. Requires an
  RWX-capable StorageClass.
- **PVC `ReadWriteOnce`** — only one pod per node can mount it. Do not scale
  beyond one replica; use `emptyDir` if you need more.
- **Pre-seeded / air-gapped** — populate the volume once, then set
  `modelCache.preload=never`: replicas never download and fail fast (clear error)
  if the model is missing.
- **`modelCache.downloadInitContainer.enabled=true`** — the download runs in an
  initContainer before the app container, which then uses `PRECOG_PRELOAD=never`
  and only reads from the cache. Useful to keep network I/O out of the app
  container.
- **`modelCache.downloadJob.enabled=true`** — a one-shot Job (post-install /
  post-upgrade hook) pre-populates the cache. It requires a persistent cache
  (`persistence.enabled=true` or `persistence.existingClaim`). To download once
  and never from the pods, install with the Job and `replicaCount=0`, wait for
  it, then scale up with `preload=never`:

  ```bash
  helm install precog deploy/helm/precog \
    --set modelCache.persistence.enabled=true \
    --set modelCache.downloadJob.enabled=true \
    --set replicaCount=0
  kubectl wait --for=condition=complete job/precog-model-download --timeout=10m
  helm upgrade precog deploy/helm/precog \
    --set modelCache.persistence.enabled=true \
    --set modelCache.preload=never --set replicaCount=2
  ```

  If you leave `preload=auto`, the Job only warms the cache and the pods remain
  self-healing (they download if needed, serialized by the Hugging Face lock).

The cache check requires both `config.json` and `model.safetensors` in a
snapshot directory, so a partially downloaded snapshot is never treated as
complete.

Multiple revisions can coexist in the cache (Hugging Face keeps one snapshot per
revision). Set `PRECOG_PRUNE_OLD_REVISIONS=true` (Helm:
`modelCache.pruneOldRevisions=true`) to remove snapshots other than the pinned
`PRECOG_MODEL_REVISION` after download, freeing disk when rotating revisions.

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
| `PRECOG_RATE_LIMIT_REQUESTS` | Requests per window per client (0 = off) | `0` |
| `PRECOG_RATE_LIMIT_WINDOW_S` | Rate-limit window in seconds | `60` |
| `PRECOG_LOG_JSON` | JSON logs | `true` |

An optional `PRECOG_API_KEY` enables bearer auth.

### Effective limits

`PRECOG_MAX_CONTEXT` and `PRECOG_MAX_SERIES` are upper bounds. The API
advertises (via `/v1/capabilities`) and enforces the intersection with the
active engine's effective capabilities: the current TimesFM-3 backend honors at
most 15360 context samples and 32 variates (targets plus covariates) per joint
forecast. A request above either limit is rejected with `422` before inference
instead of being silently truncated or subsampled; MCP consumers receive
`FORECAST_REJECTED`.
