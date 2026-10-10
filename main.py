import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from tracker import ROOT, sweep
from tracker.markets import MARKETS, Market, locate, select

FIELDS = ["date", "product_id", "category", "store", "sku", "name", "store_id",
          "regular_price", "sale_price", "loyalty_price", "unit", "net_amount", "in_stock", "group"]


def scrape_products(market: Market, today: str, rows: list[dict], failures: list[str], warnings: list[str]) -> None:
    """Add the hand-picked products in markets/<market>/products.json to rows."""
    path = market.config / "products.json"
    products = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    for product in products:
        try:
            _, store = locate(product["url"])
            row = store.scraper.scrape(product)
            row.update(date=today, product_id=product["id"], category=product["category"],
                       group=product.get("group", "picked"))
            rows.append(row)
            print(f"OK   {product['id']}: {row['regular_price'] / 100:.2f} {market.currency}")
            if row["store_id"] != store.store_id:
                warnings.append(f"{product['id']}: store_id {row['store_id']} (expected {store.store_id})")
        except Exception as e:
            failures.append(product["id"])
            print(f"FAIL {product['id']}: {e!r}")
        time.sleep(2)


def run_sweeps(rules: list[dict], today: str, rows: list[dict], failures: list[str]) -> None:
    """Add every sweep's products to rows. A failing sweep is reported and skipped, never fatal."""
    tracked = {(r["store"], r["sku"]) for r in rows}
    for rule in rules:
        try:
            swept = [r for r in sweep.run(rule) if (r["store"], r["sku"]) not in tracked]
        except Exception as e:
            failures.append(f"sweep:{rule['name']}")
            print(f"FAIL sweep {rule['name']}: {e!r}")
            continue
        for row in swept:
            row["date"] = today
            tracked.add((row["store"], row["sku"]))
        rows += swept
        print(f"SWEEP {rule['name']}: {len(swept)} products -> {rule['category']}")


def save(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {path.relative_to(ROOT)}")


def run_market(market: Market) -> bool:
    print(f"== {market.name}")
    today = datetime.now(market.timezone).date().isoformat()
    rows, failures, warnings = [], [], []
    scrape_products(market, today, rows, failures, warnings)
    run_sweeps(sweep.load_rules(market), today, rows, failures)
    if rows:
        save(rows, market.daily / f"{today}.csv")
    for w in warnings:
        print(f"WARNING {w}")
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
    return not (failures or warnings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect today's prices")
    parser.add_argument("--market", choices=MARKETS, help="only this market (default: all)")
    args = parser.parse_args(argv)
    results = [run_market(market) for market in select(args.market)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
