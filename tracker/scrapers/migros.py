import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

URL = "https://www.migros.com.tr/rest/products/screens/{sku}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
}


def to_sku(value: str) -> str:
    value = value.strip()
    path = urlparse(value).path.rstrip("/")

    if "-p-" in path:
        hex_id = path.rsplit("-p-", 1)[1]
        try:
            return f"{int(hex_id, 16):08d}"
        except ValueError:
            raise ValueError(f"Not a valid hex product id in: {value!r}") from None

    if value.isdigit():
        return value.zfill(8)

    raise ValueError(f"Can't find a SKU in: {value!r}")


def fetch_product(sku: str) -> dict:
    r = requests.get(URL.format(sku=sku), headers=HEADERS, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("successful"):
        raise RuntimeError(f"Migros returned successful=false for {sku}")
    return body["data"]["storeProductInfoDTO"]


def parse(p: dict) -> dict:
    main_props = p.get("propertyInfosMap", {}).get("MAIN", [])
    net = next((x["value"] for x in main_props if x.get("customId") == "netKg"), None)
    return {
        "sku": p["sku"],
        "name": p["name"],
        "store_id": p["storeId"],
        "regular_price": p["regularPrice"],
        "sale_price": p["salePrice"],
        "loyalty_price": p["loyaltyPrice"],
        "unit": p["unit"],
        "net_amount": float(net) if net else None,
        "in_stock": p["status"] == "IN_SALE" and p["saleable"],
    }



def scrape(product: dict) -> dict:
    sku = to_sku(product["url"])
    raw = fetch_product(sku)
    if raw["sku"] != sku:
        raise RuntimeError(f"SKU mismatch: asked for {sku}, got {raw['sku']}")
    return {"store": "migros", **parse(raw)}