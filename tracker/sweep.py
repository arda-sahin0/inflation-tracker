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
    leaf_map = rule.get("leaf_map")          # shop leaf -> index category, for whole-shelf rules
    name = rule.get("name") or rule.get("query") or rule.get("shop_category")
    rows, seen = [], set()
    for page in pages:
        for product in migros.usable_listing_products(page, rule):
            sku = product["sku"].zfill(8)
            if sku in seen or sku in excluded:
                continue
            if leaf_map is not None:
                leaf = (migros.category_names(product) or [""])[-1]
                category = leaf_map.get(leaf)
                if category is None:                 # a shelf we don't track (e.g. olives)
                    continue
            else:
                category = rule["category"]
            seen.add(sku)
            row = migros.listing_row(product, category)
            row["group"] = rule.get("group") or name   # its elementary group within the category
            rows.append(row)
    return rows


def fetch_pages(rule: dict, max_pages: int | None = None, sleep: float = SLEEP_SECONDS) -> list[dict]:
    max_pages = max_pages or int(rule.get("max_pages", MAX_PAGES))
    store = rule.get("store", "migros")
    if store != "migros":
        raise ValueError(f"sweeps are only implemented for migros, not {store!r}")

    where = {"query": rule.get("query"), "shop_category": rule.get("shop_category")}
    first = migros.listing_page(**where)
    pages = [first]
    total = min(int(first.get("pageCount", 1)), max_pages)
    if total > 1:
        page_param = migros.detect_page_param(**where)
        for page in range(2, total + 1):
            time.sleep(sleep)
            pages.append(migros.listing_page(**where, page=page, page_param=page_param))
    return pages


def check_rule(rule: dict) -> None:
    """A rule with no category filter would sweep up everything the query returns."""
    # a category page is its own filter; a search needs one
    if not (rule.get("shop_category") or rule.get("include_categories") or rule.get("match_category")
            or rule.get("leaf_map") or rule.get("allow_all")):
        raise ValueError(f"sweep {rule.get('name', rule.get('query'))!r} has no include_categories; "
                         f"run discover.py <query> --categories to find them")


def run(rule: dict) -> list[dict]:
    check_rule(rule)
    rows = collect(fetch_pages(rule), rule)
    minimum = rule.get("min_products", 0)
    if len(rows) < minimum:
        raise RuntimeError(f"sweep {rule['query']!r} returned {len(rows)} products, expected >= {minimum}")
    return rows


def load_rules(include_disabled: bool = False, path=None) -> list[dict]:
    """Rules from sweeps.json. A rule with "enabled": false is a draft and is skipped."""
    path = path or ROOT / "sweeps.json"
    rules = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return rules if include_disabled else [r for r in rules if r.get("enabled", True)]
