from __future__ import annotations

import csv
import json

import update_data as base

EXTRA_STOCKS = {
    "OSCR": ("Oscar Health, Inc.", "0001568651"),
    "CRDO": ("Credo Technology Group Holding Ltd", "0001807794"),
    "APP": ("AppLovin Corporation", "0001751008"),
    "NBIS": ("Nebius Group N.V.", "0001513845"),
    "ZETA": ("Zeta Global Holdings Corp.", "0001851003"),
    "AAOI": ("Applied Optoelectronics, Inc.", "0001158114"),
    "DOCN": ("DigitalOcean Holdings, Inc.", "0001582961"),
    "LITE": ("Lumentum Holdings Inc.", "0001633978"),
    "SNOW": ("Snowflake Inc.", "0001640147"),
    "LUNR": ("Intuitive Machines, Inc.", "0001844452"),
}


def finalize_stock(stock: dict, total: int) -> None:
    factors = []
    available = 0
    for key, label, category, source_type, definition in base.FACTOR_CATALOG:
        value = stock["values"].get(key)
        ok = value is not None
        available += int(ok)
        factors.append({
            "key": key,
            "label": label,
            "category": category,
            "value": value,
            "display": base.display(key, value),
            "definition": definition,
            "available": ok,
            "source_type": source_type,
            "sources": base.factor_sources(source_type, stock["links"]),
        })
    stock["factors"] = factors
    stock["available_factor_count"] = available
    stock["total_factor_count"] = total
    stock["current_price"] = stock["values"].get("price")
    stock["current_price_display"] = base.display("price", stock["current_price"])
    stock["predicted_price"] = stock["values"].get("predicted_price")
    stock["predicted_price_display"] = base.display("predicted_price", stock["predicted_price"])
    stock["prediction_date"] = base.prediction_date()


def write_csv(payload: dict) -> None:
    cols = [
        "timestamp",
        "symbol",
        "stock_name",
        "current_price",
        "predicted_price",
        "prediction_date",
        "available_factors",
        "total_factors",
        "factors",
    ]
    with (base.DOCS / "sentiment.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        for stock in payload["stocks"]:
            factor_text = ", ".join(f"{factor['label']}={factor['display']}" for factor in stock["factors"])
            writer.writerow({
                "timestamp": payload["summary"]["updated_at_london"],
                "symbol": stock["symbol"],
                "stock_name": stock["name"],
                "current_price": stock["current_price_display"],
                "predicted_price": stock["predicted_price_display"],
                "prediction_date": stock["prediction_date"],
                "available_factors": stock["available_factor_count"],
                "total_factors": stock["total_factor_count"],
                "factors": factor_text,
            })


def main() -> None:
    data_path = base.DOCS / "data.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    existing_symbols = {stock["symbol"] for stock in payload.get("stocks", [])}
    spy_close = base.yahoo("SPY")["close"]
    stocks = payload.get("stocks", [])

    for symbol, (name, cik) in EXTRA_STOCKS.items():
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
    payload["factor_catalog"] = [
        {"key": k, "label": l, "category": c, "source_type": s, "definition": d}
        for k, l, c, s, d in base.FACTOR_CATALOG
    ]

    data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(payload)


if __name__ == "__main__":
    main()
