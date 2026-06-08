from __future__ import annotations

import csv
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dateutil import tz

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TIMEZONE = "Europe/London"
WATCHLIST = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "BTC-USD"]
TRADING_DAYS = 252

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 IvySets/2.0",
        "Accept": "application/json,text/csv,text/html,application/xml;q=0.9,*/*;q=0.8",
    }
)

METHODOLOGY = [
    {
        "id": "MKT_TREND",
        "module": "Market Trend",
        "formula": "SPY close vs 50DMA/200DMA; 63D and 252D total return.",
        "rationale": "Trend and time-series momentum are used as empirical regime filters; the dashboard uses them as trade-permission gates, not forecasts.",
        "primary_source": "Yahoo Finance chart API",
        "evidence_reference": "Hurst, Ooi, Pedersen, A Century of Evidence on Trend-Following Investing; Moskowitz, Ooi, Pedersen, Time Series Momentum.",
        "failure_rule": "If history is insufficient or the source fails, the module is marked Unavailable and excluded from the regime score.",
    },
    {
        "id": "VOL_RISK",
        "module": "Volatility / Risk Budget",
        "formula": "20D annualized realized volatility = stdev(log returns, 20) * sqrt(252); VIX percentile vs 1Y history; SPY drawdown vs 63D high.",
        "rationale": "Volatility determines risk budget. Higher realized or implied volatility reduces permitted position size.",
        "primary_source": "Yahoo Finance chart API, Cboe VIX via Yahoo symbol ^VIX",
        "evidence_reference": "Cboe VIX methodology; volatility-managed portfolio literature.",
        "failure_rule": "If volatility cannot be computed, the module is marked Unavailable and no synthetic volatility is inserted.",
    },
    {
        "id": "CREDIT_STRESS",
        "module": "Credit Stress",
        "formula": "High Yield OAS current level, 3Y z-score, and 20-observation change.",
        "rationale": "Widening high-yield spreads indicate deteriorating credit risk appetite and reduce equity risk permission.",
        "primary_source": "FRED BAMLH0A0HYM2",
        "evidence_reference": "ICE BofA US High Yield Option-Adjusted Spread definition via FRED.",
        "failure_rule": "If FRED data is unavailable, credit stress is marked Unavailable and not estimated.",
    },
    {
        "id": "FIN_CONDITIONS",
        "module": "Financial Conditions",
        "formula": "NFCI level and 4-week change.",
        "rationale": "Positive NFCI values indicate tighter-than-average financial conditions; tightening conditions reduce risk permission.",
        "primary_source": "FRED NFCI",
        "evidence_reference": "Chicago Fed National Financial Conditions Index documentation.",
        "failure_rule": "If NFCI data is unavailable, the module is marked Unavailable.",
    },
    {
        "id": "OPTIONS_CROWDING",
        "module": "Options Crowding",
        "formula": "Total, equity, and index put/call ratios with trailing percentile rank.",
        "rationale": "Put/call extremes identify defensive hedging or speculative crowding; used as context, not a direct signal.",
        "primary_source": "Cboe daily options statistics CSV",
        "evidence_reference": "Cboe daily market statistics; AAII sentiment indicator guidance.",
        "failure_rule": "If Cboe CSV parsing fails, options data is marked Unavailable.",
    },
    {
        "id": "RETAIL_SENTIMENT",
        "module": "Retail Sentiment Context",
        "formula": "AAII bullish percentage minus bearish percentage, validation required.",
        "rationale": "AAII survey is used only as contrarian context and never as a standalone trading trigger.",
        "primary_source": "AAII Investor Sentiment Survey",
        "evidence_reference": "AAII survey documentation and caveat that sentiment should not be used in isolation.",
        "failure_rule": "If bullish/neutral/bearish percentages cannot be validated, the module is marked Unavailable.",
    },
    {
        "id": "VALUATION_CONTEXT",
        "module": "Long-Term Valuation",
        "formula": "Shiller CAPE current value and percentile when source history is available.",
        "rationale": "CAPE is long-horizon allocation context, not a short-term trade timer.",
        "primary_source": "Multpl Shiller PE table",
        "evidence_reference": "Cyclically adjusted price-to-earnings ratio / Shiller CAPE literature.",
        "failure_rule": "If CAPE cannot be parsed and validated, valuation is marked Unavailable.",
    },
    {
        "id": "WATCHLIST_READINESS",
        "module": "Watchlist Trade Readiness",
        "formula": "Ticker trend vs 50DMA/200DMA, 63D return, relative strength vs SPY, 20D realized volatility, 63D drawdown, and volatility-adjusted size.",
        "rationale": "Ranks symbols by observable trend, relative strength, volatility, and damage control.",
        "primary_source": "Yahoo Finance chart API",
        "evidence_reference": "Momentum, relative strength, trend-following, and volatility risk-budgeting literature.",
        "failure_rule": "If a ticker has insufficient history, its status is Unavailable and size is 0x.",
    },
]


def now() -> str:
    return datetime.now(tz.gettz(TIMEZONE)).isoformat(timespec="seconds")


def num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else value
    try:
        cleaned = str(value).strip().replace(",", "").replace("%", "")
        if cleaned in {"", ".", "-", "—", "N/A"}:
            return None
        parsed = float(cleaned)
        return None if math.isnan(parsed) or math.isinf(parsed) else parsed
    except Exception:
        return None


def pct(value: float | None, decimals: int = 1) -> str:
    return "Unavailable" if value is None else f"{value * 100:.{decimals}f}%"


def fmt(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "Unavailable"
    return f"{value:,.{decimals}f}"


def clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def get_text(url: str) -> str | None:
    try:
        response = SESSION.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def get_json(url: str) -> dict[str, Any] | None:
    try:
        response = SESSION.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def percentile_rank(value: float | None, history: list[float]) -> float | None:
    history = [x for x in history if x is not None and math.isfinite(x)]
    if value is None or not history:
        return None
    below = sum(1 for x in history if x <= value)
    return below / len(history)


def z_score(value: float | None, history: list[float]) -> float | None:
    history = [x for x in history if x is not None and math.isfinite(x)]
    if value is None or len(history) < 30:
        return None
    sd = statistics.stdev(history)
    if sd == 0:
        return None
    return (value - statistics.mean(history)) / sd


def yahoo_history(symbol: str, range_: str = "2y") -> dict[str, Any]:
    safe = requests.utils.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}?range={range_}&interval=1d"
    data = get_json(url)
    if not data:
        return {"symbol": symbol, "url": url, "closes": [], "timestamps": []}
    try:
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = [num(x) for x in result.get("indicators", {}).get("quote", [{}])[0].get("close", [])]
        paired = [(t, c) for t, c in zip(timestamps, closes) if c is not None and c > 0]
        return {"symbol": symbol, "url": url, "timestamps": [p[0] for p in paired], "closes": [p[1] for p in paired]}
    except Exception:
        return {"symbol": symbol, "url": url, "closes": [], "timestamps": []}


def sma(values: list[float], window: int) -> float | None:
    return None if len(values) < window else sum(values[-window:]) / window


def return_n(values: list[float], window: int) -> float | None:
    if len(values) <= window or values[-window - 1] == 0:
        return None
    return values[-1] / values[-window - 1] - 1


def realized_vol(values: list[float], window: int = 20) -> float | None:
    if len(values) <= window:
        return None
    returns = [math.log(values[i] / values[i - 1]) for i in range(len(values) - window, len(values)) if values[i - 1] > 0]
    if len(returns) < max(10, window // 2):
        return None
    return statistics.stdev(returns) * math.sqrt(TRADING_DAYS)


def drawdown(values: list[float], window: int = 63) -> float | None:
    if len(values) < window:
        return None
    high = max(values[-window:])
    return None if high <= 0 else values[-1] / high - 1


def module(id_: str, title: str, status: str, score: float | None, decision: str, evidence: list[dict[str, Any]], source: str, source_url: str, formula: str) -> dict[str, Any]:
    return {
        "id": id_,
        "title": title,
        "status": status,
        "score": None if score is None else round(score, 2),
        "decision_impact": decision,
        "evidence": evidence,
        "source": source,
        "source_url": source_url,
        "formula": formula,
        "updated_at_london": now(),
        "available": score is not None,
    }


def metric(label: str, value: float | None, display: str, status: str) -> dict[str, Any]:
    return {"label": label, "value": None if value is None else round(value, 6), "display": display, "status": status}


def market_trend_module(spy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float | None]]:
    closes = spy["closes"]
    close = closes[-1] if closes else None
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200)
    ret63 = return_n(closes, 63)
    ret252 = return_n(closes, 252)
    if None in (close, ma50, ma200, ret63, ret252):
        mod = module("MKT_TREND", "Market Trend", "Unavailable", None, "No trade permission change; required data unavailable.", [], "Yahoo Finance", "https://finance.yahoo.com/quote/SPY", "SPY close vs 50DMA/200DMA plus 63D/252D momentum.")
        return mod, {"close": close, "ma50": ma50, "ma200": ma200, "ret63": ret63, "ret252": ret252}
    points = 0
    points += 2 if close > ma200 else -2
    points += 1 if close > ma50 else -1
    points += 1 if ma50 > ma200 else -1
    points += 1 if ret63 > 0 else -1
    points += 1 if ret252 > 0 else -1
    score = clamp(points / 6 * 100)
    if score >= 60:
        status, decision = "Constructive", "Broad trend permits normal long exposure if other risk modules agree."
    elif score >= 0:
        status, decision = "Mixed", "Use selective exposure; require stronger ticker-level evidence."
    else:
        status, decision = "Broken", "Restrict new long exposure until broad trend repairs."
    evidence = [
        metric("SPY close vs 200DMA", close - ma200, f"{fmt(close)} vs {fmt(ma200)}", "pass" if close > ma200 else "fail"),
        metric("SPY close vs 50DMA", close - ma50, f"{fmt(close)} vs {fmt(ma50)}", "pass" if close > ma50 else "fail"),
        metric("50DMA vs 200DMA", ma50 - ma200, f"{fmt(ma50)} vs {fmt(ma200)}", "pass" if ma50 > ma200 else "fail"),
        metric("3M momentum", ret63, pct(ret63), "pass" if ret63 > 0 else "fail"),
        metric("12M momentum", ret252, pct(ret252), "pass" if ret252 > 0 else "fail"),
    ]
    return module("MKT_TREND", "Market Trend", status, score, decision, evidence, "Yahoo Finance", "https://finance.yahoo.com/quote/SPY", "SPY close vs 50DMA/200DMA plus 63D/252D momentum."), {"close": close, "ma50": ma50, "ma200": ma200, "ret63": ret63, "ret252": ret252}


def volatility_module(spy: dict[str, Any], vix: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float | None]]:
    spy_closes = spy["closes"]
    vix_closes = vix["closes"]
    rv20 = realized_vol(spy_closes, 20)
    dd63 = drawdown(spy_closes, 63)
    vix_now = vix_closes[-1] if vix_closes else None
    vix_pct = percentile_rank(vix_now, vix_closes[-252:]) if vix_closes else None
    if rv20 is None or dd63 is None or vix_now is None:
        return module("VOL_RISK", "Volatility / Risk Budget", "Unavailable", None, "No volatility-based size adjustment; required data unavailable.", [], "Yahoo Finance / Cboe VIX", "https://finance.yahoo.com/quote/%5EVIX", "20D realized volatility, VIX percentile, and SPY 63D drawdown."), {"rv20": rv20, "dd63": dd63, "vix": vix_now, "vix_pct": vix_pct, "multiplier": None}
    risk_penalty = 0
    if rv20 > 0.30:
        risk_penalty += 45
    elif rv20 > 0.22:
        risk_penalty += 25
    elif rv20 > 0.16:
        risk_penalty += 10
    if vix_now >= 30 or (vix_pct is not None and vix_pct >= 0.90):
        risk_penalty += 45
    elif vix_now >= 22 or (vix_pct is not None and vix_pct >= 0.75):
        risk_penalty += 25
    elif vix_now >= 18:
        risk_penalty += 10
    if dd63 <= -0.15:
        risk_penalty += 30
    elif dd63 <= -0.08:
        risk_penalty += 15
    score = clamp(100 - risk_penalty * 1.5)
    if risk_penalty >= 80:
        status, multiplier, decision = "Defensive", 0.25, "Use defensive size only; volatility and drawdown are elevated."
    elif risk_penalty >= 45:
        status, multiplier, decision = "Reduced", 0.50, "Use half-size entries unless ticker evidence is very strong."
    else:
        status, multiplier, decision = "Normal", 1.00, "Volatility permits normal planned position size."
    evidence = [
        metric("20D realized volatility", rv20, pct(rv20), "watch" if rv20 > 0.22 else "pass"),
        metric("VIX level", vix_now, fmt(vix_now), "watch" if vix_now >= 22 else "pass"),
        metric("VIX 1Y percentile", vix_pct, pct(vix_pct), "watch" if vix_pct is not None and vix_pct >= 0.75 else "pass"),
        metric("SPY drawdown from 63D high", dd63, pct(dd63), "watch" if dd63 <= -0.08 else "pass"),
        metric("Volatility size multiplier", multiplier, f"{multiplier:.2f}x", "pass" if multiplier >= 0.75 else "watch"),
    ]
    return module("VOL_RISK", "Volatility / Risk Budget", status, score, decision, evidence, "Yahoo Finance / Cboe VIX", "https://finance.yahoo.com/quote/%5EVIX", "20D realized volatility, VIX percentile, and SPY 63D drawdown."), {"rv20": rv20, "dd63": dd63, "vix": vix_now, "vix_pct": vix_pct, "multiplier": multiplier}


def fred_series(series: str) -> tuple[list[float], str]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    text = get_text(url)
    if not text:
        return [], url
    values: list[float] = []
    try:
        for row in csv.DictReader(text.splitlines()):
            value = num(row.get(series))
            if value is not None:
                values.append(value)
    except Exception:
        return [], url
    return values, url


def credit_module() -> tuple[dict[str, Any], dict[str, float | None]]:
    values, url = fred_series("BAMLH0A0HYM2")
    current = values[-1] if values else None
    trailing = values[-756:] if values else []
    z = z_score(current, trailing)
    change20 = current - values[-21] if current is not None and len(values) > 21 else None
    if current is None:
        return module("CREDIT_STRESS", "Credit Stress", "Unavailable", None, "Credit module excluded; FRED source unavailable.", [], "FRED", url, "High-yield OAS current level, 3Y z-score, 20-observation change."), {"oas": None, "z": None, "change20": None}
    stress = 0
    stress += 50 if current >= 7 else 30 if current >= 5 else 0
    stress += 35 if z is not None and z >= 2 else 20 if z is not None and z >= 1 else 0
    stress += 35 if change20 is not None and change20 >= 1 else 20 if change20 is not None and change20 >= 0.5 else 0
    score = clamp(100 - stress * 1.6)
    status = "Stress" if stress >= 70 else "Watch" if stress >= 30 else "Benign"
    decision = "Reduce equity risk and avoid weak-balance-sheet trades." if status == "Stress" else "Monitor credit confirmation before adding risk." if status == "Watch" else "Credit conditions do not restrict equity risk."
    evidence = [
        metric("High-yield OAS", current, f"{fmt(current)}%", "watch" if current >= 5 else "pass"),
        metric("3Y z-score", z, fmt(z), "watch" if z is not None and z >= 1 else "pass"),
        metric("20-observation change", change20, f"{fmt(change20)} pts", "watch" if change20 is not None and change20 >= 0.5 else "pass"),
    ]
    return module("CREDIT_STRESS", "Credit Stress", status, score, decision, evidence, "FRED", url, "High-yield OAS current level, 3Y z-score, 20-observation change."), {"oas": current, "z": z, "change20": change20}


def financial_conditions_module() -> tuple[dict[str, Any], dict[str, float | None]]:
    values, url = fred_series("NFCI")
    current = values[-1] if values else None
    change4 = current - values[-5] if current is not None and len(values) > 5 else None
    if current is None:
        return module("FIN_CONDITIONS", "Financial Conditions", "Unavailable", None, "Financial conditions excluded; FRED source unavailable.", [], "FRED", url, "NFCI level and 4-week change."), {"nfci": None, "change4": None}
    pressure = 0
    pressure += 50 if current > 0.5 else 25 if current > 0 else 0
    pressure += 35 if change4 is not None and change4 > 0.25 else 20 if change4 is not None and change4 > 0.10 else 0
    score = clamp(100 - pressure * 1.7)
    status = "Tight" if pressure >= 60 else "Tightening" if pressure >= 25 else "Loose / Neutral"
    decision = "Tight conditions reduce risk budget." if status == "Tight" else "Conditions are tightening; keep sizing conservative." if status == "Tightening" else "Financial conditions do not restrict risk."
    evidence = [
        metric("NFCI level", current, fmt(current), "watch" if current > 0 else "pass"),
        metric("4-week change", change4, fmt(change4), "watch" if change4 is not None and change4 > 0.10 else "pass"),
    ]
    return module("FIN_CONDITIONS", "Financial Conditions", status, score, decision, evidence, "FRED", url, "NFCI level and 4-week change."), {"nfci": current, "change4": change4}


def put_call_module() -> tuple[dict[str, Any], dict[str, float | None]]:
    url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv"
    text = get_text(url)
    parsed: dict[str, list[float]] = {"total": [], "equity": [], "index": []}
    if text:
        try:
            rows = list(csv.DictReader(text.splitlines()))
            headers = list(rows[0].keys()) if rows else []
            mapping: dict[str, str] = {}
            for header in headers:
                h = re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()
                if "ratio" in h and "total" in h:
                    mapping["total"] = header
                if "ratio" in h and "equity" in h:
                    mapping["equity"] = header
                if "ratio" in h and "index" in h:
                    mapping["index"] = header
            for row in rows:
                for key, header in mapping.items():
                    value = num(row.get(header))
                    if value is not None and 0.1 <= value <= 5:
                        parsed[key].append(value)
        except Exception:
            parsed = {"total": [], "equity": [], "index": []}
    total = parsed["total"][-1] if parsed["total"] else None
    equity = parsed["equity"][-1] if parsed["equity"] else None
    index = parsed["index"][-1] if parsed["index"] else None
    total_pct = percentile_rank(total, parsed["total"][-252:]) if total is not None else None
    equity_pct = percentile_rank(equity, parsed["equity"][-252:]) if equity is not None else None
    index_pct = percentile_rank(index, parsed["index"][-252:]) if index is not None else None
    if total is None and equity is None and index is None:
        return module("OPTIONS_CROWDING", "Options Crowding", "Unavailable", None, "Options module excluded; Cboe data unavailable.", [], "Cboe", "https://www.cboe.com/us/options/market_statistics/daily/", "Put/call ratios and trailing percentiles."), {"total": None, "equity": None, "index": None}
    percentiles = [p for p in [total_pct, equity_pct, index_pct] if p is not None]
    extreme_high = any(p >= 0.90 for p in percentiles)
    extreme_low = any(p <= 0.10 for p in percentiles)
    score = 50.0
    if extreme_high:
        status, decision, score = "Defensive extreme", "Options flow shows elevated hedging; avoid adding weak longs without confirmation.", 25
    elif extreme_low:
        status, decision, score = "Speculative extreme", "Options flow is crowded/speculative; avoid chasing extended moves.", 35
    else:
        status, decision, score = "Balanced", "Options crowding does not restrict trade permission.", 70
    evidence = [
        metric("Total put/call", total, fmt(total), "watch" if total_pct is not None and (total_pct >= 0.90 or total_pct <= 0.10) else "pass"),
        metric("Total put/call percentile", total_pct, pct(total_pct), "watch" if total_pct is not None and (total_pct >= 0.90 or total_pct <= 0.10) else "pass"),
        metric("Equity put/call", equity, fmt(equity), "watch" if equity_pct is not None and (equity_pct >= 0.90 or equity_pct <= 0.10) else "pass"),
        metric("Index put/call", index, fmt(index), "watch" if index_pct is not None and (index_pct >= 0.90 or index_pct <= 0.10) else "pass"),
    ]
    return module("OPTIONS_CROWDING", "Options Crowding", status, score, decision, evidence, "Cboe", "https://www.cboe.com/us/options/market_statistics/daily/", "Put/call ratios and trailing percentiles."), {"total": total, "equity": equity, "index": index, "total_pct": total_pct, "equity_pct": equity_pct, "index_pct": index_pct}


def aaii_module() -> tuple[dict[str, Any], dict[str, float | None]]:
    url = "https://www.aaii.com/sentimentsurvey"
    text = get_text(url) or ""
    plain = re.sub(r"<[^>]+>", " ", text)
    values = {}
    for label in ["Bullish", "Neutral", "Bearish"]:
        match = re.search(label + r"[^0-9]{0,120}([0-9]+(?:\.[0-9]+)?)%", plain, re.I | re.S)
        values[label.lower()] = num(match.group(1)) if match else None
    bullish, neutral, bearish = values["bullish"], values["neutral"], values["bearish"]
    valid = None not in (bullish, neutral, bearish) and 90 <= bullish + neutral + bearish <= 110 and bullish > 1 and bearish > 1
    if not valid:
        return module("RETAIL_SENTIMENT", "Retail Sentiment Context", "Unavailable", None, "Retail sentiment excluded; AAII values could not be validated.", [], "AAII", url, "AAII bullish minus bearish spread."), {"bullish": bullish, "bearish": bearish, "spread": None}
    spread = bullish - bearish
    if spread >= 25:
        status, score, decision = "Optimistic", 35, "Retail optimism is elevated; use as contrarian caution only."
    elif spread <= -25:
        status, score, decision = "Pessimistic", 35, "Retail pessimism is elevated; do not use alone, but watch for oversold setups."
    else:
        status, score, decision = "Neutral", 70, "Retail survey context does not restrict risk."
    evidence = [
        metric("Bullish", bullish / 100, pct(bullish / 100), "context"),
        metric("Neutral", neutral / 100, pct(neutral / 100), "context"),
        metric("Bearish", bearish / 100, pct(bearish / 100), "context"),
        metric("Bull-bear spread", spread, f"{fmt(spread)} pts", "watch" if abs(spread) >= 25 else "pass"),
    ]
    return module("RETAIL_SENTIMENT", "Retail Sentiment Context", status, score, decision, evidence, "AAII", url, "AAII bullish minus bearish spread."), {"bullish": bullish, "bearish": bearish, "spread": spread}


def cape_module() -> tuple[dict[str, Any], dict[str, float | None]]:
    url = "https://www.multpl.com/shiller-pe/table/by-month"
    text = get_text(url) or ""
    values = [num(x) for x in re.findall(r">\s*([0-9]{1,2}(?:\.[0-9]+)?)\s*</td>", text)]
    values = [v for v in values if v is not None and 5 <= v <= 80]
    current = values[0] if values else None
    pct_rank = percentile_rank(current, values) if current is not None else None
    if current is None:
        return module("VALUATION_CONTEXT", "Long-Term Valuation", "Unavailable", None, "Valuation context excluded; CAPE source unavailable.", [], "Multpl", url, "Shiller CAPE current value and historical percentile."), {"cape": None, "cape_pct": None}
    if pct_rank is not None and pct_rank >= 0.85:
        status, score, decision = "Expensive", 30, "Long-term allocation caution; not a short-term trade blocker."
    elif pct_rank is not None and pct_rank <= 0.25:
        status, score, decision = "Cheap / Fair", 70, "Long-term valuation is supportive; not a short-term entry trigger."
    else:
        status, score, decision = "Fair / Elevated", 55, "Valuation is context only; use trend and risk modules for trade permission."
    evidence = [
        metric("Shiller CAPE", current, fmt(current), "context"),
        metric("CAPE percentile", pct_rank, pct(pct_rank), "watch" if pct_rank is not None and pct_rank >= 0.85 else "context"),
    ]
    return module("VALUATION_CONTEXT", "Long-Term Valuation", status, score, decision, evidence, "Multpl", url, "Shiller CAPE current value and historical percentile."), {"cape": current, "cape_pct": pct_rank}


def regime_from_modules(modules: list[dict[str, Any]], trend_data: dict[str, float | None], vol_data: dict[str, float | None], credit_data: dict[str, float | None], fin_data: dict[str, float | None]) -> dict[str, Any]:
    multiplier = 1.0
    reasons: list[str] = []
    if trend_data.get("close") is None or trend_data.get("ma200") is None:
        multiplier = min(multiplier, 0.5)
        reasons.append("SPY trend unavailable")
    elif trend_data["close"] < trend_data["ma200"]:
        multiplier = min(multiplier, 0.25)
        reasons.append("SPY below 200DMA")
    elif trend_data.get("ret63") is not None and trend_data["ret63"] < 0:
        multiplier = min(multiplier, 0.5)
        reasons.append("SPY 3M momentum negative")
    vol_mult = vol_data.get("multiplier")
    if vol_mult is not None:
        multiplier = min(multiplier, vol_mult)
        if vol_mult <= 0.5:
            reasons.append("volatility risk budget reduced")
    if credit_data.get("z") is not None and credit_data["z"] >= 2:
        multiplier = min(multiplier, 0.25)
        reasons.append("high-yield spread z-score stress")
    elif credit_data.get("change20") is not None and credit_data["change20"] >= 0.5:
        multiplier = min(multiplier, 0.5)
        reasons.append("credit spreads widening")
    if fin_data.get("nfci") is not None and fin_data["nfci"] > 0.5:
        multiplier = min(multiplier, 0.25)
        reasons.append("financial conditions tight")
    elif fin_data.get("change4") is not None and fin_data["change4"] > 0.10:
        multiplier = min(multiplier, 0.5)
        reasons.append("financial conditions tightening")
    if trend_data.get("close") is not None and trend_data.get("ma200") is not None and trend_data["close"] < trend_data["ma200"] and vol_data.get("vix") is not None and vol_data["vix"] >= 30:
        multiplier = 0.0
        reasons.append("broad trend broken and VIX stress")
    if multiplier >= 0.75:
        code, label, permission = "GREEN", "Risk-on", "New long trades allowed if ticker is Eligible."
    elif multiplier >= 0.50:
        code, label, permission = "AMBER", "Selective", "New longs limited to strongest tickers; use half size."
    elif multiplier > 0:
        code, label, permission = "RED", "Risk-off", "New longs restricted; planned trades only; use quarter size."
    else:
        code, label, permission = "BLACK", "Capital protection", "No new long trades; review existing exposure."
    if not reasons:
        reasons = ["broad trend and risk modules permit normal exposure"]
    available_scores = [m["score"] for m in modules if m.get("score") is not None]
    evidence_score = sum(available_scores) / len(available_scores) if available_scores else None
    return {
        "regime_code": code,
        "regime_label": label,
        "trade_permission": permission,
        "position_size_multiplier": multiplier,
        "primary_reason": "; ".join(reasons[:4]),
        "evidence_score": None if evidence_score is None else round(evidence_score, 2),
    }


def ticker_readiness(symbol: str, history: dict[str, Any], spy_ret63: float | None, market_multiplier: float) -> dict[str, Any]:
    closes = history.get("closes", [])
    close = closes[-1] if closes else None
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200)
    ret63 = return_n(closes, 63)
    rv20 = realized_vol(closes, 20)
    dd63 = drawdown(closes, 63)
    rel = None if ret63 is None or spy_ret63 is None else ret63 - spy_ret63
    target_vol = 0.60 if symbol == "BTC-USD" else 0.25
    vol_multiplier = 0.0 if rv20 is None or rv20 <= 0 else min(1.0, target_vol / rv20)
    size = round(market_multiplier * vol_multiplier, 2)
    reasons: list[str] = []
    if None in (close, ma50, ma200, ret63, rv20, dd63):
        return {
            "symbol": symbol,
            "status": "Unavailable",
            "position_size_multiplier": 0.0,
            "price": None,
            "trend": "Unavailable",
            "relative_strength_vs_spy": None,
            "realized_volatility_20d": rv20,
            "drawdown_63d": dd63,
            "return_63d": ret63,
            "risk_adjusted_momentum": None,
            "reason": "Insufficient validated price history.",
            "next_step": "Do not trade from this dashboard until data is available.",
        }
    if close > ma50 and close > ma200:
        trend = "Above 50DMA and 200DMA"
    elif close > ma200:
        trend = "Above 200DMA, below 50DMA"
        reasons.append("below 50DMA")
    else:
        trend = "Below 200DMA"
        reasons.append("below 200DMA")
    if rel is not None and rel < 0:
        reasons.append("underperforming SPY over 63D")
    if ret63 < 0:
        reasons.append("negative 63D momentum")
    if rv20 > target_vol * 1.5:
        reasons.append("elevated volatility")
    if dd63 < -0.12:
        reasons.append("drawdown greater than 12%")
    if market_multiplier == 0:
        status = "Blocked"
        next_step = "No new long trade while market regime is capital protection."
    elif close < ma200 or (ret63 < 0 and rel is not None and rel < 0):
        status = "Avoid"
        next_step = "Wait for price to repair trend and relative strength before considering entry."
        size = min(size, 0.25)
    elif close < ma50 or (rel is not None and rel < 0) or rv20 > target_vol * 1.5 or dd63 < -0.12:
        status = "Watch"
        next_step = "Research only; require technical repair or smaller entry size."
        size = min(size, 0.50)
    else:
        status = "Eligible"
        next_step = "Eligible for planned setup, subject to personal entry rules and risk limits."
    if not reasons:
        reasons.append("trend and relative strength acceptable")
    risk_adjusted = None if rv20 in (None, 0) or ret63 is None else ret63 / rv20
    return {
        "symbol": symbol,
        "status": status,
        "position_size_multiplier": size,
        "price": round(close, 4),
        "trend": trend,
        "relative_strength_vs_spy": None if rel is None else round(rel, 6),
        "realized_volatility_20d": None if rv20 is None else round(rv20, 6),
        "drawdown_63d": None if dd63 is None else round(dd63, 6),
        "return_63d": None if ret63 is None else round(ret63, 6),
        "risk_adjusted_momentum": None if risk_adjusted is None else round(risk_adjusted, 6),
        "reason": "; ".join(reasons[:5]),
        "next_step": next_step,
    }


def write_outputs() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    spy = yahoo_history("SPY")
    vix = yahoo_history("^VIX")
    trend_mod, trend_data = market_trend_module(spy)
    vol_mod, vol_data = volatility_module(spy, vix)
    credit_mod, credit_data = credit_module()
    fin_mod, fin_data = financial_conditions_module()
    options_mod, options_data = put_call_module()
    aaii_mod, aaii_data = aaii_module()
    cape_mod, cape_data = cape_module()
    modules = [trend_mod, vol_mod, credit_mod, fin_mod, options_mod, aaii_mod, cape_mod]
    regime = regime_from_modules(modules, trend_data, vol_data, credit_data, fin_data)
    histories = {symbol: yahoo_history(symbol) for symbol in WATCHLIST}
    watchlist = [ticker_readiness(symbol, histories[symbol], trend_data.get("ret63"), regime["position_size_multiplier"]) for symbol in WATCHLIST]
    summary = {
        "name": "IvySets Evidence-Based Market Regime",
        "timezone": TIMEZONE,
        "updated_at_london": now(),
        "watchlist": WATCHLIST,
        **regime,
        "eligible_count": sum(1 for row in watchlist if row["status"] == "Eligible"),
        "watch_count": sum(1 for row in watchlist if row["status"] == "Watch"),
        "avoid_count": sum(1 for row in watchlist if row["status"] in {"Avoid", "Blocked"}),
        "unavailable_count": sum(1 for row in watchlist if row["status"] == "Unavailable"),
        "csv_url": "docs/sentiment.csv",
    }
    payload = {
        "summary": summary,
        "modules": modules,
        "watchlist": watchlist,
        "methodology": METHODOLOGY,
        "source_health": {
            "market_data": len(spy.get("closes", [])) >= 200,
            "vix_data": len(vix.get("closes", [])) >= 100,
            "credit_data": credit_mod["available"],
            "financial_conditions_data": fin_mod["available"],
            "options_data": options_mod["available"],
            "aaii_data": aaii_mod["available"],
            "cape_data": cape_mod["available"],
        },
    }
    (DOCS / "data.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (DOCS / "sentiment.csv").open("w", newline="", encoding="utf-8") as handle:
        columns = [
            "timestamp",
            "section",
            "symbol",
            "metric",
            "value",
            "status",
            "decision_impact",
            "position_size_multiplier",
            "source",
            "source_url",
            "formula_id",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for mod in modules:
            writer.writerow(
                {
                    "timestamp": summary["updated_at_london"],
                    "section": "module",
                    "symbol": "",
                    "metric": mod["title"],
                    "value": mod["score"],
                    "status": mod["status"],
                    "decision_impact": mod["decision_impact"],
                    "position_size_multiplier": summary["position_size_multiplier"],
                    "source": mod["source"],
                    "source_url": mod["source_url"],
                    "formula_id": mod["id"],
                }
            )
            for ev in mod.get("evidence", []):
                writer.writerow(
                    {
                        "timestamp": summary["updated_at_london"],
                        "section": "evidence",
                        "symbol": "",
                        "metric": f"{mod['title']} - {ev['label']}",
                        "value": ev.get("display"),
                        "status": ev.get("status"),
                        "decision_impact": mod["decision_impact"],
                        "position_size_multiplier": summary["position_size_multiplier"],
                        "source": mod["source"],
                        "source_url": mod["source_url"],
                        "formula_id": mod["id"],
                    }
                )
        for row in watchlist:
            writer.writerow(
                {
                    "timestamp": summary["updated_at_london"],
                    "section": "watchlist",
                    "symbol": row["symbol"],
                    "metric": "Trade Readiness",
                    "value": row["status"],
                    "status": row["status"],
                    "decision_impact": f"{row['reason']} | {row['next_step']}",
                    "position_size_multiplier": row["position_size_multiplier"],
                    "source": "Yahoo Finance chart API",
                    "source_url": f"https://finance.yahoo.com/quote/{requests.utils.quote(row['symbol'], safe='')}",
                    "formula_id": "WATCHLIST_READINESS",
                }
            )


if __name__ == "__main__":
    write_outputs()
