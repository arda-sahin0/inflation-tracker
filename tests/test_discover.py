import json

import pytest

from discover import add_to_basket, build_entry, candidates, category_path, leaf_counts, suggest_include
from tracker import ROOT
from tracker.scrapers import migros

SEARCH = json.loads((ROOT / "tests" / "fixtures" / "migros_search_sut.json").read_text(encoding="utf-8"))
INFO = SEARCH["data"]["searchInfo"]


def test_ads_and_delisted_products_are_dropped():
    rows = candidates(INFO)
    skus = [r["sku"] for r in rows]
    assert "11019917" not in skus          # sponsored
    assert "11010267" not in skus          # NOT_IN_SALE
    assert "11011520" in skus
    assert len(rows) == 5


def test_sponsored_can_be_shown_on_request():
    assert len(candidates(INFO, include_sponsored=True)) == 7   # 8 items, one delisted


def test_candidate_carries_size_price_and_a_usable_url():
    row = next(r for r in candidates(INFO) if r["sku"] == "11011520")
    assert row["name"] == "Migros %3 Yağlı Uht Süt 1 L"
    assert (row["unit"], row["net_amount"]) == ("PIECE", 1000)
    assert row["price"] == 5275                      # kuruş
    assert row["per_kg"] == 5275                     # 1 L pack: same per litre
    assert migros.to_sku(row["url"]) == "11011520"   # the url the scraper will use
    assert row["category_path"].startswith("Süt, Kahvaltılık / Süt")


def test_build_entry_is_minimal_and_matches_products_json_shape():
    detail = {"name": "Migros %3 Yağlı Uht Süt 1 L", "prettyName": "migros-3-yagli-uht-sut-1-l-p-a805c0"}
    entry = build_entry(detail, "dairy_eggs")
    assert entry == {
        "id": "migros-3-yagli-1l-migros",
        "category": "dairy_eggs",
        "url": "https://www.migros.com.tr/migros-3-yagli-uht-sut-1-l-p-a805c0",
    }
    assert migros.to_sku(entry["url"]) == "11011520"
    assert build_entry(detail, "dairy_eggs", "sut-migros-uht-1l")["id"] == "sut-migros-uht-1l"


def test_basket_refuses_duplicates():
    basket = [{"id": "sut-sek-1l", "category": "dairy_eggs",
               "url": "https://www.migros.com.tr/sek-yeni-nesil-pastorize-gunluk-sut-1-l-p-a8251e"}]
    fresh = {"id": "new", "category": "dairy_eggs",
             "url": "https://www.migros.com.tr/migros-3-yagli-uht-sut-1-l-p-a805c0"}
    assert len(add_to_basket(basket, fresh)) == 2

    with pytest.raises(ValueError, match="already in products.json"):
        add_to_basket(basket, {**fresh, "id": "sut-sek-1l"})

    same_product = {"id": "another-name", "category": "dairy_eggs",
                    "url": "https://www.migros.com.tr/sek-yeni-nesil-pastorize-gunluk-sut-1-l-p-a8251e"}
    with pytest.raises(ValueError, match="already tracked"):
        add_to_basket(basket, same_product)


def test_category_path_reads_oldest_ancestor_first():
    product = {"categoryAscendants": [{"name": "Süt"}, {"name": "Süt, Kahvaltılık"}],
               "category": {"name": "Uzun Ömürlü Süt"}}
    assert category_path(product) == "Süt, Kahvaltılık / Süt / Uzun Ömürlü Süt"


def test_leaf_counts_ignore_ads_and_rank_by_size():
    leaves = leaf_counts([INFO])
    assert leaves[0]["leaf"] == "Uzun Ömürlü Süt"
    assert leaves[0]["count"] == 5                       # 2 ads and 1 delisted item left out
    assert "Bitkisel İçecek" not in {l["leaf"] for l in leaves}


def test_suggestion_keeps_the_big_categories_only():
    leaves = [{"leaf": "Beyaz Peynir", "count": 28}, {"leaf": "Kaşar Peyniri", "count": 19},
              {"leaf": "Krem Peynir", "count": 6}, {"leaf": "Pizza", "count": 2}]
    assert suggest_include(leaves) == ["Beyaz Peynir", "Kaşar Peyniri"]
    assert suggest_include([]) == []
