from __future__ import annotations

import csv
import json
from datetime import date
from statistics import mean, median
from typing import Any

import update_data as base

HISTORY_PATH = base.DOCS / "prediction_history.csv"
FIELDS = [
    "forecast_day",
    "prediction_timestamp",
    "symbol",
    "stock_name",
    "current_price_at_prediction",
    "projected_price",
    "projection_low",
    "projection_high",
    "projection_date",
    "actual_price",
    "direction_projected",
    "direction_actual",
    "absolute_error",
    "percentage_error",
    "inside_range",
    "benchmark_absolute_error",
    "benchmark_percentage_error",
    "available_factors",
    "total_factors",
]


def num(value: Any) -> float | None:
    return base.to_num(value)


def read_rows() -> list[dict[str, str]]:
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(rows: list[dict[str, Any]]) -> None:
    with HISTORY_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def direction(start: float | None, end: float | None) -> str:
    if start is None or end is None:
        return ""
    if end > start:
        return "UP"
    if end < start:
        return "DOWN"
    return "FLAT"


def evaluate_rows(rows: list[dict[str, Any]], current_prices: dict[str, float]) -> None:
    today = date.today().isoformat()
    for row in rows:
        if row.get("actual_price"):
            continue
        projection_date = row.get("projection_date", "")
        symbol = row.get("symbol", "")
        actual = current_prices.get(symbol)
        if not projection_date or projection_date > today or actual is None:
            continue
        start = num(row.get("current_price_at_prediction"))
        projected = num(row.get("projected_price"))
        low = num(row.get("projection_low"))
        high = num(row.get("projection_high"))
        row["actual_price"] = f"{actual:.6f}"
        row["direction_projected"] = direction(start, projected)
        row["direction_actual"] = direction(start, actual)
        if projected is not None:
            abs_error = abs(actual - projected)
            row["absolute_error"] = f"{abs_error:.6f}"
            row["percentage_error"] = "" if actual == 0 else f"{abs_error / abs(actual):.6f}"
        if low is not None and high is not None:
            row["inside_range"] = "TRUE" if min(low, high) <= actual <= max(low, high) else "FALSE"
        if start is not None:
            b_err = abs(actual - start)
            row["benchmark_absolute_error"] = f"{b_err:.6f}"
            row["benchmark_percentage_error"] = "" if actual == 0 else f"{b_err / abs(actual):.6f}"


def append_today_predictions(rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    timestamp = payload.get("summary", {}).get("updated_at_london", "")
    forecast_day = timestamp[:10]
    existing = {(row.get("forecast_day"), row.get("symbol"), row.get("projection_date")) for row in rows}
    for stock in payload.get("stocks", []):
        values = stock.get("values", {})
        symbol = stock.get("symbol", "")
        projection_date = stock.get("prediction_date") or values.get("forecast_date") or ""
        key = (forecast_day, symbol, projection_date)
        if not symbol or key in existing:
            continue
        rows.append({
            "forecast_day": forecast_day,
            "prediction_timestamp": timestamp,
            "symbol": symbol,
            "stock_name": stock.get("name", ""),
            "current_price_at_prediction": values.get("price") or stock.get("current_price") or "",
            "projected_price": values.get("predicted_price") or stock.get("predicted_price") or "",
            "projection_low": values.get("prediction_low") or "",
            "projection_high": values.get("prediction_high") or "",
            "projection_date": projection_date,
            "actual_price": "",
            "direction_projected": "",
            "direction_actual": "",
            "absolute_error": "",
            "percentage_error": "",
            "inside_range": "",
            "benchmark_absolute_error": "",
            "benchmark_percentage_error": "",
            "available_factors": stock.get("available_factor_count", ""),
            "total_factors": stock.get("total_factor_count", ""),
        })
        existing.add(key)


def pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in rows if row.get("actual_price")]
    pending_rows = [row for row in rows if not row.get("actual_price")]
    pending = len(pending_rows)
    pending_dates = sorted({row.get("projection_date", "") for row in pending_rows if row.get("projection_date")})
    first_pending = pending_dates[0] if pending_dates else None
    explanation = "No closed forecast yet. Accuracy appears only after a projection date has passed and actual price can be compared."
    if not closed:
        return {
            "status": "Waiting for first closed forecast",
            "explanation": explanation,
            "closed_predictions": 0,
            "pending_predictions": pending,
            "first_pending_projection_date": first_pending,
            "directional_accuracy_pct": None,
            "mean_error_pct": None,
            "median_error_pct": None,
            "range_coverage_pct": None,
            "benchmark_mean_error_pct": None,
            "model_vs_benchmark": "Waiting for actual prices",
        }
    direction_hits = [1 for row in closed if row.get("direction_projected") == row.get("direction_actual")]
    error_pcts = [num(row.get("percentage_error")) for row in closed if num(row.get("percentage_error")) is not None]
    benchmark_pcts = [num(row.get("benchmark_percentage_error")) for row in closed if num(row.get("benchmark_percentage_error")) is not None]
    inside = [row.get("inside_range") == "TRUE" for row in closed if row.get("inside_range")]
    model_mean = mean(error_pcts) if error_pcts else None
    bench_mean = mean(benchmark_pcts) if benchmark_pcts else None
    vs_benchmark = "Waiting for benchmark comparison"
    if model_mean is not None and bench_mean is not None:
        vs_benchmark = "Beating no-change benchmark" if model_mean < bench_mean else "Not beating no-change benchmark"
    return {
        "status": "Measured",
        "explanation": "Closed forecasts have actual prices available, so accuracy metrics are now measured.",
        "closed_predictions": len(closed),
        "pending_predictions": pending,
        "first_pending_projection_date": first_pending,
        "directional_accuracy_pct": round(100 * len(direction_hits) / len(closed), 2),
        "mean_error_pct": pct(model_mean),
        "median_error_pct": pct(median(error_pcts)) if error_pcts else None,
        "range_coverage_pct": round(100 * sum(inside) / len(inside), 2) if inside else None,
        "benchmark_mean_error_pct": pct(bench_mean),
        "model_vs_benchmark": vs_benchmark,
    }


def attach_stock_accuracy(payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for stock in payload.get("stocks", []):
        symbol = stock.get("symbol")
        closed = [row for row in rows if row.get("symbol") == symbol and row.get("actual_price")]
        pending = [row for row in rows if row.get("symbol") == symbol and not row.get("actual_price")]
        first_pending = min((row.get("projection_date") for row in pending if row.get("projection_date")), default=None)
        if not closed:
            stock["accuracy"] = {
                "status": "Waiting for first closed forecast",
                "closed_predictions": 0,
                "pending_predictions": len(pending),
                "first_pending_projection_date": first_pending,
            }
            continue
        hit = sum(1 for row in closed if row.get("direction_projected") == row.get("direction_actual"))
        errors = [num(row.get("percentage_error")) for row in closed if num(row.get("percentage_error")) is not None]
        stock["accuracy"] = {
            "status": "Measured",
            "closed_predictions": len(closed),
            "pending_predictions": len(pending),
            "first_pending_projection_date": first_pending,
            "directional_accuracy_pct": round(100 * hit / len(closed), 2),
            "mean_error_pct": pct(mean(errors)) if errors else None,
        }


def main() -> None:
    data_path = base.DOCS / "data.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    current_prices = {stock.get("symbol", ""): num((stock.get("values") or {}).get("price") or stock.get("current_price")) for stock in payload.get("stocks", [])}
    current_prices = {symbol: value for symbol, value in current_prices.items() if value is not None}
    rows = read_rows()
    evaluate_rows(rows, current_prices)
    append_today_predictions(rows, payload)
    write_rows(rows)
    payload["accuracy"] = build_summary(rows)
    payload["accuracy"]["history_file"] = "prediction_history.csv"
    attach_stock_accuracy(payload, rows)
    data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
