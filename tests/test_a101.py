import json

import pytest

from tracker import ROOT
from tracker.scrapers.a101 import parse, to_sku

FIXTURES = ROOT / "tests" / "fixtures"
PRODUCT = {
    "id": "sut-pinar-1l-a101",
    "name": "Pınar %1 Yağlı Süt 1 L",
    "unit": "PIECE",
    "net_amount": 1000,
    "url": "https://www.a101.com.tr/kapida/sut-urunleri-kahvaltilik/pinar-1-yagli-sut_p-12003704",
}


def load_product(name: str = "a101_12003704.json") -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["product"]


def test_to_sku():
    assert to_sku(PRODUCT["url"]) == "12003704"
    assert to_sku("  " + PRODUCT["url"] + "/  ") == "12003704"
    assert to_sku("12003704") == "12003704"


@pytest.mark.parametrize("bad", [
    "https://www.a101.com.tr/kapida/firindan/ekmek-200-g",
    "not a url",
    "",
])
def test_to_sku_rejects_garbage(bad):
    with pytest.raises(ValueError):
        to_sku(bad)


def test_parse():
    row = parse(load_product(), PRODUCT)
    assert row["sku"] == "12003704"
    assert row["name"] == "Pınar %1 Yağlı Süt 1 L"
    assert row["store_id"] == "VS032"
    assert row["regular_price"] == 6500
    assert row["sale_price"] == 6500
    assert row["loyalty_price"] is None
    assert row["unit"] == "PIECE"
    assert row["net_amount"] == 1000
    assert row["in_stock"] is True


def test_discounted_price_is_separate():
    raw = load_product() | {"price": {"normal": 6500, "discounted": 5900}}
    row = parse(raw, PRODUCT)
    assert row["regular_price"] == 6500
    assert row["sale_price"] == 5900


def test_out_of_stock():
    raw = load_product() | {"stock": "OUT", "quantity": 0}
    assert parse(raw, PRODUCT)["in_stock"] is False


def test_weighed_product_has_no_size():
    product = {"id": "domates-a101", "name": "Domates kg", "unit": "GRAM",
               "url": "https://www.a101.com.tr/kapida/meyve-sebze/domates-kg_p-20000761"}
    row = parse(load_product(), product)
    assert row["unit"] == "GRAM"
    assert row["net_amount"] is None

AISLE = json.loads((FIXTURES / "a101_aisle_C05.json").read_text(encoding="utf-8"))


def sweep(rule):
    from tracker.scrapers import a101
    a101._aisles["C05"] = AISLE
    try:
        return a101.sweep_rows(rule)
    finally:
        a101._aisles.pop("C05", None)


def test_listing_rows_use_a101s_own_net_weight_and_shelf_price():
    rows = sweep({"name": "a101_sut", "group": "a101:Süt", "category": "dairy_eggs", "store": "a101",
                  "shop_category": "C0502"})
    torku = next(r for r in rows if r["sku"] == "12003241")
    assert torku["name"] == "Torku %0,5 Yağlı Süt 4x1 L"
    assert torku["net_amount"] == 4000
    assert torku["regular_price"] == 25500
    assert torku["sale_price"] == 17000
    assert torku["product_id"] == "a101-12003241"
    assert torku["group"] == "a101:Süt" and torku["store_id"] == "VS032"
    assert len(rows) == 3


def test_out_of_stock_products_are_left_out_of_a_sweep():
    rows = sweep({"name": "a101_yumurta", "category": "dairy_eggs", "store": "a101", "shop_category": "C0503"})
    assert [r["sku"] for r in rows] == ["11001218"]
    assert rows[0]["net_amount"] == 1725


def test_a_shelf_belongs_to_the_aisle_in_its_id():
    from tracker.scrapers import a101
    assert a101.aisle_of("C0502") == "C05"
    assert [s["prettyName"] for s in a101.shelves(AISLE)] == ["C0502", "C0503"]


def test_one_shelf_can_be_split_by_product_name():
    base = {"category": "dairy_eggs", "store": "a101", "shop_category": "C0502"}
    birsah = sweep({**base, "name": "a", "name_pattern": "birşah"})
    rest = sweep({**base, "name": "b", "exclude_pattern": "birşah"})
    assert sorted(r["sku"] for r in birsah) == ["12000244", "12000319"]
    assert [r["sku"] for r in rest] == ["12003241"]
