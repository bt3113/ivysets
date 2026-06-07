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
TZ = "Europe/London"
WATCHLIST = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "BTC-USD"]
ST_SYMBOLS = {"BTC-USD": "BTC.X"}
S = requests.Session()
S.headers.update({"User-Agent": "IvySets/1.0", "Accept": "application/json,text/csv,text/html,application/xml;q=0.9,*/*;q=0.8"})

POS = set("beat beats surge surges gain gains rally rallies upgrade upgraded strong growth record higher profit profits bullish optimistic launch approval outperform raises raise buyback dividend resilient expands partnership wins win".split())
NEG = set("miss misses drop drops fall falls plunge plunges downgrade downgraded weak loss losses lower bearish warning probe investigation recall lawsuit cuts cut layoffs risk risks slump slumps concern concerns fraud delay delays".split())


def now() -> str:
    return datetime.now(tz.gettz(TZ)).isoformat(timespec="seconds")


def fnum(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return None if math.isnan(float(x)) or math.isinf(float(x)) else float(x)
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def get_json(url: str) -> dict[str, Any] | None:
    try:
        r = S.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def get_text(url: str) -> str | None:
    try:
        r = S.get(url, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def score_label(v: float | None, pos_cut: float = 20, neg_cut: float = -20) -> str:
    if v is None:
        return "Unavailable"
    if v >= pos_cut:
        return "Risk-on"
    if v <= neg_cut:
        return "Risk-off"
    return "Neutral"


def metric(category: str, name: str, value: Any, unit: str, signal: str, score: float | None, source: str, url: str, cadence: str = "hourly", symbol: str = "") -> dict[str, Any]:
    n = fnum(value)
    if isinstance(value, str):
        disp = value
    elif n is None:
        disp = "—"
    elif abs(n) >= 1000:
        disp = f"{n:,.2f}"
    else:
        disp = f"{n:.2f}"
    return {"updated_at_london": now(), "category": category, "metric": name, "symbol": symbol, "value": disp, "raw_value": "" if n is None else round(n, 6), "unit": unit, "signal": signal, "score": "" if score is None else round(score, 2), "source": source, "source_url": url, "cadence": cadence}


def clamp(x: float, a: float = -100, b: float = 100) -> float:
    return max(a, min(b, x))


def pct_signal(p: float | None) -> tuple[str, float | None]:
    if p is None:
        return "Unavailable", None
    s = clamp(p * 12)
    return ("Positive" if p > 1 else "Negative" if p < -1 else "Flat", s)


def yahoo(symbol: str) -> dict[str, float | None]:
    safe = requests.utils.quote(symbol, safe="")
    data = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}?range=5d&interval=1d")
    if not data:
        return {"price": None, "change_pct": None}
    try:
        res = data["chart"]["result"][0]
        meta = res.get("meta", {})
        price = fnum(meta.get("regularMarketPrice") or meta.get("chartPreviousClose"))
        prev = fnum(meta.get("previousClose") or meta.get("chartPreviousClose"))
        closes = [fnum(x) for x in res.get("indicators", {}).get("quote", [{}])[0].get("close", [])]
        closes = [x for x in closes if x is not None]
        if len(closes) >= 2:
            price = price or closes[-1]
            prev = prev or closes[-2]
        chg = None if price is None or not prev else (price - prev) / prev * 100
        return {"price": price, "change_pct": chg}
    except Exception:
        return {"price": None, "change_pct": None}


def fear_greed() -> dict[str, Any]:
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    d = get_json(url) or {}
    fg = d.get("fear_and_greed") or {}
    val = fnum(fg.get("score"))
    label = str(fg.get("rating") or "Unavailable").title()
    sc = None if val is None else (val - 50) * 2
    return metric("Market", "Fear & Greed", val, "0-100", label, sc, "CNN", url)


def market_rows() -> list[dict[str, Any]]:
    rows = [fear_greed()]
    vix = yahoo("^VIX")
    v = vix["price"]
    sig = "Unavailable" if v is None else "Calm" if v < 15 else "Normal" if v < 22 else "Risk-off" if v < 30 else "Stress"
    sc = None if v is None else 70 if v < 15 else 25 if v < 22 else -35 if v < 30 else -80
    rows.append(metric("Volatility", "VIX Level", v, "index", sig, sc, "Yahoo Finance", "https://finance.yahoo.com/quote/%5EVIX"))
    sig, sc = pct_signal(vix["change_pct"])
    rows.append(metric("Volatility", "VIX Change", vix["change_pct"], "%", sig, None if sc is None else -sc, "Yahoo Finance", "https://finance.yahoo.com/quote/%5EVIX"))
    for sym, name in [("^GSPC", "S&P 500 Change"), ("^IXIC", "Nasdaq Change"), ("^RUT", "Russell 2000 Change"), ("GC=F", "Gold Change"), ("CL=F", "Oil Change")]:
        q = yahoo(sym); sig, sc = pct_signal(q["change_pct"])
        rows.append(metric("Market" if sym.startswith("^") else "Macro", name, q["change_pct"], "%", sig, sc, "Yahoo Finance", f"https://finance.yahoo.com/quote/{requests.utils.quote(sym, safe='')}"))
    dxy = yahoo("DX-Y.NYB")["price"]
    rows.append(metric("Macro", "US Dollar Index", dxy, "index", "Dollar strength" if dxy and dxy >= 106 else "Dollar softness" if dxy and dxy <= 101 else "Neutral", -25 if dxy and dxy >= 106 else 20 if dxy and dxy <= 101 else 0, "Yahoo Finance", "https://finance.yahoo.com/quote/DX-Y.NYB"))
    tnx = yahoo("^TNX")["price"]
    y = None if tnx is None else tnx / 10
    rows.append(metric("Rates", "US 10Y Yield", y, "%", "Yield pressure" if y and y > 5 else "Moderate pressure" if y and y > 4.2 else "Contained", -45 if y and y > 5 else -20 if y and y > 4.2 else 10, "Yahoo Finance", "https://finance.yahoo.com/quote/%5ETNX"))
    return rows


def fred(series: str) -> tuple[float | None, str]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    text = get_text(url)
    if not text:
        return None, url
    for r in reversed(list(csv.DictReader(text.splitlines()))):
        v = fnum(r.get(series))
        if v is not None:
            return v, url
    return None, url


def macro_rows() -> list[dict[str, Any]]:
    rows = []
    hy, u = fred("BAMLH0A0HYM2")
    rows.append(metric("Credit", "High Yield Spread", hy, "%", "Credit appetite" if hy and hy < 3.5 else "Normal" if hy and hy < 5 else "Credit stress" if hy and hy < 7 else "High stress" if hy else "Unavailable", 45 if hy and hy < 3.5 else 5 if hy and hy < 5 else -45 if hy and hy < 7 else -80 if hy else None, "FRED", u, "daily"))
    nfci, u = fred("NFCI")
    rows.append(metric("Financial Conditions", "NFCI", nfci, "index", "Loose conditions" if nfci and nfci < -0.5 else "Easy conditions" if nfci and nfci < 0 else "Tightening" if nfci and nfci < 0.5 else "Tight stress" if nfci else "Unavailable", 40 if nfci and nfci < -0.5 else 20 if nfci and nfci < 0 else -25 if nfci and nfci < 0.5 else -65 if nfci else None, "FRED", u, "weekly"))
    crypto = get_json("https://api.alternative.me/fng/?limit=1") or {}
    try:
        item = crypto["data"][0]; v = fnum(item.get("value")); lab = item.get("value_classification", "Unavailable")
    except Exception:
        v = None; lab = "Unavailable"
    rows.append(metric("Crypto", "Crypto Fear & Greed", v, "0-100", lab, None if v is None else (v - 50) * 2, "Alternative.me", "https://api.alternative.me/fng/?limit=1", "daily", "BTC-USD"))
    return rows


def cboe_rows() -> list[dict[str, Any]]:
    url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv"
    text = get_text(url)
    vals = {"Total Put/Call Ratio": None, "Equity Put/Call Ratio": None, "Index Put/Call Ratio": None}
    if text:
        try:
            last = list(csv.DictReader(text.splitlines()))[-1]
            low = {str(k).lower(): v for k, v in last.items()}
            for k in list(vals):
                for col, val in low.items():
                    if all(x in col for x in k.lower().replace("ratio", "").split()):
                        vals[k] = fnum(val); break
        except Exception:
            pass
    rows = []
    for k, v in vals.items():
        sig = "Unavailable" if v is None else "Defensive" if v >= 1.15 else "Speculative" if v <= .65 else "Balanced"
        sc = None if v is None else -45 if v >= 1.15 else 35 if v <= .65 else 5
        rows.append(metric("Options", k, v, "ratio", sig, sc, "Cboe", "https://www.cboe.com/us/options/market_statistics/daily/", "daily"))
    return rows


def aaii_naaim_rows() -> list[dict[str, Any]]:
    rows = []
    text = get_text("https://www.aaii.com/sentimentsurvey") or ""
    plain = re.sub(r"<[^>]+>", " ", text)
    def near(label: str) -> float | None:
        m = re.search(label + r"[^0-9]{0,80}([0-9]+(?:\.[0-9]+)?)%", plain, re.I | re.S)
        return fnum(m.group(1)) if m else None
    bull, bear = near("Bullish"), near("Bearish")
    spread = None if bull is None or bear is None else bull - bear
    rows.append(metric("Survey", "AAII Bullish", bull, "%", "Elevated optimism" if bull and bull > 45 else "Low optimism" if bull and bull < 25 else "Normal" if bull else "Unavailable", None if bull is None else clamp((bull - 37.5) * 3), "AAII", "https://www.aaii.com/sentimentsurvey", "weekly"))
    rows.append(metric("Survey", "AAII Bearish", bear, "%", "Elevated pessimism" if bear and bear > 45 else "Low pessimism" if bear and bear < 25 else "Normal" if bear else "Unavailable", None if bear is None else clamp((30 - bear) * 3), "AAII", "https://www.aaii.com/sentimentsurvey", "weekly"))
    rows.append(metric("Survey", "AAII Bull-Bear Spread", spread, "pts", score_label(spread, 15, -15), None if spread is None else clamp(spread * 2.5), "AAII", "https://www.aaii.com/sentimentsurvey", "weekly"))
    text = get_text("https://www.naaim.org/programs/naaim-exposure-index/") or ""
    plain = re.sub(r"<[^>]+>", " ", text)
    m = re.search(r"Exposure Index[^0-9-]{0,160}(-?[0-9]+(?:\.[0-9]+)?)", plain, re.I)
    val = fnum(m.group(1)) if m else None
    rows.append(metric("Positioning", "NAAIM Exposure", val, "index", "Managers risk-on" if val and val > 60 else "Balanced" if val and val > 35 else "Managers defensive" if val else "Unavailable", 30 if val and val > 60 else 0 if val and val > 35 else -35 if val else None, "NAAIM", "https://www.naaim.org/programs/naaim-exposure-index/", "weekly"))
    return rows


def news_sent(symbol: str) -> tuple[float | None, int]:
    safe = requests.utils.quote(symbol, safe="")
    text = get_text(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={safe}&region=US&lang=en-US")
    if not text:
        return None, 0
    try:
        root = ET.fromstring(text); titles = [i.findtext("title") or "" for i in root.findall(".//item")]
    except Exception:
        titles = re.findall(r"<title>(.*?)</title>", text, re.S)
    scores = []
    for t in titles[:20]:
        words = re.findall(r"[A-Za-z']+", t.lower())
        p, n = sum(w in POS for w in words), sum(w in NEG for w in words)
        scores.append(0 if not p and not n else (p - n) / max(p + n, 1) * 100)
    return (sum(scores) / len(scores), len(titles)) if scores else (None, len(titles))


def stocktwits(symbol: str) -> tuple[float | None, int]:
    st = ST_SYMBOLS.get(symbol, symbol)
    data = get_json(f"https://api.stocktwits.com/api/2/streams/symbol/{requests.utils.quote(st, safe='')}.json")
    msgs = [] if not data else data.get("messages", [])
    bull = bear = 0
    for msg in msgs:
        lab = (((msg.get("entities") or {}).get("sentiment") or {}).get("basic") or "").lower()
        bull += lab == "bullish"; bear += lab == "bearish"
    return (None, len(msgs)) if bull + bear == 0 else (bull / (bull + bear) * 100, len(msgs))


def watchlist_rows() -> list[dict[str, Any]]:
    rows = []
    for sym in WATCHLIST:
        q = yahoo(sym); sig, sc = pct_signal(q["change_pct"])
        rows.append(metric("Watchlist", "Price Change", q["change_pct"], "%", sig, sc, "Yahoo Finance", f"https://finance.yahoo.com/quote/{requests.utils.quote(sym, safe='')}", symbol=sym))
        ns, count = news_sent(sym)
        rows.append(metric("Watchlist", "News Sentiment", ns, "-100 to 100", ("Positive news tone" if ns and ns > 15 else "Negative news tone" if ns and ns < -15 else "Neutral news tone" if ns is not None else "Unavailable") + f"; {count} headlines", None if ns is None else clamp(ns), "Yahoo Finance RSS", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={requests.utils.quote(sym, safe='')}&region=US&lang=en-US", symbol=sym))
        ss, vol = stocktwits(sym)
        rows.append(metric("Watchlist", "Stocktwits Bullish", ss, "%", ("Retail bullish" if ss and ss > 65 else "Retail bearish" if ss and ss < 35 else "Retail balanced" if ss is not None else "Unavailable") + f"; {vol} messages", None if ss is None else clamp((ss - 50) * 3), "Stocktwits", f"https://stocktwits.com/symbol/{ST_SYMBOLS.get(sym, sym)}", symbol=sym))
    return rows


def overall(rows: list[dict[str, Any]]) -> tuple[float, str]:
    weights = {"Fear & Greed": 1.2, "VIX Level": 1.1, "VIX Change": .7, "S&P 500 Change": .9, "Nasdaq Change": .8, "Russell 2000 Change": .7, "High Yield Spread": 1, "NFCI": .9, "Total Put/Call Ratio": .8, "AAII Bull-Bear Spread": .6, "NAAIM Exposure": .6, "Crypto Fear & Greed": .4}
    vals = []
    for r in rows:
        s = fnum(r.get("score"))
        if s is not None:
            vals.append((s, weights.get(r["metric"], .15 if r["category"] == "Watchlist" else .3)))
    if not vals:
        return 0, "Unavailable"
    score = clamp(sum(v * w for v, w in vals) / sum(w for _, w in vals))
    label = "Strong risk-on" if score >= 60 else "Risk-on" if score >= 20 else "Strong risk-off" if score <= -60 else "Risk-off" if score <= -20 else "Neutral"
    return score, label


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    rows = []
    for fn in (market_rows, macro_rows, cboe_rows, aaii_naaim_rows, watchlist_rows):
        try:
            rows += fn()
        except Exception as e:
            rows.append(metric("System", "Collector Warning", str(e)[:120], "text", "Warning", None, "IvySets", ""))
    sc, lab = overall(rows)
    rows.insert(0, metric("Summary", "Overall Sentiment Score", sc, "-100 to 100", lab, sc, "IvySets", ""))
    payload = {"summary": {"name": "IvySets Market Sentiment", "timezone": TZ, "updated_at_london": now(), "overall_score": round(sc, 2), "overall_label": lab, "watchlist": WATCHLIST, "csv_url": "sentiment.csv"}, "metrics": rows}
    (DOCS / "data.json").write_text(json.dumps(payload, indent=2) + "\n")
    cols = ["updated_at_london", "category", "metric", "symbol", "value", "raw_value", "unit", "signal", "score", "source", "source_url", "cadence"]
    with (DOCS / "sentiment.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
