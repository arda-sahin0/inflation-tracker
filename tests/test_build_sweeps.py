import json

import pytest

from build_sweeps import build
from tracker import ROOT
from tracker.sweep import check_rule

CATALOG = {"store": "migros", "crawled": "2026-10-09", "aisles": [
    {"name": "Süt, Kahvaltılık", "prettyName": "sut-kahvaltilik-c-4", "count": 1499, "shelves": [
        {"name": "Peynir", "prettyName": "peynir-c-6d", "count": 402, "leaves": [
            {"name": "Beyaz Peynir", "prettyName": "beyaz-peynir-c-40b", "count": 106}]},
        {"name": "Yoğurt", "prettyName": "yogurt-c-6e", "count": 138, "leaves": [
            {"name": "Sade Yoğurt", "prettyName": "sade-yogurt-c-411", "count": 35},
            {"name": "Kaymaklı Yoğurt", "prettyName": "kaymakli-yogurt-c-410", "count": 14},
            {"name": "Yoğurt Mayası", "prettyName": "yogurt-mayasi-c-415", "count": 4}]},
    ]},
]}


def test_a_whole_shelf_becomes_one_rule_on_its_category_page():
    rules = build(CATALOG, {"store": "migros", "shelves": [
        {"category": "dairy_eggs", "path": "Süt, Kahvaltılık/Peynir"}]})
    assert rules == [{
        "name": "peynir", "group": "Peynir", "category": "dairy_eggs", "store": "migros",
        "shop_category": "peynir-c-6d", "max_pages": 15, "min_products": 201,
    }]
    check_rule(rules[0])               # a category page is its own filter


def test_chosen_sub_shelves_share_one_group():
    rules = build(CATALOG, {"store": "migros", "shelves": [
        {"category": "dairy_eggs", "path": "Süt, Kahvaltılık/Yoğurt", "group": "Yoğurt",
         "leaves": ["Sade Yoğurt", "Kaymaklı Yoğurt"]}]})
    assert [r["shop_category"] for r in rules] == ["sade-yogurt-c-411", "kaymakli-yogurt-c-410"]
    assert {r["group"] for r in rules} == {"Yoğurt"}
    assert "yogurt-mayasi-c-415" not in {r["shop_category"] for r in rules}


def test_a_mapping_that_does_not_match_the_shop_is_refused_with_the_options():
    with pytest.raises(ValueError, match="shelves: Peynir, Yoğurt"):
        build(CATALOG, {"store": "migros", "shelves": [{"category": "dairy_eggs", "path": "Süt, Kahvaltılık/Süt"}]})
    with pytest.raises(ValueError, match="there are: Sade Yoğurt"):
        build(CATALOG, {"store": "migros", "shelves": [
            {"category": "dairy_eggs", "path": "Süt, Kahvaltılık/Yoğurt", "leaves": ["Ayran"]}]})


def test_mapping_the_same_shelf_twice_is_refused():
    entry = {"category": "dairy_eggs", "path": "Süt, Kahvaltılık/Peynir"}
    with pytest.raises(ValueError, match="mapped twice"):
        build(CATALOG, {"store": "migros", "shelves": [entry, entry]})


def test_the_real_mapping_builds_against_the_real_catalogue():
    catalog_file = ROOT / "catalog" / "migros.json"
    if not catalog_file.exists():
        pytest.skip("run catalog.py first")
    mapping = json.loads((ROOT / "shelf_map.json").read_text(encoding="utf-8"))
    rules = build(json.loads(catalog_file.read_text(encoding="utf-8")), mapping)
    divisions = json.loads((ROOT / "weights.json").read_text(encoding="utf-8"))["divisions"]
    every_category = {c for d in divisions.values() for c in d["categories"]}
    assert {r["category"] for r in rules} == every_category      # nothing left uncovered
