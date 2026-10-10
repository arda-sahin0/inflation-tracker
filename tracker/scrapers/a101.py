import re
import time
from datetime import date

import requests

from tracker.naming import parse_size

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


LIST_URL = f"https://rio.a101.com.tr/{TOKEN}/CALL/Store/listCategoryProducts/{STORE}"
AISLE_IDS = [f"C{n:02d}" for n in range(1, 31)]
SLEEP_SECONDS = 1.0
_aisles: dict[str, dict] = {}


def list_category(aisle_id: str) -> dict:
    if aisle_id not in _aisles:
        response = requests.get(LIST_URL, params={**PARAMS, "categoryId": aisle_id, "v": 3},
                                headers=HEADERS, timeout=60)
        response.raise_for_status()
        body = response.json()
        if "children" not in body:
            raise RuntimeError(f"A101 aisle {aisle_id}: no shelves in the response")
        _aisles[aisle_id] = body
    return _aisles[aisle_id]


def aisle_of(shelf_id: str) -> str:
    """C0502 (Süt) belongs to aisle C05."""
    return shelf_id[:3]


def shelves(aisle: dict) -> list[dict]:
    return [{"name": c["name"], "prettyName": c["id"], "count": int(c.get("itemCount", 0)), "leaves": []}
            for c in aisle.get("children", [])]


def shelf_products(aisle: dict, shelf_id: str) -> list[dict]:
    for child in aisle.get("children", []):
        if child["id"] == shelf_id:
            return child.get("products", [])
    raise KeyError(f"A101 shelf {shelf_id} not found in aisle {aisle.get('id')}")


def sellable(product: dict) -> bool:
    return bool(product.get("isEnabled")) and (product.get("stock") or 0) > 0 \
        and not product.get("isBlacklisted")


def listing_row(product: dict, category: str, group: str) -> dict:
    """A price row from a listing entry. A101 states net weight itself; the name is only a fallback."""
    attributes = product.get("attributes", {})
    name = attributes.get("name", product["id"])
    if str(attributes.get("salesUnitOfMeasure", "")).upper() == "KG":
        unit, net_amount = "GRAM", None
    else:
        unit = "PIECE"
        net_amount = float(attributes["netWeight"]) if attributes.get("netWeight") else parse_size(name)[1]
    price = product["price"]
    return {
        "store": "a101",
        "sku": str(product["id"]),
        "name": name,
        "store_id": STORE,
        "regular_price": int(price["normal"]),
        "sale_price": int(price.get("discounted", price["normal"])),
        "loyalty_price": None,
        "unit": unit,
        "net_amount": net_amount,
        "in_stock": sellable(product),
        "product_id": f"a101-{product['id']}",
        "category": category,
        "group": group,
    }


def sweep_rows(rule: dict) -> list[dict]:
    """All sellable products on one A101 shelf. The aisle is downloaded once and shared by its shelves.

    name_pattern and exclude_pattern split one shelf by product name, e.g. rice out of pulses.
    """
    shelf_id = rule["shop_category"]
    products = shelf_products(list_category(aisle_of(shelf_id)), shelf_id)
    keep = re.compile(rule["name_pattern"], re.IGNORECASE) if rule.get("name_pattern") else None
    drop = re.compile(rule["exclude_pattern"], re.IGNORECASE) if rule.get("exclude_pattern") else None

    def wanted(product: dict) -> bool:
        name = product.get("attributes", {}).get("name", "")
        return sellable(product) and (keep is None or keep.search(name)) and not (drop and drop.search(name))

    return [listing_row(p, rule["category"], rule["group"]) for p in products if wanted(p)]


def shelf_label(node: dict) -> str:
    return node["name"]


def pages_for(count: int) -> int:
    """A whole aisle arrives in one response, so a shelf never needs a second page."""
    return 1


def crawl(skip: set[str], sleep: float = SLEEP_SECONDS, log=print) -> dict:
    """A101 numbers its aisles C01, C02, ... and one request returns an aisle with all its shelves."""
    aisles = []
    for aisle_id in AISLE_IDS:
        time.sleep(sleep)
        try:
            aisle = list_category(aisle_id)
        except Exception as e:
            log(f"      {aisle_id}: no aisle ({type(e).__name__})")
            continue
        if aisle.get("name") in skip:
            log(f"skip  {aisle['name']}")
            continue
        aisles.append({"name": aisle["name"], "prettyName": aisle_id,
                       "count": int(aisle.get("itemCount", 0)), "shelves": shelves(aisle)})
        log(f"      {aisle_id} {aisle['name']}: {len(aisles[-1]['shelves'])} shelves")
    return {"store": "a101", "crawled": date.today().isoformat(), "aisles": aisles}
