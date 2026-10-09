"""
Turn the crawled catalogue plus your shelf mapping into sweeps.json.

    python catalog.py https://www.migros.com.tr/    # 1. map each shop (now and then)
    python catalog.py https://www.a101.com.tr/
    python build_sweeps.py                          # 2. rebuild sweeps.json from shelf_maps/*.json

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
SPLIT_MIN_SHARE = 0.15  # ...but a rule that takes only part of a shelf by name gets a lower bar


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
    """One rule per shop shelf. Groups are per store ("migros:Peynir", "a101:Peynir"), so each
    chain's cheese is one elementary group and the two chains count equally within a category."""
    count = int(node.get("count", 0))
    label = node["prettyName"].rsplit("-c-", 1)[0] if store == "migros" else node["name"]
    return {
        "name": f"{store}_{slug(label)}",
        "group": f"{store}:{group}",
        "category": category,
        "store": store,
        "shop_category": node["prettyName"],
        "max_pages": max(1, math.ceil(count / PAGE_SIZE) + 1) if store == "migros" else 1,
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
            rule = rule_for(shelf, entry["category"], group, mapping["store"])
            for key in ("name", "name_pattern", "exclude_pattern"):    # one shelf split by product name
                if key in entry:
                    rule[key] = entry[key] if key != "name" else f"{mapping['store']}_{entry['name']}"
            if "name_pattern" in entry or "exclude_pattern" in entry:
                # the crawl only knows the whole shelf's count, not each part's
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
            rules.append(rule_for(leaves[name], entry["category"], group, mapping["store"]))
    if problems:
        raise ValueError("shelf_map.json does not match the catalogue:\n  " + "\n  ".join(problems))
    names = [r["name"] for r in rules]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"the same shelf is mapped twice: {', '.join(sorted(duplicates))}")
    return rules


def main() -> int:
    rules = []
    for map_file in sorted((ROOT / "shelf_maps").glob("*.json")):
        mapping = json.loads(map_file.read_text(encoding="utf-8"))
        catalog_file = ROOT / "catalog" / f"{mapping['store']}.json"
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
    (ROOT / "sweeps.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(rules)} rules -> sweeps.json\n")
    print(f"{'category':<18} {'groups':>6} {'products':>9} {'requests':>9}")
    for category in sorted({r["category"] for r in rules}):
        mine = [r for r in rules if r["category"] == category]
        products = sum(r["min_products"] for r in mine) * 2
        requests_ = sum(r["max_pages"] for r in mine if r["store"] == "migros") \
            + len({r["shop_category"][:3] for r in mine if r["store"] == "a101"})
        print(f"{category:<18} {len({r['group'] for r in mine}):>6} {products:>9} {requests_:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
