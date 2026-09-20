from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verify_dist_archives import main, problems  # noqa: E402


def _wheel(path: Path, members: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, "")
    return path


def test_clean_wheel_has_no_problems(tmp_path: Path) -> None:
    wheel = _wheel(
        tmp_path / "precog_api-0.21.1-py3-none-any.whl",
        ["precog_api/__init__.py", "precog_api/app.py", "precog_api-0.21.1.dist-info/METADATA"],
    )
    assert problems(wheel) == []


def test_model_weight_is_rejected(tmp_path: Path) -> None:
    wheel = _wheel(
        tmp_path / "precog_api-0.21.1-py3-none-any.whl",
        ["precog_api/__init__.py", "precog_api/model.safetensors"],
    )
    assert any("model artifact" in problem for problem in problems(wheel))


def test_repository_payload_is_rejected(tmp_path: Path) -> None:
    wheel = _wheel(
        tmp_path / "precog_api-0.21.1-py3-none-any.whl",
        ["precog_api/__init__.py", "packages/sdk-python/src/precog_client/client.py", "uv.lock"],
    )
    found = problems(wheel)
    assert any("repository/cache path" in problem for problem in found)
    assert any("repository file" in problem for problem in found)


def test_main_fails_on_bad_archive(tmp_path: Path) -> None:
    _wheel(
        tmp_path / "precog_api-0.21.1-py3-none-any.whl",
        ["precog_api/__init__.py", "precog_api/weights.bin"],
    )
    assert main([str(tmp_path)]) == 1


def test_main_requires_archives(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 1
