from __future__ import annotations

from pathlib import Path

import pytest

from precog_api import warmup
from precog_api.config import Settings

pytestmark = pytest.mark.unit

MODEL_ID = "google/timesfm-3.0-pytorch"


def _make_cache(root: Path, **files: str) -> Path:
    snapshot = root / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    for name in files or {"config.json": "{}", "model.safetensors": "x"}:
        (snapshot / name).write_text(files.get(name, "x"))
    return root


def test_is_model_present_true(tmp_path: Path) -> None:
    _make_cache(tmp_path)
    assert warmup.is_model_present(tmp_path, MODEL_ID) is True


def test_is_model_present_incomplete(tmp_path: Path) -> None:
    _make_cache(tmp_path, **{"config.json": "{}"})
    assert warmup.is_model_present(tmp_path, MODEL_ID) is False


def test_is_model_present_empty(tmp_path: Path) -> None:
    assert warmup.is_model_present(tmp_path, MODEL_ID) is False


def test_ensure_model_skips_download_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_cache(tmp_path)

    def _boom(_: Settings) -> None:
        raise AssertionError("download should not be called")

    monkeypatch.setattr(warmup, "download_model", _boom)
    settings = Settings(cache_dir=str(tmp_path), preload="auto")
    assert warmup.ensure_model(settings) is True


def test_ensure_model_downloads_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Settings] = []
    monkeypatch.setattr(warmup, "download_model", lambda s: calls.append(s))

    settings = Settings(cache_dir=str(tmp_path), preload="auto", preload_retries=0)
    assert warmup.ensure_model(settings) is True
    assert len(calls) == 1


def test_preload_never_does_not_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_: Settings) -> None:
        raise AssertionError("download should not be called")

    monkeypatch.setattr(warmup, "download_model", _boom)
    settings = Settings(cache_dir=str(tmp_path), preload="never", model_required=False)
    assert warmup.ensure_model(settings) is False


def test_preload_never_missing_is_fatal_when_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_: Settings) -> None:
        raise AssertionError("download should not be called")

    monkeypatch.setattr(warmup, "download_model", _boom)
    settings = Settings(cache_dir=str(tmp_path), preload="never", model_required=True)
    with pytest.raises(SystemExit):
        warmup.ensure_model(settings)


def test_failure_is_fatal_when_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_: Settings) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(warmup, "download_model", _boom)
    settings = Settings(
        cache_dir=str(tmp_path), preload="always", preload_retries=0, model_required=True
    )
    with pytest.raises(SystemExit):
        warmup.ensure_model(settings)


def test_failure_is_tolerated_when_not_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_: Settings) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(warmup, "download_model", _boom)
    settings = Settings(
        cache_dir=str(tmp_path), preload="always", preload_retries=0, model_required=False
    )
    assert warmup.ensure_model(settings) is False


def test_model_cache_path_uses_setting(tmp_path: Path) -> None:
    settings = Settings(cache_dir=str(tmp_path))
    assert warmup.model_cache_path(settings) == tmp_path


def _fake_repo(root: Path, revisions: list[str]) -> Path:
    repo = root / f"models--{MODEL_ID.replace('/', '--')}"
    (repo / "blobs").mkdir(parents=True)
    (repo / "snapshots").mkdir()
    for revision in revisions:
        blob = repo / "blobs" / f"{revision}.bin"
        blob.write_text("x")
        snapshot = repo / "snapshots" / revision
        snapshot.mkdir()
        (snapshot / "config.json").write_text("{}")
        (snapshot / "model.safetensors").symlink_to(blob)
    return repo


def test_prune_cache_keeps_pinned_revision(tmp_path: Path) -> None:
    kept, dropped = "a" * 40, "b" * 40
    repo = _fake_repo(tmp_path, [kept, dropped])
    settings = Settings(cache_dir=str(tmp_path), model_id=MODEL_ID, model_revision=kept)

    removed = warmup.prune_cache(settings)

    assert removed == 1
    assert (repo / "snapshots" / kept).is_dir()
    assert not (repo / "snapshots" / dropped).exists()
    assert (repo / "blobs" / f"{kept}.bin").exists()
    assert not (repo / "blobs" / f"{dropped}.bin").exists()


def test_prune_cache_skips_without_pinned_commit(tmp_path: Path) -> None:
    _fake_repo(tmp_path, ["a" * 40])
    settings = Settings(cache_dir=str(tmp_path), model_id=MODEL_ID, model_revision="main")
    assert warmup.prune_cache(settings) == 0


def test_prune_cache_missing_repo(tmp_path: Path) -> None:
    settings = Settings(cache_dir=str(tmp_path), model_id=MODEL_ID, model_revision="a" * 40)
    assert warmup.prune_cache(settings) == 0
