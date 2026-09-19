# ADR 0007 — TimesFM execution defaults and calibration ownership

- Status: proposed
- Date: 2026-09-19

## Context

[ADR 0006](0006-execution-layer.md) removes TimesFM-specific knobs from the
canonical execution problem and requires `TimesFM3Engine` to set execution
behavior explicitly instead of inheriting it accidentally. This ADR records the
remaining decisions so the Phase 2 Engine refactor has one documented source of
truth. It is the deliverable of issue #176 and precedes the refactor.

Today the engine forwards `use_symmetric_averaging` from the request (default
`False`), applies `quantile_spread_scale` (default `1.0`, a no-op), and inherits
`make_positive`, `sort_quantiles`, `use_znorm` and `padding_mode` from
`TimesFM3Evaluator` without declaring them.

## Decisions

### 1. Symmetric averaging stays disabled

`TimesFM3Engine` sets `use_symmetric_averaging=False`.

This preserves the current Precog default (no behavior change). It was
re-evaluated against the real TimesFM-3 path with
`benchmarks/symmetric_averaging.py` (32 windows, context 168, horizon 24, the
Grafana/Thanos series in `benchmarks/data/complex_series.json`):

| `use_symmetric_averaging` | MAE | 80% coverage | pinball |
| ------------------------- | --- | ------------ | ------- |
| `False` (chosen) | 3.94e8 | 87.1% | 2.35e8 |
| `True` | 4.37e8 | 87.2% | 2.56e8 |

`False` has lower point error and lower pinball loss at comparable coverage, so
there is no evidence to change the default. Evidence:
`benchmarks/data/symmetric_averaging.json`.

### 2. Calibration is not part of the execution problem

`quantile_spread_scale` is removed from the canonical request and Precog does
**not** apply calibration by default in Phase 2.

`scale = 1.0` (today's default) is a no-op, so removing the field changes no
current behavior. The existing calibration sweep
(`benchmarks/data/calibration.json`) found the no-calibration setting has the
lowest pinball loss (1.88e7 vs 1.94e7 at `1.5`) and 78.3% coverage against a
nominal 80%, so no default correction is warranted. If calibration is ever
needed it becomes an explicit engine/deployment configuration or a dedicated
post-processing stage; no calibration framework is built now.

### 3. Evaluator arguments set explicitly

`TimesFM3Engine` sets these arguments on every `predict_batch` call rather than
relying on evaluator defaults:

| Argument | Value | Rationale |
| -------- | ----- | --------- |
| `return_quantiles` | `True` | The engine owns the fixed quantile grid; the API slices requested levels |
| `use_symmetric_averaging` | `False` | Decision 1 |
| `make_positive` | `False` | No silent domain-specific non-negativity (ADR 0006) |
| `sort_quantiles` | `True` | Monotonic quantiles are a normalization invariant |
| `use_znorm` | `False` | Input is caller-prepared and finite (ADR 0006) |
| `padding_mode` | `"none"` | Precog never pads or silently adapts input |

`make_positive=False` is a correctness/domain decision, not a tuning change:
the execution layer has no knowledge of the target's business domain, so it
must not clamp negative predictions to zero (ADR 0006, Decision 4).

## Scope

- No canonical request field is added.
- No multi-engine abstraction is introduced.
- No REST contract cutover is implemented here; the explicit arguments and
  `make_positive=False` land in the Engine-boundary refactor (#177).

## Consequences

- The execution defaults are documented and testable at the engine boundary.
- Removing the per-request knob means a future change to symmetric averaging or
  calibration is a deployment decision with benchmark evidence, not per-call
  behavior.
