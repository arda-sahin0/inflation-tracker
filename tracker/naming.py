"""Turn a shop's product name into the fields products.json needs."""
import re
import unicodedata

MULTIPACK = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(ml|lt|l|gr|g|kg)\b", re.IGNORECASE)
SINGLE = re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{3})+|\d+(?:[,.]\d+)?)\s*(ml|lt|l|gr|g|kg)\b", re.IGNORECASE)
BY_WEIGHT = re.compile(r"(?<![\d,.])\s*\bkg\s*$", re.IGNORECASE)
COUNTED = re.compile(r"(\d+)\s*['’]?\s*(li|lı|lu|lü)\b|(\badet\b)", re.IGNORECASE)

TO_BASE = {"ml": 1, "lt": 1000, "l": 1000, "gr": 1, "g": 1, "kg": 1000}
THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")


def _number(text: str) -> float:
    """Turkish numbers: '1.480' is one thousand four hundred eighty, '1,5' is one and a half."""
    if THOUSANDS.match(text):
        return float(text.replace(".", ""))
    return float(text.replace(",", "."))


EGG_SIZE = re.compile(r"(\d+)\s*-\s*(\d+)\s*g\b|(\d+)\s*g\b", re.IGNORECASE)


def _eggs(name: str) -> float | None:
    """Egg packs state the weight of ONE egg ("20'li XL 73 G", "30'lu 53-62 G"): count x egg weight,
    using the middle of a size range. That is also how A101 computes its own netWeight."""
    count = COUNTED.search(name)
    size = EGG_SIZE.search(name)
    if not (count and count.group(1) and size):
        return None
    low, high, single = size.groups()
    per_egg = (int(low) + int(high)) / 2 if low else int(single)
    return int(count.group(1)) * per_egg


def parse_size(name: str) -> tuple[str, float | None]:
    """('GRAM', None) for goods priced per kg, else ('PIECE', net amount in g/ml or None)."""
    if "yumurta" in name.lower():
        return "PIECE", _eggs(name)

    match = MULTIPACK.search(name)
    if match:
        count, amount, unit = match.groups()
        return "PIECE", int(count) * _number(amount) * TO_BASE[unit.lower()]

    sizes = [_number(a) * TO_BASE[u.lower()] for a, u in SINGLE.findall(name)]
    if sizes:
        return "PIECE", max(sizes)

    if BY_WEIGHT.search(name):
        return "GRAM", None

    return "PIECE", None


def slugify(text: str) -> str:
    text = text.replace("ı", "i").replace("İ", "i").replace("ş", "s").replace("Ş", "s")
    text = text.replace("ğ", "g").replace("Ğ", "g").replace("ç", "c").replace("Ç", "c")
    text = text.replace("ö", "o").replace("Ö", "o").replace("ü", "u").replace("Ü", "u")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def suggest_id(name: str, store: str, words: int = 3) -> str:
    """A short, stable id: first few words of the name, the size, then the store."""
    unit, amount = parse_size(name)
    parts = [w for w in slugify(name).split("-") if w not in ("kg", "g", "l", "ml", "lt", "gr")]
    slug = "-".join(parts[:words])
    liquid = bool(re.search(r"\b(ml|lt|l)\b", name, re.IGNORECASE))
    if unit == "GRAM":
        size = "kg"
    elif amount and amount >= 1000 and amount % 1000 == 0:
        size = f"{amount // 1000:g}" + ("l" if liquid else "kg")
    elif amount:
        size = f"{amount:g}" + ("ml" if liquid else "g")
    else:
        size = ""
    return "-".join(part for part in (slug, size, store) if part)
