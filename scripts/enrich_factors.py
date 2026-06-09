from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import requests

import update_data as base

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "IvySets factor enrichment contact: tekwanib1@gmail.com",
    "Accept": "application/json,text/csv,text/html,*/*;q=0.8",
})

MODULES = "price,summaryDetail,defaultKeyStatistics,financialData,incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory"

SEC_TAGS = {
    "revenue": ["Revenues", "Revenue", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractsWithCustomers"],
    "gross_profit": ["GrossProfit", "GrossProfitLoss"],
    "operating_income": ["OperatingIncomeLoss", "OperatingProfitLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "eps_diluted": ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare", "DilutedEarningsLossPerShareFromContinuingOperations"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PaymentsToAcquireProductiveAssets"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["StockholdersEquity", "Equity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "EquityAttributableToOwnersOfParent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "rd_to_sales_raw": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "sga_to_sales_raw": ["SellingGeneralAndAdministrativeExpense"],
    "interest_raw": ["InterestExpense", "InterestExpenseNonOperating", "FinanceCosts"],
    "debt_current_raw": ["ShortTermBorrowings", "ShortTermDebt", "LongTermDebtCurrent", "BorrowingsCurrent"],
    "debt_long_raw": ["LongTermDebt", "LongTermDebtNoncurrent", "BorrowingsNoncurrent"],
    "shares_raw": ["EntityCommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingDiluted"],
}

YAHOO_KEYS = {
    "market_cap": [("price", "marketCap"), ("defaultKeyStatistics", "marketCap")],
    "enterprise_value": [("defaultKeyStatistics", "enterpriseValue")],
    "avg_dollar_volume_20d": [("price", "averageDailyVolume10Day")],
    "beta_1y": [("defaultKeyStatistics", "beta")],
    "revenue": [("financialData", "totalRevenue"), ("incomeStatementHistory", "totalRevenue")],
    "gross_profit": [("incomeStatementHistory", "grossProfit")],
    "operating_income": [("incomeStatementHistory", "operatingIncome")],
    "net_income": [("incomeStatementHistory", "netIncome")],
    "eps_diluted": [("defaultKeyStatistics", "trailingEps")],
    "operating_cash_flow": [("financialData", "operatingCashflow"), ("cashflowStatementHistory", "totalCashFromOperatingActivities")],
    "capex": [("cashflowStatementHistory", "capitalExpenditures")],
    "free_cash_flow": [("financialData", "freeCashflow")],
    "total_assets": [("balanceSheetHistory", "totalAssets")],
    "total_liabilities": [("balanceSheetHistory", "totalLiab")],
    "shareholders_equity": [("balanceSheetHistory", "totalStockholderEquity")],
    "cash": [("financialData", "totalCash"), ("balanceSheetHistory", "cash")],
    "total_debt": [("financialData", "totalDebt"), ("balanceSheetHistory", "longTermDebt"), ("balanceSheetHistory", "shortLongTermDebt")],
    "debt_to_equity": [("financialData", "debtToEquity")],
    "revenue_growth_yoy": [("financialData", "revenueGrowth")],
    "gross_margin": [("financialData", "grossMargins")],
    "operating_margin": [("financialData", "operatingMargins")],
    "net_margin": [("financialData", "profitMargins")],
    "roa": [("financialData", "returnOnAssets")],
    "roe": [("financialData", "returnOnEquity")],
    "pe": [("summaryDetail", "trailingPE")],
    "ps": [("summaryDetail", "priceToSalesTrailing12Months")],
    "pb": [("defaultKeyStatistics", "priceToBook")],
    "ev_sales": [("defaultKeyStatistics", "enterpriseToRevenue")],
    "ev_ebitda": [("defaultKeyStatistics", "enterpriseToEbitda")],
}


def yget(symbol: str) -> tuple[dict[str, Any], str]:
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{requests.utils.quote(symbol, safe='')}?modules={MODULES}"
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        result = (((r.json() or {}).get("quoteSummary") or {}).get("result") or [{}])[0]
        return result or {}, url
    except Exception:
        return {}, url


def val(obj: Any) -> float | None:
    if isinstance(obj, dict):
        for key in ("raw", "fmt"):
            if key in obj:
                return base.to_num(obj.get(key))
    return base.to_num(obj)


def nested(module: dict[str, Any], key: str) -> float | None:
    if key in module:
        return val(module[key])
    history = module.get("incomeStatementHistory") or module.get("balanceSheetStatements") or module.get("cashflowStatements")
    if isinstance(history, list) and history:
        return val(history[0].get(key))
    return None


def yvalue(data: dict[str, Any], candidates: list[tuple[str, str]]) -> float | None:
    for module_name, key in candidates:
        module = data.get(module_name) or {}
        value = nested(module, key)
        if value is not None:
            return abs(value) if key == "capitalExpenditures" else value
    return None


def sec_facts(cik: str) -> dict[str, Any]:
    try:
        r = SESSION.get(base.sec_url(cik), timeout=30)
        r.raise_for_status()
        return r.json() or {}
    except Exception:
        return {}


def sec_latest(facts: dict[str, Any], tags: list[str]) -> float | None:
    all_facts = facts.get("facts") or {}
    best = None
    for taxonomy in all_facts.values():
        if not isinstance(taxonomy, dict):
            continue
        for tag in tags:
            node = taxonomy.get(tag)
            if not node:
                continue
            for unit_values in (node.get("units") or {}).values():
                for item in unit_values:
                    value = base.to_num(item.get("val"))
                    fy = item.get("fy") or 0
                    form = item.get("form") or ""
                    if value is None:
                        continue
                    weight = (int(fy) if str(fy).isdigit() else 0, 2 if form in {"10-K", "20-F", "10-K/A", "20-F/A"} else 1)
                    if best is None or weight > best[0]:
                        best = (weight, value)
    return None if best is None else best[1]


def set_if_missing(values: dict[str, Any], key: str, value: float | None) -> None:
    if values.get(key) is None and value is not None and math.isfinite(value):
        values[key] = value


def recompute(values: dict[str, Any]) -> None:
    set_if_missing(values, "total_debt", sum(x for x in [values.get("debt_current_raw"), values.get("debt_long_raw")] if x is not None) or None)
    set_if_missing(values, "enterprise_value", None if values.get("market_cap") is None else values.get("market_cap") + (values.get("total_debt") or 0) - (values.get("cash") or 0))
    set_if_missing(values, "free_cash_flow", None if values.get("operating_cash_flow") is None or values.get("capex") is None else values.get("operating_cash_flow") - values.get("capex"))
    set_if_missing(values, "gross_margin", base.div(values.get("gross_profit"), values.get("revenue")))
    set_if_missing(values, "operating_margin", base.div(values.get("operating_income"), values.get("revenue")))
    set_if_missing(values, "net_margin", base.div(values.get("net_income"), values.get("revenue")))
    set_if_missing(values, "fcf_margin", base.div(values.get("free_cash_flow"), values.get("revenue")))
    set_if_missing(values, "cfo_to_net_income", base.div(values.get("operating_cash_flow"), values.get("net_income")))
    set_if_missing(values, "debt_to_equity", base.div(values.get("total_debt"), values.get("shareholders_equity")))
    set_if_missing(values, "cash_to_assets", base.div(values.get("cash"), values.get("total_assets")))
    set_if_missing(values, "liabilities_to_assets", base.div(values.get("total_liabilities"), values.get("total_assets")))
    set_if_missing(values, "roa", base.div(values.get("net_income"), values.get("total_assets")))
    set_if_missing(values, "roe", base.div(values.get("net_income"), values.get("shareholders_equity")))
    set_if_missing(values, "pe", base.div(values.get("price"), values.get("eps_diluted")))
    set_if_missing(values, "ps", base.div(values.get("market_cap"), values.get("revenue")))
    set_if_missing(values, "pb", base.div(values.get("market_cap"), values.get("shareholders_equity")))
    set_if_missing(values, "p_fcf", base.div(values.get("market_cap"), values.get("free_cash_flow")))
    set_if_missing(values, "ev_sales", base.div(values.get("enterprise_value"), values.get("revenue")))
    set_if_missing(values, "ev_ebitda", base.div(values.get("enterprise_value"), values.get("ebitda")))
    set_if_missing(values, "rd_to_sales", base.div(values.get("rd_to_sales_raw"), values.get("revenue")))
    set_if_missing(values, "sga_to_sales", base.div(values.get("sga_to_sales_raw"), values.get("revenue")))
    set_if_missing(values, "interest_coverage", base.div(values.get("operating_income"), values.get("interest_raw")))


def enrich_stock(stock: dict[str, Any]) -> None:
    values = stock.get("values") or {}
    ydata, yurl = yget(stock["symbol"])
    facts = sec_facts(stock.get("cik", ""))
    sec_link = base.sec_url(stock.get("cik", ""))

    for key, tags in SEC_TAGS.items():
        raw = sec_latest(facts, tags)
        if key in {"capex", "debt_current_raw", "debt_long_raw"} and raw is not None:
            raw = abs(raw)
        set_if_missing(values, key, raw)

    for key, candidates in YAHOO_KEYS.items():
        raw = yvalue(ydata, candidates)
        if key == "avg_dollar_volume_20d" and raw is not None and values.get("price") is not None:
            raw = raw * values["price"]
        if key == "debt_to_equity" and raw is not None and raw > 5:
            raw = raw / 100
        set_if_missing(values, key, raw)

    recompute(values)
    stock["values"] = values
    for factor in stock.get("factors", []):
        key = factor["key"]
        value = values.get(key)
        factor["value"] = value
        factor["display"] = base.display(key, value)
        factor["available"] = value is not None
        source_type = factor.get("source_type")
        if source_type == "sec":
            factor["sources"] = [{"label": "SEC companyfacts JSON", "url": sec_link}, {"label": "Yahoo quote summary", "url": yurl}]
        elif source_type == "calculated":
            factor["sources"] = [{"label": "Yahoo quote summary", "url": yurl}, {"label": "SEC companyfacts JSON", "url": sec_link}]
        elif source_type == "yahoo":
            factor["sources"] = [{"label": "Yahoo chart JSON", "url": stock["links"]["yahoo_chart"]}, {"label": "Yahoo quote summary", "url": yurl}]
    stock["available_factor_count"] = sum(1 for f in stock.get("factors", []) if f.get("available"))
    stock["current_price"] = values.get("price")
    stock["current_price_display"] = base.display("price", values.get("price"))
    stock["predicted_price"] = values.get("predicted_price")
    stock["predicted_price_display"] = base.display("predicted_price", values.get("predicted_price"))
    positives = stock.get("positives", []) or []
    risks = stock.get("risks", []) or []
    stock["analysis_text"] = f"{stock['symbol']} has {stock['available_factor_count']}/{stock['total_factor_count']} factors available after SEC multi-taxonomy and Yahoo summary enrichment. Current price is {stock['current_price_display']}. Predicted price center by {stock.get('prediction_date')} is {stock['predicted_price_display']}. Positive checks: {', '.join(positives) if positives else 'none shown'}. Risk checks: {', '.join(risks) if risks else 'none shown'}."


def write_csv(payload: dict[str, Any]) -> None:
    cols = ["timestamp", "symbol", "stock_name", "current_price", "predicted_price", "prediction_date", "available_factors", "total_factors", "factors"]
    with (base.DOCS / "sentiment.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        for stock in payload["stocks"]:
            factor_text = ", ".join(f"{factor['label']}={factor['display']}" for factor in stock["factors"])
            writer.writerow({"timestamp": payload["summary"]["updated_at_london"], "symbol": stock["symbol"], "stock_name": stock["name"], "current_price": stock["current_price_display"], "predicted_price": stock["predicted_price_display"], "prediction_date": stock["prediction_date"], "available_factors": stock["available_factor_count"], "total_factors": stock["total_factor_count"], "factors": factor_text})


def main() -> None:
    path = base.DOCS / "data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for stock in payload.get("stocks", []):
        before = stock.get("available_factor_count", 0)
        enrich_stock(stock)
        stock["enrichment_note"] = f"Available factors changed from {before} to {stock.get('available_factor_count', before)}."
    payload["summary"]["updated_at_london"] = base.now()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(payload)


if __name__ == "__main__":
    main()
