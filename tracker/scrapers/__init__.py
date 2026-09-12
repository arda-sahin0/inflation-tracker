from urllib.parse import urlparse

from . import a101, migros

SCRAPERS = {
    "www.migros.com.tr": migros.scrape,
    "www.a101.com.tr": a101.scrape,
}


def get_scraper(url: str):
    domain = urlparse(url).netloc.lower()
    try:
        return SCRAPERS[domain]
    except KeyError:
        raise ValueError(f"No scraper for domain {domain!r}") from None