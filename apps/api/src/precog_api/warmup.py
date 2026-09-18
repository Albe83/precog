"""Provision the TimesFM-3 weights into the model cache.

Used by the container entrypoint to download the weights into a mounted volume
when they are not already present. Works with any volume type: an ephemeral
directory, a named volume, a bind mount or a Kubernetes PVC.

The download is environment-agnostic: it only needs the Hugging Face hub layout
under ``PRECOG_CACHE_DIR`` and the pinned revision.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from precog_api.config import Settings

logger = logging.getLogger("precog.warmup")

REQUIRED_FILES = ("config.json", "model.safetensors")


def model_cache_path(settings: Settings) -> Path:
    """Return the cache directory the engine and the downloader share."""
    if settings.cache_dir:
        return Path(settings.cache_dir)
    from huggingface_hub import constants  # noqa: PLC0415

    return Path(constants.HF_HUB_CACHE)


def is_model_present(cache_dir: Path, model_id: str) -> bool:
    """Check for a complete snapshot of ``model_id`` in the hub cache."""
    snapshots = cache_dir / f"models--{model_id.replace('/', '--')}" / "snapshots"
    if not snapshots.is_dir():
        return False
    return any(
        all((snapshot / name).is_file() for name in REQUIRED_FILES)
        for snapshot in snapshots.iterdir()
        if snapshot.is_dir()
    )


def download_model(settings: Settings) -> None:
    """Download the pinned model revision into the cache directory."""
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    cache_dir = model_cache_path(settings)
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "downloading %s@%s into %s",
        settings.model_id,
        settings.model_revision or "main",
        cache_dir,
    )
    snapshot_download(
        repo_id=settings.model_id,
        revision=settings.model_revision,
        cache_dir=str(cache_dir),
        token=settings.hf_token,
    )


def ensure_model(settings: Settings) -> bool:
    """Ensure the model is available locally, downloading it if needed."""
    cache_dir = model_cache_path(settings)
    if settings.preload == "never":
        present = is_model_present(cache_dir, settings.model_id)
        logger.info("preload disabled; model present=%s in %s", present, cache_dir)
        if not present and settings.model_required:
            raise SystemExit(
                f"model {settings.model_id} not present in {cache_dir} and PRECOG_PRELOAD=never"
            )
        return present
    if settings.preload == "auto" and is_model_present(cache_dir, settings.model_id):
        logger.info("model already present in %s", cache_dir)
        return True

    last_error: Exception | None = None
    for attempt in range(settings.preload_retries + 1):
        try:
            download_model(settings)
            return True
        except Exception as exc:  # noqa: BLE001 - report any download failure
            last_error = exc
            logger.warning("download attempt %d failed: %s", attempt + 1, exc)
            if attempt < settings.preload_retries:
                time.sleep(min(2**attempt, 30))

    message = f"failed to provision model {settings.model_id}: {last_error}"
    if settings.model_required:
        raise SystemExit(message)
    logger.error("%s (continuing; startup may fail)", message)
    return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ensure_model(Settings())


if __name__ == "__main__":
    main()
