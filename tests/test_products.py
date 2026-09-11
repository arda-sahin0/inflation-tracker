import json

from tracker import ROOT
from tracker.scrapers import get_scraper
from tracker.scrapers.migros import to_sku

ALLOWED_CATEGORIES = {
    "bread_cereals", "meat", "dairy_eggs", "oils_fats", "fruit_nuts",
    "vegetables_pulses", "sugar_sweets", "other_food", "tea_coffee",
    "drinks", "household", "personal_care",
}


def load_products() -> list[dict]:
    return json.loads((ROOT / "products.json").read_text(encoding="utf-8"))


def test_ids_are_unique():
    ids = [p["id"] for p in load_products()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"Duplicate ids: {duplicates}"


def test_every_product_is_valid():
    for p in load_products():
        assert {"id", "category", "url"} <= p.keys(), f"Missing field in {p}"
        assert p["category"] in ALLOWED_CATEGORIES, f"{p['id']}: unknown category {p['category']!r}"
        get_scraper(p["url"])                  # no scraper handles this domain
        if "migros.com.tr" in p["url"]:
            to_sku(p["url"])                   # link has no valid SKU