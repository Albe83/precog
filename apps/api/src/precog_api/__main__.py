"""Package entry point: ``python -m precog_api`` / ``precog-api``."""

from __future__ import annotations

import uvicorn

from precog_api.app import create_app
from precog_api.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
