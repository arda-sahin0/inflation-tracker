"""
Builds a daily price index from data/raw/*.csv.

Method (the same idea statistics offices use):
  1. Unit price per product: per kg / L where possible, otherwise per pack.
  2. Per category: chained Jevons index = each day, the geometric mean of
     (today's price / yesterday's price) over products that exist on both days.
  3. Overall: weighted average of the category indices, weights from weights.json
     (TurkStat's 2026 CPI division weights, split equally inside each division).

Outputs (data/index/ in CI, data/local/ when run by hand):
  daily_index.csv   one row per day: every category + overall
  store_index.csv   one row per day: overall index per store
  summary.md        human-readable snapshot, also used for posting later
"""
import json
import os

import numpy as np
import pandas as pd

from tracker import ROOT

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / ("index" if os.getenv("GITHUB_ACTIONS") == "true" else "local")

MAX_GAP_DAYS = 3     # a missing price is carried forward for at most this many days
FOOD_DIVISION = "food_and_non_alcoholic_beverages"
JUMP_PCT = 25        # a one-day price move this large is flagged for review


def load_config() -> dict:
    return json.loads((ROOT / "weights.json").read_text(encoding="utf-8"))


def load_weights(config: dict | None = None) -> dict[str, float]:
    """category -> weight (division weight split equally inside the division)."""
    config = load_config() if config is None else config
    weights = {}
    for division in config["divisions"].values():
        for category in division["categories"]:
            weights[category] = division["weight"] / len(division["categories"])
    return weights


def food_categories(config: dict | None = None) -> list[str]:
    config = load_config() if config is None else config
    return list(config["divisions"][FOOD_DIVISION]["categories"])


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
    relatives = prices / prices.shift(1)                   # NaN if missing on either day
    daily_change = np.exp(np.log(relatives).mean(axis=1))  # geometric mean
    daily_change = daily_change.fillna(1.0)                # no comparable products -> no change
    daily_change.iloc[0] = 1.0
    return 100 * daily_change.cumprod()


def weighted_overall(category_index: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    w = pd.Series({c: weights.get(c, 0.0) for c in category_index.columns}, dtype=float)
    if w.sum() == 0:
        raise SystemExit("No category in the data has a weight in weights.json")
    return (category_index * w).sum(axis=1) / w.sum()


def build_index(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    weights = load_weights() if weights is None else weights
    df = add_unit_price(df)
    prices = price_table(df)
    category_of = df.groupby("product_id")["category"].last()

    result = pd.DataFrame(index=prices.index)
    for category, products in category_of.groupby(category_of).groups.items():
        result[category] = chained_jevons(prices[list(products)])

    overall = weighted_overall(result, weights)
    food = [c for c in food_categories() if c in result.columns]
    # headline: food has the best coverage; with no food category present it equals overall
    result["food"] = weighted_overall(result[food], weights) if food else overall
    result["overall"] = overall
    result.index.name = "date"
    return result


def build_store_index(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """One overall index per store, each on its own products."""
    weights = load_weights() if weights is None else weights
    out = pd.DataFrame()
    for store, rows in df.groupby("store"):
        out[store] = build_index(rows, weights)["food"]
    out.index.name = "date"
    return out


def size_changes(df: pd.DataFrame) -> pd.DataFrame:
    """Products whose package size (net_amount) changed — possible shrinkflation."""
    d = df.dropna(subset=["net_amount"]).sort_values("date")
    d = d.assign(previous=d.groupby("product_id")["net_amount"].shift(1))
    changed = d[d["previous"].notna() & (d["net_amount"] != d["previous"])]
    return changed[["date", "product_id", "previous", "net_amount"]]


def product_changes(df: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    """Per-product change since the start and over the last `days` days."""
    prices = price_table(add_unit_price(df))
    first_valid = prices.apply(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
    latest = prices.iloc[-1]
    week_ago = prices.iloc[max(0, len(prices) - 1 - days)]
    out = pd.DataFrame({
        "since_start_pct": (latest / first_valid - 1) * 100,
        f"last_{days}d_pct": (latest / week_ago - 1) * 100,
        "latest_tl": latest / 100,
    })
    names = df.groupby("product_id")[["name", "store"]].last()
    return out.join(names).dropna(subset=["since_start_pct"]).sort_values("since_start_pct", ascending=False)


def big_jumps(df: pd.DataFrame, pct: float = JUMP_PCT) -> pd.DataFrame:
    """One-day price moves larger than `pct` — usually a promotion or a swapped product."""
    prices = price_table(add_unit_price(df))
    change = prices / prices.shift(1) - 1
    rows = []
    for date, day in change.iterrows():
        for product_id, value in day.dropna().items():
            if abs(value) * 100 >= pct:
                rows.append({"date": date, "product_id": product_id,
                             "from_tl": prices[product_id].shift(1).loc[date] / 100,
                             "to_tl": prices[product_id].loc[date] / 100,
                             "change_pct": value * 100})
    return pd.DataFrame(rows)


def write_summary(index: pd.DataFrame, stores: pd.DataFrame, changes: pd.DataFrame, path,
                  jumps: pd.DataFrame | None = None) -> str:
    latest, first = index.iloc[-1], index.iloc[0]
    days = (index.index[-1] - index.index[0]).days
    food_total = latest["food"] / first["food"] - 1
    basket_total = latest["overall"] / first["overall"] - 1
    annual = (1 + food_total) ** (365 / days) - 1 if days else 0.0

    lines = [
        f"# Market basket index — {index.index[-1]:%d %B %Y}",
        "",
        f"- Period: {index.index[0]:%d %b %Y} to {index.index[-1]:%d %b %Y} ({days} days)",
        f"- **Food & non-alcoholic beverages: {latest['food']:.2f}** ({food_total * 100:+.2f}%)",
        f"- Whole basket (incl. household & personal care): {latest['overall']:.2f} "
        f"({basket_total * 100:+.2f}%)",
        f"- Food at the same pace for a year would be: {annual * 100:+.1f}%",
        "",
        "## By store (food index, each on its own products)",
        "",
        "| Store | Index | Change |",
        "| --- | --- | --- |",
    ]
    for store in stores.columns:
        change = stores[store].iloc[-1] / stores[store].iloc[0] - 1
        lines.append(f"| {store} | {stores[store].iloc[-1]:.2f} | {change * 100:+.2f}% |")

    lines += ["", "## By category", "", "| Category | Index | Change |", "| --- | --- | --- |"]
    for category in sorted(c for c in index.columns if c not in ("overall", "food")):
        change = latest[category] / first[category] - 1
        lines.append(f"| {category} | {latest[category]:.2f} | {change * 100:+.2f}% |")

    lines += ["", "## Biggest movers since the start", "", "| Product | Store | Now (TL) | Change |",
              "| --- | --- | --- | --- |"]
    movers = pd.concat([changes.head(5), changes.tail(5)])
    for product_id, row in movers.iterrows():
        name = row["name"] if isinstance(row["name"], str) else product_id
        lines.append(f"| {name} | {row['store']} | {row['latest_tl']:.2f} | {row['since_start_pct']:+.1f}% |")

    if jumps is not None and not jumps.empty:
        lines += ["", f"## One-day moves over {JUMP_PCT}% (worth a look)", "",
                  "| Date | Product | From (TL) | To (TL) |", "| --- | --- | --- | --- |"]
        for _, row in jumps.iterrows():
            lines.append(f"| {row['date']:%Y-%m-%d} | {row['product_id']} | "
                         f"{row['from_tl']:.2f} | {row['to_tl']:.2f} |")

    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    df = load_prices()
    weights = load_weights()
    index = build_index(df, weights)
    stores = build_store_index(df, weights)
    changes = product_changes(df)
    jumps = big_jumps(df)

    OUT.mkdir(parents=True, exist_ok=True)
    index.round(2).to_csv(OUT / "daily_index.csv")
    stores.round(2).to_csv(OUT / "store_index.csv")
    changes.round(2).to_csv(OUT / "product_changes.csv")
    if not jumps.empty:
        jumps.round(2).to_csv(OUT / "price_jumps.csv", index=False)
    print(write_summary(index, stores, changes, OUT / "summary.md", jumps))

    sizes = size_changes(df)
    if not sizes.empty:
        print("Package size changes:")
        print(sizes.to_string(index=False))


if __name__ == "__main__":
    main()
