import json

from tracker import ROOT
from tracker.scrapers import migros
import pytest

from tracker.sweep import check_rule, collect, load_rules

PAGE = json.loads((ROOT / "tests" / "fixtures" / "migros_search_sut.json")
                  .read_text(encoding="utf-8"))["data"]["searchInfo"]
RULE = {"category": "dairy_eggs", "query": "süt", "match_category": "Süt"}


def test_sweep_keeps_only_real_in_sale_products():
    rows = collect([PAGE], RULE)
    assert len(rows) == 5                                   # 8 items − 2 ads − 1 delisted
    assert all(row["in_stock"] for row in rows)
    assert all(row["category"] == "dairy_eggs" for row in rows)


def test_sweep_rows_have_everything_the_csv_needs():
    row = next(r for r in collect([PAGE], RULE) if r["sku"] == "11011520")
    assert row["product_id"] == "migros-11011520"           # stable id, no hand-written entry
    assert row["store"] == "migros"
    assert row["regular_price"] == 5275
    assert (row["unit"], row["net_amount"]) == ("PIECE", 1000)   # size read from the name
    assert row["store_id"] == 20000000000607


def test_the_same_product_is_never_collected_twice():
    assert len(collect([PAGE, PAGE], RULE)) == len(collect([PAGE], RULE))


def test_excluded_skus_stay_out():
    rows = collect([PAGE], {**RULE, "exclude_skus": ["11011520"]})
    assert "11011520" not in {r["sku"] for r in rows}


def test_a_foreign_shop_category_is_filtered_out():
    foreign = {"storeProductInfos": [
        {"sku": "99999999", "name": "Yulaf İçeceği 1 L", "status": "IN_SALE", "regularPrice": 100,
         "prettyName": "x-p-1", "category": {"name": "Bitkisel İçecek"},
         "categoryAscendants": [{"name": "Kahvaltılık"}]},
    ]}
    assert collect([foreign], RULE) == []
    assert len(collect([foreign], {**RULE, "match_category": None})) == 1


def test_shop_unit_wins_over_the_name():
    page = {"storeProductInfos": [
        {"sku": "12345678", "name": "Beyaz Peynir 1 Kg", "status": "IN_SALE", "regularPrice": 44000,
         "unit": "GRAM", "prettyName": "beyaz-peynir-p-1", "category": {"name": "Süt"}},
    ]}
    row = migros.listing_row(page["storeProductInfos"][0], "dairy_eggs")
    assert (row["unit"], row["net_amount"]) == ("GRAM", None)


PLANT_DRINK = {"sku": "11019914", "name": "Nilky Yulaflı İçecek 1 L", "status": "IN_SALE",
               "regularPrice": 17995, "prettyName": "nilky-yulafli-icecek-1-l-p-1",
               "category": {"name": "Bitkisel İçecek"},
               "categoryAscendants": [{"name": "Süt"}, {"name": "Süt, Kahvaltılık"}]}


def test_leaf_category_filter_keeps_plant_drinks_out_of_milk():
    """A search for "süt" returns oat and almond drinks filed under the Süt branch."""
    page = {"storeProductInfos": PAGE["storeProductInfos"] + [PLANT_DRINK]}
    loose = collect([page], {**RULE, "match_category": "Süt"})
    strict = collect([page], {"category": "dairy_eggs", "query": "süt",
                              "include_categories": ["Günlük Süt", "Uzun Ömürlü Süt"]})
    assert "11019914" in {r["sku"] for r in loose}       # the old, too-wide rule
    assert "11019914" not in {r["sku"] for r in strict}
    assert len(strict) == 5


def test_excluded_shop_categories_are_dropped():
    page = {"storeProductInfos": [PLANT_DRINK]}
    rule = {"category": "dairy_eggs", "query": "süt", "exclude_categories": ["Bitkisel İçecek"]}
    assert collect([page], rule) == []


def test_swept_rows_carry_their_group_name():
    rows = collect([PAGE], {**RULE, "name": "milk"})
    assert {r["group"] for r in rows} == {"milk"}
    assert {r["group"] for r in collect([PAGE], RULE)} == {"süt"}   # falls back to the query


def test_a_rule_without_a_category_filter_is_refused():
    with pytest.raises(ValueError, match="include_categories"):
        check_rule({"name": "everything", "query": "süt", "category": "dairy_eggs"})
    check_rule({"query": "süt", "include_categories": ["Günlük Süt"]})      # fine
    check_rule({"query": "süt", "allow_all": True})                         # deliberate


def test_draft_rules_do_not_run(tmp_path):
    config = tmp_path / "sweeps.json"
    config.write_text(json.dumps([
        {"name": "milk", "query": "süt", "category": "dairy_eggs", "include_categories": ["Günlük Süt"]},
        {"name": "cheese", "query": "peynir", "category": "dairy_eggs", "include_categories": [], "enabled": False},
    ]), encoding="utf-8")
    assert [r["name"] for r in load_rules(path=config)] == ["milk"]
    assert [r["name"] for r in load_rules(include_disabled=True, path=config)] == ["milk", "cheese"]


def test_every_live_rule_is_configured():
    divisions = json.loads((ROOT / "weights.json").read_text(encoding="utf-8"))["divisions"]
    ALLOWED_CATEGORIES = {c for d in divisions.values() for c in d["categories"]}
    for rule in load_rules():
        check_rule(rule)                                  # raises if a rule has no category filter
        assert rule["category"] in ALLOWED_CATEGORIES, rule["name"]
    names = [r["name"] for r in load_rules(include_disabled=True)]
    assert len(names) == len(set(names)), "sweep names must be unique (they are the group ids)"


def test_a_whole_shelf_rule_sorts_products_by_leaf_into_index_categories():
    page = {"storeProductInfos": PAGE["storeProductInfos"] + [PLANT_DRINK]}
    rule = {"name": "milk_shelf", "shop_category": "sut-c-6c",
            "leaf_map": {"Uzun Ömürlü Süt": "dairy_eggs"}}       # plant drinks: not mapped, so left out
    rows = collect([page], rule)
    assert {r["category"] for r in rows} == {"dairy_eggs"}
    assert "11019914" not in {r["sku"] for r in rows}
    assert {r["group"] for r in rows} == {"milk_shelf"}
    check_rule(rule)                                             # a leaf_map counts as a category filter


def test_listing_needs_exactly_one_target():
    for bad in ({}, {"query": "süt", "shop_category": "sut-c-6c"}):
        with pytest.raises(ValueError):
            migros.listing_page(**bad)
