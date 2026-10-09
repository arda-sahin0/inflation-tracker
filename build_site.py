"""
Renders docs/index.html — the public GitHub Pages dashboard.

site_template.html holds the page; the placeholder __DATA__ is replaced with the
numbers computed by index.py, so the site is a single self-contained file.
Run after index.py; the daily workflow commits the result.
"""
import json

import pandas as pd

import index as ix
from tracker import ROOT

TEMPLATE = ROOT / "site_template.html"
OUT = ROOT / "docs" / "index.html"


def dashboard_data() -> dict:
    df = ix.load_prices()
    weights = ix.load_weights()
    idx = ix.build_index(df, weights).round(3)
    stores = ix.build_store_index(df, weights).round(3)
    changes = ix.product_changes(df).round(2)
    jumps = ix.big_jumps(df)
    categories = [c for c in idx.columns if c not in ("food", "overall")]

    def movers(frame: pd.DataFrame) -> list[dict]:
        out = []
        for product_id, row in frame.iterrows():
            out.append({
                "name": row["name"] if isinstance(row["name"], str) else product_id,
                "store": {"migros": "Migros", "a101": "A101"}.get(row["store"], row["store"]),
                "tl": float(row["latest_tl"]),
                "pct": float(row["since_start_pct"]),
            })
        return out

    return {
        "generated": str(idx.index[-1].date()),
        "dates": [d.strftime("%Y-%m-%d") for d in idx.index],
        "food": idx["food"].tolist(),
        "overall": idx["overall"].tolist(),
        "stores": {s: stores[s].dropna().tolist() for s in stores.columns},
        "categories": {c: round(float(idx[c].iloc[-1]), 2) for c in categories},
        "n_products": int(df["product_id"].nunique()),
        "n_products_store": {k: int(v) for k, v in df.groupby("store")["product_id"].nunique().items()},
        "movers_up": movers(changes.head(6)),
        "movers_down": movers(changes.tail(3)),
        "jumps": int(len(jumps)),
    }


def main() -> None:
    data = dashboard_data()
    page = TEMPLATE.read_text(encoding="utf-8")
    if "__DATA__" not in page:
        raise SystemExit(f"{TEMPLATE.name} has no __DATA__ placeholder")
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} — {len(page) // 1024} KB, "
          f"{len(data['dates'])} days, {data['n_products']} products")


if __name__ == "__main__":
    main()
