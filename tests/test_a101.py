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