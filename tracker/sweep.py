"""
Category sweeps: collect a whole shop category in a handful of requests.

A listing page carries ~35 products with their prices, so a category of 300
products costs ~9 requests instead of 300. Sweeps are defined in sweeps.json:

    {"category": "dairy_eggs", "store": "migros", "query": "süt",
     "match_category": "Süt", "min_products": 20, "exclude_skus": []}

`query` is what the shop searches for; `match_category` keeps only products
filed under that shop category, so a search for "süt" doesn't drag in oat drinks.
Swept products get the id "<store>-<sku>", which is stable for as long as the
shop keeps the product.
"""
import json
import time

from tracker import ROOT
from tracker.scrapers import migros

MAX_PAGES = 20
SLEEP_SECONDS = 1.0


def collect(pages: list[dict], rule: dict) -> list[dict]:
    """Price rows from already-fetched listing pages. Pure, so it is testable offline."""
    excluded = {str(sku).zfill(8) for sku in rule.get("exclude_skus", [])}
    rows, seen = [], set()
    for page in pages:
        for product in migros.usable_listing_products(page, rule):
            sku = product["sku"].zfill(8)
            if sku in seen or sku in excluded:
                continue
            seen.add(sku)
            row = migros.listing_row(product, rule["category"])
            row["group"] = rule.get("name", rule["query"])     # its own elementary group
            rows.append(row)
    return rows


def fetch_pages(rule: dict, max_pages: int = MAX_PAGES, sleep: float = SLEEP_SECONDS) -> list[dict]:
    store = rule.get("store", "migros")
    if store != "migros":
        raise ValueError(f"sweeps are only implemented for migros, not {store!r}")

    first = migros.search_page(rule["query"])
    pages = [first]
    total = min(int(first.get("pageCount", 1)), max_pages)
    if total > 1:
        page_param = migros.detect_page_param(rule["query"])
        for page in range(2, total + 1):
            time.sleep(sleep)
            pages.append(migros.search_page(rule["query"], page, page_param))
    return pages


def run(rule: dict) -> list[dict]:
    rows = collect(fetch_pages(rule), rule)
    minimum = rule.get("min_products", 0)
    if len(rows) < minimum:
        raise RuntimeError(f"sweep {rule['query']!r} returned {len(rows)} products, expected >= {minimum}")
    return rows


def load_rules() -> list[dict]:
    path = ROOT / "sweeps.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
