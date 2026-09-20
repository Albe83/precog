"""Application release version consistency.

Every application artifact must report the same SemVer as the application
release (the root ``pyproject.toml``):

    root pyproject  ==  apps/api  ==  apps/mcp  ==  Helm chart version/appVersion

The SDK pair (``precog-client`` / ``precog-schemas``) is intentionally on its
own version train and is not checked here.

CLI: ``python tools/release_metadata.py`` prints the versions and exits non-zero
if any application artifact has drifted from the root version.
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APP_PACKAGES: dict[str, Path] = {
    "precog-api": Path("apps/api/pyproject.toml"),
    "precog-mcp": Path("apps/mcp/pyproject.toml"),
}
HELM_CHART = Path("deploy/helm/precog/Chart.yaml")

_CHART_VERSION = re.compile(r"^version:\s*\"?([^\"\s]+)\"?\s*$", re.MULTILINE)
_CHART_APP_VERSION = re.compile(r"^appVersion:\s*\"?([^\"\s]+)\"?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class VersionReport:
    application: str
    packages: dict[str, str]
    chart_version: str
    chart_app_version: str

    @property
    def mismatches(self) -> dict[str, str]:
        drifted: dict[str, str] = {
            name: version for name, version in self.packages.items() if version != self.application
        }
        if self.chart_version != self.application:
            drifted["helm chart version"] = self.chart_version
        if self.chart_app_version != self.application:
            drifted["helm chart appVersion"] = self.chart_app_version
        return drifted


def read_package_version(path: Path) -> str:
    with path.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def read_chart_versions(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    version = _CHART_VERSION.search(text)
    app_version = _CHART_APP_VERSION.search(text)
    if version is None or app_version is None:
        raise ValueError(f"could not read version/appVersion from {path}")
    return version.group(1), app_version.group(1)


def collect(root: Path = ROOT) -> VersionReport:
    chart_version, chart_app_version = read_chart_versions(root / HELM_CHART)
    return VersionReport(
        application=read_package_version(root / "pyproject.toml"),
        packages={name: read_package_version(root / rel) for name, rel in APP_PACKAGES.items()},
        chart_version=chart_version,
        chart_app_version=chart_app_version,
    )


def main() -> int:
    report = collect()
    print(f"application version: {report.application}")
    for name, version in report.packages.items():
        print(f"  {name}: {version}")
    print(f"  helm chart: version={report.chart_version} appVersion={report.chart_app_version}")

    if report.mismatches:
        for name, version in sorted(report.mismatches.items()):
            print(
                f"::error::{name} version {version} != application version "
                f"{report.application}; run release-please or fix the metadata",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
