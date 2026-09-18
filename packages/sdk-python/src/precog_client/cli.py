"""Command-line interface for the Precog API."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from precog_client.client import PrecogClient
from precog_client.errors import PrecogError
from precog_schemas import ForecastOptions, ForecastRequest, Mode, SeriesInput


def request_from_csv(
    path: str,
    *,
    horizon: int,
    series_id: str = "series",
    mode: str | Mode = Mode.univariate,
) -> ForecastRequest:
    """Build a univariate request from a single-column CSV (header optional)."""
    values: list[float] = []
    with Path(path).open(newline="") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            try:
                values.append(float(row[-1].strip()))
            except ValueError:
                continue  # skip header or non-numeric cells
    if not values:
        raise ValueError(f"no numeric values found in {path}")
    return ForecastRequest(
        mode=Mode(mode),
        horizon=horizon,
        series=[SeriesInput(id=series_id, target=values)],
        options=ForecastOptions(),
    )


def request_from_json(path: str) -> ForecastRequest:
    """Build a request from a full ForecastRequest JSON payload."""
    return ForecastRequest.model_validate(json.loads(Path(path).read_text()))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="precog", description="Precog API client.")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL.")
    parser.add_argument("--api-key", default=None, help="Bearer token.")
    sub = parser.add_subparsers(dest="command", required=True)

    forecast = sub.add_parser("forecast", help="Run a forecast.")
    forecast.add_argument("--file", help="ForecastRequest JSON file.")
    forecast.add_argument("--csv", help="Single-column CSV series (univariate).")
    forecast.add_argument("--horizon", type=int, default=24, help="Steps to forecast.")
    forecast.add_argument("--id", default="series", help="Series id for --csv.")
    forecast.add_argument("--mode", default="univariate", choices=["univariate", "multivariate"])

    sub.add_parser("capabilities", help="Show model and API capabilities.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    with PrecogClient(args.url, api_key=args.api_key) as client:
        try:
            if args.command == "capabilities":
                payload: dict = client.capabilities().model_dump(mode="json")
            elif args.file:
                payload = client.forecast_request(request_from_json(args.file)).model_dump(
                    mode="json"
                )
            elif args.csv:
                request = request_from_csv(
                    args.csv, horizon=args.horizon, series_id=args.id, mode=args.mode
                )
                payload = client.forecast_request(request).model_dump(mode="json")
            else:
                parser.error("forecast requires --file or --csv")
                return 2
        except (PrecogError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    json.dump(payload, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
