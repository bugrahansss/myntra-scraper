"""Scrape Myntra listings and product pages (price, MRP, sizes, stock per seller) with Python."""

from .client import MyntraScraper, ScrapeError
from .parser import (
    LISTING_FIELDS,
    PRODUCT_FIELDS,
    SIZE_FIELDS,
    extract_myx,
    listing_info,
    parse_listing,
    parse_product,
    parse_products,
    parse_sizes,
    product_url,
)

__all__ = [
    "LISTING_FIELDS",
    "MyntraScraper",
    "PRODUCT_FIELDS",
    "SIZE_FIELDS",
    "ScrapeError",
    "extract_myx",
    "listing_info",
    "parse_listing",
    "parse_product",
    "parse_products",
    "parse_sizes",
    "product_url",
]

__version__ = "0.1.1"
