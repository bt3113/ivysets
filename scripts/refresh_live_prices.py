from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import requests
from dateutil import tz

import update_data as base

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "IvySets live price refresh contact: tekwanib1@gmail.com",
    "Accept": "application/json,text/html,*/*;q=0.8",
})

TIMEZONE = "Europe/London"


def chart_url(symbol: str, interval: str = "1m", range_: str = "1d") -> str:
    safe = requests.utils.quote(symbol, safe="")
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}?range={range_}&interval={interval}&includePrePost=true"


def quote_page(symbol: str) -> str:
    return f"https://finance.yahoo.com/quote/{requests.utils.quote(symbol, safe='')}"


def sec_filings(cik: str) -> str:
    clean = str(cik).lstrip("0") or str(cik)
    return f"https://www.sec.gov/edgar/browse/?CIK={clean}&owner=exclude&action=getcompany"


def get_chart(symbol: str) -> tuple[float | None, str | None, str, str]:
    url = chart_url(symbol)
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        payload = response.json()
        result = (((payload or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None, None, url, "No chart result"
        timestamps = result.get("timestamp") or []
        closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
        last_price = None
        last_ts = None
        for ts_value, close_value in zip(timestamps, closes):
            price = base.to_num(close_value)
            if price is not None and math.isfinite(price):
                last_price = price
                last_ts = ts_value
        meta = result.get("meta") or {}
        regular = base.to_num(meta.get("regularMarketPrice"))
        if last_price is None and regular is not None:
            last_price = regular
            last_ts = meta.get("regularMarketTime")
        if last_ts:
            dt = datetime.fromtimestamp(int(last_ts), tz=timezone.utc).astimezone(tz.gettz(TIMEZONE))
            return last_price, dt.isoformat(timespec="seconds"), url, "Yahoo intraday chart"
        return last_price, None, url, "Yahoo intraday chart"
    except Exception as exc:
        return None, None, url, f"Yahoo intraday error: {exc}"


def get_factor(stock: dict[str, Any], key: str) -> dict[str, Any] | None:
    for factor in stock.get("factors", []):
        if factor.get("key") == key:
            return factor
    return None


def set_factor(stock: dict[str, Any], key: str, value: Any) -> None:
    factor = get_factor(stock, key)
    if factor is None:
        return
    factor["value"] = value
    factor["display"] = base.display(key, value)
    factor["available"] = value is not None


def source_links(stock: dict[str, Any], source_type: str) -> list[dict[str, str]]:
    symbol = stock.get("symbol", "")
    cik = stock.get("cik", "")
    yahoo_human = {"label": "Yahoo quote page", "url": quote_page(symbol)}
    yahoo_intraday = {"label": "Yahoo intraday source", "url": chart_url(symbol)}
    yahoo_daily = {"label": "Yahoo daily source", "url": chart_url(symbol, interval="1d", range_="2y")}
    sec_human = {"label": "SEC filings page", "url": sec_filings(cik)}
    sec_json = {"label": "SEC companyfacts source", "url": base.sec_url(cik)}
    if source_type == "yahoo":
        return [yahoo_human, yahoo_intraday, yahoo_daily]
    if source_type == "sec":
        return [sec_human, sec_json]
    return [yahoo_human, yahoo_intraday, yahoo_daily, sec_human, sec_json]


def update_sources(stock: dict[str, Any]) -> None:
    for factor in stock.get("factors", []):
        factor["sources"] = source_links(stock, factor.get("source_type", "calculated"))


def recompute_price_dependent(stock: dict[str, Any], old_price: float | None, new_price: float) -> None:
    values = stock.setdefault("values", {})
    values["price"] = new_price
    shares = values.get("shares")
    if shares is not None:
        values["market_cap"] = new_price * shares
    if values.get("market_cap") is not None:
        values["enterprise_value"] = values.get("market_cap") + (values.get("total_debt") or 0) - (values.get("cash") or 0)
    values["pe"] = base.div(new_price, values.get("eps_diluted"))
    values["ps"] = base.div(values.get("market_cap"), values.get("revenue"))
    values["pb"] = base.div(values.get("market_cap"), values.get("shareholders_equity"))
    values["p_fcf"] = base.div(values.get("market_cap"), values.get("free_cash_flow"))
    values["ev_sales"] = base.div(values.get("enterprise_value"), values.get("revenue"))
    values["ev_ebitda"] = base.div(values.get("enterprise_value"), values.get("ebitda"))
    if old_price and old_price > 0:
        scale = new_price / old_price
        for key in ("predicted_price", "prediction_low", "prediction_high"):
            if values.get(key) is not None:
                values[key] *= scale

    for key in ["price", "market_cap", "enterprise_value", "pe", "ps", "pb", "p_fcf", "ev_sales", "ev_ebitda", "predicted_price", "prediction_low", "prediction_high"]:
        set_factor(stock, key, values.get(key))

    stock["current_price"] = new_price
    stock["current_price_display"] = base.display("price", new_price)
    stock["predicted_price"] = values.get("predicted_price")
    stock["predicted_price_display"] = base.display("predicted_price", values.get("predicted_price"))


def refresh_stock(stock: dict[str, Any]) -> None:
    symbol = stock.get("symbol", "")
    if not symbol:
        return
    old_price = base.to_num((stock.get("values") or {}).get("price") or stock.get("current_price"))
    new_price, source_time, source_url, source_status = get_chart(symbol)
    update_sources(stock)
    stock["price_source"] = {
        "provider": "Yahoo Finance intraday chart",
        "quote_page": quote_page(symbol),
        "source_url": source_url,
        "source_time_london": source_time,
        "status": source_status,
        "note": "Used for current displayed price. Other technical factors use daily history; SEC factors use company filings or companyfacts.",
    }
    if new_price is None:
        stock["price_source"]["status"] = f"Could not refresh intraday price. Existing price retained. {source_status}"
        return
    recompute_price_dependent(stock, old_price, new_price)
    price_factor = get_factor(stock, "price")
    if price_factor:
        price_factor["sources"] = [{"label": "Yahoo quote page", "url": quote_page(symbol)}, {"label": "Yahoo intraday source", "url": source_url}]
        price_factor["source_time_london"] = source_time
    stock["available_factor_count"] = sum(1 for factor in stock.get("factors", []) if factor.get("available"))


def main() -> None:
    data_path = base.DOCS / "data.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    for stock in payload.get("stocks", []):
        refresh_stock(stock)
    payload.setdefault("summary", {})["price_mode"] = "intraday"
    payload["summary"]["price_source"] = "Yahoo Finance intraday chart, refreshed by GitHub workflow"
    payload["summary"]["price_source_warning"] = "Not exchange-direct real time. GitHub Pages shows the latest completed workflow result."
    payload["summary"]["updated_at_london"] = base.now()
    data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
