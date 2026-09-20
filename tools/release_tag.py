"""Authoritative SemVer release-tag validation for the release workflows.

A release tag must be ``v`` followed by a valid `SemVer 2.0.0
<https://semver.org/>`_ version::

    vMAJOR.MINOR.PATCH[-prerelease][+build]

The leading ``v`` is required. Branches (``main``), raw commit SHAs and
malformed/``v``-shaped-but-not-SemVer names are rejected. This is the single
implementation used by both ``publish-images`` and ``publish-chart``.

CLI (used from workflows)::

    python tools/release_tag.py --github-output v1.2.3
    # -> version=1.2.3
    #    prerelease=false
"""

from __future__ import annotations

import argparse
import re
import sys

__all__ = ["InvalidReleaseTag", "parse_release_tag"]

# SemVer 2.0.0 with a mandatory leading "v".
#
# prerelease identifiers: numeric without leading zeroes, or alphanumerics that
# contain at least one non-digit; identifiers are dot-separated and non-empty.
# build identifiers: dot-separated alphanumerics (leading zeroes allowed),
# non-empty.
_SEMVER = re.compile(
    r"^v"
    r"(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>"
    r"(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*"
    r"))?"
    r"(?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    r"$"
)


class InvalidReleaseTag(ValueError):
    """The value is not a ``v``-prefixed SemVer release tag."""


def parse_release_tag(tag: str) -> tuple[str, bool]:
    """Return ``(version, is_prerelease)`` for a valid release tag.

    ``version`` is the SemVer value without the leading ``v`` (build metadata
    included). ``is_prerelease`` is based on the prerelease part only, so
    ``v1.2.3+build-1`` is stable. Raises :class:`InvalidReleaseTag` otherwise.
    """

    match = _SEMVER.fullmatch(tag)
    if match is None:
        raise InvalidReleaseTag(
            f"'{tag}' is not a SemVer release tag "
            "(expected vMAJOR.MINOR.PATCH[-prerelease][+build]); "
            "branches, commit SHAs and arbitrary refs are rejected"
        )

    version = f"{match.group('major')}.{match.group('minor')}.{match.group('patch')}"
    prerelease = match.group("prerelease")
    if prerelease is not None:
        version = f"{version}-{prerelease}"
    build = match.group("build")
    if build is not None:
        version = f"{version}+{build}"
    return version, prerelease is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v1.2.3")
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="emit version=/prerelease= lines for $GITHUB_OUTPUT and GitHub annotations",
    )
    args = parser.parse_args(argv)

    try:
        version, prerelease = parse_release_tag(args.tag)
    except InvalidReleaseTag as exc:
        if args.github_output:
            print(f"::error::{exc}", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1

    prerelease_value = "true" if prerelease else "false"
    if args.github_output:
        print(f"version={version}")
        print(f"prerelease={prerelease_value}")
    else:
        print(f"version={version} prerelease={prerelease_value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
