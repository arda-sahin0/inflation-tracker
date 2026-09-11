import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from tracker import ROOT
from tracker.scrapers import get_scraper

TURKEY = timezone(timedelta(hours=3))
FIELDS = ["date", "product_id", "category", "store", "sku", "name", "store_id",
          "regular_price", "sale_price", "loyalty_price", "unit", "net_amount", "in_stock"]


def main() -> int:
    today = datetime.now(TURKEY).date().isoformat()
    products = json.loads((ROOT / "products.json").read_text(encoding="utf-8"))

    rows, failures = [], []
    for product in products:
        try:
            scrape = get_scraper(product["url"])
            row = scrape(product)
            row.update(date=today, product_id=product["id"], category=product["category"])
            rows.append(row)
            print(f"OK   {product['id']}: {row['regular_price'] / 100:.2f} TL")
        except Exception as e:
            failures.append(product["id"])
            print(f"FAIL {product['id']}: {e!r}")
        time.sleep(2)

    if rows:
        out = ROOT / "data" / "raw" / f"{today}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved {len(rows)} rows to {out.relative_to(ROOT)}")

    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())