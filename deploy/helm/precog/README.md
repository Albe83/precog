# precog

Helm chart for the Precog TimesFM-3 zero-shot forecasting API (CPU), with an
optional MCP server. Model weights are **not baked into the image**: they are
downloaded at startup into a cache volume (or pre-seeded), so the images are
weight-free.

- Chart version: `0.2.0` · app version: `0.4.0`
- Images: `ghcr.io/albe83/precog-api`, `ghcr.io/albe83/precog-mcp` (weight-free)

## Prerequisites

- Kubernetes 1.24+ (`apps/v1`, `policy/v1`).
- Container images: the published ones above, or a local build.
- Egress to `huggingface.co` for the first download, unless the cache volume is
  pre-seeded (`modelCache.preload=never`).
- A StorageClass supporting `ReadWriteMany` if you enable a shared cache PVC
  (otherwise use `ReadWriteOnce` with one replica, or the default `emptyDir`).

## Install with the published images

```bash
helm install precog deploy/helm/precog \
  --namespace precog --create-namespace \
  --set image.repository=ghcr.io/albe83/precog-api \
  --set image.tag=v0.4.0 \
  --set mcp.enabled=true \
  --set mcp.image.repository=ghcr.io/albe83/precog-mcp \
  --set mcp.image.tag=v0.4.0 \
  --set mcp.allowedHosts="precog-mcp.precog.svc:80"
```

`mcp.allowedHosts` is needed because the MCP HTTP transport validates the Host
header (DNS-rebinding protection); behind a gateway or a Service DNS name the
default localhost-only allowlist rejects it. Use `"*"` to disable the check when
the listener is reachable only through a trusted gateway plus NetworkPolicy.

## Install with a locally built image

```bash
podman build --format docker -t precog-api:local .
kind load docker-image precog-api:local    # or: k3s ctr images import
helm install precog deploy/helm/precog --set image.pullPolicy=Never
```

## Common scenarios

Persist the model cache (avoids re-downloading on restart):

```bash
helm upgrade --install precog deploy/helm/precog \
  --set modelCache.persistence.enabled=true \
  --set modelCache.persistence.size=5Gi
```

`ReadWriteMany` is the default; on a `ReadWriteOnce`-only StorageClass use a
single replica and override the access mode:

```bash
--set modelCache.persistence.accessModes[0]=ReadWriteOnce --set replicaCount=1
```

Download once and never from the pods (install scaled to zero, run the Job,
then scale up):

```bash
helm install precog deploy/helm/precog \
  --set modelCache.persistence.enabled=true \
  --set modelCache.downloadJob.enabled=true --set replicaCount=0
kubectl wait --for=condition=complete job/precog-model-download --timeout=10m
helm upgrade precog deploy/helm/precog \
  --set modelCache.persistence.enabled=true \
  --set modelCache.preload=never --set replicaCount=2
```

Download in an initContainer so the app container only reads the cache:

```bash
--set modelCache.downloadInitContainer.enabled=true
```

Require bearer auth:

```bash
--set config.apiKey=secret
```

Enable autoscaling and a PodDisruptionBudget:

```bash
--set autoscaling.enabled=true --set podDisruptionBudget.enabled=true
```

## Access

```bash
kubectl -n precog port-forward svc/precog 8000:80
curl -s localhost:8000/v1/forecast -H 'content-type: application/json' -d \
  '{"mode":"univariate","horizon":4,"series":[{"id":"a","target":[1,2,3,4,5]}]}'
```

## Upgrade / uninstall

```bash
helm upgrade precog deploy/helm/precog -n precog
helm uninstall precog -n precog
```

## Values

### Top level

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `replicaCount` | int | `1` | API replicas (ignored when `autoscaling.enabled`). |
| `nameOverride` | string | `""` | Override the chart name. |
| `fullnameOverride` | string | `""` | Override the generated full name. |
| `podAnnotations` | map | `{}` | Extra pod annotations. |
| `nodeSelector` | map | `{}` | Pod node selector. |
| `tolerations` | list | `[]` | Pod tolerations. |
| `affinity` | map | `{}` | Pod affinity. |

### Image

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `image.repository` | string | `precog-api` | API image (e.g. `ghcr.io/albe83/precog-api`). |
| `image.tag` | string | `local` | API image tag (e.g. `v0.4.0`). |
| `image.pullPolicy` | string | `IfNotPresent` | Image pull policy (`Never` for locally loaded images). |

### Service

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `service.type` | string | `ClusterIP` | Service type. |
| `service.port` | int | `80` | Service port. |
| `service.targetPort` | int | `8000` | API container port. |

### Model cache (`modelCache`)

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `modelCache.modelId` | string | `google/timesfm-3.0-pytorch` | Hugging Face repo id. |
| `modelCache.revision` | string | `43046b85…` | Pinned revision to download. |
| `modelCache.preload` | string | `auto` | `auto` download if missing, `always` force, `never` expect pre-seeded. |
| `modelCache.mountPath` | string | `/opt/precog/hf` | Cache mount path. |
| `modelCache.hfTokenSecret` | string | `""` | Secret name with key `hf-token` (gated repos). |
| `modelCache.persistence.enabled` | bool | `false` | Create/use a PVC; `false` uses `emptyDir`. |
| `modelCache.persistence.existingClaim` | string | `""` | Use an existing PVC instead of creating one. |
| `modelCache.persistence.accessModes` | list | `[ReadWriteMany]` | PVC access modes. |
| `modelCache.persistence.size` | string | `5Gi` | PVC size. |
| `modelCache.persistence.storageClass` | string | `""` | StorageClass (empty = cluster default). |
| `modelCache.downloadInitContainer.enabled` | bool | `false` | Download in an initContainer; app then uses `preload=never`. |
| `modelCache.downloadInitContainer.resources` | map | 100m/256Mi → 1/1Gi | InitContainer resources. |
| `modelCache.downloadJob.enabled` | bool | `false` | One-shot Job (post-install/post-upgrade) to pre-populate the PVC. Requires a PVC. |
| `modelCache.downloadJob.backoffLimit` | int | `3` | Job backoff limit. |
| `modelCache.downloadJob.ttlSecondsAfterFinished` | int | `600` | Job TTL after completion. |
| `modelCache.downloadJob.resources` | map | 100m/256Mi → 1/1Gi | Job resources. |

### Runtime config (`config`) → rendered into a ConfigMap

| Key | Env | Default | Description |
| --- | --- | ------- | ----------- |
| `config.engine` | `PRECOG_ENGINE` | `timesfm3` | `timesfm3` or `fake`. |
| `config.device` | `PRECOG_DEVICE` | `cpu` | Inference device. |
| `config.torchThreads` | `PRECOG_TORCH_THREADS` | `0` | `0` = torch default. |
| `config.maxConcurrency` | `PRECOG_MAX_CONCURRENCY` | `1` | Concurrent inferences (keep `1` on CPU). |
| `config.maxHorizon` | `PRECOG_MAX_HORIZON` | `1024` | Max horizon per request. |
| `config.maxContext` | `PRECOG_MAX_CONTEXT` | `16384` | Max context length. |
| `config.maxSeries` | `PRECOG_MAX_SERIES` | `64` | Max series per request. |
| `config.enableDocs` | `PRECOG_ENABLE_DOCS` | `true` | Serve `/docs` and `/openapi.json`. |
| `config.apiKey` | `PRECOG_API_KEY` | `""` | If set, creates a Secret and requires bearer auth. |

### Resources and probes

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `resources.requests` | map | 1 CPU / 3Gi | API requests (the model needs ~3Gi RSS). |
| `resources.limits` | map | 4 CPU / 8Gi | API limits. |
| `readinessProbe` | map | 10s/10s/5s/6 | Readiness probe on `/readyz`. |
| `livenessProbe` | map | 60s/20s/5s/3 | Liveness probe on `/healthz`. |
| `startupProbe.periodSeconds` | int | `10` | Startup probe period. |
| `startupProbe.failureThreshold` | int | `60` | ~10 min budget for cold start (download + load). |

### Autoscaling, PDB, service account

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `autoscaling.enabled` | bool | `false` | Enable an HPA on CPU. |
| `autoscaling.minReplicas` | int | `1` | HPA min replicas. |
| `autoscaling.maxReplicas` | int | `3` | HPA max replicas. |
| `autoscaling.targetCPUUtilizationPercentage` | int | `80` | HPA target CPU. |
| `podDisruptionBudget.enabled` | bool | `false` | Create a PDB. |
| `podDisruptionBudget.minAvailable` | int | `1` | PDB min available. |
| `serviceAccount.create` | bool | `true` | Create a ServiceAccount. |
| `serviceAccount.name` | string | `""` | ServiceAccount name override. |

### MCP server (`mcp`)

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `mcp.enabled` | bool | `false` | Deploy the MCP server next to the API. |
| `mcp.image.repository` | string | `precog-mcp` | MCP image (e.g. `ghcr.io/albe83/precog-mcp`). |
| `mcp.image.tag` | string | `local` | MCP image tag. |
| `mcp.image.pullPolicy` | string | `IfNotPresent` | MCP pull policy. |
| `mcp.apiUrl` | string | `""` | API URL; defaults to the API Service in this release. |
| `mcp.allowedHosts` | string | `""` | Allowed Host headers (comma-separated) or `*` to disable the check. |
| `mcp.service.port` | int | `80` | MCP Service port. |
| `mcp.service.targetPort` | int | `8765` | MCP container port. |
| `mcp.resources` | map | 50m/128Mi → 500m/512Mi | MCP resources. |

## Notes

- The API downloads the pinned revision into `modelCache.mountPath`; the cache
  check requires `config.json` and `model.safetensors`, so a partial snapshot is
  never used.
- On CPU, keep `config.maxConcurrency=1` and scale with replicas: a single
  inference already uses multiple threads (see `docs/runbook.md`).
- Pods run as non-root with a read-only root filesystem and an `emptyDir` on
  `/tmp`.
- The TimesFM-3 weights are non-commercial; the images do not contain them. A
  locally baked variant (`PRECOG_BAKE_WEIGHTS=true`) must not be published. See
  `THIRD_PARTY_NOTICES.md`.
