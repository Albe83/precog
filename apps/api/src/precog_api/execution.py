"""Canonical Precog execution types and Engine protocol (ADR 0006).

These are server-internal execution types, not HTTP DTOs. The REST wire contract
lives in :mod:`precog_schemas`; :mod:`precog_api.mapping` translates between the
two. The Engine boundary only sees the canonical problem and returns normalized
predictions, never API timing or provenance.

Phase 2 standalone: the API still accepts the pre-release wire contract and maps
it onto this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExecutionTarget:
    """One target series, ordered oldest to newest."""

    id: str
    values: list[float]


@dataclass(frozen=True)
class ExecutionPastCovariate:
    """A covariate known only during the historical context."""

    id: str
    values: list[float]


@dataclass(frozen=True)
class ExecutionKnownFutureCovariate:
    """A covariate whose history and future values are both known."""

    id: str
    history: list[float]
    future: list[float]


@dataclass(frozen=True)
class ExecutionProblem:
    """A canonical, single-role forecasting problem.

    Targets are forecast jointly, matching the semantic contract. ``quantiles``
    is empty for point-only output.
    """

    horizon: int
    targets: list[ExecutionTarget]
    quantiles: list[float] = field(default_factory=list)
    past_covariates: list[ExecutionPastCovariate] = field(default_factory=list)
    known_future_covariates: list[ExecutionKnownFutureCovariate] = field(default_factory=list)


@dataclass(frozen=True)
class QuantileExecutionResult:
    """One requested quantile level and its values for a target."""

    level: float
    values: list[float]


@dataclass(frozen=True)
class TargetExecutionResult:
    """Normalized point forecast and requested quantiles for one target."""

    id: str
    forecast: list[float]
    quantiles: list[QuantileExecutionResult] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionResult:
    """Normalized engine predictions only: no timing, envelope or provenance."""

    targets: list[TargetExecutionResult]


class Engine(Protocol):
    """Minimal contract the API depends on."""

    @property
    def ready(self) -> bool:
        """Whether the engine finished loading and can serve forecasts."""

    @property
    def max_context(self) -> int | None:
        """Effective context length honored by the engine, or ``None`` if unbounded."""

    @property
    def max_variates(self) -> int | None:
        """Effective variates per forward pass, or ``None`` if unbounded."""

    def predict(self, problem: ExecutionProblem) -> ExecutionResult:
        """Run one canonical execution problem and return a normalized result."""


__all__ = [
    "Engine",
    "ExecutionKnownFutureCovariate",
    "ExecutionPastCovariate",
    "ExecutionProblem",
    "ExecutionResult",
    "ExecutionTarget",
    "QuantileExecutionResult",
    "TargetExecutionResult",
]
