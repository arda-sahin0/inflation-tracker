import json

import pytest

from tracker import ROOT
from tracker.scrapers.migros import parse, to_sku

FIXTURES = ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("value, expected", [
    ("https://www.migros.com.tr/sek-yeni-nesil-pastorize-gunluk-sut-1-l-p-a8251e", "11019550"),
    ("https://www.migros.com.tr/master-farm-yerli-ceviz-ici-150-g-p-7b498d", "08079757"),  # zero-padding
    ("https://www.migros.com.tr/muz-yerli-kg-p-1a01b70?utm_source=x", "27270000"),         # query string
    ("  https://www.migros.com.tr/muz-yerli-kg-p-1a01b70/  ", "27270000"),                 # spaces, slash
    ("11019550", "11019550"),
    ("8079757", "08079757"),
])
def test_to_sku(value, expected):
    assert to_sku(value) == expected


@pytest.mark.parametrize("bad", [
    "https://www.migros.com.tr/sut-p-xyz",   # not hex
    "not a url",
    "",
])
def test_to_sku_rejects_garbage(bad):
    with pytest.raises(ValueError):
        to_sku(bad)


def test_parse_packaged_product():
    row = parse(load_fixture("migros_11019550.json"))
    assert row["sku"] == "11019550"
    assert row["regular_price"] == 9995
    assert row["unit"] == "PIECE"
    assert row["net_amount"] == 1000.0
    assert row["in_stock"] is True


def test_parse_weighed_product():
    row = parse(load_fixture("migros_27270000.json"))
    assert row["unit"] == "GRAM"
    assert row["net_amount"] is None
    assert isinstance(row["regular_price"], int)