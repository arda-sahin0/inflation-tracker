import json

import pytest

from tracker import ROOT, sweep
from tracker.markets import MARKETS
from tracker.scrapers import migros

PAGE = json.loads((ROOT / "tests" / "fixtures" / "migros_search_sut.json")
                  .read_text(encoding="utf-8"))["data"]["searchInfo"]
RULE = {"name": "migros_sut", "group": "migros:Süt", "category": "dairy_eggs", "store": "migros",
        "shop_category": "sut-c-6c", "max_pages": 6, "min_products": 3}


def test_a_sweep_keeps_only_real_in_sale_products():
    rows = migros.collect([PAGE], RULE)
    assert len(rows) == 5
    assert all(row["in_stock"] for row in rows)
    assert {row["category"] for row in rows} == {"dairy_eggs"}
    assert {row["group"] for row in rows} == {"migros:Süt"}


def test_sweep_rows_have_everything_the_csv_needs():
    row = next(r for r in migros.collect([PAGE], RULE) if r["sku"] == "11011520")
    assert row["product_id"] == "migros-11011520"
    assert row["store"] == "migros"
    assert row["regular_price"] == 5275
    assert (row["unit"], row["net_amount"]) == ("PIECE", 1000)
    assert row["store_id"] == 20000000000607


def test_the_same_product_is_never_collected_twice():
    assert len(migros.collect([PAGE, PAGE], RULE)) == len(migros.collect([PAGE], RULE))


def test_shop_unit_wins_over_the_name():
    product = {"sku": "12345678", "name": "Beyaz Peynir 1 Kg", "status": "IN_SALE", "regularPrice": 44000,
               "unit": "GRAM", "prettyName": "beyaz-peynir-p-1", "category": {"name": "Süt"}}
    row = migros.listing_row(product, "dairy_eggs", "migros:Peynir")
    assert (row["unit"], row["net_amount"]) == ("GRAM", None)


def test_a_shelf_that_comes_back_too_small_fails_the_sweep():
    original = migros.sweep_rows
    migros.sweep_rows = lambda rule: migros.collect([PAGE], rule)
    try:
        assert len(sweep.run(RULE)) == 5
        with pytest.raises(RuntimeError, match="expected >= 50"):
            sweep.run({**RULE, "min_products": 50})
    finally:
        migros.sweep_rows = original


def test_every_live_rule_is_complete_and_unique():
    for market in MARKETS.values():
        divisions = json.loads((market.config / "weights.json").read_text(encoding="utf-8"))["divisions"]
        categories = {c for d in divisions.values() for c in d["categories"]}
        stores = {s.key for s in market.stores}
        rules = sweep.load_rules(market)
        for rule in rules:
            assert {"name", "group", "category", "store", "shop_category"} <= rule.keys(), rule
            assert rule["category"] in categories, rule["name"]
            assert rule["store"] in stores, rule["name"]
        names = [r["name"] for r in rules]
        assert len(names) == len(set(names)), "sweep names must be unique"


def test_listing_needs_exactly_one_target():
    for bad in ({}, {"query": "süt", "shop_category": "sut-c-6c"}):
        with pytest.raises(ValueError):
            migros.listing_page(**bad)
