"""
Builds a daily price index for each market from data/raw/<market>/*.csv.

Method (the same idea statistics offices use):
  1. Unit price per product: per kg / L where possible, otherwise per pack.
  2. Per category: chained Jevons index = each day, the geometric mean of
     (today's price / yesterday's price) over products that exist on both days.
  3. Overall: weighted average of the category indices, weights from the market's
     weights.json (the national CPI division weights, split equally inside each division).

Outputs (data/index/<market>/ in CI, data/local/<market>/ when run by hand):
  daily_index.csv   one row per day: every category + overall
  store_index.csv   one row per day: overall index per store
  summary.md        human-readable snapshot, also used for posting later
"""
import argparse
import json

import numpy as np
import pandas as pd

from tracker.markets import MARKETS, Market, select

MAX_GAP_DAYS = 3
FOOD_DIVISION = "food_and_non_alcoholic_beverages"
JUMP_PCT = 25


def load_config(market: Market) -> dict:
    return json.loads((market.config / "weights.json").read_text(encoding="utf-8"))


def load_weights(config: dict) -> dict[str, float]:
    """category -> weight (division weight split equally inside the division)."""
    weights = {}
    for division in config["divisions"].values():
        for category in division["categories"]:
            weights[category] = division["weight"] / len(division["categories"])
    return weights


def food_categories(config: dict) -> list[str]:
    return list(config["divisions"][FOOD_DIVISION]["categories"])


def load_prices(market: Market) -> pd.DataFrame:
    files = sorted(market.raw.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSV files in {market.raw}")
    df = pd.concat((pd.read_csv(f, dtype={"sku": str}) for f in files), ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    if "group" not in df.columns:
        df["group"] = "picked"
    df["group"] = df["group"].fillna("picked")
    return df


def add_unit_price(df: pd.DataFrame) -> pd.DataFrame:
    """Price per kg/L in the smallest currency unit (kuruş, cent) where the size is known, else as listed."""
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


def daily_links(prices: pd.DataFrame) -> pd.Series:
    """Each day's price change: geometric mean of (today / yesterday) over products priced on both days.

    NaN on days where no product has two consecutive prices, so callers can tell
    "no change" apart from "nothing to compare".
    """
    relatives = prices / prices.shift(1)
    return np.exp(np.log(relatives).mean(axis=1))


def chain(links: pd.Series) -> pd.Series:
    """Turn daily changes into an index that starts at 100."""
    links = links.fillna(1.0)
    links.iloc[0] = 1.0
    return 100 * links.cumprod()


def weighted_overall(category_index: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    w = pd.Series({c: weights.get(c, 0.0) for c in category_index.columns}, dtype=float)
    if w.sum() == 0:
        raise SystemExit("No category in the data has a weight in weights.json")
    return (category_index * w).sum(axis=1) / w.sum()


def groups_of(df: pd.DataFrame) -> pd.DataFrame:
    """product_id -> its category and its elementary group."""
    out = df.groupby("product_id")[["category", "group"]].last()
    return out.reset_index().set_index("product_id")


def build_index(df: pd.DataFrame, weights: dict[str, float], food: list[str]) -> pd.DataFrame:
    """Every category, the weighted overall basket and the food headline, all starting at 100."""
    if "group" not in df.columns:
        df = df.assign(group="picked")
    df = add_unit_price(df)
    prices = price_table(df)

    result = pd.DataFrame(index=prices.index)
    for category, members in groups_of(df).groupby("category"):
        links = {}
        for name, ids in members.groupby("group").groups.items():
            columns = [i for i in ids if i in prices.columns]
            if columns:
                links[name] = daily_links(prices[columns])
        category_link = np.exp(np.log(pd.DataFrame(links)).mean(axis=1))
        result[category] = chain(category_link)

    overall = weighted_overall(result, weights)
    present = [c for c in food if c in result.columns]
    result["food"] = weighted_overall(result[present], weights) if present else overall
    result["overall"] = overall
    result.index.name = "date"
    return result


def build_store_index(df: pd.DataFrame, weights: dict[str, float], food: list[str]) -> pd.DataFrame:
    """Food index per store, each on its own products, all rebased to a shared start day.

    A store added later (A101 started on 13 Sep) has no earlier prices, so the
    common start is the first day every store has data. Without the rebase the
    stores would sit on different base days and not be comparable.
    """
    series = {store: build_index(rows, weights, food)["food"] for store, rows in df.groupby("store")}
    frame = pd.DataFrame(series)
    complete = frame.dropna(how="any")
    if complete.empty:
        raise SystemExit("No single day has prices from every store")
    start = complete.index.min()
    out = frame.loc[start:] / frame.loc[start] * 100
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


def write_summary(index: pd.DataFrame, stores: pd.DataFrame, changes: pd.DataFrame, path, currency: str,
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

    lines += ["", "## Biggest movers since the start", "", f"| Product | Store | Now ({currency}) | Change |",
              "| --- | --- | --- | --- |"]
    movers = pd.concat([changes.head(5), changes.tail(5)])
    for product_id, row in movers.iterrows():
        name = row["name"] if isinstance(row["name"], str) else product_id
        lines.append(f"| {name} | {row['store']} | {row['latest_tl']:.2f} | {row['since_start_pct']:+.1f}% |")

    if jumps is not None and not jumps.empty:
        lines += ["", f"## One-day moves over {JUMP_PCT}% (worth a look)", "",
                  f"| Date | Product | From ({currency}) | To ({currency}) |", "| --- | --- | --- | --- |"]
        for _, row in jumps.iterrows():
            lines.append(f"| {row['date']:%Y-%m-%d} | {row['product_id']} | "
                         f"{row['from_tl']:.2f} | {row['to_tl']:.2f} |")

    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def run(market: Market) -> None:
    df = load_prices(market)
    config = load_config(market)
    weights, food = load_weights(config), food_categories(config)
    index = build_index(df, weights, food)
    stores = build_store_index(df, weights, food)
    changes = product_changes(df)
    jumps = big_jumps(df)

    out = market.output
    out.mkdir(parents=True, exist_ok=True)
    index.round(2).to_csv(out / "daily_index.csv")
    stores.round(2).to_csv(out / "store_index.csv")
    changes.round(2).to_csv(out / "product_changes.csv")
    if not jumps.empty:
        jumps.round(2).to_csv(out / "price_jumps.csv", index=False)
    print(write_summary(index, stores, changes, out / "summary.md", market.currency, jumps))

    sizes = size_changes(df)
    if not sizes.empty:
        print("Package size changes:")
        print(sizes.to_string(index=False))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the price index")
    parser.add_argument("--market", choices=MARKETS, help="only this market (default: all)")
    args = parser.parse_args(argv)
    for market in select(args.market):
        run(market)


if __name__ == "__main__":
    main()
