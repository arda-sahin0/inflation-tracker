"""
The countries the tracker covers and the stores priced in each.

A market keeps its own configuration in markets/<key>/ (weights, shelf maps,
catalogues, sweeps) and its own data in data/raw/<key>/ and data/index/<key>/.
Every store's scraper module offers the same functions: scrape, sweep_rows,
crawl, shelf_label and pages_for.
"""
import os
from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

from tracker import ROOT
from tracker.scrapers import a101, migros

IN_CI = os.getenv("GITHUB_ACTIONS") == "true"


@dataclass(frozen=True)
class Store:
    key: str
    name: str
    domain: str
    store_id: int | str
    scraper: ModuleType


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    currency: str
    timezone: tzinfo
    site_path: str
    skip_aisles: frozenset[str]
    stores: tuple[Store, ...]

    @property
    def config(self) -> Path:
        return ROOT / "markets" / self.key

    @property
    def raw(self) -> Path:
        return ROOT / "data" / "raw" / self.key

    @property
    def output(self) -> Path:
        """Where a run writes: data/index/<key> on GitHub, data/local/<key> on your machine."""
        return ROOT / "data" / ("index" if IN_CI else "local") / self.key

    @property
    def daily(self) -> Path:
        """Where a day's prices are saved: data/raw/<key> on GitHub, data/local/<key> on your machine."""
        return self.raw if IN_CI else ROOT / "data" / "local" / self.key

    @property
    def site(self) -> Path:
        return ROOT / "docs" / self.site_path / "index.html"


TURKEY = Market(
    key="tr",
    name="Türkiye",
    currency="TL",
    timezone=timezone(timedelta(hours=3)),
    site_path="",
    skip_aisles=frozenset({"Elektronik", "Çiçek", "Evcil Hayvan", "Kitap, Kırtasiye, Oyuncak", "Ev, Yaşam", "Bebek"}),
    stores=(
        Store("migros", "Migros", "www.migros.com.tr", 20000000000607, migros),
        Store("a101", "A101", "www.a101.com.tr", a101.STORE, a101),
    ),
)

MARKETS = {market.key: market for market in (TURKEY,)}
STORES = {store.key: store for market in MARKETS.values() for store in market.stores}


def select(key: str | None = None) -> list[Market]:
    """One market by its key, or all of them when no key is given."""
    return list(MARKETS.values()) if key is None else [MARKETS[key]]


def market_of(store_key: str) -> Market:
    return next(m for m in MARKETS.values() if any(s.key == store_key for s in m.stores))


def locate(url: str) -> tuple[Market, Store]:
    """The market and store a shop link belongs to."""
    domain = urlparse(url if "//" in url else f"https://{url}").netloc.lower()
    for market in MARKETS.values():
        for store in market.stores:
            if store.domain == domain:
                return market, store
    raise ValueError(f"no store for {domain!r}; known: {', '.join(s.domain for s in STORES.values())}")
