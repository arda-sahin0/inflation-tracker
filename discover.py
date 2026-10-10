"""
Find products in Migros's catalogue and add them to products.json, or dry-run the sweeps.

    python discover.py süt                                  # list what the shop has
    python discover.py süt --pages 3                        # more result pages
    python discover.py süt --add 11011520 --category dairy_eggs
    python discover.py --replace sut-sek-1l                 # find a stand-in for a dead product
    python discover.py --check-sweeps                       # what would every sweep collect?

Nothing is added without --add: a search result is a suggestion, not a basket change.
"""
import argparse
import json
import sys

import index
from tracker import sweep
from tracker.markets import MARKETS, STORES, market_of, select
from tracker.naming import parse_size, suggest_id
from tracker.scrapers import migros

MARKET = market_of("migros")
PRODUCTS = MARKET.config / "products.json"


def candidates(search_info: dict, include_sponsored: bool = False) -> list[dict]:
    """Turn a search response into basket candidates, ads and dead products removed."""
    rows = []
    for product in search_info.get("storeProductInfos", []):
        if product.get("sponsored") and not include_sponsored:
            continue
        if product.get("status") != "IN_SALE":
            continue
        unit, net_amount = parse_size(product["name"])
        price = product.get("regularPrice")
        rows.append({
            "sku": product["sku"],
            "name": product["name"],
            "unit": unit,
            "net_amount": net_amount,
            "price": price,
            "shown_price": product.get("shownPrice"),
            "on_offer": bool(product.get("discountRate")),
            "category_path": " / ".join(migros.category_names(product)),
            "url": "https://www.migros.com.tr/" + product["prettyName"],
            "per_kg": round(price * 1000 / net_amount) if (price and net_amount) else price,
        })
    return rows


def load_basket() -> list[dict]:
    return json.loads(PRODUCTS.read_text(encoding="utf-8"))


def save_basket(basket: list[dict]) -> None:
    PRODUCTS.write_text(json.dumps(basket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_to_basket(basket: list[dict], entry: dict) -> list[dict]:
    """Append one product. Refuses a repeated id or a product that is already tracked."""
    if any(p["id"] == entry["id"] for p in basket):
        raise ValueError(f"id {entry['id']!r} is already in products.json")
    if any(migros.to_sku(p["url"]) == migros.to_sku(entry["url"])
           for p in basket if "migros.com.tr" in p["url"]):
        raise ValueError(f"{entry['url']} is already tracked under another id")
    return basket + [entry]


def build_entry(dto: dict, category: str, product_id: str | None = None) -> dict:
    """products.json entry for a Migros product (the scraper reads name and size from the API)."""
    return {
        "id": product_id or suggest_id(dto["name"], "migros"),
        "category": category,
        "url": "https://www.migros.com.tr/" + dto["prettyName"],
    }


def print_table(rows: list[dict], basket: list[dict]) -> None:
    tracked = {migros.to_sku(p["url"]) for p in basket if "migros.com.tr" in p["url"]}
    print(f"{'sku':<10} {'price':>9} {'per kg/L':>9}  {'size':<12} {'name':<46} category")
    for row in rows:
        mark = "*" if row["sku"].zfill(8) in tracked else " "
        size = "per kg" if row["unit"] == "GRAM" else (f"{row['net_amount']:g}" if row["net_amount"] else "—")
        offer = " (offer)" if row["on_offer"] else ""
        print(f"{mark}{row['sku']:<9} {row['price'] / 100:>9.2f} "
              f"{row['per_kg'] / 100:>9.2f}  {size:<12} {row['name'][:46]:<46} {row['category_path']}{offer}")
    print("\n* = already in your basket. Add one with:  --add <sku> --category <category>")


def check_sweeps(market_key: str | None) -> int:
    """Dry-run every rule on its first page. Writes nothing."""
    problems = 0
    for market in select(market_key):
        print(f"== {market.name}")
        for rule in sweep.load_rules(market):
            name = rule["name"]
            try:
                rows = STORES[rule["store"]].scraper.sweep_rows({**rule, "max_pages": 1})
                print(f"{name:<24} {len(rows):>4} products on the first page -> {rule['category']}")
                for row in rows[:3]:
                    print(f"{'':<24}   · {row['name'][:56]}")
                if not rows:
                    problems += 1
                    print(f"{'':<24}   nothing on this shelf — has the shop moved it? Run catalog.py again")
            except Exception as e:
                problems += 1
                print(f"{name:<24} FAILED: {e!r}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search Migros and add products to the basket")
    parser.add_argument("query", nargs="?", help="what to search for, e.g. süt")
    parser.add_argument("--pages", type=int, default=1, help="how many result pages to read")
    parser.add_argument("--add", metavar="SKU", help="add this product to products.json")
    parser.add_argument("--category", help="category for --add (must exist in weights.json)")
    parser.add_argument("--id", help="override the generated product id")
    parser.add_argument("--replace", metavar="PRODUCT_ID", help="find a stand-in for a tracked product")
    parser.add_argument("--include-sponsored", action="store_true", help="also show advertised results")
    parser.add_argument("--check-sweeps", action="store_true", help="dry-run every sweep: what would each collect?")
    parser.add_argument("--market", choices=MARKETS, help="with --check-sweeps: only this market")
    args = parser.parse_args(argv)

    if args.check_sweeps:
        return check_sweeps(args.market)

    basket = load_basket()

    if args.replace:
        entry = next((p for p in basket if p["id"] == args.replace), None)
        if entry is None:
            print(f"{args.replace!r} is not in products.json")
            return 1
        detail = migros.fetch_product(migros.to_sku(entry["url"]))
        args.query = detail["name"]
        print(f"Looking for something like: {detail['name']}  (category {entry['category']})\n")

    if args.add:
        if not args.category:
            print("--add needs --category")
            return 1
        categories = index.load_weights(index.load_config(MARKET))
        if args.category not in categories:
            print(f"unknown category {args.category!r}; known: {', '.join(sorted(categories))}")
            return 1
        detail = migros.fetch_product(args.add.zfill(8))
        entry = build_entry(detail, args.category, args.id)
        try:
            basket = add_to_basket(basket, entry)
        except ValueError as e:
            print(f"not added: {e}")
            return 1
        save_basket(basket)
        unit, net = parse_size(detail["name"])
        print(f"Added {entry['id']}  ({detail['name']}, {detail['regularPrice'] / 100:.2f} {MARKET.currency}, "
              f"{unit.lower()}{'' if net is None else f' {net:g}'})")
        print(f"products.json now has {len(basket)} products. Commit it and the next run picks it up.")
        return 0

    if not args.query:
        parser.print_help()
        return 1

    page_param = migros.detect_page_param(query=args.query) if args.pages > 1 else "sayfa"
    rows, info = [], None
    for page in range(1, args.pages + 1):
        info = migros.listing_page(query=args.query, page=page, page_param=page_param)
        rows += candidates(info, args.include_sponsored)
    print(f"{info.get('hitCount', '?')} hits, {info.get('pageCount', '?')} pages; "
          f"showing {len(rows)} after dropping ads and out-of-sale items\n")
    print_table(rows, basket)
    return 0


if __name__ == "__main__":
    sys.exit(main())
