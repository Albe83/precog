from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_tag import InvalidReleaseTag, parse_release_tag  # noqa: E402

VALID: list[tuple[str, str, bool]] = [
    ("v1.2.3", "1.2.3", False),
    ("v0.0.0", "0.0.0", False),
    ("v10.20.30", "10.20.30", False),
    ("v1.2.3-alpha-beta", "1.2.3-alpha-beta", True),
    ("v1.2.3-rc.1", "1.2.3-rc.1", True),
    ("v1.2.3-0", "1.2.3-0", True),
    ("v1.2.3-0.1", "1.2.3-0.1", True),
    ("v1.2.3+linux-x86", "1.2.3+linux-x86", False),
    ("v1.2.3+build.5", "1.2.3+build.5", False),
    ("v1.2.3-rc.1+build-2", "1.2.3-rc.1+build-2", True),
]

INVALID: list[str] = [
    "",
    "main",
    "v1.2",
    "1.2.3",
    "V1.2.3",
    "638b97c538ae3d30fd72057458fbc52d72f81abe",
    "v1.2.3-01",  # numeric prerelease identifier with a leading zero
    "v1.2.3-alpha..1",  # empty identifier
    "v1.2.3-.alpha",  # empty identifier
    "v1.2.3-alpha.",  # trailing empty identifier
    "v1.2.3-",  # empty prerelease
    "v1.2.3+",  # empty build
    "v1.2.3-+x",  # empty prerelease before build
    "v1.2.3-alpha_beta",  # underscore is not allowed
    "v1.2.3+build_1",  # underscore is not allowed
    "v01.2.3",  # leading zero in major
    "v1.02.3",  # leading zero in minor
    "v1.2.03",  # leading zero in patch
    "release-1.2.3",
    "v1.2.3 ",
]


@pytest.mark.parametrize(("tag", "version", "prerelease"), VALID)
def test_valid_release_tags(tag: str, version: str, prerelease: bool) -> None:
    assert parse_release_tag(tag) == (version, prerelease)


@pytest.mark.parametrize("tag", INVALID)
def test_invalid_release_tags(tag: str) -> None:
    with pytest.raises(InvalidReleaseTag):
        parse_release_tag(tag)


def test_cli_reports_version_and_prerelease() -> None:
    script = Path(__file__).resolve().parents[1] / "release_tag.py"
    result = subprocess.run(
        [sys.executable, str(script), "--github-output", "v1.2.3-rc.1+build-2"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["version=1.2.3-rc.1+build-2", "prerelease=true"]


def test_cli_rejects_non_semver() -> None:
    script = Path(__file__).resolve().parents[1] / "release_tag.py"
    result = subprocess.run(
        [sys.executable, str(script), "--github-output", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "is not a SemVer release tag" in result.stderr
