"""
Map a shop's catalogue from its homepage link: aisles -> shelves -> leaf categories.

    python catalog.py https://www.migros.com.tr/

Writes markets/<market>/catalog/<store>.json and prints the tree with product counts.
Run it when you want to rebuild the sweeps, not daily.
"""
import argparse
import json
import sys

from tracker import ROOT
from tracker.markets import locate


def print_tree(catalog: dict) -> None:
    for aisle in catalog["aisles"]:
        print(f"\n{aisle['name']}  ({aisle['count']})  {aisle['prettyName']}")
        for shelf in aisle["shelves"]:
            print(f"  {shelf['name']}  ({shelf['count']})  {shelf['prettyName']}")
            for leaf in shelf["leaves"]:
                print(f"      {leaf['name']}  ({leaf['count']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map a shop's catalogue from its homepage")
    parser.add_argument("url", help="the shop's homepage, e.g. https://www.migros.com.tr/")
    parser.add_argument("--keep", nargs="*", default=[], help="aisles to crawl even if skipped by default")
    args = parser.parse_args(argv)

    try:
        market, store = locate(args.url)
    except ValueError as e:
        print(e)
        return 1

    catalog = store.scraper.crawl(market.skip_aisles - set(args.keep))
    out = market.config / "catalog" / f"{store.key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_tree(catalog)
    shelves = sum(len(a["shelves"]) for a in catalog["aisles"])
    leaves = sum(len(s["leaves"]) for a in catalog["aisles"] for s in a["shelves"])
    print(f"\n{len(catalog['aisles'])} aisles, {shelves} shelves, {leaves} leaf categories -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
