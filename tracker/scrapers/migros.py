from urllib.parse import urlparse
import requests

URL = "https://www.migros.com.tr/rest/products/screens/{sku}"
SEARCH_URL = "https://www.migros.com.tr/rest/search/screens/products"
SITE = "https://www.migros.com.tr/"
PAGE_PARAM_CANDIDATES = ("sayfa", "page", "pageNumber")
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

# ---------- listings: one request returns ~35 products with their prices ----------

def search_page(query: str, page: int = 1, page_param: str = "sayfa") -> dict:
    """One page of search results (the payload behind a category or search page)."""
    params = {"q": query}
    if page > 1:
        params[page_param] = page
    response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()
    body = response.json()
    if not body.get("successful"):
        raise RuntimeError(f"Migros search failed for {query!r}")
    return body["data"]["searchInfo"]


def detect_page_param(query: str) -> str:
    """Migros doesn't document its paging parameter — find the one that moves the results."""
    first = search_page(query)["storeProductInfos"]
    if not first:
        return PAGE_PARAM_CANDIDATES[0]
    for candidate in PAGE_PARAM_CANDIDATES:
        try:
            second = search_page(query, page=2, page_param=candidate)["storeProductInfos"]
        except Exception:
            continue
        if second and second[0]["sku"] != first[0]["sku"]:
            return candidate
    raise RuntimeError("No paging parameter worked — only the first page is reachable")


def category_names(product: dict) -> list[str]:
    names = [a["name"] for a in reversed(product.get("categoryAscendants", []))]
    if product.get("category"):
        names.append(product["category"]["name"])
    return names


def listing_row(product: dict, category: str) -> dict:
    """A price row built from a listing entry (no netKg here — the size comes from the name)."""
    from tracker.naming import parse_size

    unit, net_amount = parse_size(product["name"])
    if product.get("unit") == "GRAM":          # the shop knows better than the name
        unit, net_amount = "GRAM", None
    return {
        "store": "migros",
        "sku": product["sku"].zfill(8),
        "name": product["name"],
        "store_id": product.get("storeId"),
        "regular_price": int(product["regularPrice"]),
        "sale_price": int(product.get("shownPrice", product["regularPrice"])),
        "loyalty_price": None,
        "unit": unit,
        "net_amount": net_amount,
        "in_stock": product.get("status") == "IN_SALE",
        "product_id": f"migros-{product['sku'].zfill(8)}",
        "category": category,
    }


def wanted(product: dict, rule: dict) -> bool:
    """Does this listing entry belong in the sweep?

    include_categories matches the shop's own leaf category ("Günlük Süt"), which is
    what keeps plant drinks and milkshakes out of a milk sweep. match_category is the
    looser form: any category in the product's path.
    """
    if product.get("sponsored") or product.get("status") != "IN_SALE":
        return False

    path = category_names(product)
    leaf = path[-1] if path else ""
    include = rule.get("include_categories")
    if include and leaf not in include:
        return False
    if rule.get("match_category") and rule["match_category"] not in path:
        return False
    if set(rule.get("exclude_categories", [])) & set(path):
        return False
    return True


def usable_listing_products(search_info: dict, rule: dict | str | None = None) -> list[dict]:
    """In-sale, non-sponsored products that match the sweep rule."""
    if isinstance(rule, str) or rule is None:
        rule = {"match_category": rule}
    return [p for p in search_info.get("storeProductInfos", []) if wanted(p, rule)]
