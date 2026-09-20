from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

CACHE = os.environ.get("PRECOG_CACHE_DIR", "/home/albe/.cache/precog/models")


def test_upstream_timesfm_limits_match_documented_capabilities() -> None:
    """Detect drift in the upstream TimesFM-3 effective limits.

    The API caps context and variates from the live evaluator; this asserts the
    values documented in ``docs/deploy.md`` still match the installed backend.
    """
    from timesfm3.torch.evaluator import _MAX_VARIATES_PER_FORWARD
    from timesfm3.torch.timesfm3_forecaster import _MAX_CONTEXT_LENGTH

    from precog_api.engine_timesfm3 import effective_max_variates

    assert effective_max_variates() == _MAX_VARIATES_PER_FORWARD
    assert _MAX_CONTEXT_LENGTH == 15360
    assert _MAX_VARIATES_PER_FORWARD == 32


def test_real_engine_execution_capabilities_are_effective() -> None:
    """`GET /v1/capabilities` reflects the live TimesFM-3 limits and grid (#179)."""
    if not Path(CACHE).is_dir():
        pytest.skip(f"model cache not available at {CACHE}")

    from precog_api.app import create_app
    from precog_api.config import Settings

    settings = Settings(
        engine="timesfm3",
        cache_dir=CACHE,
        local_files_only=True,
        per_core_batch_size=4,
        torch_threads=8,
    )
    with TestClient(create_app(settings)) as client:
        body = client.get("/v1/capabilities").json()

    assert body["engine"] == "timesfm3"
    assert body["limits"]["max_horizon"] == 1024
    assert body["limits"]["max_context"] == 15360
    assert body["limits"]["max_variates"] == 32
    assert body["limits"]["max_targets"] == 64
    assert len(body["quantile_levels"]) == 9
    # Runtime grid is the engine's, not a wire constant.
    assert 0.5 in body["quantile_levels"]
