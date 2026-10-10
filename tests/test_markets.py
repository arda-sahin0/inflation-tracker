import json

import pytest

from tracker.markets import MARKETS, STORES, locate, select


def test_a_shop_link_finds_its_market_and_store():
    market, store = locate("https://www.a101.com.tr/kapida/sut-urunleri-kahvaltilik/pinar-1-yagli-sut_p-12003704")
    assert (market.key, store.key) == ("tr", "a101")
    assert locate("www.migros.com.tr")[1].key == "migros"
    with pytest.raises(ValueError, match="no store"):
        locate("https://www.carrefoursa.com/")


def test_no_market_means_every_market():
    assert select() == list(MARKETS.values())
    assert [m.key for m in select("tr")] == ["tr"]


def test_every_store_offers_the_whole_scraper_interface():
    for store in STORES.values():
        for function in ("scrape", "sweep_rows", "crawl", "shelf_label", "pages_for"):
            assert callable(getattr(store.scraper, function, None)), f"{store.key}.{function}"


def test_every_market_has_its_configuration_and_its_own_site():
    sites = [market.site for market in MARKETS.values()]
    assert len(sites) == len(set(sites))
    for market in MARKETS.values():
        assert (market.config / "weights.json").exists(), market.key
        assert market.raw.parent.name == "raw" and market.raw.name == market.key


def test_hand_picked_products_are_valid():
    for market in MARKETS.values():
        path = market.config / "products.json"
        products = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        divisions = json.loads((market.config / "weights.json").read_text(encoding="utf-8"))["divisions"]
        categories = {c for d in divisions.values() for c in d["categories"]}
        ids = [p["id"] for p in products]
        assert len(ids) == len(set(ids)), "product ids must be unique"
        for product in products:
            assert {"id", "category", "url"} <= product.keys(), product
            assert product["category"] in categories, product["id"]
            owner, store = locate(product["url"])
            assert owner is market, product["id"]
            store.scraper.to_sku(product["url"])
