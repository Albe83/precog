from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


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
