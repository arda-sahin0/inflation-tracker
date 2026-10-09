"""
Map a shop's catalogue from its homepage link: aisles -> shelves -> leaf categories.

    python catalog.py https://www.migros.com.tr/

Writes catalog/migros.json and prints the tree with product counts. It reads one
page per aisle and per shelf (the leaf names come from the shelf page), so a full
crawl is roughly 150 requests. Run it when you want to (re)build sweeps.json, not daily.
"""
import argparse
import json
import sys
import time
from datetime import date
from urllib.parse import urlparse

from tracker import ROOT
from tracker.scrapers import a101, migros

OUT_DIR = ROOT / "catalog"
SKIP_AISLES = {"Elektronik", "Çiçek", "Evcil Hayvan", "Kitap, Kırtasiye, Oyuncak", "Ev, Yaşam", "Bebek"}
SLEEP_SECONDS = 1.0


def crawl_migros(skip: set[str], sleep: float = SLEEP_SECONDS, log=print) -> dict:
    aisles = []
    for aisle in migros.real_aisles(migros.top_level_categories()):
        if aisle["name"] in skip:
            log(f"skip  {aisle['name']}")
            continue
        time.sleep(sleep)
        info = migros.listing_page(shop_category=aisle["prettyName"])
        shelves = []
        for shelf in migros.child_categories(info):
            time.sleep(sleep)
            shelf_info = migros.listing_page(shop_category=shelf["prettyName"])
            leaves = [leaf for leaf in migros.child_categories(shelf_info)
                      if leaf["prettyName"] != shelf["prettyName"]]
            shelves.append({**shelf, "leaves": leaves})
            log(f"      {aisle['name']} / {shelf['name']}: {len(leaves)} leaves")
        aisles.append({"name": aisle["name"], "prettyName": aisle["prettyName"],
                       "count": int(info.get("hitCount", 0)), "shelves": shelves})
    return {"store": "migros", "crawled": date.today().isoformat(), "aisles": aisles}


def crawl_a101(skip: set[str], sleep: float = SLEEP_SECONDS, log=print) -> dict:
    """A101 numbers its aisles C01, C02, ... and one request returns an aisle with all its shelves."""
    aisles = []
    for aisle_id in a101.AISLE_IDS:
        time.sleep(sleep)
        try:
            aisle = a101.list_category(aisle_id)
        except Exception as e:
            log(f"      {aisle_id}: no aisle ({type(e).__name__})")
            continue
        if aisle.get("name") in skip:
            log(f"skip  {aisle['name']}")
            continue
        aisles.append({"name": aisle["name"], "prettyName": aisle_id,
                       "count": int(aisle.get("itemCount", 0)), "shelves": a101.shelves(aisle)})
        log(f"      {aisle_id} {aisle['name']}: {len(aisles[-1]['shelves'])} shelves")
    return {"store": "a101", "crawled": date.today().isoformat(), "aisles": aisles}


CRAWLERS = {"www.migros.com.tr": ("migros", crawl_migros), "www.a101.com.tr": ("a101", crawl_a101)}


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

    domain = urlparse(args.url if "//" in args.url else f"https://{args.url}").netloc.lower()
    if domain not in CRAWLERS:
        print(f"{domain}: no crawler for this shop yet (known: {', '.join(CRAWLERS)})")
        return 1

    store, crawl = CRAWLERS[domain]
    catalog = crawl(SKIP_AISLES - set(args.keep))
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{store}.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_tree(catalog)
    shelves = sum(len(a["shelves"]) for a in catalog["aisles"])
    leaves = sum(len(s["leaves"]) for a in catalog["aisles"] for s in a["shelves"])
    print(f"\n{len(catalog['aisles'])} aisles, {shelves} shelves, {leaves} leaf categories -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
