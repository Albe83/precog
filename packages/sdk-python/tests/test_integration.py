from __future__ import annotations

import os

import pytest

from precog_client import PrecogClient

pytestmark = pytest.mark.integration


def test_contract_against_live_api() -> None:
    base_url = os.environ.get("PRECOG_API_URL")
    if not base_url:
        pytest.skip("set PRECOG_API_URL to run the contract test")

    with PrecogClient(base_url, timeout=60.0) as client:
        response = client.forecast(
            horizon=3,
            targets=[{"id": "s", "values": [100, 102, 101, 105, 107, 106, 108, 109, 112, 111]}],
            quantiles=[0.1, 0.5, 0.9],
        )

    assert response.model.id == "timesfm-3.0"
    assert len(response.targets[0].forecast) == 3
    assert [quantile.level for quantile in response.targets[0].quantiles] == [0.1, 0.5, 0.9]
