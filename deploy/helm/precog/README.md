# precog

Helm chart for the Precog TimesFM-3 zero-shot forecasting API (CPU), with an
optional MCP server. Model weights are **not baked into the image**: they are
downloaded at startup into a cache volume (or pre-seeded), so the images are
weight-free.

- Versioning: the chart `version`/`appVersion` follow the app release (see
  `CHANGELOG.md`).
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
  --set image.tag=v0.6.0 \
  --set mcp.enabled=true \
  --set mcp.image.repository=ghcr.io/albe83/precog-mcp \
  --set mcp.image.tag=v0.6.0 \
  --set mcp.allowedHosts="precog-mcp.precog.svc:80"
```

`mcp.allowedHosts` is needed because the MCP HTTP transport validates the Host
header (DNS-rebinding protection); behind a gateway or a Service DNS name the
default localhost-only allowlist rejects it. Use `"*"` to disable the check when
the listener is reachable only through a trusted gateway plus NetworkPolicy.

## Install from the published chart (OCI)

The chart is packaged and published per release, so a deployment can be pinned
by chart version (replace `0.6.0` with the release you want to pin):

```bash
helm install precog oci://ghcr.io/albe83/precog-charts/precog \
  --version 0.6.0 --namespace precog --create-namespace \
  --set image.repository=ghcr.io/albe83/precog-api \
  --set image.tag=v0.6.0 \
  --set mcp.enabled=true \
  --set mcp.image.repository=ghcr.io/albe83/precog-mcp \
  --set mcp.image.tag=v0.6.0
```

The same `.tgz` is attached to each GitHub release:

```bash
gh release download v0.6.0 -p 'precog-*.tgz'
helm install precog precog-0.6.0.tgz
```

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

Use an existing Secret for the API key (no plaintext in values):

```bash
--set config.existingSecret=precog-api-key --set config.existingSecretKey=api-key
```

Enable autoscaling and a PodDisruptionBudget:

```bash
--set autoscaling.enabled=true --set podDisruptionBudget.enabled=true
```

Autoscaling shares the model cache: with more than one replica use a shared PVC
(default `ReadWriteMany`) or accept a per-pod download with
`--set modelCache.allowEphemeralWithHpa=true` (otherwise the chart fails to
render).

Run the connectivity test and expose metrics:

```bash
helm test precog -n precog
--set metrics.serviceMonitor.enabled=true \
--set metrics.serviceMonitor.labels.release=kube-prometheus-stack
```

Mount a corporate CA (TLS inspection) and point Python at it:

```bash
--set extraVolumes[0].name=corp-ca \
--set extraVolumes[0].secret.secretName=corp-ca \
--set extraVolumeMounts[0].name=corp-ca \
--set extraVolumeMounts[0].mountPath=/etc/ssl/certs/corp-ca.crt \
--set extraVolumeMounts[0].subPath=ca.crt \
--set extraEnv[0].name=SSL_CERT_FILE \
--set extraEnv[0].value=/etc/ssl/certs/corp-ca.crt
```

Restrict network access (default-deny ingress unless rules are given):

```bash
--set networkPolicy.enabled=true \
--set networkPolicy.mcp.ingress[0].from[0].podSelector.matchLabels.app\.kubernetes\.io/name=agentgateway \
--set networkPolicy.mcp.ingress[0].ports[0].port=8765 \
--set networkPolicy.api.ingress[0].from[0].podSelector.matchLabels.app\.kubernetes\.io/name=precog-mcp \
--set networkPolicy.api.ingress[0].ports[0].port=8000
```

When egress is restricted, allow the API to reach `huggingface.co` (and DNS) on
first start unless the cache volume is pre-seeded.

Publish through the Gateway API (needs the CRDs; attach to an existing Gateway):

```bash
--set httpRoute.enabled=true \
--set httpRoute.parentRefs[0].name=private-corporate \
--set httpRoute.parentRefs[0].namespace=gateway-system \
--set httpRoute.hostnames[0]=precog.example.com \
--set httpRoute.api.enabled=true \
--set mcp.enabled=true
```

## Access

```bash
kubectl -n precog port-forward svc/precog 8000:80
curl -s localhost:8000/v1/forecast -H 'content-type: application/json' -d \
  '{"horizon":4,"targets":[{"id":"a","values":[1,2,3,4,5]}],"quantiles":[0.1,0.9]}'
```

## Upgrade / uninstall

```bash
helm upgrade precog deploy/helm/precog -n precog
helm uninstall precog -n precog
```

## MCP topology

- **`sidecar` (default)** — the MCP runs as a second container in the API pod
  (`PRECOG_API_URL=http://127.0.0.1:8000`). Fewer pods, no cross-pod hop; but it
  scales with the API, shares the pod lifecycle and its resource requests add
  up. A stable Service is optional (`mcp.service.enabled=true`), needed by
  gateways and `helm test`.
- **`deployment`** — a separate `precog-mcp` Deployment and Service (independent
  scaling/lifecycle). Use it when a gateway targets the MCP Service or you want
  to scale it independently.

Migration: installs that relied on the separate `precog-mcp` Service must set
`mcp.deploymentMode=deployment` (or enable `mcp.service.enabled` in sidecar
mode).

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
| `extraEnv` | list | `[]` | Extra env vars on the API, MCP, download initContainer and Job. |
| `extraEnvFrom` | list | `[]` | Extra `envFrom` sources (ConfigMap/Secret) on those containers. |
| `extraVolumes` | list | `[]` | Extra pod volumes (e.g. a corporate CA Secret). |
| `extraVolumeMounts` | list | `[]` | Extra volume mounts on those containers. |
| `imagePullSecrets` | list | `[]` | Image pull secrets for both workloads (and the Job). |
| `podLabels` | map | `{}` | Extra pod labels (API and MCP). |
| `priorityClassName` | string | `""` | Pod priority class (API, MCP and Job). |
| `topologySpreadConstraints` | list | `[]` | Pod topology spread constraints (API and MCP). |

### Image

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `image.repository` | string | `precog-api` | API image (e.g. `ghcr.io/albe83/precog-api`). |
| `image.tag` | string | `local` | API image tag (e.g. `v0.6.0`). |
| `image.pullPolicy` | string | `IfNotPresent` | Image pull policy (`Never` for locally loaded images). |

### Service

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `service.type` | string | `ClusterIP` | Service type. |
| `service.port` | int | `80` | Service port. |
| `service.targetPort` | int | `8000` | API container port. |
| `service.annotations` | map | `{}` | Annotations on both Services (API and MCP). |

### Model cache (`modelCache`)

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `modelCache.modelId` | string | `google/timesfm-3.0-pytorch` | Hugging Face repo id. |
| `modelCache.revision` | string | `43046b85…` | Pinned revision to download. |
| `modelCache.preload` | string | `auto` | `auto` download if missing, `always` force, `never` expect pre-seeded. |
| `modelCache.pruneOldRevisions` | bool | `false` | Remove cached snapshots other than `revision` (needs a pinned revision). |
| `modelCache.mountPath` | string | `/opt/precog/hf` | Cache mount path. |
| `modelCache.hfTokenSecret` | string | `""` | Secret name with key `hf-token` (gated repos). |
| `modelCache.persistence.enabled` | bool | `false` | Create/use a PVC; `false` uses `emptyDir`. |
| `modelCache.persistence.existingClaim` | string | `""` | Use an existing PVC instead of creating one (implies persistence enabled). |
| `modelCache.persistence.accessModes` | list | `[ReadWriteMany]` | PVC access modes. |
| `modelCache.persistence.size` | string | `5Gi` | PVC size. |
| `modelCache.persistence.storageClass` | string | `""` | StorageClass (empty = cluster default). |
| `modelCache.allowEphemeralWithHpa` | bool | `false` | Allow HPA with `maxReplicas>1` without a shared cache (per-pod download). |
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
| `config.apiKey` | `PRECOG_API_KEY` | `""` | Creates a chart-managed Secret and requires bearer auth. Mutually exclusive with `config.existingSecret`. |
| `config.existingSecret` | `PRECOG_API_KEY` | `""` | Use an existing Secret for the bearer token (no chart-managed Secret). |
| `config.existingSecretKey` | — | `api-key` | Key within `config.existingSecret`. |

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
| `terminationGracePeriodSeconds` | int | `360` | API pod termination grace period (keep above the request timeout). |

### MCP server (`mcp`)

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `mcp.enabled` | bool | `false` | Deploy the MCP server. |
| `mcp.deploymentMode` | string | `sidecar` | `sidecar` (container in the API pod) or `deployment` (separate Deployment+Service). |
| `mcp.image.repository` | string | `precog-mcp` | MCP image (e.g. `ghcr.io/albe83/precog-mcp`). |
| `mcp.image.tag` | string | `local` | MCP image tag. |
| `mcp.image.pullPolicy` | string | `IfNotPresent` | MCP pull policy. |
| `mcp.apiUrl` | string | `""` | API URL; defaults to the API Service in this release. |
| `mcp.allowedHosts` | string | `""` | Allowed Host headers (comma-separated) or `*` to disable the check. |
| `mcp.service.port` | int | `80` | MCP Service port. |
| `mcp.service.enabled` | bool | `false` | Sidecar mode only: render an MCP Service (deployment mode always has one). |
| `mcp.service.targetPort` | int | `8765` | MCP container port. |
| `mcp.resources` | map | 50m/128Mi → 500m/512Mi | MCP resources. |
| `mcp.terminationGracePeriodSeconds` | int | `30` | MCP pod termination grace period. |

### Tests and metrics

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `tests.enabled` | bool | `true` | Render the `helm test` connectivity pod. |
| `metrics.serviceMonitor.enabled` | bool | `false` | Create a ServiceMonitor scraping the API and MCP `/metrics` endpoints. |
| `metrics.serviceMonitor.interval` | string | `30s` | Scrape interval. |
| `metrics.serviceMonitor.scrapeTimeout` | string | `10s` | Scrape timeout. |
| `metrics.serviceMonitor.path` | string | `/metrics` | Metrics path. |
| `metrics.serviceMonitor.labels` | map | `{}` | Extra labels (e.g. your Prometheus release). |

`helm test precog` runs the API `/readyz` check and, when the MCP is enabled,
an MCP `/metrics` check. GitOps tools that do not execute Helm test hooks (for
example Argo CD) will not run them — set `tests.enabled=false` there.

### NetworkPolicy (`networkPolicy`, disabled by default)

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `networkPolicy.enabled` | bool | `false` | Render a NetworkPolicy per workload. |
| `networkPolicy.egress` | list | `[]` | Common egress rules used when a workload list is empty. |
| `networkPolicy.api.ingress` | list | `[]` | API ingress rules (`from`/`ports`); empty = deny all ingress. |
| `networkPolicy.api.egress` | list | `[]` | API egress rules (allow `huggingface.co` + DNS when restricted). |
| `networkPolicy.mcp.ingress` | list | `[]` | MCP ingress rules. |
| `networkPolicy.mcp.egress` | list | `[]` | MCP egress rules. |

### HTTPRoute (`httpRoute`, disabled by default)

| Key | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `httpRoute.enabled` | bool | `false` | Render an HTTPRoute (requires Gateway API CRDs). |
| `httpRoute.parentRefs` | list | `[]` | Target Gateway refs (required when enabled). |
| `httpRoute.hostnames` | list | `[]` | Hostnames. |
| `httpRoute.annotations` | map | `{}` | Annotations. |
| `httpRoute.labels` | map | `{}` | Extra labels. |
| `httpRoute.api.enabled` | bool | `false` | Publish the REST API. |
| `httpRoute.api.path` / `pathType` | string | `/` / `PathPrefix` | API match. |
| `httpRoute.mcp.enabled` | bool | `true` | Publish the MCP endpoint at `/mcp`. |
| `httpRoute.mcp.path` / `pathType` | string | `/mcp` / `PathPrefix` | MCP match. |

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
