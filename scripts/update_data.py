from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dateutil import tz

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TIMEZONE = "Europe/London"
TRADING_DAYS = 252
STOCKS = {
    "AAPL": ("Apple Inc.", "0000320193"),
    "MSFT": ("Microsoft Corporation", "0000789019"),
    "NVDA": ("NVIDIA Corporation", "0001045810"),
    "AMZN": ("Amazon.com, Inc.", "0001018724"),
    "GOOGL": ("Alphabet Inc.", "0001652044"),
    "META": ("Meta Platforms, Inc.", "0001326801"),
    "TSLA": ("Tesla, Inc.", "0001318605"),
    "AVGO": ("Broadcom Inc.", "0001730168"),
    "JPM": ("JPMorgan Chase & Co.", "0000019617"),
    "LLY": ("Eli Lilly and Company", "0000059478"),
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "IvySets stock factor dashboard contact: tekwanib1@gmail.com",
    "Accept": "application/json,text/csv,text/html,*/*;q=0.8",
})

FACTOR_CATALOG = [
    ("price","Current price","Market","yahoo","Latest daily adjusted/regular close from Yahoo chart data."),
    ("market_cap","Market cap","Market","calculated","Price multiplied by SEC-reported shares outstanding."),
    ("enterprise_value","Enterprise value","Market","calculated","Market cap plus debt minus cash."),
    ("avg_dollar_volume_20d","20D avg dollar volume","Liquidity","calculated","Average 20D volume multiplied by latest price."),
    ("return_1d","1D return","Momentum","calculated","One trading-day total return from Yahoo closes."),
    ("return_5d","5D return","Momentum","calculated","Five trading-day total return from Yahoo closes."),
    ("return_20d","20D return","Momentum","calculated","Twenty trading-day total return from Yahoo closes."),
    ("return_63d","63D return","Momentum","calculated","Approximate 3-month return from Yahoo closes."),
    ("return_126d","126D return","Momentum","calculated","Approximate 6-month return from Yahoo closes."),
    ("return_252d","252D return","Momentum","calculated","Approximate 12-month return from Yahoo closes."),
    ("relative_strength_63d","63D relative strength vs SPY","Momentum","calculated","Ticker 63D return minus SPY 63D return."),
    ("sma_50","50DMA","Trend","calculated","50-day simple moving average."),
    ("sma_200","200DMA","Trend","calculated","200-day simple moving average."),
    ("price_vs_50dma","Price vs 50DMA","Trend","calculated","Current price divided by 50DMA minus 1."),
    ("price_vs_200dma","Price vs 200DMA","Trend","calculated","Current price divided by 200DMA minus 1."),
    ("distance_52w_high","Distance from 52W high","Risk","calculated","Current price relative to one-year high."),
    ("distance_52w_low","Distance from 52W low","Risk","calculated","Current price relative to one-year low."),
    ("rsi_14","RSI 14","Momentum","calculated","14-day relative strength index from Yahoo closes."),
    ("realized_vol_20d","20D realized volatility","Risk","calculated","Annualized stdev of 20 daily log returns."),
    ("realized_vol_60d","60D realized volatility","Risk","calculated","Annualized stdev of 60 daily log returns."),
    ("beta_1y","1Y beta vs SPY","Risk","calculated","Covariance with SPY divided by SPY variance over one year."),
    ("correlation_spy_1y","1Y correlation vs SPY","Risk","calculated","Daily return correlation with SPY over one year."),
    ("max_drawdown_1y","1Y max drawdown","Risk","calculated","Largest peak-to-trough loss over one year."),
    ("downside_vol_60d","60D downside volatility","Risk","calculated","Annualized stdev of negative daily returns."),
    ("atr_14_pct","ATR 14 as % price","Risk","calculated","Average true range over 14 days divided by price."),
    ("forecast_date","Prediction date","Forecast","calculated","Seven calendar days ahead."),
    ("predicted_price","Predicted price center","Forecast","calculated","Factor-adjusted statistical center from recent drift, volatility and peer factor rank."),
    ("prediction_low","68% prediction low","Forecast","calculated","Center minus one recent-volatility standard deviation over five trading days."),
    ("prediction_high","68% prediction high","Forecast","calculated","Center plus one recent-volatility standard deviation over five trading days."),
    ("revenue","Revenue","Fundamental","sec","Latest annual revenue from SEC companyfacts."),
    ("revenue_growth_yoy","Revenue growth YoY","Growth","calculated","Latest annual revenue growth versus prior year."),
    ("gross_profit","Gross profit","Fundamental","sec","Latest annual gross profit from SEC companyfacts."),
    ("gross_margin","Gross margin","Quality","calculated","Gross profit divided by revenue."),
    ("operating_income","Operating income","Fundamental","sec","Latest annual operating income from SEC companyfacts."),
    ("operating_margin","Operating margin","Quality","calculated","Operating income divided by revenue."),
    ("net_income","Net income","Fundamental","sec","Latest annual net income from SEC companyfacts."),
    ("net_margin","Net margin","Quality","calculated","Net income divided by revenue."),
    ("eps_diluted","Diluted EPS","Fundamental","sec","Latest annual diluted EPS from SEC companyfacts."),
    ("eps_growth_yoy","EPS growth YoY","Growth","calculated","Latest annual diluted EPS growth versus prior year."),
    ("operating_cash_flow","Operating cash flow","Quality","sec","Latest annual operating cash flow from SEC companyfacts."),
    ("capex","Capital expenditure","Investment","sec","Latest annual capex cash outflow from SEC companyfacts."),
    ("free_cash_flow","Free cash flow","Quality","calculated","Operating cash flow minus capital expenditure."),
    ("fcf_margin","FCF margin","Quality","calculated","Free cash flow divided by revenue."),
    ("cfo_to_net_income","CFO / net income","Quality","calculated","Operating cash flow divided by net income."),
    ("total_assets","Total assets","Balance sheet","sec","Latest annual total assets from SEC companyfacts."),
    ("total_liabilities","Total liabilities","Balance sheet","sec","Latest annual total liabilities from SEC companyfacts."),
    ("shareholders_equity","Shareholders equity","Balance sheet","sec","Latest annual shareholders equity from SEC companyfacts."),
    ("cash","Cash and equivalents","Balance sheet","sec","Latest annual cash and equivalents from SEC companyfacts."),
    ("total_debt","Total debt","Balance sheet","calculated","Current plus long-term debt from SEC companyfacts."),
    ("debt_to_equity","Debt / equity","Balance sheet","calculated","Total debt divided by shareholders equity."),
    ("cash_to_assets","Cash / assets","Balance sheet","calculated","Cash divided by assets."),
    ("liabilities_to_assets","Liabilities / assets","Balance sheet","calculated","Liabilities divided by assets."),
    ("roa","ROA","Quality","calculated","Net income divided by total assets."),
    ("roe","ROE","Quality","calculated","Net income divided by shareholders equity."),
    ("pe","P/E","Valuation","calculated","Price divided by diluted EPS."),
    ("ps","P/S","Valuation","calculated","Market cap divided by revenue."),
    ("pb","P/B","Valuation","calculated","Market cap divided by shareholders equity."),
    ("p_fcf","P/FCF","Valuation","calculated","Market cap divided by free cash flow."),
    ("ev_sales","EV/Sales","Valuation","calculated","Enterprise value divided by revenue."),
    ("ev_ebitda","EV/EBITDA","Valuation","calculated","Enterprise value divided by estimated EBITDA."),
    ("rd_to_sales","R&D / sales","Investment","calculated","Research and development divided by revenue."),
    ("sga_to_sales","SG&A / sales","Efficiency","calculated","SG&A expense divided by revenue."),
    ("share_change_yoy","Diluted share change YoY","Capital allocation","calculated","Change in diluted weighted-average shares."),
    ("interest_coverage","Interest coverage","Balance sheet","calculated","Operating income divided by interest expense."),
]

LITERATURE = [
    {"topic":"Value","study":"Fama and French (1992, 1993) document size and book-to-market effects in average returns.","dashboard_use":"Valuation ratios are analysis factors, not direct price targets."},
    {"topic":"Profitability and investment","study":"Fama and French (2015) add profitability and investment factors to their five-factor model.","dashboard_use":"Margins, ROA, ROE, FCF margin and asset growth are quality/investment checks."},
    {"topic":"Momentum","study":"Jegadeesh and Titman (1993) document intermediate-term return continuation.","dashboard_use":"20D, 63D, 126D, 252D returns and relative strength are momentum factors."},
]


def now() -> str:
    return datetime.now(tz.gettz(TIMEZONE)).isoformat(timespec="seconds")


def prediction_date() -> str:
    return (datetime.now(tz.gettz(TIMEZONE)) + timedelta(days=7)).date().isoformat()


def to_num(x: Any) -> float | None:
    if x is None or isinstance(x, bool): return None
    if isinstance(x, (int, float)):
        v=float(x); return None if math.isnan(v) or math.isinf(v) else v
    try:
        s=str(x).replace(",","").replace("%","").strip()
        if s in {"","-",".","—","N/A"}: return None
        v=float(s); return None if math.isnan(v) or math.isinf(v) else v
    except Exception: return None


def div(a: float | None, b: float | None) -> float | None:
    return None if a is None or b in (None,0) else a/b


def get_json(url: str) -> Any | None:
    try:
        r=SESSION.get(url,timeout=35); r.raise_for_status(); return r.json()
    except Exception: return None


def yahoo_url(symbol: str) -> str:
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol,safe='')}?range=2y&interval=1d"


def yahoo(symbol: str) -> dict[str, list[float]]:
    result=((((get_json(yahoo_url(symbol)) or {}).get("chart") or {}).get("result") or [None])[0])
    if not result: return {"close":[],"high":[],"low":[],"volume":[]}
    q=(result.get("indicators",{}).get("quote") or [{}])[0]
    out={"close":[],"high":[],"low":[],"volume":[]}
    for c,h,l,v in zip(q.get("close",[]),q.get("high",[]),q.get("low",[]),q.get("volume",[])):
        c,h,l,v=to_num(c),to_num(h),to_num(l),to_num(v)
        if c is not None and h is not None and l is not None:
            out["close"].append(c); out["high"].append(h); out["low"].append(l); out["volume"].append(v or 0)
    return out


def ret(values:list[float],days:int)->float|None:
    return None if len(values)<=days or values[-days-1]==0 else values[-1]/values[-days-1]-1

def sma(values:list[float],days:int)->float|None:
    return None if len(values)<days else sum(values[-days:])/days

def log_returns(values:list[float],days:int|None=None)->list[float]:
    vals=values[-(days+1):] if days else values
    return [math.log(vals[i]/vals[i-1]) for i in range(1,len(vals)) if vals[i-1]>0 and vals[i]>0]

def realized_vol(values:list[float],days:int)->float|None:
    rs=log_returns(values,days)
    return None if len(rs)<max(8,days//3) else statistics.stdev(rs)*math.sqrt(TRADING_DAYS)

def rsi(values:list[float],days:int=14)->float|None:
    if len(values)<=days: return None
    gains=[]; losses=[]
    for i in range(len(values)-days,len(values)):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(abs(min(d,0)))
    ag,al=sum(gains)/days,sum(losses)/days
    return 100.0 if al==0 else 100-100/(1+ag/al)

def atr_pct(high:list[float],low:list[float],close:list[float],days:int=14)->float|None:
    if len(close)<=days: return None
    trs=[max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1])) for i in range(len(close)-days,len(close))]
    return div(sum(trs)/len(trs),close[-1])

def max_drawdown(values:list[float],days:int=252)->float|None:
    if len(values)<2: return None
    vals=values[-days:]; peak=vals[0]; worst=0.0
    for v in vals: peak=max(peak,v); worst=min(worst,v/peak-1)
    return worst

def downside_vol(values:list[float],days:int=60)->float|None:
    rs=[x for x in log_returns(values,days) if x<0]
    return None if len(rs)<5 else statistics.stdev(rs)*math.sqrt(TRADING_DAYS)

def beta_corr(stock:list[float],spy:list[float],days:int=252)->tuple[float|None,float|None]:
    sr,mr=log_returns(stock,days),log_returns(spy,days); length=min(len(sr),len(mr))
    if length<60: return None,None
    sr,mr=sr[-length:],mr[-length:]; ms,mm=statistics.mean(sr),statistics.mean(mr)
    cov=sum((a-ms)*(b-mm) for a,b in zip(sr,mr))/(length-1); var_m=statistics.variance(mr)
    beta=None if var_m==0 else cov/var_m
    corr=None if statistics.stdev(sr)==0 or statistics.stdev(mr)==0 else cov/(statistics.stdev(sr)*statistics.stdev(mr))
    return beta,corr


def sec_url(cik:str)->str: return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
def sec_companyfacts(cik:str)->dict[str,Any]: return get_json(sec_url(cik)) or {}

def fact_items(facts:dict[str,Any],tag:str,units:tuple[str,...])->list[dict[str,Any]]:
    all_units=(((facts.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}).get("units") or {}
    for unit in units:
        if unit in all_units: return all_units[unit]
    return []

def latest_annual(facts:dict[str,Any],tags:list[str],units:tuple[str,...]=("USD","shares","USD/shares"))->tuple[float|None,float|None]:
    vals={}
    for tag in tags:
        for item in fact_items(facts,tag,units):
            val,fy=to_num(item.get("val")),item.get("fy")
            if val is not None and fy is not None and item.get("form") in {"10-K","10-K/A"} and item.get("fp")=="FY": vals[int(fy)]=val
    items=sorted(vals.items())
    return (None,None) if not items else (items[-1][1], items[-2][1] if len(items)>1 else None)

def growth(c:float|None,p:float|None)->float|None: return None if c is None or p in (None,0) else c/abs(p)-1


def fundamentals(cik:str)->dict[str,float|None]:
    facts=sec_companyfacts(cik)
    revenue,rev_prev=latest_annual(facts,["Revenues","SalesRevenueNet","RevenueFromContractWithCustomerExcludingAssessedTax"])
    gross_profit,_=latest_annual(facts,["GrossProfit"]); op_inc,_=latest_annual(facts,["OperatingIncomeLoss"]); net_inc,_=latest_annual(facts,["NetIncomeLoss","ProfitLoss"])
    eps,eps_prev=latest_annual(facts,["EarningsPerShareDiluted"],("USD/shares",)); ocf,_=latest_annual(facts,["NetCashProvidedByUsedInOperatingActivities"])
    capex_raw,_=latest_annual(facts,["PaymentsToAcquirePropertyPlantAndEquipment","PaymentsToAcquireProductiveAssets"]); capex=None if capex_raw is None else abs(capex_raw)
    assets,_=latest_annual(facts,["Assets"]); liabilities,_=latest_annual(facts,["Liabilities"]); equity,_=latest_annual(facts,["StockholdersEquity","StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
    cash,_=latest_annual(facts,["CashAndCashEquivalentsAtCarryingValue","CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
    debt_current,_=latest_annual(facts,["ShortTermBorrowings","ShortTermDebt","LongTermDebtCurrent"]); debt_long,_=latest_annual(facts,["LongTermDebtNoncurrent","LongTermDebt"])
    debt_vals=[v for v in [debt_current,debt_long] if v is not None]; debt=sum(debt_vals) if debt_vals else None
    shares,shares_prev=latest_annual(facts,["WeightedAverageNumberOfDilutedSharesOutstanding","WeightedAverageNumberOfSharesOutstandingDiluted"],("shares",)); shares_out,_=latest_annual(facts,["EntityCommonStockSharesOutstanding"],("shares",))
    rd,_=latest_annual(facts,["ResearchAndDevelopmentExpense"]); sga,_=latest_annual(facts,["SellingGeneralAndAdministrativeExpense"]); dda,_=latest_annual(facts,["DepreciationDepletionAndAmortization","DepreciationDepletionAndAmortizationExpense"]); interest,_=latest_annual(facts,["InterestExpenseNonOperating","InterestExpense"])
    fcf=None if ocf is None or capex is None else ocf-capex; ebitda=None if op_inc is None else op_inc+(dda or 0)
    return {"revenue":revenue,"revenue_growth_yoy":growth(revenue,rev_prev),"gross_profit":gross_profit,"gross_margin":div(gross_profit,revenue),"operating_income":op_inc,"operating_margin":div(op_inc,revenue),"net_income":net_inc,"net_margin":div(net_inc,revenue),"eps_diluted":eps,"eps_growth_yoy":growth(eps,eps_prev),"operating_cash_flow":ocf,"capex":capex,"free_cash_flow":fcf,"fcf_margin":div(fcf,revenue),"cfo_to_net_income":div(ocf,net_inc),"total_assets":assets,"total_liabilities":liabilities,"shareholders_equity":equity,"cash":cash,"total_debt":debt,"debt_to_equity":div(debt,equity),"cash_to_assets":div(cash,assets),"liabilities_to_assets":div(liabilities,assets),"roa":div(net_inc,assets),"roe":div(net_inc,equity),"rd_to_sales":div(rd,revenue),"sga_to_sales":div(sga,revenue),"share_change_yoy":growth(shares,shares_prev),"shares":shares_out or shares,"ebitda":ebitda,"interest_coverage":div(op_inc,interest)}


def factor_percentile(stocks:list[dict[str,Any]],key:str,higher_better:bool)->dict[str,float|None]:
    pairs=[(s["symbol"],s["values"].get(key)) for s in stocks]; pairs=[(a,b) for a,b in pairs if b is not None and math.isfinite(b)]
    if len(pairs)<3: return {s["symbol"]:None for s in stocks}
    ordered=sorted(v for _,v in pairs); out={}
    for sym,val in pairs:
        rank=sum(1 for x in ordered if x<=val)/len(ordered); out[sym]=100*(rank if higher_better else 1-rank)
    for s in stocks: out.setdefault(s["symbol"],None)
    return out

def avg(vals:list[float|None])->float|None:
    xs=[v for v in vals if v is not None and math.isfinite(v)]
    return None if not xs else sum(xs)/len(xs)


def compute_stock(symbol:str,name:str,cik:str,spy_close:list[float])->dict[str,Any]:
    h=yahoo(symbol); close,high,low,vol=h["close"],h["high"],h["low"],h["volume"]
    price=close[-1] if close else None; f=fundamentals(cik); shares=f.get("shares")
    market_cap=None if price is None or shares is None else price*shares; ev=None if market_cap is None else market_cap+(f.get("total_debt") or 0)-(f.get("cash") or 0)
    s50,s200=sma(close,50),sma(close,200); beta,corr=beta_corr(close,spy_close); high_52=max(close[-252:]) if len(close)>=252 else None; low_52=min(close[-252:]) if len(close)>=252 else None
    r20=log_returns(close,20); daily_mu=statistics.mean(r20) if len(r20)>=10 else None; daily_sd=statistics.stdev(r20) if len(r20)>=10 else None
    base_center=None if price is None or daily_mu is None else math.exp(math.log(price)+daily_mu*5)
    vals={"price":price,"market_cap":market_cap,"enterprise_value":ev,"avg_dollar_volume_20d":None if price is None or len(vol)<20 else sum(vol[-20:])/20*price,"return_1d":ret(close,1),"return_5d":ret(close,5),"return_20d":ret(close,20),"return_63d":ret(close,63),"return_126d":ret(close,126),"return_252d":ret(close,252),"relative_strength_63d":None if ret(close,63) is None or ret(spy_close,63) is None else ret(close,63)-ret(spy_close,63),"sma_50":s50,"sma_200":s200,"price_vs_50dma":None if price is None or s50 is None else price/s50-1,"price_vs_200dma":None if price is None or s200 is None else price/s200-1,"distance_52w_high":None if price is None or high_52 in (None,0) else price/high_52-1,"distance_52w_low":None if price is None or low_52 in (None,0) else price/low_52-1,"rsi_14":rsi(close),"realized_vol_20d":realized_vol(close,20),"realized_vol_60d":realized_vol(close,60),"beta_1y":beta,"correlation_spy_1y":corr,"max_drawdown_1y":max_drawdown(close),"downside_vol_60d":downside_vol(close),"atr_14_pct":atr_pct(high,low,close),"forecast_date":prediction_date(),"predicted_price":base_center,"prediction_low":None if base_center is None or daily_sd is None else math.exp(math.log(base_center)-daily_sd*math.sqrt(5)),"prediction_high":None if base_center is None or daily_sd is None else math.exp(math.log(base_center)+daily_sd*math.sqrt(5)),**f}
    vals["pe"]=div(price,vals.get("eps_diluted")); vals["ps"]=div(market_cap,vals.get("revenue")); vals["pb"]=div(market_cap,vals.get("shareholders_equity")); vals["p_fcf"]=div(market_cap,vals.get("free_cash_flow")); vals["ev_sales"]=div(ev,vals.get("revenue")); vals["ev_ebitda"]=div(ev,vals.get("ebitda"))
    return {"symbol":symbol,"name":name,"cik":cik,"values":vals,"links":{"yahoo_chart":yahoo_url(symbol),"yahoo_quote":f"https://finance.yahoo.com/quote/{requests.utils.quote(symbol,safe='')}","sec_companyfacts":sec_url(cik)}}


def add_analysis(stocks:list[dict[str,Any]])->None:
    groups={"value_score":[("pe",False),("ps",False),("pb",False),("p_fcf",False),("ev_sales",False),("ev_ebitda",False)],"quality_score":[("gross_margin",True),("operating_margin",True),("net_margin",True),("fcf_margin",True),("roa",True),("roe",True),("cfo_to_net_income",True),("debt_to_equity",False)],"growth_score":[("revenue_growth_yoy",True),("eps_growth_yoy",True),("return_252d",True),("share_change_yoy",False)],"momentum_score":[("return_20d",True),("return_63d",True),("return_126d",True),("return_252d",True),("relative_strength_63d",True),("price_vs_50dma",True),("price_vs_200dma",True)],"risk_score":[("realized_vol_20d",False),("realized_vol_60d",False),("beta_1y",False),("atr_14_pct",False),("max_drawdown_1y",True),("downside_vol_60d",False)]}
    scores={k:factor_percentile(stocks,k,hb) for pairs in groups.values() for k,hb in pairs}
    for s in stocks:
        sym=s["symbol"]; cat={g:avg([scores[k].get(sym) for k,_ in pairs]) for g,pairs in groups.items()}; overall=avg(list(cat.values()))
        s["category_scores"]={k:None if v is None else round(v,1) for k,v in cat.items()}; s["overall_score"]=None if overall is None else round(overall,1)
        v=s["values"]; tilt=0 if overall is None else (overall-50)/50*0.0025
        if v.get("predicted_price") is not None:
            m=math.exp(tilt*5); v["predicted_price"]*=m
            if v.get("prediction_low") is not None: v["prediction_low"]*=m
            if v.get("prediction_high") is not None: v["prediction_high"]*=m
        positives=[]; risks=[]
        checks=[("price_vs_200dma","200DMA trend",lambda x:x>0),("relative_strength_63d","relative strength",lambda x:x>0),("revenue_growth_yoy","revenue growth",lambda x:x>0),("fcf_margin","FCF margin",lambda x:x>0)]
        for key,label,cond in checks:
            val=v.get(key)
            if val is not None: (positives if cond(val) else risks).append(label)
        if v.get("debt_to_equity") is not None and v["debt_to_equity"]>2: risks.append("balance-sheet leverage")
        missing=sum(1 for key,*_ in FACTOR_CATALOG if v.get(key) is None)
        s["positives"]=positives[:4]; s["risks"]=risks[:4]; s["missing_count"]=missing
        s["analysis_text"]=f"{sym} has {len(FACTOR_CATALOG)-missing}/{len(FACTOR_CATALOG)} factors available. Current price is {display('price',v.get('price'))}. Predicted price center by {v.get('forecast_date')} is {display('predicted_price',v.get('predicted_price'))}. Positive checks: {', '.join(s['positives']) if s['positives'] else 'none shown'}. Risk checks: {', '.join(s['risks']) if s['risks'] else 'none shown'}."


def money(v:float|None)->str:
    if v is None: return "Unavailable"
    if abs(v)>=1e12: return f"${v/1e12:.2f}T"
    if abs(v)>=1e9: return f"${v/1e9:.2f}B"
    if abs(v)>=1e6: return f"${v/1e6:.2f}M"
    return f"${v:,.2f}"

def percent(v:float|None)->str: return "Unavailable" if v is None else f"{v*100:.1f}%"
def ratio(v:float|None)->str: return "Unavailable" if v is None else f"{v:.2f}"

def display(key:str,value:Any)->str:
    if value is None: return "Unavailable"
    if key=="forecast_date": return str(value)
    if key in {"price","predicted_price","prediction_low","prediction_high","market_cap","enterprise_value","avg_dollar_volume_20d","revenue","gross_profit","operating_income","net_income","operating_cash_flow","capex","free_cash_flow","total_assets","total_liabilities","shareholders_equity","cash","total_debt"}: return money(value)
    if "return" in key or "growth" in key or "margin" in key or key in {"price_vs_50dma","price_vs_200dma","distance_52w_high","distance_52w_low","realized_vol_20d","realized_vol_60d","correlation_spy_1y","max_drawdown_1y","downside_vol_60d","atr_14_pct","cash_to_assets","liabilities_to_assets","roa","roe","rd_to_sales","sga_to_sales","share_change_yoy"}: return percent(value)
    return ratio(value)

def factor_sources(source_type:str,links:dict[str,str])->list[dict[str,str]]:
    if source_type=="yahoo": return [{"label":"Yahoo chart JSON","url":links["yahoo_chart"]},{"label":"Yahoo quote","url":links["yahoo_quote"]}]
    if source_type=="sec": return [{"label":"SEC companyfacts JSON","url":links["sec_companyfacts"]}]
    return [{"label":"Yahoo chart JSON","url":links["yahoo_chart"]},{"label":"SEC companyfacts JSON","url":links["sec_companyfacts"]}]


def write_outputs()->None:
    DOCS.mkdir(parents=True,exist_ok=True); spy_close=yahoo("SPY")["close"]
    stocks=[compute_stock(sym,name,cik,spy_close) for sym,(name,cik) in STOCKS.items()]
    add_analysis(stocks); total=len(FACTOR_CATALOG)
    for s in stocks:
        factors=[]; available=0
        for key,label,category,source_type,definition in FACTOR_CATALOG:
            value=s["values"].get(key); ok=value is not None; available+=int(ok)
            factors.append({"key":key,"label":label,"category":category,"value":value,"display":display(key,value),"definition":definition,"available":ok,"source_type":source_type,"sources":factor_sources(source_type,s["links"])})
        s["factors"]=factors; s["available_factor_count"]=available; s["total_factor_count"]=total
        s["current_price"]=s["values"].get("price"); s["current_price_display"]=display("price",s["current_price"])
        s["predicted_price"]=s["values"].get("predicted_price"); s["predicted_price_display"]=display("predicted_price",s["predicted_price"]); s["prediction_date"]=prediction_date()
    stocks.sort(key=lambda x:x["symbol"])
    payload={"summary":{"name":"IvySets X-Theory Analysis","updated_at_london":now(),"timezone":TIMEZONE,"stock_count":len(stocks),"factor_count":total,"refresh_minutes":15},"stocks":stocks,"factor_catalog":[{"key":k,"label":l,"category":c,"source_type":s,"definition":d} for k,l,c,s,d in FACTOR_CATALOG],"literature":LITERATURE}
    (DOCS/"data.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    cols=["timestamp","symbol","stock_name","current_price","predicted_price","prediction_date","available_factors","total_factors","factors"]
    with (DOCS/"sentiment.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for s in stocks:
            factor_text=", ".join(f"{fac['label']}={fac['display']}" for fac in s["factors"])
            w.writerow({"timestamp":payload["summary"]["updated_at_london"],"symbol":s["symbol"],"stock_name":s["name"],"current_price":s["current_price_display"],"predicted_price":s["predicted_price_display"],"prediction_date":s["prediction_date"],"available_factors":s["available_factor_count"],"total_factors":s["total_factor_count"],"factors":factor_text})

if __name__=="__main__": write_outputs()
