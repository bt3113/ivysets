from __future__ import annotations

import json

import update_data as base
from append_tickers import finalize_stock, write_csv

UK_REQUESTED_STOCKS = {
    "BCS": ("Barclays PLC", "0000312069"),
    "BTGOF": ("BT Group plc", "0000756620"),
    "LYG": ("Lloyds Banking Group plc", "0001160106"),
}


def main() -> None:
    data_path = base.DOCS / "data.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    existing_symbols = {stock["symbol"] for stock in payload.get("stocks", [])}
    spy_close = base.yahoo("SPY")["close"]
    stocks = payload.get("stocks", [])

    for symbol, (name, cik) in UK_REQUESTED_STOCKS.items():
        if symbol not in existing_symbols:
            stocks.append(base.compute_stock(symbol, name, cik, spy_close))

    base.add_analysis(stocks)
    total = len(base.FACTOR_CATALOG)
    for stock in stocks:
        finalize_stock(stock, total)

    stocks.sort(key=lambda item: item["symbol"])
    payload["stocks"] = stocks
    payload["summary"]["name"] = "IvySets X-Theory Analysis"
    payload["summary"]["updated_at_london"] = base.now()
    payload["summary"]["stock_count"] = len(stocks)
    payload["summary"]["factor_count"] = total
    payload["summary"]["refresh_minutes"] = 15

    data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(payload)


if __name__ == "__main__":
    main()
