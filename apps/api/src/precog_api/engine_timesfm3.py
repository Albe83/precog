"""TimesFM-3 engine.

Imported lazily so the base installation does not require torch. The mapping
follows the real TimesFM-3 API (``TimesFM3Evaluator.predict_batch``) validated
during the PREC-1 spike and contains all backend-specific shape translation
(ADR 0006): single vs joint targets, covariate stacking, known-future
history+future concatenation, quantile-column selection and evaluator options.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from precog_api.config import Settings
from precog_api.execution import (
    ExecutionKnownFutureCovariate,
    ExecutionPastCovariate,
    ExecutionProblem,
    ExecutionResult,
    QuantileExecutionResult,
    TargetExecutionResult,
)

# Used only when the engine extra is unavailable; the live evaluator is the
# source of truth so capability enforcement cannot drift from the backend.
_FALLBACK_MAX_VARIATES = 32


def effective_max_variates() -> int:
    """Variates the active TimesFM-3 evaluator accepts per forward pass.

    Above this limit the evaluator subsamples covariates and chunks targets,
    which would silently change the consumer's data; Precog rejects instead.
    """
    try:
        from timesfm3.torch.evaluator import _MAX_VARIATES_PER_FORWARD
    except ImportError:  # pragma: no cover - engine extra not installed
        return _FALLBACK_MAX_VARIATES
    return int(_MAX_VARIATES_PER_FORWARD)


class TimesFM3Engine:
    """Adapter around ``timesfm3.TimesFM3Evaluator``."""

    def __init__(self, settings: Settings) -> None:
        import torch  # noqa: PLC0415
        from timesfm3 import ModelConfig, TimesFM3Evaluator  # noqa: PLC0415

        if settings.torch_threads > 0:
            torch.set_num_threads(settings.torch_threads)

        model_dir = Path(settings.model_path)
        if model_dir.is_dir():
            checkpoint = settings.model_path
            local_only = True
        else:
            checkpoint = settings.model_id
            local_only = settings.local_files_only
        config = ModelConfig(
            checkpoint_path=checkpoint,
            per_core_batch_size=settings.per_core_batch_size,
            device=settings.device,
            revision=settings.model_revision,
            cache_dir=settings.cache_dir,
            local_files_only=local_only,
        )
        self._evaluator = TimesFM3Evaluator(config)
        # ``global_context`` is the context length the model actually honors;
        # anything longer is truncated by the backend.
        self._max_context = int(self._evaluator.global_context)
        self._max_variates = effective_max_variates()
        # The active quantile grid is the model's own, not the REST schema's.
        self._quantile_levels = tuple(float(level) for level in self._evaluator.config.quantiles)
        self._ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def max_context(self) -> int:
        return self._max_context

    @property
    def max_variates(self) -> int:
        return self._max_variates

    @property
    def quantile_levels(self) -> tuple[float, ...]:
        """The quantile grid the active model produces, in column order."""
        return self._quantile_levels

    def predict(self, problem: ExecutionProblem) -> ExecutionResult:
        if len(problem.targets) == 1:
            return self._predict_univariate(problem)
        return self._predict_joint(problem)

    def _predict_univariate(self, problem: ExecutionProblem) -> ExecutionResult:
        target = problem.targets[0]
        past_only = _stacked(problem.past_covariates)
        past_future = _stacked_known(problem.known_future_covariates)
        outputs = list(
            self._evaluator.predict_batch(
                contexts=[np.asarray(target.values, dtype=np.float32)],
                horizon=problem.horizon,
                past_only_covariates=[past_only] if past_only is not None else None,
                past_future_covariates=[past_future] if past_future is not None else None,
                ts_ids=[target.id],
                **_EVALUATOR_OPTIONS,
                return_quantiles=bool(problem.quantiles),
            )
        )
        return ExecutionResult(
            targets=[_target_result(target.id, outputs[0], problem, self._quantile_levels)]
        )

    def _predict_joint(self, problem: ExecutionProblem) -> ExecutionResult:
        contexts = [np.asarray(target.values, dtype=np.float32) for target in problem.targets]
        kwargs: dict[str, object] = {}
        past_only = _stacked(problem.past_covariates)
        past_future = _stacked_known(problem.known_future_covariates)
        if past_only is not None:
            kwargs["past_only_covariates"] = [past_only]
        if past_future is not None:
            kwargs["past_future_covariates"] = [past_future]
        outputs = list(
            self._evaluator.predict_batch(
                contexts=[np.stack(contexts)],
                horizon=problem.horizon,
                **_EVALUATOR_OPTIONS,
                return_quantiles=bool(problem.quantiles),
                **kwargs,
            )
        )
        output = outputs[0]
        return ExecutionResult(
            targets=[
                _target_result(target.id, output, problem, self._quantile_levels, index=index)
                for index, target in enumerate(problem.targets)
            ]
        )


# Explicit evaluator options (ADR 0007): set rather than inherited, so evaluator
# benchmark defaults cannot silently change Precog behavior.
_EVALUATOR_OPTIONS: dict[str, object] = {
    "use_symmetric_averaging": False,
    "make_positive": False,
    "sort_quantiles": True,
    "use_znorm": False,
    "padding_mode": "none",
}


def _stacked(covariates: list[ExecutionPastCovariate]) -> np.ndarray | None:
    """Stack covariate channels into an ``(n_channels, length)`` array."""
    if not covariates:
        return None
    return np.stack([np.asarray(covariate.values, dtype=np.float32) for covariate in covariates])


def _stacked_known(known: list[ExecutionKnownFutureCovariate]) -> np.ndarray | None:
    """Concatenate known-future ``history + future`` into the backend array."""
    if not known:
        return None
    return np.stack(
        [
            np.asarray([*covariate.history, *covariate.future], dtype=np.float32)
            for covariate in known
        ]
    )


def _target_result(
    target_id: str,
    output: Any,
    problem: ExecutionProblem,
    quantile_levels: tuple[float, ...],
    *,
    index: int | None = None,
) -> TargetExecutionResult:
    """Normalize one backend output into a canonical target result."""
    forecast = np.asarray(output.forecast)
    point = forecast.reshape(-1) if index is None else np.atleast_2d(forecast)[index].reshape(-1)

    quantiles: list[QuantileExecutionResult] = []
    if problem.quantiles:
        raw = output.quantiles
        if raw is None:
            raise RuntimeError("evaluator returned no quantiles although they were requested")
        matrix = np.asarray(raw)
        if index is not None:
            matrix = matrix[index]
        for level in problem.quantiles:
            column = _column_index(level, quantile_levels)
            quantiles.append(
                QuantileExecutionResult(level=level, values=matrix[:, column].tolist())
            )

    return TargetExecutionResult(id=target_id, forecast=point.tolist(), quantiles=quantiles)


def _column_index(level: float, quantile_levels: tuple[float, ...]) -> int:
    """Map a requested level to its column in the active model quantile grid."""
    for index, candidate in enumerate(quantile_levels):
        if abs(candidate - level) < 1e-9:
            return index
    raise ValueError(f"unsupported quantile level {level}")
