import math

import pandas as pd
import pytest

from index import build_index, build_store_index, chained_jevons, load_weights


def rows(data):
    """data: list of (date, product_id, category, regular_price) → DataFrame like the raw CSVs."""
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "product_id": p, "category": c, "regular_price": price,
          "unit": "PIECE", "net_amount": None, "in_stock": True}
         for d, p, c, price in data]
    )


def test_one_product_up_10_percent_other_flat():
    prices = pd.DataFrame({"a": [100, 110], "b": [50, 50]})
    index = chained_jevons(prices)
    assert index.iloc[0] == 100
    assert index.iloc[1] == pytest.approx(100 * math.sqrt(1.10))


def test_new_product_does_not_jump_the_index():
    df = rows([
        ("2026-09-11", "a", "dairy_eggs", 100),
        ("2026-09-12", "a", "dairy_eggs", 100),
        ("2026-09-12", "b", "dairy_eggs", 999),
        ("2026-09-13", "a", "dairy_eggs", 100),
        ("2026-09-13", "b", "dairy_eggs", 999),
    ])
    assert build_index(df, {"dairy_eggs": 1})["dairy_eggs"].tolist() == pytest.approx([100, 100, 100])


def test_missing_day_is_carried_forward():
    df = rows([
        ("2026-09-11", "a", "dairy_eggs", 100),
        # 09-12 missing
        ("2026-09-13", "a", "dairy_eggs", 120),
    ])
    assert build_index(df, {"dairy_eggs": 1})["dairy_eggs"].tolist() == pytest.approx([100, 100, 120])


def test_overall_is_weighted_average_of_categories():
    df = rows([
        ("2026-09-11", "a", "dairy_eggs", 100), ("2026-09-11", "b", "meat", 100),
        ("2026-09-12", "a", "dairy_eggs", 110), ("2026-09-12", "b", "meat", 100),
    ])
    index = build_index(df, {"dairy_eggs": 3, "meat": 1})
    assert index["overall"].iloc[-1] == pytest.approx((110 * 3 + 100 * 1) / 4)


def test_shrinkflation_counts_as_a_price_rise():
    df = rows([
        ("2026-09-11", "a", "sugar_sweets", 100),
        ("2026-09-12", "a", "sugar_sweets", 100),
    ])
    df["net_amount"] = [100.0, 80.0]
    index = build_index(df, {"sugar_sweets": 1})
    assert index["sugar_sweets"].iloc[-1] == pytest.approx(125)


def test_weights_split_division_equally_and_cover_the_basket():
    weights = load_weights()
    food = ["bread_cereals", "meat", "dairy_eggs", "oils_fats", "fruit_nuts",
            "vegetables_pulses", "sugar_sweets", "other_food", "tea_coffee", "drinks"]
    assert sum(weights[c] for c in food) == pytest.approx(24.44)      # TurkStat 2026 food weight
    assert weights["household"] == pytest.approx(7.92)
    assert weights["personal_care"] == pytest.approx(4.49)
    assert all(weights[c] == pytest.approx(24.44 / 10) for c in food)


def test_food_headline_ignores_non_food_categories():
    df = rows([
        ("2026-09-11", "a", "dairy_eggs", 100), ("2026-09-11", "b", "personal_care", 100),
        ("2026-09-12", "a", "dairy_eggs", 100), ("2026-09-12", "b", "personal_care", 200),
    ])
    index = build_index(df)
    assert index["food"].iloc[-1] == pytest.approx(100)       # food unchanged
    assert index["overall"].iloc[-1] > 100                    # whole basket moved


def test_store_index_is_computed_per_store():
    df = rows([
        ("2026-09-11", "a", "dairy_eggs", 100), ("2026-09-11", "b", "dairy_eggs", 100),
        ("2026-09-12", "a", "dairy_eggs", 150), ("2026-09-12", "b", "dairy_eggs", 100),
    ])
    df["store"] = ["migros", "a101", "migros", "a101"]
    stores = build_store_index(df)
    assert stores["migros"].iloc[-1] == pytest.approx(150)
    assert stores["a101"].iloc[-1] == pytest.approx(100)


def test_store_index_rebases_to_a_shared_start_day():
    df = rows([
        ("2026-09-11", "a", "dairy_eggs", 100),                                   # only migros
        ("2026-09-12", "a", "dairy_eggs", 200), ("2026-09-12", "b", "dairy_eggs", 50),
        ("2026-09-13", "a", "dairy_eggs", 300), ("2026-09-13", "b", "dairy_eggs", 100),
    ])
    df["store"] = ["migros", "migros", "a101", "migros", "a101"]
    stores = build_store_index(df)
    assert stores.index[0] == pd.Timestamp("2026-09-12")      # first day both stores have
    assert stores.iloc[0].tolist() == pytest.approx([100.0, 100.0])
    assert stores["migros"].iloc[-1] == pytest.approx(150)    # 200 -> 300
    assert stores["a101"].iloc[-1] == pytest.approx(200)      # 50 -> 100


def test_a_big_sweep_cannot_swamp_the_hand_picked_products():
    """Two hand-picked products flat, a 50-product sweep up 20%: the category gains ~10%."""
    data = []
    for day, factor in (("2026-09-11", 1.0), ("2026-09-12", 1.2)):
        data += [(day, "picked-a", "dairy_eggs", 100), (day, "picked-b", "dairy_eggs", 100)]
        data += [(day, f"swept-{i}", "dairy_eggs", 100 * factor) for i in range(50)]
    df = rows(data)
    df["group"] = ["picked" if p.startswith("picked") else "milk" for p in df["product_id"]]

    index = build_index(df)
    # geometric mean of the two groups: sqrt(1.0 * 1.2)
    assert index["dairy_eggs"].iloc[-1] == pytest.approx(100 * math.sqrt(1.2))
    # without grouping the 50 swept products would have pulled it to nearly 120
    assert index["dairy_eggs"].iloc[-1] < 110
