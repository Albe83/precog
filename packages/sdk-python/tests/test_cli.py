from __future__ import annotations

import pytest

from precog_client.cli import request_from_csv, request_from_json

pytestmark = pytest.mark.unit


def test_request_from_csv_skips_header(tmp_path) -> None:
    path = tmp_path / "series.csv"
    path.write_text("value\n1\n2\n3\n")
    request = request_from_csv(str(path), horizon=2, series_id="x")
    assert request.series[0].id == "x"
    assert request.series[0].target == [1.0, 2.0, 3.0]
    assert request.horizon == 2


def test_request_from_csv_requires_numbers(tmp_path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("a\nb\n")
    with pytest.raises(ValueError):
        request_from_csv(str(path), horizon=1)


def test_request_from_json(tmp_path) -> None:
    path = tmp_path / "request.json"
    path.write_text('{"mode":"univariate","horizon":2,"series":[{"id":"a","target":[1,2,3]}]}')
    request = request_from_json(str(path))
    assert request.horizon == 2
    assert request.series[0].target == [1.0, 2.0, 3.0]
