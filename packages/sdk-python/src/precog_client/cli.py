"""Command-line interface for the Precog API."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from precog_client.client import PrecogClient
from precog_client.errors import PrecogError
from precog_schemas import ForecastRequest, HistoricalSeries


def request_from_csv(
    path: str,
    *,
    horizon: int,
    series_id: str = "series",
    quantiles: list[float] | None = None,
) -> ForecastRequest:
    """Build a single-target request from a single-column CSV (header optional)."""
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
        horizon=horizon,
        targets=[HistoricalSeries(id=series_id, values=values)],
        quantiles=list(quantiles or []),
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
    forecast.add_argument("--csv", help="Single-column CSV series.")
    forecast.add_argument("--horizon", type=int, default=24, help="Steps to forecast.")
    forecast.add_argument("--id", default="series", help="Series id for --csv.")
    forecast.add_argument(
        "--quantiles",
        default="",
        help="Comma-separated quantile levels, e.g. 0.1,0.5,0.9 (default: point-only).",
    )

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
                quantiles = [float(level) for level in args.quantiles.split(",") if level.strip()]
                request = request_from_csv(
                    args.csv, horizon=args.horizon, series_id=args.id, quantiles=quantiles
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
