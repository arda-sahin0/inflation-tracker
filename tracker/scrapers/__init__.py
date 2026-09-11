from urllib.parse import urlparse

from . import migros

SCRAPERS = {
    "www.migros.com.tr": migros.scrape,
}


def get_scraper(url: str):
    domain = urlparse(url).netloc.lower()
    try:
        return SCRAPERS[domain]
    except KeyError:
        raise ValueError(f"No scraper for domain {domain!r}") from None