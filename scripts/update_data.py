from __future__ import annotations

import csv
import json
import math
import re
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
STOCKTWITS_SYMBOLS = {"BTC-USD": "BTC.X"}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 IvySets/1.0",
    "Accept": "application/json,text/csv,text/html,application/xml;q=0.9,*/*;q=0.8",
})

POSITIVE_WORDS = set("beat beats surge surges gain gains rally rallies upgrade upgraded strong growth record higher profit profits bullish optimistic approval outperform raises raise buyback dividend resilient expands partnership wins win momentum demand acceleration".split())
NEGATIVE_WORDS = set("miss misses drop drops fall falls plunge plunges downgrade downgraded weak loss losses lower bearish warning probe investigation recall lawsuit cuts cut layoffs risk risks slump slumps concern concerns fraud delay delays pressure slowdown headwind headwinds".split())


def timestamp() -> str:
    return datetime.now(tz.gettz(TIMEZONE)).isoformat(timespec="seconds")


def number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else value
    try:
        cleaned = str(value).strip().replace(",", "").replace("%", "")
        if cleaned in {"", ".", "-", "—"}:
            return None
        return float(cleaned)
    except Exception:
        return None


def clamp(value: float, low: float = -100, high: float = 100) -> float:
    return max(low, min(high, value))


def get_text(url: str) -> str | None:
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def get_json(url: str) -> dict[str, Any] | None:
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def display(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "Unavailable"
    if abs(value) >= 1000:
        return f"{value:,.{decimals}f}"
    return f"{value:.{decimals}f}"


def signal_from_score(score: float | None) -> str:
    if score is None:
        return "Unavailable"
    if score >= 60:
        return "Strong risk-on"
    if score >= 20:
        return "Risk-on"
    if score <= -60:
        return "Strong risk-off"
    if score <= -20:
        return "Risk-off"
    return "Neutral"


def card(card_id: int, category: str, metric: str, value: float | None, unit: str, score: float | None, source: str, source_url: str, cadence: str, symbol: str = "", detail: str = "", decimals: int = 2) -> dict[str, Any]:
    return {
        "updated_at_london": timestamp(),
        "card": card_id,
        "category": category,
        "metric": metric,
        "symbol": symbol,
        "value": display(value, decimals),
        "raw_value": "" if value is None else round(float(value), 6),
        "unit": unit,
        "signal": signal_from_score(score),
        "score": "" if score is None else round(float(score), 2),
        "source": source,
        "source_url": source_url,
        "cadence": cadence,
        "detail": detail,
        "status": "live" if value is not None else "unavailable",
    }


def yahoo(symbol: str) -> dict[str, float | None]:
    safe = requests.utils.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}?range=5d&interval=1d"
    data = get_json(url)
    if not data:
        return {"price": None, "change_pct": None}
    try:
        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        price = number(meta.get("regularMarketPrice") or meta.get("chartPreviousClose"))
        previous = number(meta.get("previousClose") or meta.get("chartPreviousClose"))
        closes = [number(x) for x in result.get("indicators", {}).get("quote", [{}])[0].get("close", [])]
        closes = [x for x in closes if x is not None]
        if len(closes) >= 2:
            price = price or closes[-1]
            previous = previous or closes[-2]
        change_pct = None if price is None or previous in (None, 0) else (price - previous) / previous * 100
        return {"price": price, "change_pct": change_pct}
    except Exception:
        return {"price": None, "change_pct": None}


def change_score(change_pct: float | None, multiplier: float = 12) -> float | None:
    return None if change_pct is None else clamp(change_pct * multiplier)


def fear_greed_card(card_id: int) -> dict[str, Any]:
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    data = get_json(url) or {}
    item = data.get("fear_and_greed") or {}
    value = number(item.get("score"))
    rating = str(item.get("rating") or "").title()
    score = None if value is None else (value - 50) * 2
    return card(card_id, "Market", "Fear & Greed", value, "0-100", score, "CNN", url, "hourly", detail=rating, decimals=0)


def vix_card(card_id: int) -> dict[str, Any]:
    q = yahoo("^VIX")
    value = q["price"]
    if value is None:
        score = None
        detail = "VIX unavailable"
    elif value < 15:
        score, detail = 70, "Low volatility"
    elif value < 22:
        score, detail = 20, "Normal volatility"
    elif value < 30:
        score, detail = -35, "Elevated volatility"
    else:
        score, detail = -80, "Stress volatility"
    return card(card_id, "Volatility", "VIX Level", value, "index", score, "Yahoo Finance", "https://finance.yahoo.com/quote/%5EVIX", "hourly", detail=detail)


def market_change_card(card_id: int, symbol: str, name: str, category: str, multiplier: float = 12) -> dict[str, Any]:
    q = yahoo(symbol)
    value = q["change_pct"]
    detail = "Daily price change" if value is not None else "Price change unavailable"
    return card(card_id, category, name, value, "%", change_score(value, multiplier), "Yahoo Finance", f"https://finance.yahoo.com/quote/{requests.utils.quote(symbol, safe='')}", "hourly", detail=detail)


def dollar_card(card_id: int) -> dict[str, Any]:
    value = yahoo("DX-Y.NYB")["price"]
    if value is None:
        score, detail = None, "DXY unavailable"
    elif value >= 106:
        score, detail = -30, "Dollar strength"
    elif value <= 101:
        score, detail = 25, "Dollar softness"
    else:
        score, detail = 0, "Dollar neutral"
    return card(card_id, "Macro", "US Dollar Index", value, "index", score, "Yahoo Finance", "https://finance.yahoo.com/quote/DX-Y.NYB", "hourly", detail=detail)


def ten_year_card(card_id: int) -> dict[str, Any]:
    tnx = yahoo("^TNX")["price"]
    if tnx is None:
        value = None
    else:
        value = tnx / 10 if tnx > 20 else tnx
    if value is None:
        score, detail = None, "Yield unavailable"
    elif value > 5:
        score, detail = -55, "High rate pressure"
    elif value > 4.2:
        score, detail = -25, "Moderate rate pressure"
    else:
        score, detail = 15, "Rate pressure contained"
    return card(card_id, "Rates", "US 10Y Yield", value, "%", score, "Yahoo Finance", "https://finance.yahoo.com/quote/%5ETNX", "hourly", detail=detail)


def fred_latest(series: str) -> tuple[float | None, str]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    text = get_text(url)
    if not text:
        return None, url
    try:
        rows = list(csv.DictReader(text.splitlines()))
        for row in reversed(rows):
            value = number(row.get(series))
            if value is not None:
                return value, url
    except Exception:
        pass
    return None, url


def high_yield_card(card_id: int) -> dict[str, Any]:
    value, url = fred_latest("BAMLH0A0HYM2")
    if value is None:
        score, detail = None, "Spread unavailable"
    elif value < 3.5:
        score, detail = 45, "Credit appetite"
    elif value < 5:
        score, detail = 5, "Credit normal"
    elif value < 7:
        score, detail = -45, "Credit stress"
    else:
        score, detail = -80, "High credit stress"
    return card(card_id, "Credit", "High Yield Spread", value, "%", score, "FRED", url, "daily", detail=detail)


def put_call_card(card_id: int) -> dict[str, Any]:
    url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv"
    text = get_text(url)
    value = None
    if text:
        try:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            header = [h.strip().lower() for h in lines[0].split(",")]
            latest = [v.strip() for v in lines[-1].split(",")]
            for index, name in enumerate(header):
                normalized = re.sub(r"[^a-z0-9]+", " ", name).strip()
                if index < len(latest) and "total" in normalized and "ratio" in normalized:
                    value = number(latest[index])
                    break
            if value is None and len(latest) >= 4:
                numeric_values = [number(v) for v in latest]
                candidates = [v for v in numeric_values if v is not None and 0.2 <= v <= 2.5]
                value = candidates[-1] if candidates else None
        except Exception:
            value = None
    if value is None:
        score, detail = None, "Cboe ratio unavailable"
    elif value >= 1.15:
        score, detail = -45, "Defensive options flow"
    elif value <= 0.65:
        score, detail = 35, "Speculative options flow"
    else:
        score, detail = 5, "Balanced options flow"
    return card(card_id, "Options", "Total Put/Call Ratio", value, "ratio", score, "Cboe", "https://www.cboe.com/us/options/market_statistics/daily/", "daily", detail=detail)


def aaii_card(card_id: int) -> dict[str, Any]:
    url = "https://www.aaii.com/sentimentsurvey"
    text = get_text(url) or ""
    plain = re.sub(r"<[^>]+>", " ", text)

    def find_pct(label: str) -> float | None:
        match = re.search(label + r"[^0-9]{0,90}([0-9]+(?:\.[0-9]+)?)%", plain, re.I | re.S)
        return number(match.group(1)) if match else None

    bullish = find_pct("Bullish")
    bearish = find_pct("Bearish")
    if bullish is None or bearish is None or bullish <= 0 or bearish <= 0 or bullish + bearish > 100:
        value = None
        detail = "AAII parser unavailable"
    else:
        value = bullish - bearish
        detail = f"Bullish {bullish:.1f}%, bearish {bearish:.1f}%"
    return card(card_id, "Survey", "AAII Bull-Bear Spread", value, "pts", None if value is None else clamp(value * 2.5), "AAII", url, "weekly", detail=detail)


def crypto_fear_card(card_id: int) -> dict[str, Any]:
    url = "https://api.alternative.me/fng/?limit=1"
    data = get_json(url) or {}
    try:
        item = data["data"][0]
        value = number(item.get("value"))
        detail = str(item.get("value_classification") or "")
    except Exception:
        value, detail = None, "Crypto sentiment unavailable"
    return card(card_id, "Crypto", "Crypto Fear & Greed", value, "0-100", None if value is None else (value - 50) * 2, "Alternative.me", url, "daily", "BTC-USD", detail=detail, decimals=0)


def news_sentiment(symbol: str) -> tuple[float | None, int]:
    safe = requests.utils.quote(symbol, safe="")
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={safe}&region=US&lang=en-US"
    text = get_text(url)
    if not text:
        return None, 0
    try:
        root = ET.fromstring(text)
        titles = [node.findtext("title") or "" for node in root.findall(".//item")]
    except Exception:
        titles = re.findall(r"<title>(.*?)</title>", text, re.S)
    scores: list[float] = []
    for title in titles[:20]:
        words = re.findall(r"[A-Za-z']+", title.lower())
        positive = sum(word in POSITIVE_WORDS for word in words)
        negative = sum(word in NEGATIVE_WORDS for word in words)
        if positive or negative:
            scores.append((positive - negative) / max(positive + negative, 1) * 100)
        else:
            scores.append(0)
    return (sum(scores) / len(scores), len(titles)) if scores else (None, len(titles))


def stocktwits_sentiment(symbol: str) -> tuple[float | None, int]:
    st_symbol = STOCKTWITS_SYMBOLS.get(symbol, symbol)
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{requests.utils.quote(st_symbol, safe='')}.json"
    data = get_json(url)
    messages = [] if not data else data.get("messages", [])
    bullish = bearish = 0
    for message in messages:
        label = (((message.get("entities") or {}).get("sentiment") or {}).get("basic") or "").lower()
        bullish += label == "bullish"
        bearish += label == "bearish"
    total = bullish + bearish
    return (None, len(messages)) if total == 0 else (bullish / total * 100, len(messages))


def watchlist_card(card_id: int, symbol: str) -> dict[str, Any]:
    quote = yahoo(symbol)
    price_score = change_score(quote["change_pct"], 12)
    news_score, headline_count = news_sentiment(symbol)
    social_bullish, message_count = stocktwits_sentiment(symbol)
    social_score = None if social_bullish is None else clamp((social_bullish - 50) * 3)

    parts = [score for score in [price_score, news_score, social_score] if score is not None]
    value = None if not parts else sum(parts) / len(parts)
    detail_parts = []
    if quote["change_pct"] is not None:
        detail_parts.append(f"price {quote['change_pct']:+.2f}%")
    if news_score is not None:
        detail_parts.append(f"news {news_score:+.0f} from {headline_count} headlines")
    if social_bullish is not None:
        detail_parts.append(f"social {social_bullish:.0f}% bullish from {message_count} messages")
    detail = "; ".join(detail_parts) if detail_parts else "No current data from configured sources"
    source_url = f"https://finance.yahoo.com/quote/{requests.utils.quote(symbol, safe='')}"
    return card(card_id, "Watchlist", f"{symbol} Composite Sentiment", value, "-100 to 100", value, "Yahoo Finance RSS + Stocktwits", source_url, "hourly", symbol, detail=detail)


def build_cards() -> list[dict[str, Any]]:
    cards = [
        fear_greed_card(1),
        vix_card(2),
        put_call_card(3),
        market_change_card(4, "^GSPC", "S&P 500 Change", "Market"),
        market_change_card(5, "^IXIC", "Nasdaq Change", "Market"),
        market_change_card(6, "^RUT", "Russell 2000 Change", "Market"),
        ten_year_card(7),
        high_yield_card(8),
        dollar_card(9),
        market_change_card(10, "GC=F", "Gold Change", "Macro", 10),
        market_change_card(11, "CL=F", "Oil Change", "Macro", 10),
        aaii_card(12),
    ]
    for index, symbol in enumerate(WATCHLIST, start=13):
        cards.append(watchlist_card(index, symbol))
    cards.append(crypto_fear_card(20))
    return cards[:20]


def overall(cards: list[dict[str, Any]]) -> tuple[float, str, int, int]:
    scores = [number(row.get("score")) for row in cards]
    scores = [score for score in scores if score is not None]
    if not scores:
        return 0, "Unavailable", 0, 0
    value = clamp(sum(scores) / len(scores))
    positive = len([score for score in scores if score >= 20])
    negative = len([score for score in scores if score <= -20])
    return value, signal_from_score(value), positive, negative


def write_outputs() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    cards = build_cards()
    score, label, positive, negative = overall(cards)
    payload = {
        "summary": {
            "name": "IvySets Market Sentiment",
            "timezone": TIMEZONE,
            "updated_at_london": timestamp(),
            "overall_score": round(score, 2),
            "overall_label": label,
            "card_count": len(cards),
            "positive_cards": positive,
            "negative_cards": negative,
            "watchlist": WATCHLIST,
            "csv_url": "sentiment.csv",
        },
        "metrics": cards,
    }
    (DOCS / "data.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    columns = ["updated_at_london", "card", "category", "metric", "symbol", "value", "raw_value", "unit", "signal", "score", "source", "source_url", "cadence", "detail", "status"]
    with (DOCS / "sentiment.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(cards)


if __name__ == "__main__":
    write_outputs()
