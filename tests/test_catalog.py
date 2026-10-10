import json

import catalog
from tracker import ROOT
from tracker.scrapers import a101, migros

FIXTURES = ROOT / "tests" / "fixtures"
TOP = json.loads((FIXTURES / "migros_top_level.json").read_text(encoding="utf-8"))["data"]
AISLE = json.loads((FIXTURES / "migros_category_sut_kahvaltilik.json").read_text(encoding="utf-8"))["data"]["searchInfo"]


def test_promotions_and_brand_pages_are_not_aisles():
    names = [c["name"] for c in migros.real_aisles(TOP)]
    assert names == ["Meyve, Sebze", "Süt, Kahvaltılık", "Atıştırmalık", "Elektronik"]


def test_category_page_lists_the_next_level_down():
    shelves = migros.child_categories(AISLE)
    assert [s["name"] for s in shelves][:3] == ["Süt", "Peynir", "Yoğurt"]
    assert shelves[0] == {"name": "Süt", "prettyName": "sut-c-6c", "count": 140}
    assert migros.child_categories({"aggregationGroups": []}) == []


def test_crawl_walks_aisles_and_shelves_and_skips_what_it_should():
    shelf_pages = {
        "sut-c-6c": [("Günlük Süt", 40, "gunluk-sut-c-409"), ("Uzun Ömürlü Süt", 60, "uzun-omurlu-sut-c-40a"),
                     ("Bitkisel İçecek", 30, "bitkisel-icecek-c-40b")],
    }

    def fake_listing(query=None, shop_category=None, page=1, page_param="sayfa"):
        if shop_category == "sut-kahvaltilik-c-4":
            return {**AISLE, "aggregationGroups": [{"type": "CATEGORY", "aggregationInfos": [
                {"label": "Süt", "count": 140, "prettyName": "sut-c-6c"}]}]}
        leaves = shelf_pages.get(shop_category, [])
        return {"hitCount": 0, "aggregationGroups": [{"type": "CATEGORY", "aggregationInfos": [
            {"label": n, "count": c, "prettyName": p} for n, c, p in leaves]}]}

    originals = migros.top_level_categories, migros.listing_page
    migros.top_level_categories = lambda: TOP
    migros.listing_page = fake_listing
    try:
        result = migros.crawl(skip={"Elektronik", "Atıştırmalık", "Meyve, Sebze"}, sleep=0, log=lambda *_: None)
    finally:
        migros.top_level_categories, migros.listing_page = originals

    assert [a["name"] for a in result["aisles"]] == ["Süt, Kahvaltılık"]
    aisle = result["aisles"][0]
    assert aisle["count"] == 1501
    assert aisle["shelves"][0]["name"] == "Süt"
    assert [l["name"] for l in aisle["shelves"][0]["leaves"]] == ["Günlük Süt", "Uzun Ömürlü Süt", "Bitkisel İçecek"]


def test_an_unknown_shop_is_refused():
    assert catalog.main(["https://www.carrefoursa.com/"]) == 1


def test_a101_crawl_probes_numbered_aisles_and_skips_gaps():
    aisle = json.loads((FIXTURES / "a101_aisle_C05.json").read_text(encoding="utf-8"))

    def fake_list(aisle_id):
        if aisle_id == "C05":
            return aisle
        raise RuntimeError("no such aisle")

    original_list, original_ids = a101.list_category, a101.AISLE_IDS
    a101.list_category, a101.AISLE_IDS = fake_list, ["C04", "C05", "C06"]
    try:
        result = a101.crawl(skip=set(), sleep=0, log=lambda *_: None)
    finally:
        a101.list_category, a101.AISLE_IDS = original_list, original_ids
    assert [a["prettyName"] for a in result["aisles"]] == ["C05"]
    assert [s["name"] for s in result["aisles"][0]["shelves"]] == ["Süt", "Yumurta"]
