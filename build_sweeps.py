"""
Turn each market's crawled catalogues plus its shelf maps into its sweeps.json.

    python catalog.py https://www.migros.com.tr/    # 1. map each shop (now and then)
    python build_sweeps.py                          # 2. rebuild markets/<market>/sweeps.json

Each mapped shelf (or sub-shelf) becomes one rule that reads that category page,
so no search terms and no name matching are involved: the page is the filter.
"""
import argparse
import json
import sys

from tracker.markets import MARKETS, STORES, Market, select
from tracker.naming import slugify

MIN_SHARE = 0.5
SPLIT_MIN_SHARE = 0.15


def find_shelf(catalog: dict, path: str) -> dict:
    aisle_name, _, shelf_name = path.partition("/")
    for aisle in catalog["aisles"]:
        if aisle["name"] == aisle_name:
            for shelf in aisle["shelves"]:
                if shelf["name"] == shelf_name:
                    return shelf
            known = ", ".join(s["name"] for s in aisle["shelves"])
            raise KeyError(f"no shelf {shelf_name!r} in {aisle_name!r}; shelves: {known}")
    raise KeyError(f"no aisle {aisle_name!r}; aisles: {', '.join(a['name'] for a in catalog['aisles'])}")


def rule_for(node: dict, category: str, group: str, store: str) -> dict:
    """One rule per shop shelf. Groups are per store ("migros:Peynir", "a101:Peynir"), so each
    chain's cheese is one elementary group and the chains count equally within a category."""
    scraper = STORES[store].scraper
    count = int(node.get("count", 0))
    return {
        "name": f"{store}_{slugify(scraper.shelf_label(node)).replace('-', '_')}",
        "group": f"{store}:{group}",
        "category": category,
        "store": store,
        "shop_category": node["prettyName"],
        "max_pages": scraper.pages_for(count),
        "min_products": max(1, int(count * MIN_SHARE)),
    }


def build(catalog: dict, mapping: dict) -> list[dict]:
    store = mapping["store"]
    rules, problems = [], []
    for entry in mapping["shelves"]:
        try:
            shelf = find_shelf(catalog, entry["path"])
        except KeyError as e:
            problems.append(str(e))
            continue
        group = entry.get("group", shelf["name"])
        if not entry.get("leaves"):
            rule = rule_for(shelf, entry["category"], group, store)
            if "name" in entry:
                rule["name"] = f"{store}_{entry['name']}"
            for key in ("name_pattern", "exclude_pattern"):
                if key in entry:
                    rule[key] = entry[key]
                    rule["min_products"] = max(1, int(int(shelf.get("count", 0)) * SPLIT_MIN_SHARE))
            if "min_products" in entry:
                rule["min_products"] = entry["min_products"]
            rules.append(rule)
            continue
        leaves = {leaf["name"]: leaf for leaf in shelf["leaves"]}
        for name in entry["leaves"]:
            if name not in leaves:
                problems.append(f"{entry['path']}: no sub-shelf {name!r}; there are: {', '.join(leaves)}")
                continue
            rules.append(rule_for(leaves[name], entry["category"], group, store))
    if problems:
        raise ValueError("the shelf map does not match the catalogue:\n  " + "\n  ".join(problems))
    names = [r["name"] for r in rules]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"the same shelf is mapped twice: {', '.join(sorted(duplicates))}")
    return rules


def build_market(market: Market) -> int:
    print(f"== {market.name}")
    rules = []
    for map_file in sorted((market.config / "shelf_maps").glob("*.json")):
        mapping = json.loads(map_file.read_text(encoding="utf-8"))
        catalog_file = market.config / "catalog" / f"{mapping['store']}.json"
        if not catalog_file.exists():
            print(f"{mapping['store']}: no catalogue yet, skipped — run catalog.py on its homepage")
            continue
        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
        try:
            store_rules = build(catalog, mapping)
        except ValueError as e:
            print(f"{mapping['store']}: {e}")
            return 1
        print(f"{mapping['store']}: {len(store_rules)} rules (catalogue crawled {catalog['crawled']})")
        rules += store_rules
    out = market.config / "sweeps.json"
    out.write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(rules)} rules -> {out.name}\n")
    print(f"{'category':<18} {'groups':>6} {'rules':>6}")
    for category in sorted({r["category"] for r in rules}):
        mine = [r for r in rules if r["category"] == category]
        print(f"{category:<18} {len({r['group'] for r in mine}):>6} {len(mine):>6}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the sweep rules from the shelf maps")
    parser.add_argument("--market", choices=MARKETS, help="only this market (default: all)")
    args = parser.parse_args(argv)
    return max(build_market(market) for market in select(args.market))


if __name__ == "__main__":
    sys.exit(main())
