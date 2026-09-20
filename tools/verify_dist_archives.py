"""Reject model/cache and repository payloads from built Python distributions.

Used by the packaging workflows to prove that wheels/sdists contain only the
intended package. It is intentionally conservative: it fails on model weight
files, model/cache directories, and signs of a whole-checkout payload (other
workspace trees, ``uv.lock``, VCS/node_modules).

CLI: ``python tools/verify_dist_archives.py <dir-or-archive>...``
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_SUFFIXES = (".bin", ".ckpt", ".gguf", ".onnx", ".pt", ".pth", ".safetensors")
FORBIDDEN_PATH_SEGMENTS = (
    "/.git/",
    "/.venv/",
    "/.cache/",
    "/node_modules/",
    "/models/",
    "/benchmarks/",
    "/deploy/",
    "/webui/",
    "/apps/",
    "/packages/",
)
FORBIDDEN_FILENAMES = ("uv.lock",)


def archive_members(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return archive.getnames()
    raise ValueError(f"unsupported archive type: {path}")


def problems(path: Path) -> list[str]:
    found: list[str] = []
    for member in archive_members(path):
        normalized = member.lower().replace("\\", "/")
        for suffix in FORBIDDEN_SUFFIXES:
            if normalized.endswith(suffix):
                found.append(f"model artifact: {member}")
        padded = f"/{normalized.strip('/')}/"
        for segment in FORBIDDEN_PATH_SEGMENTS:
            if segment in padded:
                found.append(f"repository/cache path ({segment}): {member}")
        if Path(normalized).name in FORBIDDEN_FILENAMES:
            found.append(f"repository file: {member}")
    return found


def _archives(paths: list[Path]) -> list[Path]:
    archives: list[Path] = []
    for path in paths:
        if path.is_dir():
            archives.extend(
                candidate
                for candidate in sorted(path.rglob("*"))
                if candidate.is_file()
                and (candidate.suffix == ".whl" or candidate.name.endswith(".tar.gz"))
            )
        else:
            archives.append(path)
    return archives


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="dist directories or archives")
    args = parser.parse_args(argv)

    archives = _archives(args.paths)
    if not archives:
        print("::error::no distribution archives found", file=sys.stderr)
        return 1

    failed = False
    for archive in archives:
        found = problems(archive)
        if found:
            failed = True
            for problem in found:
                print(f"::error::{archive}: {problem}", file=sys.stderr)
        else:
            print(f"ok: {archive}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
