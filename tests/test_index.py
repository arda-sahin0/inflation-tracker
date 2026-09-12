import math

import pandas as pd
import pytest

from index import build_index, chained_jevons


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
        ("2026-09-11", "a", "dairy", 100),
        ("2026-09-12", "a", "dairy", 100),
        ("2026-09-12", "b", "dairy", 999),
        ("2026-09-13", "a", "dairy", 100),
        ("2026-09-13", "b", "dairy", 999),
    ])
    assert build_index(df, {"dairy": 1})["dairy"].tolist() == pytest.approx([100, 100, 100])


def test_missing_day_is_carried_forward():
    df = rows([
        ("2026-09-11", "a", "dairy", 100),
        # 09-12 missing
        ("2026-09-13", "a", "dairy", 120),
    ])
    assert build_index(df, {"dairy": 1})["dairy"].tolist() == pytest.approx([100, 100, 120])


def test_overall_is_weighted_average_of_categories():
    df = rows([
        ("2026-09-11", "a", "dairy", 100), ("2026-09-11", "b", "meat", 100),
        ("2026-09-12", "a", "dairy", 110), ("2026-09-12", "b", "meat", 100),
    ])
    index = build_index(df, {"dairy": 3, "meat": 1})
    assert index["overall"].iloc[-1] == pytest.approx((110 * 3 + 100 * 1) / 4)


def test_shrinkflation_counts_as_a_price_rise():
    df = rows([
        ("2026-09-11", "a", "snacks", 100),
        ("2026-09-12", "a", "snacks", 100),
    ])
    df["net_amount"] = [100.0, 80.0]
    index = build_index(df, {"snacks": 1})
    assert index["snacks"].iloc[-1] == pytest.approx(125)
