import re
import requests

TOKEN = "dbmk89vnr"
STORE = "VS032"
API = f"https://rio.a101.com.tr/{TOKEN}/CALL/Store/getProductBySku/{STORE}"

PARAMS = {
    "channel": "SLOT",
    "__culture": "tr-TR",
    "__platform": "web",
    "data": "e30=",
    "__isbase64": "true",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
}

SKU_IN_URL = re.compile(r"_p-(\d+)/?$")


def to_sku(value: str) -> str:
    """'https://www.a101.com.tr/kapida/.../pinar-1-yagli-sut_p-12003704' -> '12003704'"""
    value = value.strip()
    match = SKU_IN_URL.search(value)
    if match:
        return match.group(1)
    if value.isdigit():
        return value
    raise ValueError(f"Can't find a SKU in: {value!r}")


def fetch_product(sku: str) -> dict:
    r = requests.get(API, params={**PARAMS, "sku": sku}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    body = r.json()
    if "product" not in body:
        raise RuntimeError(f"No product in A101 response for {sku}: {body}")
    return body["product"]


def parse(p: dict, product: dict) -> dict:
    """A101 only returns price and stock, so name/unit/size come from products.json."""
    price = p["price"]
    quantity = p.get("quantity")
    return {
        "sku": to_sku(product["url"]),
        "name": product.get("name", product["id"]),
        "store_id": STORE,
        "regular_price": int(price["normal"]),
        "sale_price": int(price["discounted"]),
        "loyalty_price": None,
        "unit": product.get("unit", "PIECE"),
        "net_amount": product.get("net_amount"),
        "in_stock": (quantity or 0) > 0 and p.get("stock", "").upper() != "OUT",
    }


def scrape(product: dict) -> dict:
    raw = fetch_product(to_sku(product["url"]))
    return {"store": "a101", **parse(raw, product)}