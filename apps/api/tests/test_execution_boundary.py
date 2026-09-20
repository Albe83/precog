from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_api.execution import (
    ExecutionKnownFutureCovariate,
    ExecutionPastCovariate,
    ExecutionProblem,
    ExecutionTarget,
)

QUANTILE_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

pytestmark = pytest.mark.unit


class _Output:
    def __init__(self, forecast: np.ndarray, quantiles: np.ndarray | None) -> None:
        self.forecast = forecast
        self.quantiles = quantiles


class _StubEvaluator:
    """Records predict_batch calls and returns deterministic vectors."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def predict_batch(self, **kwargs: Any):
        self.calls.append(kwargs)
        contexts = np.asarray(kwargs["contexts"][0])
        horizon = int(kwargs["horizon"])
        want_quantiles = bool(kwargs["return_quantiles"])
        if contexts.ndim == 1:
            forecast = np.full(horizon, contexts[-1], dtype=np.float32)
            quantiles = (
                np.tile(np.arange(9, dtype=np.float32), (horizon, 1)) if want_quantiles else None
            )
        else:
            targets = contexts.shape[0]
            forecast = np.tile(contexts[:, -1:], (1, horizon))
            quantiles = (
                np.tile(np.arange(9, dtype=np.float32), (targets, horizon, 1))
                if want_quantiles
                else None
            )
        return iter([_Output(forecast, quantiles)])


def _engine() -> tuple[TimesFM3Engine, _StubEvaluator]:
    engine = object.__new__(TimesFM3Engine)
    stub = _StubEvaluator()
    engine._evaluator = stub
    engine._max_context = 15360
    engine._max_variates = 32
    engine._quantile_levels = tuple(QUANTILE_LEVELS)
    engine._ready = True
    return engine, stub


def test_single_target_sets_explicit_evaluator_options() -> None:
    engine, stub = _engine()
    problem = ExecutionProblem(
        horizon=2,
        targets=[ExecutionTarget(id="a", values=[1.0, 2.0, 3.0])],
        quantiles=[0.1, 0.5, 0.9],
    )

    engine.predict(problem)

    call = stub.calls[0]
    assert call["make_positive"] is False
    assert call["use_symmetric_averaging"] is False
    assert call["sort_quantiles"] is True
    assert call["use_znorm"] is False
    assert call["padding_mode"] == "none"


def test_known_future_is_concatenated_at_the_engine_boundary() -> None:
    engine, stub = _engine()
    problem = ExecutionProblem(
        horizon=2,
        targets=[ExecutionTarget(id="a", values=[1.0, 2.0, 3.0])],
        quantiles=[0.5],
        past_covariates=[ExecutionPastCovariate(id="p", values=[0.0, 1.0, 2.0])],
        known_future_covariates=[
            ExecutionKnownFutureCovariate(id="k", history=[0.0, 0.0, 0.0], future=[1.0, 1.0])
        ],
    )

    engine.predict(problem)

    call = stub.calls[0]
    np.testing.assert_array_equal(
        np.asarray(call["past_only_covariates"][0]).reshape(-1), [0.0, 1.0, 2.0]
    )
    np.testing.assert_array_equal(
        np.asarray(call["past_future_covariates"][0]).reshape(-1), [0.0, 0.0, 0.0, 1.0, 1.0]
    )


def test_quantile_matrix_is_interpreted_by_requested_level() -> None:
    engine, _ = _engine()
    problem = ExecutionProblem(
        horizon=2,
        targets=[ExecutionTarget(id="a", values=[1.0, 2.0, 3.0])],
        quantiles=[0.1, 0.5, 0.9],
    )

    result = engine.predict(problem)

    quantiles = result.targets[0].quantiles
    assert [quantile.level for quantile in quantiles] == [0.1, 0.5, 0.9]
    assert quantiles[0].values == [0.0, 0.0]
    assert quantiles[1].values == [4.0, 4.0]
    assert quantiles[2].values == [8.0, 8.0]


def test_joint_targets_are_stacked_and_split_back() -> None:
    engine, stub = _engine()
    problem = ExecutionProblem(
        horizon=2,
        targets=[
            ExecutionTarget(id="a", values=[1.0, 2.0, 3.0]),
            ExecutionTarget(id="b", values=[4.0, 5.0, 6.0]),
        ],
        quantiles=[0.5],
    )

    result = engine.predict(problem)

    assert stub.calls[0]["contexts"][0].shape == (2, 3)
    assert [target.id for target in result.targets] == ["a", "b"]
    assert all(len(target.forecast) == 2 for target in result.targets)
    assert all(len(target.quantiles) == 1 for target in result.targets)


def test_point_only_request_skips_quantiles() -> None:
    engine, stub = _engine()
    problem = ExecutionProblem(
        horizon=2,
        targets=[ExecutionTarget(id="a", values=[1.0, 2.0, 3.0])],
        quantiles=[],
    )

    result = engine.predict(problem)

    assert stub.calls[0]["return_quantiles"] is False
    assert result.targets[0].quantiles == []


def test_unsupported_quantile_level_is_rejected() -> None:
    engine, _ = _engine()
    problem = ExecutionProblem(
        horizon=2,
        targets=[ExecutionTarget(id="a", values=[1.0, 2.0, 3.0])],
        quantiles=[0.55],
    )

    with pytest.raises(ValueError, match="unsupported quantile level"):
        engine.predict(problem)
