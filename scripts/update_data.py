from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dateutil import tz

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TIMEZONE = "Europe/London"
TRADING_DAYS = 252
STOCKS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "TSLA": "0001318605",
    "AVGO": "0001730168",
    "JPM": "0000019617",
    "LLY": "0000059478",
}

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "IvySets stock factor dashboard contact: tekwanib1@gmail.com",
        "Accept": "application/json,text/csv,text/html,*/*;q=0.8",
    }
)

LITERATURE = [
    {
        "topic": "Value / book-to-market / size",
        "study": "Fama and French (1992, 1993): size and book-to-market help explain the cross-section of average stock returns.",
        "dashboard_use": "P/E, P/B, P/S, P/FCF and market-cap context are used as valuation and size descriptors, not standalone predictions.",
    },
    {
        "topic": "Profitability and investment",
        "study": "Fama and French (2015): the five-factor model adds profitability and investment to market, size and value factors.",
        "dashboard_use": "Margins, ROA, ROE, FCF margin and asset growth are treated as quality/investment factors.",
    },
    {
        "topic": "Momentum",
        "study": "Jegadeesh and Titman (1993): stocks with strong intermediate-term returns historically continued to outperform over subsequent horizons.",
        "dashboard_use": "20D, 63D, 126D and 252D returns plus relative strength versus SPY are used for momentum ranking.",
    },
    {
        "topic": "Four-factor model",
        "study": "Carhart (1997): adds a momentum factor to explain persistence in mutual fund performance.",
        "dashboard_use": "Momentum is separated from fundamental quality rather than mixed into valuation.",
    },
    {
        "topic": "Accounting strength",
        "study": "Piotroski (2000): accounting-based signals can separate stronger from weaker value stocks.",
        "dashboard_use": "ROA, operating cash flow, accrual-style CFO/net income, leverage and margin factors are shown explicitly.",
    },
    {
        "topic": "Accruals",
        "study": "Sloan (1996): earnings components related to accruals have different persistence and implications for future returns.",
        "dashboard_use": "Operating cash flow versus net income and FCF margin are included as earnings-quality checks.",
    },
    {
        "topic": "Gross profitability",
        "study": "Novy-Marx (2013): gross profitability contains information related to expected returns.",
        "dashboard_use": "Gross margin and gross profit are included in the quality score.",
    },
    {
        "topic": "Distress / credit risk",
        "study": "Campbell, Hilscher and Szilagyi (2008): financial distress risk is related to future equity returns and poor firm fundamentals.",
        "dashboard_use": "Debt/equity, liabilities/assets, cash/assets and interest coverage are used as balance-sheet risk descriptors.",
    },
    {
        "topic": "Volatility and beta",
        "study": "Ang, Hodrick, Xing and Zhang (2006): idiosyncratic volatility is related to cross-sectional returns, with important risk implications.",
        "dashboard_use": "20D/60D volatility, beta, correlation, downside deviation, ATR and drawdown are used for risk ranking and forecast range width.",
    },
    {
        "topic": "Prediction limits",
        "study": "Market-efficiency/random-walk literature implies exact short-horizon prices are not scientifically knowable from public data alone.",
        "dashboard_use": "The website shows a one-week statistical center and 68% range from recent drift and volatility, not a guaranteed target price.",
    },
]

FACTOR_CATALOG = [
    ("price", "Current price", "Market", "Latest adjusted market price from daily data."),
    ("market_cap", "Market cap", "Market", "Price multiplied by shares outstanding where SEC shares are available."),
    ("enterprise_value", "Enterprise value", "Market", "Market cap plus debt minus cash."),
    ("avg_dollar_volume_20d", "20D avg dollar volume", "Liquidity", "Average 20-day dollar volume."),
    ("return_1d", "1D return", "Momentum", "One trading-day total return."),
    ("return_5d", "5D return", "Momentum", "Five trading-day total return."),
    ("return_20d", "20D return", "Momentum", "Twenty trading-day total return."),
    ("return_63d", "63D return", "Momentum", "Approximate 3-month return."),
    ("return_126d", "126D return", "Momentum", "Approximate 6-month return."),
    ("return_252d", "252D return", "Momentum", "Approximate 12-month return."),
    ("relative_strength_63d", "63D relative strength vs SPY", "Momentum", "Ticker 63D return minus SPY 63D return."),
    ("sma_50", "50DMA", "Trend", "50-day simple moving average."),
    ("sma_200", "200DMA", "Trend", "200-day simple moving average."),
    ("price_vs_50dma", "Price vs 50DMA", "Trend", "Distance from 50DMA."),
    ("price_vs_200dma", "Price vs 200DMA", "Trend", "Distance from 200DMA."),
    ("distance_52w_high", "Distance from 52W high", "Risk", "Current price relative to one-year high."),
    ("distance_52w_low", "Distance from 52W low", "Risk", "Current price relative to one-year low."),
    ("rsi_14", "RSI 14", "Momentum", "14-day relative strength index."),
    ("realized_vol_20d", "20D realized volatility", "Risk", "Annualized realized volatility from 20 daily log returns."),
    ("realized_vol_60d", "60D realized volatility", "Risk", "Annualized realized volatility from 60 daily log returns."),
    ("beta_1y", "1Y beta vs SPY", "Risk", "Covariance with SPY divided by SPY variance over one year."),
    ("correlation_spy_1y", "1Y correlation vs SPY", "Risk", "Correlation of daily returns with SPY."),
    ("max_drawdown_1y", "1Y max drawdown", "Risk", "Largest peak-to-trough loss over one year."),
    ("downside_vol_60d", "60D downside volatility", "Risk", "Annualized volatility of negative daily returns."),
    ("atr_14_pct", "ATR 14 as % price", "Risk", "Average true range over 14 days divided by price."),
    ("forecast_center_1w", "1W statistical center", "Forecast", "Current price projected by 20D average daily log return over five days."),
    ("forecast_low_1w", "1W 68% low", "Forecast", "Center minus one recent-volatility standard deviation over five days."),
    ("forecast_high_1w", "1W 68% high", "Forecast", "Center plus one recent-volatility standard deviation over five days."),
    ("revenue", "Revenue", "Fundamental", "Latest annual revenue from SEC companyfacts."),
    ("revenue_growth_yoy", "Revenue growth YoY", "Growth", "Latest annual revenue growth versus prior year."),
    ("gross_profit", "Gross profit", "Fundamental", "Latest annual gross profit."),
    ("gross_margin", "Gross margin", "Quality", "Gross profit divided by revenue."),
    ("operating_income", "Operating income", "Fundamental", "Latest annual operating income."),
    ("operating_margin", "Operating margin", "Quality", "Operating income divided by revenue."),
    ("net_income", "Net income", "Fundamental", "Latest annual net income."),
    ("net_margin", "Net margin", "Quality", "Net income divided by revenue."),
    ("eps_diluted", "Diluted EPS", "Fundamental", "Latest annual diluted earnings per share."),
    ("eps_growth_yoy", "EPS growth YoY", "Growth", "Latest annual diluted EPS growth versus prior year."),
    ("operating_cash_flow", "Operating cash flow", "Quality", "Latest annual operating cash flow."),
    ("capex", "Capital expenditure", "Investment", "Latest annual property/equipment purchases."),
    ("free_cash_flow", "Free cash flow", "Quality", "Operating cash flow minus capex cash outflow."),
    ("fcf_margin", "FCF margin", "Quality", "Free cash flow divided by revenue."),
    ("cfo_to_net_income", "CFO / net income", "Quality", "Operating cash flow divided by net income."),
    ("total_assets", "Total assets", "Balance sheet", "Latest annual total assets."),
    ("total_liabilities", "Total liabilities", "Balance sheet", "Latest annual total liabilities."),
    ("shareholders_equity", "Shareholders equity", "Balance sheet", "Latest annual shareholders equity."),
    ("cash", "Cash and equivalents", "Balance sheet", "Latest annual cash and equivalents."),
    ("total_debt", "Total debt", "Balance sheet", "Short-term plus long-term debt when available."),
    ("debt_to_equity", "Debt / equity", "Balance sheet", "Total debt divided by shareholders equity."),
    ("cash_to_assets", "Cash / assets", "Balance sheet", "Cash divided by assets."),
    ("liabilities_to_assets", "Liabilities / assets", "Balance sheet", "Liabilities divided by assets."),
    ("roa", "ROA", "Quality", "Net income divided by assets."),
    ("roe", "ROE", "Quality", "Net income divided by equity."),
    ("pe", "P/E", "Valuation", "Market price divided by diluted EPS."),
    ("ps", "P/S", "Valuation", "Market cap divided by revenue."),
    ("pb", "P/B", "Valuation", "Market cap divided by equity."),
    ("p_fcf", "P/FCF", "Valuation", "Market cap divided by free cash flow."),
    ("ev_sales", "EV/Sales", "Valuation", "Enterprise value divided by revenue."),
    ("ev_ebitda", "EV/EBITDA", "Valuation", "Enterprise value divided by estimated EBITDA."),
    ("rd_to_sales", "R&D / sales", "Investment", "Research and development divided by revenue."),
    ("sga_to_sales", "SG&A / sales", "Efficiency", "Selling/general/admin expense divided by revenue."),
    ("share_change_yoy", "Diluted share change YoY", "Capital allocation", "Change in diluted weighted-average shares."),
]


def now() -> str:
    return datetime.now(tz.gettz(TIMEZONE)).isoformat(timespec="seconds")


def n(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    try:
        s = str(x).replace(",", "").replace("%", "").strip()
        if s in {"", "-", ".", "—", "N/A"}:
            return None
        v = float(s)
        return None if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return None


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def get_json(url: str) -> Any | None:
    try:
        r = SESSION.get(url, timeout=35)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def yahoo(symbol: str) -> dict[str, list[float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol, safe='')}?range=2y&interval=1d"
    data = get_json(url)
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        return {"close": [], "high": [], "low": [], "volume": []}
    q = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes, highs, lows, volumes = [], [], [], []
    for c, h, l, v in zip(q.get("close", []), q.get("high", []), q.get("low", []), q.get("volume", [])):
        c, h, l, v = n(c), n(h), n(l), n(v)
        if c is not None and h is not None and l is not None:
            closes.append(c); highs.append(h); lows.append(l); volumes.append(v or 0)
    return {"close": closes, "high": highs, "low": lows, "volume": volumes}


def ret(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] == 0:
        return None
    return values[-1] / values[-days - 1] - 1


def sma(values: list[float], days: int) -> float | None:
    return None if len(values) < days else sum(values[-days:]) / days


def log_returns(values: list[float], days: int | None = None) -> list[float]:
    vals = values[-(days + 1):] if days else values
    return [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals)) if vals[i - 1] > 0 and vals[i] > 0]


def realized_vol(values: list[float], days: int) -> float | None:
    r = log_returns(values, days)
    return None if len(r) < max(8, days // 3) else statistics.stdev(r) * math.sqrt(TRADING_DAYS)


def rsi(values: list[float], days: int = 14) -> float | None:
    if len(values) <= days:
        return None
    gains, losses = [], []
    for i in range(len(values) - days, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0)); losses.append(abs(min(diff, 0)))
    avg_gain, avg_loss = sum(gains) / days, sum(losses) / days
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr_pct(high: list[float], low: list[float], close: list[float], days: int = 14) -> float | None:
    if len(close) <= days:
        return None
    trs = []
    for i in range(len(close) - days, len(close)):
        trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return safe_div(sum(trs) / len(trs), close[-1])


def max_drawdown(values: list[float], days: int = 252) -> float | None:
    if len(values) < 2:
        return None
    vals = values[-days:]
    peak = vals[0]
    worst = 0.0
    for v in vals:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def downside_vol(values: list[float], days: int = 60) -> float | None:
    r = [x for x in log_returns(values, days) if x < 0]
    return None if len(r) < 5 else statistics.stdev(r) * math.sqrt(TRADING_DAYS)


def beta_corr(stock: list[float], spy: list[float], days: int = 252) -> tuple[float | None, float | None]:
    sr, mr = log_returns(stock, days), log_returns(spy, days)
    length = min(len(sr), len(mr))
    if length < 60:
        return None, None
    sr, mr = sr[-length:], mr[-length:]
    mean_s, mean_m = statistics.mean(sr), statistics.mean(mr)
    cov = sum((a - mean_s) * (b - mean_m) for a, b in zip(sr, mr)) / (length - 1)
    var_m = statistics.variance(mr)
    beta = None if var_m == 0 else cov / var_m
    sd_s, sd_m = statistics.stdev(sr), statistics.stdev(mr)
    corr = None if sd_s == 0 or sd_m == 0 else cov / (sd_s * sd_m)
    return beta, corr


def forecast_1w(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 25:
        return None, None, None
    price = values[-1]
    r = log_returns(values, 20)
    if len(r) < 10:
        return None, None, None
    mu = statistics.mean(r)
    sd = statistics.stdev(r)
    center_log = math.log(price) + 5 * mu
    band = sd * math.sqrt(5)
    return math.exp(center_log), math.exp(center_log - band), math.exp(center_log + band)


def sec_companyfacts(cik: str) -> dict[str, Any]:
    data = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    return data or {}


def fact_items(facts: dict[str, Any], tag: str, unit_priority: tuple[str, ...]) -> list[dict[str, Any]]:
    fact = ((facts.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}
    units = fact.get("units") or {}
    for unit in unit_priority:
        if unit in units:
            return units[unit]
    return []


def annual_values(facts: dict[str, Any], tags: list[str], units: tuple[str, ...] = ("USD", "shares", "USD/shares")) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for tag in tags:
        for item in fact_items(facts, tag, units):
            val = n(item.get("val"))
            fy = item.get("fy")
            if val is None or fy is None:
                continue
            if item.get("form") in {"10-K", "10-K/A"} and item.get("fp") == "FY":
                out.append((int(fy), val))
    dedup = {}
    for fy, val in out:
        dedup[fy] = val
    return sorted(dedup.items())


def latest_annual(facts: dict[str, Any], tags: list[str], units: tuple[str, ...] = ("USD", "shares", "USD/shares")) -> tuple[float | None, float | None]:
    vals = annual_values(facts, tags, units)
    if not vals:
        return None, None
    latest = vals[-1][1]
    prev = vals[-2][1] if len(vals) > 1 else None
    return latest, prev


def growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / abs(previous) - 1


def total_debt(facts: dict[str, Any]) -> float | None:
    current, _ = latest_annual(facts, ["ShortTermBorrowings", "ShortTermDebt", "LongTermDebtCurrent"])
    long, _ = latest_annual(facts, ["LongTermDebtNoncurrent", "LongTermDebt"])
    vals = [v for v in [current, long] if v is not None]
    return sum(vals) if vals else None


def fundamentals(symbol: str, cik: str) -> dict[str, float | None]:
    facts = sec_companyfacts(cik)
    revenue, revenue_prev = latest_annual(facts, ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"])
    gross_profit, _ = latest_annual(facts, ["GrossProfit"])
    operating_income, _ = latest_annual(facts, ["OperatingIncomeLoss"])
    net_income, net_income_prev = latest_annual(facts, ["NetIncomeLoss", "ProfitLoss"])
    eps, eps_prev = latest_annual(facts, ["EarningsPerShareDiluted"], ("USD/shares",))
    ocf, _ = latest_annual(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    capex_raw, _ = latest_annual(facts, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"])
    capex = None if capex_raw is None else abs(capex_raw)
    assets, assets_prev = latest_annual(facts, ["Assets"])
    liabilities, _ = latest_annual(facts, ["Liabilities"])
    equity, equity_prev = latest_annual(facts, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
    cash, _ = latest_annual(facts, ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
    debt = total_debt(facts)
    shares, shares_prev = latest_annual(facts, ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingDiluted"], ("shares",))
    shares_out, _ = latest_annual(facts, ["EntityCommonStockSharesOutstanding"], ("shares",))
    rd, _ = latest_annual(facts, ["ResearchAndDevelopmentExpense"])
    sga, _ = latest_annual(facts, ["SellingGeneralAndAdministrativeExpense"])
    dda, _ = latest_annual(facts, ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationExpense"])
    interest, _ = latest_annual(facts, ["InterestExpenseNonOperating", "InterestExpense"])
    fcf = None if ocf is None or capex is None else ocf - capex
    ebitda = None if operating_income is None else operating_income + (dda or 0)
    return {
        "revenue": revenue,
        "revenue_growth_yoy": growth(revenue, revenue_prev),
        "gross_profit": gross_profit,
        "gross_margin": safe_div(gross_profit, revenue),
        "operating_income": operating_income,
        "operating_margin": safe_div(operating_income, revenue),
        "net_income": net_income,
        "net_margin": safe_div(net_income, revenue),
        "eps_diluted": eps,
        "eps_growth_yoy": growth(eps, eps_prev),
        "operating_cash_flow": ocf,
        "capex": capex,
        "free_cash_flow": fcf,
        "fcf_margin": safe_div(fcf, revenue),
        "cfo_to_net_income": safe_div(ocf, net_income),
        "total_assets": assets,
        "total_liabilities": liabilities,
        "shareholders_equity": equity,
        "cash": cash,
        "total_debt": debt,
        "debt_to_equity": safe_div(debt, equity),
        "cash_to_assets": safe_div(cash, assets),
        "liabilities_to_assets": safe_div(liabilities, assets),
        "roa": safe_div(net_income, assets),
        "roe": safe_div(net_income, equity),
        "rd_to_sales": safe_div(rd, revenue),
        "sga_to_sales": safe_div(sga, revenue),
        "share_change_yoy": growth(shares, shares_prev),
        "shares": shares_out or shares,
        "ebitda": ebitda,
        "interest_coverage": safe_div(operating_income, interest),
        "asset_growth_yoy": growth(assets, assets_prev),
        "equity_growth_yoy": growth(equity, equity_prev),
        "fcf_growth_yoy": None,
    }


def compute_stock(symbol: str, cik: str, spy_close: list[float]) -> dict[str, Any]:
    h = yahoo(symbol)
    close, high, low, volume = h["close"], h["high"], h["low"], h["volume"]
    f = fundamentals(symbol, cik)
    price = close[-1] if close else None
    shares = f.get("shares")
    market_cap = None if price is None or shares is None else price * shares
    debt, cash = f.get("total_debt"), f.get("cash")
    enterprise_value = None if market_cap is None else market_cap + (debt or 0) - (cash or 0)
    fc, fl, fh = forecast_1w(close)
    beta, corr = beta_corr(close, spy_close)
    s50, s200 = sma(close, 50), sma(close, 200)
    high_52 = max(close[-252:]) if len(close) >= 252 else None
    low_52 = min(close[-252:]) if len(close) >= 252 else None
    dollar_volume = None
    if price is not None and len(volume) >= 20:
        dollar_volume = sum(volume[-20:]) / 20 * price
    vals = {
        "price": price,
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "avg_dollar_volume_20d": dollar_volume,
        "return_1d": ret(close, 1),
        "return_5d": ret(close, 5),
        "return_20d": ret(close, 20),
        "return_63d": ret(close, 63),
        "return_126d": ret(close, 126),
        "return_252d": ret(close, 252),
        "relative_strength_63d": None if ret(close, 63) is None or ret(spy_close, 63) is None else ret(close, 63) - ret(spy_close, 63),
        "sma_50": s50,
        "sma_200": s200,
        "price_vs_50dma": None if price is None or s50 is None else price / s50 - 1,
        "price_vs_200dma": None if price is None or s200 is None else price / s200 - 1,
        "distance_52w_high": None if price is None or high_52 in (None, 0) else price / high_52 - 1,
        "distance_52w_low": None if price is None or low_52 in (None, 0) else price / low_52 - 1,
        "rsi_14": rsi(close),
        "realized_vol_20d": realized_vol(close, 20),
        "realized_vol_60d": realized_vol(close, 60),
        "beta_1y": beta,
        "correlation_spy_1y": corr,
        "max_drawdown_1y": max_drawdown(close),
        "downside_vol_60d": downside_vol(close),
        "atr_14_pct": atr_pct(high, low, close),
        "forecast_center_1w": fc,
        "forecast_low_1w": fl,
        "forecast_high_1w": fh,
        **f,
    }
    vals["pe"] = safe_div(price, vals.get("eps_diluted"))
    vals["ps"] = safe_div(market_cap, vals.get("revenue"))
    vals["pb"] = safe_div(market_cap, vals.get("shareholders_equity"))
    vals["p_fcf"] = safe_div(market_cap, vals.get("free_cash_flow"))
    vals["ev_sales"] = safe_div(enterprise_value, vals.get("revenue"))
    vals["ev_ebitda"] = safe_div(enterprise_value, vals.get("ebitda"))
    return {"symbol": symbol, "values": vals}


def percentile_scores(stocks: list[dict[str, Any]], keys: list[str], higher_better: bool = True) -> dict[str, float | None]:
    out = {s["symbol"]: None for s in stocks}
    pairs = [(s["symbol"], s["values"].get(k)) for s in stocks for k in []]
    return out


def score_metric(stocks: list[dict[str, Any]], key: str, higher_better: bool) -> dict[str, float | None]:
    vals = [(s["symbol"], s["values"].get(key)) for s in stocks]
    vals = [(sym, val) for sym, val in vals if val is not None and math.isfinite(val)]
    if len(vals) < 3:
        return {s["symbol"]: None for s in stocks}
    sorted_vals = sorted(v for _, v in vals)
    res = {}
    for sym, val in vals:
        rank = sum(1 for x in sorted_vals if x <= val) / len(sorted_vals)
        res[sym] = rank * 100 if higher_better else (1 - rank) * 100
    for s in stocks:
        res.setdefault(s["symbol"], None)
    return res


def mean_available(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return None if not vals else sum(vals) / len(vals)


def add_scores(stocks: list[dict[str, Any]]) -> None:
    groups = {
        "value_score": [("pe", False), ("ps", False), ("pb", False), ("p_fcf", False), ("ev_sales", False), ("ev_ebitda", False)],
        "quality_score": [("gross_margin", True), ("operating_margin", True), ("net_margin", True), ("fcf_margin", True), ("roa", True), ("roe", True), ("cfo_to_net_income", True), ("debt_to_equity", False)],
        "growth_score": [("revenue_growth_yoy", True), ("eps_growth_yoy", True), ("return_252d", True), ("asset_growth_yoy", False), ("share_change_yoy", False)],
        "momentum_score": [("return_20d", True), ("return_63d", True), ("return_126d", True), ("return_252d", True), ("relative_strength_63d", True), ("price_vs_50dma", True), ("price_vs_200dma", True)],
        "risk_score": [("realized_vol_20d", False), ("realized_vol_60d", False), ("beta_1y", False), ("atr_14_pct", False), ("max_drawdown_1y", True), ("downside_vol_60d", False)],
    }
    metric_scores = {key: score_metric(stocks, key, hb) for pairs in groups.values() for key, hb in pairs}
    for s in stocks:
        sym = s["symbol"]
        cat_scores = {}
        for group, pairs in groups.items():
            cat_scores[group] = mean_available([metric_scores[key].get(sym) for key, _ in pairs])
        overall = mean_available(list(cat_scores.values()))
        s["category_scores"] = {k: None if v is None else round(v, 1) for k, v in cat_scores.items()}
        s["overall_score"] = None if overall is None else round(overall, 1)
        v = s["values"]
        neg, pos = [], []
        if v.get("price_vs_200dma") is not None:
            (pos if v["price_vs_200dma"] > 0 else neg).append("200DMA trend")
        if v.get("relative_strength_63d") is not None:
            (pos if v["relative_strength_63d"] > 0 else neg).append("relative strength")
        if v.get("revenue_growth_yoy") is not None:
            (pos if v["revenue_growth_yoy"] > 0 else neg).append("revenue growth")
        if v.get("fcf_margin") is not None:
            (pos if v["fcf_margin"] > 0 else neg).append("FCF margin")
        if v.get("debt_to_equity") is not None and v["debt_to_equity"] > 2:
            neg.append("balance-sheet leverage")
        if overall is None:
            status = "Insufficient data"
        elif overall >= 70:
            status = "High research rank"
        elif overall >= 50:
            status = "Neutral / watch"
        else:
            status = "Weak research rank"
        s["status"] = status
        s["positives"] = pos[:4]
        s["risks"] = neg[:4]
        if v.get("forecast_center_1w") is None:
            s["next_week_model"] = "Unavailable"
        else:
            s["next_week_model"] = f"{money(v['forecast_center_1w'])} center; {money(v.get('forecast_low_1w'))}–{money(v.get('forecast_high_1w'))} 68% range"
        s["next_step"] = "Research fundamentals and wait for a defined entry setup; the model range is statistical, not a target price."


def money(v: float | None) -> str:
    if v is None:
        return "Unavailable"
    if abs(v) >= 1e12:
        return f"${v/1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:,.2f}"


def percent(v: float | None) -> str:
    return "Unavailable" if v is None else f"{v*100:.1f}%"


def ratio(v: float | None) -> str:
    return "Unavailable" if v is None else f"{v:.2f}"


def display_factor(key: str, value: float | None) -> str:
    if value is None:
        return "Unavailable"
    if key in {"price", "forecast_center_1w", "forecast_low_1w", "forecast_high_1w"}:
        return money(value)
    if key in {"market_cap", "enterprise_value", "avg_dollar_volume_20d", "revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "capex", "free_cash_flow", "total_assets", "total_liabilities", "shareholders_equity", "cash", "total_debt"}:
        return money(value)
    if "return" in key or "growth" in key or "margin" in key or key in {"price_vs_50dma", "price_vs_200dma", "distance_52w_high", "distance_52w_low", "realized_vol_20d", "realized_vol_60d", "correlation_spy_1y", "max_drawdown_1y", "downside_vol_60d", "atr_14_pct", "cash_to_assets", "liabilities_to_assets", "roa", "roe", "rd_to_sales", "sga_to_sales", "share_change_yoy"}:
        return percent(value)
    return ratio(value)


def write_outputs() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    spy = yahoo("SPY")["close"]
    stocks = [compute_stock(symbol, cik, spy) for symbol, cik in STOCKS.items()]
    add_scores(stocks)
    for s in stocks:
        factors = []
        for key, label, category, definition in FACTOR_CATALOG:
            value = s["values"].get(key)
            factors.append({"key": key, "label": label, "category": category, "value": value, "display": display_factor(key, value), "definition": definition})
        s["factors"] = factors
    stocks.sort(key=lambda x: (-1 if x.get("overall_score") is None else -x["overall_score"]))
    payload = {
        "summary": {
            "name": "IvySets Stock Factor Lab",
            "updated_at_london": now(),
            "timezone": TIMEZONE,
            "stock_count": len(stocks),
            "factor_count": len(FACTOR_CATALOG),
            "model": "One-week statistical center and 68% range from 20-day drift and realized volatility; not a guaranteed price target.",
        },
        "stocks": stocks,
        "factor_catalog": [{"key": k, "label": l, "category": c, "definition": d} for k, l, c, d in FACTOR_CATALOG],
        "literature": LITERATURE,
    }
    (DOCS / "data.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    cols = ["timestamp", "symbol", "overall_score", "status", "category", "factor", "value", "display", "definition"]
    with (DOCS / "sentiment.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in stocks:
            for fac in s["factors"]:
                w.writerow({"timestamp": payload["summary"]["updated_at_london"], "symbol": s["symbol"], "overall_score": s.get("overall_score"), "status": s.get("status"), "category": fac["category"], "factor": fac["label"], "value": fac["value"], "display": fac["display"], "definition": fac["definition"]})


if __name__ == "__main__":
    write_outputs()
