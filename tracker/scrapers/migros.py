import math
import time
from datetime import date
from urllib.parse import urlparse

import requests

from tracker.naming import parse_size

URL = "https://www.migros.com.tr/rest/products/screens/{sku}"
SEARCH_URL = "https://www.migros.com.tr/rest/search/screens/products"
SCREEN_URL = "https://www.migros.com.tr/rest/search/screens/{path}"
TOP_LEVEL_URL = "https://www.migros.com.tr/rest/categories/top-level"
PAGE_PARAM_CANDIDATES = ("sayfa", "page", "pageNumber")
PAGE_SIZE = 30
MAX_PAGES = 20
SLEEP_SECONDS = 1.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
}
_page_param: str | None = None


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


def _get_json(url: str, params: dict | None = None) -> dict:
    response = requests.get(url, params=params or {}, headers=HEADERS, timeout=20)
    response.raise_for_status()
    body = response.json()
    if not body.get("successful"):
        raise RuntimeError(f"Migros returned successful=false for {url}")
    return body["data"]


def fetch_product(sku: str) -> dict:
    return _get_json(URL.format(sku=sku))["storeProductInfoDTO"]


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


def listing_page(query: str | None = None, shop_category: str | None = None,
                 page: int = 1, page_param: str = "sayfa") -> dict:
    """One page of a listing: either a search (query) or a category page (shop_category)."""
    if bool(query) == bool(shop_category):
        raise ValueError("give exactly one of query or shop_category")
    params = {} if page == 1 else {page_param: page}
    if query:
        return _get_json(SEARCH_URL, {"q": query, **params})["searchInfo"]
    return _get_json(SCREEN_URL.format(path=shop_category), params)["searchInfo"]


def detect_page_param(query: str | None = None, shop_category: str | None = None) -> str:
    """Migros doesn't document its paging parameter — find the one that moves the results.

    The answer is the same for every listing on the site, so it is worked out once per run.
    """
    global _page_param
    if _page_param:
        return _page_param
    first = listing_page(query, shop_category)["storeProductInfos"]
    if not first:
        return PAGE_PARAM_CANDIDATES[0]
    for candidate in PAGE_PARAM_CANDIDATES:
        try:
            second = listing_page(query, shop_category, page=2, page_param=candidate)["storeProductInfos"]
        except Exception:
            continue
        if second and second[0]["sku"] != first[0]["sku"]:
            _page_param = candidate
            return candidate
    raise RuntimeError("No paging parameter worked — only the first page is reachable")


def top_level_categories() -> list[dict]:
    return _get_json(TOP_LEVEL_URL)


def real_aisles(top_level: list[dict]) -> list[dict]:
    """The shop's own aisles. Drops special pages (discounts, "only at Migros") and the
    brand or campaign pages (Lay's, Nescafé, Maç Özel...), which are flagged onboardingVisible=false."""
    return [c for c in top_level
            if not c.get("specialCategory")
            and "-c-" in c.get("prettyName", "")
            and c.get("onboardingVisible", True)]


def child_categories(search_info: dict) -> list[dict]:
    """The next level down, read from a category page's CATEGORY facet."""
    for group in search_info.get("aggregationGroups", []):
        if group.get("type") == "CATEGORY":
            return [{"name": i["label"], "prettyName": i["prettyName"], "count": int(i.get("count", 0))}
                    for i in group.get("aggregationInfos", [])]
    return []


def category_names(product: dict) -> list[str]:
    """The product's category path, oldest ancestor first."""
    names = [a["name"] for a in reversed(product.get("categoryAscendants", []))]
    if product.get("category"):
        names.append(product["category"]["name"])
    return names


def sellable(product: dict) -> bool:
    return not product.get("sponsored") and product.get("status") == "IN_SALE"


def listing_row(product: dict, category: str, group: str) -> dict:
    """A price row built from a listing entry (no netKg here — the size comes from the name)."""
    unit, net_amount = parse_size(product["name"])
    if product.get("unit") == "GRAM":
        unit, net_amount = "GRAM", None
    sku = product["sku"].zfill(8)
    return {
        "store": "migros",
        "sku": sku,
        "name": product["name"],
        "store_id": product.get("storeId"),
        "regular_price": int(product["regularPrice"]),
        "sale_price": int(product.get("shownPrice", product["regularPrice"])),
        "loyalty_price": None,
        "unit": unit,
        "net_amount": net_amount,
        "in_stock": product.get("status") == "IN_SALE",
        "product_id": f"migros-{sku}",
        "category": category,
        "group": group,
    }


def fetch_pages(shop_category: str, max_pages: int = MAX_PAGES, sleep: float = SLEEP_SECONDS) -> list[dict]:
    first = listing_page(shop_category=shop_category)
    pages = [first]
    total = min(int(first.get("pageCount", 1)), max_pages)
    if total > 1:
        page_param = detect_page_param(shop_category=shop_category)
        for page in range(2, total + 1):
            time.sleep(sleep)
            pages.append(listing_page(shop_category=shop_category, page=page, page_param=page_param))
    return pages


def collect(pages: list[dict], rule: dict) -> list[dict]:
    """Price rows from already-fetched listing pages, each product once."""
    rows, seen = [], set()
    for page in pages:
        for product in page.get("storeProductInfos", []):
            sku = product["sku"].zfill(8)
            if sku in seen or not sellable(product):
                continue
            seen.add(sku)
            rows.append(listing_row(product, rule["category"], rule["group"]))
    return rows


def sweep_rows(rule: dict) -> list[dict]:
    """All sellable products on one shelf, read page by page from its category listing."""
    return collect(fetch_pages(rule["shop_category"], int(rule.get("max_pages", MAX_PAGES))), rule)


def shelf_label(node: dict) -> str:
    """Migros reuses shelf names across aisles, so rules are named after the page instead."""
    return node["prettyName"].rsplit("-c-", 1)[0]


def pages_for(count: int) -> int:
    return max(1, math.ceil(count / PAGE_SIZE) + 1)


def crawl(skip: set[str], sleep: float = SLEEP_SECONDS, log=print) -> dict:
    """Aisles from the top-level menu, shelves from each aisle page, leaves from each shelf page."""
    aisles = []
    for aisle in real_aisles(top_level_categories()):
        if aisle["name"] in skip:
            log(f"skip  {aisle['name']}")
            continue
        time.sleep(sleep)
        info = listing_page(shop_category=aisle["prettyName"])
        shelves = []
        for shelf in child_categories(info):
            time.sleep(sleep)
            shelf_info = listing_page(shop_category=shelf["prettyName"])
            leaves = [leaf for leaf in child_categories(shelf_info) if leaf["prettyName"] != shelf["prettyName"]]
            shelves.append({**shelf, "leaves": leaves})
            log(f"      {aisle['name']} / {shelf['name']}: {len(leaves)} leaves")
        aisles.append({"name": aisle["name"], "prettyName": aisle["prettyName"],
                       "count": int(info.get("hitCount", 0)), "shelves": shelves})
    return {"store": "migros", "crawled": date.today().isoformat(), "aisles": aisles}
