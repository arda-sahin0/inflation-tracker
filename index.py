"""
Builds a daily price index from data/raw/*.csv.

Method (the same idea statistics offices use):
  1. Unit price per product: per kg / L where possible, otherwise per pack.
  2. Per category: chained Jevons index = each day, the geometric mean of
     (today's price / yesterday's price) over products that exist on both days.
  3. Overall: weighted average of the category indices.
"""
import os

import numpy as np
import pandas as pd

from tracker import ROOT

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / ("index" if os.getenv("GITHUB_ACTIONS") == "true" else "local")

WEIGHTS = {
    "bread_cereals": 1, "meat": 1, "dairy_eggs": 1, "oils_fats": 1,
    "fruit_nuts": 1, "vegetables_pulses": 1, "sugar_sweets": 1, "other_food": 1,
    "tea_coffee": 1, "drinks": 1, "household": 1, "personal_care": 1,
}

MAX_GAP_DAYS = 3


def load_prices() -> pd.DataFrame:
    files = sorted(RAW.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSV files in {RAW}")
    df = pd.concat((pd.read_csv(f, dtype={"sku": str}) for f in files), ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def add_unit_price(df: pd.DataFrame) -> pd.DataFrame:
    """Kuruş per kg/L for packaged goods with a known size, else price as listed."""
    df = df.copy()
    per_kg = df["regular_price"] * 1000 / df["net_amount"]
    use_listed = (df["unit"] == "GRAM") | df["net_amount"].isna()
    df["unit_price"] = df["regular_price"].where(use_listed, per_kg)
    return df


def price_table(df: pd.DataFrame) -> pd.DataFrame:
    """Rows = dates, columns = product_id, values = unit price (NaN = no price)."""
    df = df[df["in_stock"]]
    table = df.pivot_table(index="date", columns="product_id", values="unit_price", aggfunc="last")
    all_days = pd.date_range(table.index.min(), table.index.max(), freq="D")
    return table.reindex(all_days).ffill(limit=MAX_GAP_DAYS)


def chained_jevons(prices: pd.DataFrame) -> pd.Series:
    """Index that starts at 100. prices: rows = dates, columns = products."""
    relatives = prices / prices.shift(1)
    daily_change = np.exp(np.log(relatives).mean(axis=1))
    daily_change = daily_change.fillna(1.0)
    daily_change.iloc[0] = 1.0
    return 100 * daily_change.cumprod()


def build_index(df: pd.DataFrame, weights: dict[str, float] = WEIGHTS) -> pd.DataFrame:
    df = add_unit_price(df)
    prices = price_table(df)
    category_of = df.groupby("product_id")["category"].last()

    result = pd.DataFrame(index=prices.index)
    for category, products in category_of.groupby(category_of).groups.items():
        result[category] = chained_jevons(prices[list(products)])

    w = pd.Series({c: weights.get(c, 0) for c in result.columns}, dtype=float)
    result["overall"] = (result * w).sum(axis=1) / w.sum()
    result.index.name = "date"
    return result


def size_changes(df: pd.DataFrame) -> pd.DataFrame:
    """Products whose package size (net_amount) changed — possible shrinkflation."""
    d = df.dropna(subset=["net_amount"]).sort_values("date")
    d = d.assign(previous=d.groupby("product_id")["net_amount"].shift(1))
    changed = d[d["previous"].notna() & (d["net_amount"] != d["previous"])]
    return changed[["date", "product_id", "previous", "net_amount"]]


def main() -> None:
    df = load_prices()
    index = build_index(df)

    OUT.mkdir(parents=True, exist_ok=True)
    index.round(2).to_csv(OUT / "daily_index.csv")

    latest, first = index.iloc[-1], index.iloc[0]
    print(f"Days of data: {len(index)}  ({index.index[0].date()} → {index.index[-1].date()})")
    print(f"Overall index: {latest['overall']:.2f}  ({latest['overall'] - 100:+.2f}% since start)")
    if len(index) > 1:
        prev = index.iloc[-2]
        print(f"Change vs. previous day: {(latest['overall'] / prev['overall'] - 1) * 100:+.2f}%")
    print("\nBy category (since start):")
    for cat in sorted(c for c in index.columns if c != "overall"):
        print(f"  {cat:<20} {latest[cat] / first[cat] * 100 - 100:+6.2f}%")

    changes = size_changes(df)
    if not changes.empty:
        print("\nPackage size changes:")
        print(changes.to_string(index=False))


if __name__ == "__main__":
    main()