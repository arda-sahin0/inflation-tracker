"""
Renders each market's page of the public GitHub Pages dashboard (docs/).

site_template.html holds the page; the placeholder __DATA__ is replaced with the
numbers computed by index.py, so every page is a single self-contained file.
Run after index.py; the daily workflow commits the result.
"""
import argparse
import json

import pandas as pd

import index as ix
from tracker import ROOT
from tracker.markets import MARKETS, Market, select

TEMPLATE = ROOT / "site_template.html"
PERIODS = {"d1": 1, "w1": 7, "m1": 30}
MOVERS = 15


def values_on(series: pd.Series, dates: pd.DatetimeIndex) -> list:
    return [None if pd.isna(v) else round(float(v), 3) for v in series.reindex(dates)]


def change(series: pd.Series, days: int | None) -> float | None:
    """Percent change over the last `days` days, or since the first value when days is None."""
    s = series.dropna()
    if len(s) < 2:
        return None
    if days is None:
        base = s.iloc[0]
    else:
        start = s.index[-1] - pd.Timedelta(days=days)
        if s.index[0] > start:
            return None
        base = s.loc[:start].iloc[-1]
    return round(float((s.iloc[-1] / base - 1) * 100), 2)


def stats(series: pd.Series) -> dict:
    out = {key: change(series, days) for key, days in PERIODS.items()}
    out["all"] = change(series, None)
    out["level"] = round(float(series.dropna().iloc[-1]), 2)
    return out


def movers(df: pd.DataFrame) -> dict:
    """Products with the largest unit-price moves over the last week and since first seen."""
    changes = ix.product_changes(df, days=7)
    shelf = df.sort_values("date").groupby("product_id")[["regular_price", "category"]].last()
    changes = changes.join(shelf)

    def rows(frame: pd.DataFrame, column: str) -> list[dict]:
        return [{
            "name": row["name"] if isinstance(row["name"], str) else product_id,
            "store": row["store"],
            "cat": row["category"],
            "tl": round(float(row["regular_price"]) / 100, 2),
            "pct": round(float(row[column]), 1),
        } for product_id, row in frame.iterrows()]

    out = {}
    for key, column in (("w1", "last_7d_pct"), ("all", "since_start_pct")):
        moved = changes.dropna(subset=[column])
        moved = moved[moved[column].round(1) != 0].sort_values(column, ascending=False)
        out[key] = {"up": rows(moved[moved[column] > 0].head(MOVERS), column),
                    "down": rows(moved[moved[column] < 0].iloc[::-1].head(MOVERS), column)}
    return out


def dashboard_data(market: Market) -> dict:
    df = ix.load_prices(market)
    config = ix.load_config(market)
    weights = ix.load_weights(config)
    food = ix.food_categories(config)
    idx = ix.build_index(df, weights, food)
    stores = ix.build_store_index(df, weights, food)
    names = {store.key: store.name for store in market.stores}
    dates = idx.index
    categories = [c for c in idx.columns if c not in ("food", "overall")]

    today = df[df["date"] == df["date"].max()]
    counts = today.groupby(["category", "store"])["product_id"].nunique()

    series = {key: values_on(idx[key], dates) for key in idx.columns}
    series.update({store: values_on(stores[store], dates) for store in stores.columns})

    return {
        "generated": str(dates[-1].date()),
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "series": series,
        "stats": {key: stats(idx[key]) for key in ("food", "overall")}
                 | {store: stats(stores[store]) for store in stores.columns},
        "stores": {store: names.get(store, store) for store in stores.columns},
        "store_start": str(stores.index[0].date()),
        "categories": [{
            "key": c,
            "food": c in food,
            "weight": round(weights.get(c, 0.0), 2),
            "counts": {store: int(counts.get((c, store), 0)) for store in stores.columns},
            **stats(idx[c]),
        } for c in categories],
        "movers": movers(df),
        "n_today": int(today["product_id"].nunique()),
        "n_today_store": {k: int(v) for k, v in today.groupby("store")["product_id"].nunique().items()},
        "jumps": int(len(ix.big_jumps(df))),
    }


def render(market: Market) -> None:
    data = dashboard_data(market)
    page = TEMPLATE.read_text(encoding="utf-8")
    if "__DATA__" not in page:
        raise SystemExit(f"{TEMPLATE.name} has no __DATA__ placeholder")
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    market.site.parent.mkdir(parents=True, exist_ok=True)
    market.site.write_text(page, encoding="utf-8")
    print(f"Wrote {market.site.relative_to(ROOT)} — {len(page) // 1024} KB, "
          f"{len(data['dates'])} days, {data['n_today']} products today")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render the dashboard")
    parser.add_argument("--market", choices=MARKETS, help="only this market (default: all)")
    args = parser.parse_args(argv)
    for market in select(args.market):
        render(market)


if __name__ == "__main__":
    main()
