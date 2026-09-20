"""Engine abstraction for TimesFM-3 inference.

The API talks to an :class:`Engine` over the canonical execution boundary
(ADR 0006). Tests and local demos use :class:`FakeEngine`; production uses the
TimesFM-3 implementation loaded lazily so the base install does not require
torch.
"""

from __future__ import annotations

from precog_api.execution import (
    Engine,
    ExecutionProblem,
    ExecutionResult,
    QuantileExecutionResult,
    TargetExecutionResult,
)


class FakeEngine:
    """Deterministic engine that repeats the last observed value."""

    _QUANTILE_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

    def __init__(
        self,
        *,
        ready: bool = True,
        max_context: int | None = None,
        max_variates: int | None = None,
    ) -> None:
        self._ready = ready
        self._max_context = max_context
        self._max_variates = max_variates

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def max_context(self) -> int | None:
        return self._max_context

    @property
    def max_variates(self) -> int | None:
        return self._max_variates

    @property
    def quantile_levels(self) -> tuple[float, ...]:
        return self._QUANTILE_LEVELS

    def predict(self, problem: ExecutionProblem) -> ExecutionResult:
        targets: list[TargetExecutionResult] = []
        for target in problem.targets:
            last = float(target.values[-1])
            quantiles = [
                QuantileExecutionResult(level=level, values=[last] * problem.horizon)
                for level in problem.quantiles
            ]
            targets.append(
                TargetExecutionResult(
                    id=target.id,
                    forecast=[last] * problem.horizon,
                    quantiles=quantiles,
                )
            )
        return ExecutionResult(targets=targets)


__all__ = ["Engine", "FakeEngine"]
