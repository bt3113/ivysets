from __future__ import annotations

import json
import math
from typing import Any

import update_data as base

DAYS = 5
WINDOW = 20
TRADING_DAYS = 252


def n(x: Any) -> float | None:
    v = base.to_num(x)
    return v if v is not None and math.isfinite(v) else None


def money(x: float | None) -> str:
    return base.display("price", x)


def pc(x: float | None) -> str:
    return "Unavailable" if x is None else f"{x * 100:.3f}%"


def rr(x: float | None) -> str:
    return "Unavailable" if x is None else f"{x:.6f}"


def factor_set(stock: dict[str, Any], key: str, value: Any) -> None:
    for f in stock.get("factors", []):
        if f.get("key") == key:
            f["value"] = value
            f["display"] = base.display(key, value)
            f["available"] = value is not None
            return


def build_one(stock: dict[str, Any]) -> None:
    vals = stock.setdefault("values", {})
    price = n(vals.get("price") or stock.get("current_price"))
    r20 = n(vals.get("return_20d"))
    score = n(stock.get("overall_score"))
    vol20 = n(vals.get("realized_vol_20d"))

    if price is None or r20 is None or r20 <= -0.999999:
        vals["predicted_price"] = None
        vals["prediction_low"] = None
        vals["prediction_high"] = None
        stock["predicted_price"] = None
        stock["predicted_price_display"] = "Unavailable"
        stock["projection_calculation"] = {"status": "Unavailable", "lines": ["Projection calculation unavailable because price or 20-day return is unavailable."]}
        return

    daily = math.log1p(r20) / WINDOW
    drift_mult = math.exp(daily * DAYS)
    tilt = 0.0 if score is None else ((score - 50.0) / 50.0) * 0.0025
    factor_mult = math.exp(tilt * DAYS)
    projected = price * drift_mult * factor_mult
    daily_vol = None if vol20 is None else vol20 / math.sqrt(TRADING_DAYS)
    if daily_vol is None:
        low = None
        high = None
    else:
        span = daily_vol * math.sqrt(DAYS)
        low = projected * math.exp(-span)
        high = projected * math.exp(span)

    vals["predicted_price"] = projected
    vals["prediction_low"] = low
    vals["prediction_high"] = high
    stock["current_price"] = price
    stock["current_price_display"] = base.display("price", price)
    stock["predicted_price"] = projected
    stock["predicted_price_display"] = base.display("predicted_price", projected)
    for k in ("price", "predicted_price", "prediction_low", "prediction_high"):
        factor_set(stock, k, vals.get(k))

    stock["projection_calculation"] = {
        "status": "Calculated",
        "formula": "Projected Price = current price x drift multiplier x factor multiplier",
        "lines": [
            f"1. Current intraday price = {money(price)}.",
            f"2. 20 trading-day return = {pc(r20)}.",
            f"3. Daily drift = ln(1 + 20D return) / 20 = {pc(daily)}.",
            f"4. 5-day drift multiplier = exp(daily drift x 5) = {rr(drift_mult)}.",
            f"5. Overall factor score = {'Unavailable' if score is None else f'{score:.1f}/100'}.",
            f"6. Factor tilt = ((score - 50) / 50) x 0.0025 = {pc(tilt)}.",
            f"7. Factor multiplier = exp(factor tilt x 5) = {rr(factor_mult)}.",
            f"8. Projected Price = {money(price)} x {rr(drift_mult)} x {rr(factor_mult)} = {money(projected)}.",
            f"9. One-volatility range uses 20D annualized volatility {pc(vol20)}: {money(low)} to {money(high)}.",
        ],
    }


def main() -> None:
    path = base.DOCS / "data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("accuracy", None)
    payload.setdefault("summary", {})["projection_formula"] = "5-trading-day drift plus factor-score tilt."
    for stock in payload.get("stocks", []):
        stock.pop("accuracy", None)
        build_one(stock)
        vals = stock.get("values", {})
        stock["analysis_text"] = (
            f"{stock.get('symbol')} has {stock.get('available_factor_count')}/{stock.get('total_factor_count')} factors available. "
            f"Current displayed price is {stock.get('current_price_display')}. "
            f"Projected Price by {stock.get('prediction_date') or vals.get('forecast_date')} is {stock.get('predicted_price_display')}. "
            f"The calculation uses current price, 20-day return drift, and factor-score tilt. Exact lines are shown below. "
            f"Positive checks: {', '.join(stock.get('positives') or []) if stock.get('positives') else 'none shown'}. "
            f"Risk checks: {', '.join(stock.get('risks') or []) if stock.get('risks') else 'none shown'}."
        )
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
