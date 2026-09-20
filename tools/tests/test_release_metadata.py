from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_metadata import (  # noqa: E402
    ROOT,
    collect,
    expected_mismatches,
    read_chart_versions,
    read_package_version,
)

ROOT_PYPROJECT = """\
[project]
name = "precog"
version = "{version}"
"""

APP_PYPROJECT = """\
[project]
name = "{name}"
version = "{version}"
"""

CHART = """\
apiVersion: v2
name: precog
version: {version}
appVersion: {app_version}
"""


def _write_repo(
    root: Path,
    *,
    app: str,
    api: str,
    mcp: str,
    chart_version: str,
    chart_app_version: str,
) -> None:
    (root / "apps/api").mkdir(parents=True)
    (root / "apps/mcp").mkdir(parents=True)
    (root / "deploy/helm/precog").mkdir(parents=True)
    (root / "pyproject.toml").write_text(ROOT_PYPROJECT.format(version=app))
    (root / "apps/api/pyproject.toml").write_text(
        APP_PYPROJECT.format(name="precog-api", version=api)
    )
    (root / "apps/mcp/pyproject.toml").write_text(
        APP_PYPROJECT.format(name="precog-mcp", version=mcp)
    )
    (root / "deploy/helm/precog/Chart.yaml").write_text(
        CHART.format(version=chart_version, app_version=chart_app_version)
    )


def test_repository_application_versions_are_consistent() -> None:
    report = collect(ROOT)
    assert report.mismatches == {}


def test_mismatches_are_detected(tmp_path: Path) -> None:
    _write_repo(
        tmp_path,
        app="2.0.0",
        api="1.9.0",
        mcp="2.0.0",
        chart_version="2.0.0",
        chart_app_version="1.9.0",
    )
    assert collect(tmp_path).mismatches == {
        "precog-api": "1.9.0",
        "helm chart appVersion": "1.9.0",
    }


def test_chart_versions_allow_quotes(tmp_path: Path) -> None:
    chart = tmp_path / "Chart.yaml"
    chart.write_text('version: "1.2.3"\nappVersion: "1.2.3"\n')
    assert read_chart_versions(chart) == ("1.2.3", "1.2.3")


def test_read_package_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(ROOT_PYPROJECT.format(version="3.4.5"))
    assert read_package_version(pyproject) == "3.4.5"


def test_expected_mismatches() -> None:
    report = collect(ROOT)
    assert expected_mismatches(report, None) == []
    assert expected_mismatches(report, report.application) == []
    assert expected_mismatches(report, "99.0.0") == [
        f"application version {report.application} != expected release 99.0.0"
    ]
