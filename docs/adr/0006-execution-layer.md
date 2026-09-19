# ADR 0006 — Precog execution layer and canonical forecast contract

- Status: accepted
- Date: 2026-09-19

## Context

[ADR 0005](0005-mcp-semantic-boundary.md) established the MCP server as the
agent-facing **semantic** interface and deliberately deferred the future role
and shape of the REST API to a later decision. That decision is this ADR.

Phase 1 left two surfaces with different abstractions:

- the MCP server exposes a model-independent forecasting problem;
- the REST API exposes `ForecastRequest`, which is simultaneously the wire DTO,
  the engine input and a partially TimesFM-shaped structure (`mode`,
  request-level vs per-series covariates, `return_quantiles`,
  `symmetric_averaging`, `quantile_spread_scale`, `interpolate_missing`).

The intended Phase 2 direction is:

```text
Semantic plane                  Execution plane
Agent
  │
  ▼
MCP semantic interface ──compile/translate──▶ REST Execution API
                                                 │
                                                 ▼
                                          Engine boundary
                                                 │
                                                 ▼
                                          TimesFM3Engine
                                                 │
                                                 ▼
                                        TimesFM3Evaluator
```

Precog has not been released, so backward compatibility with the current REST
contract is **not** a design constraint. This ADR defines the target contract;
it does **not** implement the Phase 2 REST redesign.

## Decision

### 1. REST is the execution layer

The REST API represents the Precog **execution plane**. It accepts an
already-compiled forecasting problem and runs it on the active engine.

- It **may** expose runtime/execution concepts that are useful to an execution
  client (engine, device, effective limits, execution features).
- It **must not** become a second semantic API or a copy of the MCP semantic
  contract.
- The MCP server remains a client of this API: the semantic plane compiles an
  agent request into one or more canonical execution problems.

### 2. The engine boundary is explicit

The API depends on a **canonical Precog execution problem**, not on the wire
DTO and not on a TimesFM-shaped type. `ForecastRequest` stops playing three
roles at once:

```text
REST wire contract
      ↓  (validation + mapping)
canonical execution problem (ExecutionProblem)
      ↓  Engine protocol
TimesFM3Engine
      ↓
TimesFM3Evaluator
```

### 3. TimesFM abstraction is pragmatic

The canonical contract omits TimesFM-specific structure when that is simple to
do. This ADR does **not** introduce:

- engine registries;
- routing;
- per-request engine selection;
- plugin frameworks;
- speculative multi-engine architecture.

There is currently only TimesFM-3. The goal is a clean Precog execution
boundary, not a generic forecasting framework.

### 4. Non-negativity is an explicit engine choice

The canonical problem has no field for domain-specific output constraints.
`make_positive` is therefore **not** a request field, and Precog must not
silently impose a non-negativity assumption on data it does not understand.

`TimesFM3Evaluator` enables `make_positive=True` as a benchmark default while the
base forecaster defaults to `False`. Today Precog inherits the evaluator default
without declaring it. Phase 2 must make the choice explicit in `TimesFM3Engine`
(set `make_positive=False`, no silent clamping) rather than inherit it; if
non-negativity is ever wanted for a specific domain, it becomes an explicit,
documented policy, not an evaluator side effect.

### 5. Pre-release reset and relationship to ADR 0004

Phase 2 is a **one-time pre-release reset of `/v1` in place**. Precog has never
been released, so there is no `/v2` and no backward-compatibility machinery for
the current REST contract.

[ADR 0004](0004-api-versioning.md) (versioning and deprecation) applies **after**
the redesigned execution contract becomes the new baseline: from that point the
`/v1` rules (additive changes within a major, breaking changes under a new major,
deprecation windows) take effect. ADR 0004 is amended to scope its compatibility
commitment to released contracts so the two ADRs do not contradict each other.

## Canonical execution request

The following is the proposed starting point for the canonical problem. It is a
Precog-level problem, not the REST wire schema. This PR defines it but does not
implement the wire contract; once the redesigned contract becomes the baseline,
its evolution follows [ADR 0004](0004-api-versioning.md).

```json
{
  "horizon": 24,
  "targets": [
    { "id": "cpu", "values": [1.0, 2.0, 3.0] },
    { "id": "memory", "values": [10.0, 11.0, 12.0] }
  ],
  "past_covariates": [
    { "id": "requests", "values": [100.0, 110.0, 120.0] }
  ],
  "known_future_covariates": [
    {
      "id": "maintenance",
      "history": [0.0, 0.0, 0.0],
      "future": [0.0, 1.0, 1.0]
    }
  ],
  "quantiles": [0.1, 0.5, 0.9]
}
```

| Field | Type | Notes |
| ----- | ---- | ----- |
| `horizon` | integer ≥ 1 | Number of future steps |
| `targets` | array of `{id, values}` | Forecast jointly; all share one context length |
| `past_covariates` | array of `{id, values}` | Known during the context only; shared across targets |
| `known_future_covariates` | array of `{id, history, future}` | History plus already-known future values; shared across targets |
| `quantiles` | array of numbers | Requested levels; `[]` means point-only output |

`values`, `history` and `future` must be finite numbers. All series must be
equally sampled and aligned; leading/trailing gaps and NaN are rejected. ID
uniqueness is enforced across all series (`targets` + covariates).

### Design choices and simplifications

- **`mode` is removed.** The number of targets already says whether the problem
  has one target or multiple jointly-forecast targets. Engine/API select the
  backend path; the caller never declares `univariate`/`multivariate`.
- **`return_quantiles` is removed.** The requested levels are explicit:
  `"quantiles": []` for point-only, or a non-empty list for probabilistic
  output. Requesting a level the engine cannot produce is rejected, never
  silently dropped or substituted.
- **One covariate placement.** Covariates are always request-level and shared
  across targets. The per-series vs request-level split disappears.
- **`interpolate_missing` is removed.** Per the Phase 1 boundary, Precog accepts
  prepared numeric input and does not clean or mutate caller data.
- **`symmetric_averaging` is removed from the problem.** It is a TimesFM
  execution/configuration concern, not part of the canonical problem (see
  *Compromises*).
- **`quantile_spread_scale` is removed from the problem.** It is
  calibration/post-processing, not a fundamental execution field (see
  *Compromises*).
- **Known-future covariates keep `history` + `future`.** The concatenated
  `context + horizon` form expected by TimesFM is reconstructed inside
  `TimesFM3Engine`.

### Representativeness vs the current implementation

The canonical problem must represent, without semantic loss, every forecasting
case the **semantic** MCP contract supports. Mapping from the current REST
contract:

| Current REST concept | Canonical representation |
| -------------------- | ------------------------ |
| `mode` | absent; derived from `len(targets)` |
| `series[].target` | `targets[].values` |
| `series[].past_covariates` / `series[].future_covariates` | not representable per target; moved to request-level arrays |
| `past_covariates` / `future_covariates` (request-level) | request-level arrays |
| `future_covariates` (`context + horizon` concatenation) | `known_future_covariates[].history` + `.future` |
| `options.return_quantiles` | `quantiles` is empty or non-empty |
| `options.interpolate_missing` | absent; non-finite input is rejected |
| `options.symmetric_averaging` | engine configuration |
| `options.quantile_spread_scale` | calibration/post-processing (deferred) |

**Deliberate narrowing.** The current REST `univariate` mode can forecast many
independent series with heterogeneous context lengths and per-series covariates
in a single request. The canonical problem does not: targets in one problem are
jointly forecast and share covariates, matching the MCP semantic contract
(`forecast.targets` are "forecast jointly"). Independent series are submitted
as separate execution problems. This is not considered a semantic loss, because
the semantic contract never exposed per-series covariate placement or
heterogeneous independent batches. If batching independent problems becomes a
real need, it is a new execution concept (a batch endpoint) and is out of scope
here.

## Canonical execution response

```json
{
  "horizon": 2,
  "targets": [
    {
      "id": "cpu",
      "forecast": [1.1, 1.2],
      "quantiles": [
        { "level": 0.1, "values": [1.0, 1.05] },
        { "level": 0.5, "values": [1.1, 1.2] },
        { "level": 0.9, "values": [1.2, 1.35] }
      ]
    }
  ],
  "model": { "id": "timesfm-3.0", "revision": null },
  "usage": { "latency_ms": 42.0, "context_len": 96 }
}
```

| Field | Notes |
| ----- | ----- |
| `horizon` | Echoes the accepted horizon |
| `targets[].id` | Target identity, in request order |
| `targets[].forecast` | Point forecast (median quantile), length `horizon` |
| `targets[].quantiles` | One `{level, values}` entry per requested level; `[]` for point-only |
| `model.id` | Configured model id |
| `model.revision` | Configured/known model revision when available, `null` otherwise |
| `usage` | Execution metadata added by the API: `latency_ms`, `context_len` |

Design notes:

- **The response envelope is assembled at the API layer, not by the engine.**
  `ExecutionResult` (the Engine protocol return value) carries only the
  normalized predictions — one entry per target with `id`, `forecast` and
  `quantiles`. The API adds the REST envelope: `horizon` from the accepted
  problem, `model` provenance from configuration, and `usage` from measured
  request timing and the problem's context length. This keeps `ExecutionResult`
  a single-role type and avoids recreating the multi-role `ForecastRequest`
  problem.
- **`model.revision` is not resolved.** It reports the configured revision when
  one is set and stays `null` otherwise. Resolving an actual HF commit SHA or
  local checkpoint revision is additional work and is not promised here.
- **Quantiles are explicit and per target**, as a list of `{level, values}`.
  JSON object keys must be strings, so a level-keyed mapping forces a formatting
  convention (`"0.1"`) and positional matrices force a documented orientation.
  A list of objects is self-describing and order-independent, and it removes the
  matrix-orientation class of contract bugs at the execution boundary.
- The response contains **only the requested levels**. There is no implicit
  "all levels" payload.
- **TimesFM quantile-matrix interpretation belongs to the engine boundary.**
  The evaluator returns a fixed-width quantile matrix; `TimesFM3Engine` selects
  the requested columns, orders them and converts them to the canonical shape.
  MCP never sees the backend matrix.
- **Point forecast = median quantile.** Which column is the median is a model
  concern (`median_quantile_index`); it is resolved at the engine boundary, not
  by callers.

## Engine protocol

The minimal protocol the API depends on:

```python
class Engine(Protocol):
    @property
    def ready(self) -> bool:
        """Whether the engine finished loading and can serve forecasts."""

    @property
    def max_context(self) -> int | None:
        """Effective context length honored by the engine, or None if unbounded."""

    @property
    def max_variates(self) -> int | None:
        """Effective variates per forward pass, or None if unbounded."""

    def predict(self, problem: ExecutionProblem) -> ExecutionResult:
        """Run one canonical execution problem and return a normalized result."""
```

- Readiness, effective context limit, effective variate limit, prediction from
  the canonical problem and a normalized result are the whole contract.
- `ExecutionResult` is the **normalized engine prediction only**: an ordered
  list of per-target results (`id`, point `forecast`, `quantiles`). It carries
  no latency, no HTTP envelope and no provenance; those are added by the API
  (see *Canonical execution response*).
- `max_horizon` is **not** an engine property; it stays a Precog policy/limit
  checked at the API boundary and advertised by execution capabilities.
- No `max_series`/`max_targets` engine property is added: the variate limit
  already bounds targets plus covariates per forward pass.
- Engine selection stays a deployment setting (`PRECOG_ENGINE`), never a
  per-request concept.

Canonical types live with the execution plane (e.g. a dedicated
`precog_api.execution` module); the REST wire DTOs stay in `packages/schemas`.
The MCP server and the SDK must not import server internals.

## Where TimesFM-specific translation belongs

All backend shape translation lives inside `TimesFM3Engine`:

| Concern | Handling |
| ------- | -------- |
| `len(targets) == 1` vs `> 1` | 1-D context vs stacked multi-variate context; the evaluator's `univariate`/joint paths |
| Known-future `history` + `future` | concatenated to `context + horizon` before `predict_batch` |
| Covariate arrays | stacked into `(channels, length)` arrays |
| Quantile matrix | slice requested level columns; order and label them |
| Median column | `median_quantile_index` from the model config |
| `symmetric_averaging` | engine configuration (was a request option) |
| Calibration (`quantile_spread_scale`) | calibration/post-processing step, not the execution problem (deferred, see below) |
| `make_positive` | explicit engine choice, not inherited from the evaluator benchmark default (Phase 2 sets it to `False`) |
| `sort_quantiles`, `use_znorm`, `padding_mode` | evaluator/engine defaults |

The MCP anti-corruption adapter (`precog_mcp.adapter`) then only maps the
semantic request to a canonical execution problem and the canonical result to
the semantic result. **The `mode` selection currently in `to_rest_request`
becomes an engine-boundary concern.**

## Execution capabilities: `GET /v1/capabilities`

`GET /v1/capabilities` is the **execution/runtime** discovery surface. It is
distinct from the MCP resource:

```text
precog://capabilities   = semantic capabilities for agents
GET /v1/capabilities    = execution/runtime capabilities
```

| Field | Notes |
| ----- | ----- |
| `engine` | Active engine id (`fake`, `timesfm3`) |
| `model.id` | Configured model id |
| `model.revision` | Configured/known model revision when available, `null` otherwise |
| `device` | Execution device (`cpu` today; parametric via `PRECOG_DEVICE`) |
| `limits.max_horizon` | Configured max horizon |
| `limits.max_context` | Effective max context (min of config and engine) |
| `limits.max_variates` | Effective variates per forward pass (min of config and engine), `null` if unbounded |
| `limits.max_targets` | Policy ceiling: the actual number of targets accepted for a specific request may be lower, because targets and covariate channels share the `max_variates` execution budget |
| `quantile_levels` | Levels the engine can produce (fixed grid today) |
| `features` | Execution-level support flags (point/probabilistic, past covariates, known-future covariates, joint targets) |
| `auth_required` | Whether a bearer token is required |

The semantic resource keeps owning semantic flags and the quantile levels
accepted by the MCP contract; it derives only `max_horizon` and
`max_context_length` from this endpoint and drops execution-only fields
(engine, device, variate limits, covariate packing, calibration knobs). This
endpoint is not redesigned in this issue.

## Python SDK / consumer direction

Recorded decisions:

- The **WebUI is abandoned for now** and is out of scope.
- The Python SDK may be changed freely.
- The Python SDK should be evaluated as the **official client of the Execution
  API**.
- Phase 2 should evaluate adding `AsyncPrecogClient` and using it from the MCP
  server instead of maintaining a separate MCP HTTP client
  (`precog_mcp.client`).
- The TypeScript SDK **must not drive the architecture**. It may be updated
  mechanically later or deferred if appropriate.

SDK migration is not implemented in this issue.

## Consequences

- The MCP semantic plane and the REST execution plane evolve independently:
  semantic operations can compose execution problems without leaking TimesFM
  shapes, and execution/runtime concerns stay off the agent surface.
- `ForecastRequest`-style multi-role DTOs are retired; the engine depends on a
  canonical problem, so a future backend change is contained at one boundary.
- The execution response is self-describing and free of matrix-orientation
  coupling.
- Removing request-level TimesFM knobs means the engine must own sensible
  defaults. Non-negativity is decided explicitly (`make_positive=False`); a
  behavior decision (and benchmark) is still required for `symmetric_averaging`
  and calibration before implementation.
- The contract is deliberately narrow: independent per-series batches are not
  representable, and adding them later is an explicit new decision.

## Compromises and warnings from validating against TimesFM-3

1. **Fixed quantile grid.** The evaluator produces a fixed set of levels (nine
   today). The canonical request may only ask for a subset of that grid; an
   unsupported level is rejected at the API boundary. Expanding the grid is a
   backend capability change, not a contract change.
2. **`symmetric_averaging` default drift.** The current REST option defaults to
   `false`, while `TimesFM3Evaluator` benchmark defaults use symmetric
   averaging. Moving the knob into engine configuration must preserve the
   intended default deliberately; changing it can materially change accuracy
   and must be benchmarked.
3. **Calibration ownership.** `quantile_spread_scale` is currently applied
   inside `TimesFM3Engine._calibrate_quantiles`. Moving calibration out of the
   execution problem means Phase 2 must decide where it lives (engine config vs
   a dedicated post-processing step). Dropping it implicitly would change
   historical outputs for callers that relied on it.
4. **Silent backend adaptation.** Above the variate limit the evaluator
   subsamples covariates and chunks targets with a fixed RNG seed, silently
   changing the problem. The canonical contract keeps Precog's fail-closed
   behavior: the API rejects such problems instead of adapting them.
5. **Non-declared model effects.** `make_positive` (clamps negative forecasts
   to zero) and `sort_quantiles` are evaluator defaults, not request fields.
   `make_positive` is a domain assumption Precog must not apply silently, so
   Phase 2 sets it explicitly to `False` in `TimesFM3Engine` (see Decision 4);
   `sort_quantiles` stays an execution default.
6. **NaN handling.** Although the evaluator has internal missing-value handling
   (`padding_mode="none"`, `use_znorm=false`), Precog rejects non-finite input
   per the Phase 1 boundary. The canonical contract exposes no interpolation
   control.
7. **Context is never truncated.** `global_context` is the honored maximum.
   Problems longer than the effective context are rejected, not truncated.
8. **One joint problem per request.** The current univariate multi-series
   independent batch has no canonical representation; it is submitted as
   separate problems. This is documented rather than papered over with a
   speculative batch abstraction.
9. **Variate limit is combinatorial.** `max_variates` counts targets plus
   covariates in a forward pass; it must be reported by execution capabilities
   and enforced before inference, or Precog would inherit the backend's silent
   adaptation.

## Validation performed

The design was checked against the current implementation:

- `packages/schemas` REST models (`ForecastRequest`, `SeriesInput`,
  `ForecastOptions`, `ForecastResponse`, `Capabilities`);
- `apps/api` request validation and effective-limit enforcement
  (`_enforce_limits`, `_max_unit_variates`, `Capabilities`);
- the `Engine` protocol and `FakeEngine`;
- `TimesFM3Engine` and the real `TimesFM3Evaluator.predict_batch()` behavior
  (contexts of 1-D vs stacked multi-variate arrays, covariate stacking,
  `global_context`, `_MAX_VARIATES_PER_FORWARD` chunking/subsampling,
  `ForecastOutput.forecast`/`quantiles` shapes and the median index);
- the MCP REST adapter (`to_rest_request`, `from_rest_response`) and the
  `precog://capabilities` resource;
- the Python SDK (`PrecogClient`) and the TypeScript SDK types (only to confirm
  current REST dependencies).

No supported semantic behavior of the MCP contract is lost by the canonical
problem. The only narrowing is the independent multi-series batch described
above.

## Non-goals (Phase 2)

Out of scope for this ADR and the redesign it gates:

- multi-engine routing, engine selection per request, or a generic forecasting
  framework;
- Chronos or any new model;
- ensembles;
- async/background forecast jobs;
- persistence and datasource integrations;
- anomaly detection;
- semantic REST endpoints that duplicate MCP;
- WebUI redesign;
- backward-compatibility machinery for the old REST contract.

Implementation decomposition for the follow-up work is proposed in the issue
comment, not here.
