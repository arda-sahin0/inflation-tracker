"""
Turn the crawled catalogue plus your shelf mapping into sweeps.json.

    python catalog.py https://www.migros.com.tr/    # 1. map the shop (now and then)
    python build_sweeps.py                          # 2. rebuild the sweep rules from shelf_map.json

Each mapped shelf (or sub-shelf) becomes one rule that reads that category page,
so no search terms and no name matching are involved: the page is the filter.
"""
import json
import math
import re
import sys
import unicodedata

from tracker import ROOT

PAGE_SIZE = 30          # Migros shows ~30-36 products per page; err on the side of one page more
MIN_SHARE = 0.5         # a rule fails if it returns less than half of what the crawl saw


def slug(text: str) -> str:
    for a, b in (("ı", "i"), ("İ", "i"), ("ş", "s"), ("Ş", "s"), ("ğ", "g"), ("Ğ", "g"),
                 ("ç", "c"), ("Ç", "c"), ("ö", "o"), ("Ö", "o"), ("ü", "u"), ("Ü", "u")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


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
    count = int(node.get("count", 0))
    return {
        "name": slug(node["prettyName"].rsplit("-c-", 1)[0]),
        "group": group,
        "category": category,
        "store": store,
        "shop_category": node["prettyName"],
        "max_pages": max(1, math.ceil(count / PAGE_SIZE) + 1),
        "min_products": max(1, int(count * MIN_SHARE)),
    }


def build(catalog: dict, mapping: dict) -> list[dict]:
    rules, problems = [], []
    for entry in mapping["shelves"]:
        try:
            shelf = find_shelf(catalog, entry["path"])
        except KeyError as e:
            problems.append(str(e))
            continue
        group = entry.get("group", shelf["name"])
        if not entry.get("leaves"):
            rules.append(rule_for(shelf, entry["category"], group, mapping["store"]))
            continue
        leaves = {leaf["name"]: leaf for leaf in shelf["leaves"]}
        for name in entry["leaves"]:
            if name not in leaves:
                problems.append(f"{entry['path']}: no sub-shelf {name!r}; there are: {', '.join(leaves)}")
                continue
            rules.append(rule_for(leaves[name], entry["category"], group, mapping["store"]))
    if problems:
        raise ValueError("shelf_map.json does not match the catalogue:\n  " + "\n  ".join(problems))
    names = [r["name"] for r in rules]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"the same shelf is mapped twice: {', '.join(sorted(duplicates))}")
    return rules


def main() -> int:
    mapping = json.loads((ROOT / "shelf_map.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "catalog" / f"{mapping['store']}.json").read_text(encoding="utf-8"))
    try:
        rules = build(catalog, mapping)
    except ValueError as e:
        print(e)
        return 1
    (ROOT / "sweeps.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{len(rules)} rules -> sweeps.json (catalogue crawled {catalog['crawled']})\n")
    print(f"{'category':<18} {'groups':>6} {'products':>9} {'pages':>6}")
    for category in sorted({r["category"] for r in rules}):
        mine = [r for r in rules if r["category"] == category]
        products = sum(r["min_products"] for r in mine) * 2
        print(f"{category:<18} {len({r['group'] for r in mine}):>6} {products:>9} {sum(r['max_pages'] for r in mine):>6}")
    pages = sum(r["max_pages"] for r in rules)
    print(f"\nat most {pages} page requests a day (~{pages * 2 // 60} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
