import json

from tracker import ROOT
from tracker.scrapers import migros
from tracker.sweep import collect

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
