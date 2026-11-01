"""Parse Myntra listing and product pages.

Myntra renders every page on the server and ships the data in one inline script:
``<script>window.__myx = {...}</script>``. Listing pages keep their products in
``searchData.results.products``; product pages keep the full style in ``pdpData``.
No HTML selectors are needed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

MYNTRA = "https://www.myntra.com"
_MYX_RE = re.compile(r"window\.__myx\s*=\s*")
_decoder = json.JSONDecoder()

LISTING_FIELDS = [
    "product_id",
    "name",
    "brand",
    "price_inr",
    "mrp_inr",
    "discount_pct",
    "rating",
    "rating_count",
    "sizes",
    "gender",
    "article_type",
    "colour",
    "image",
    "url",
]

PRODUCT_FIELDS = [
    "product_id",
    "name",
    "brand",
    "price_inr",
    "mrp_inr",
    "discount_pct",
    "rating",
    "rating_count",
    "colour",
    "article_type",
    "gender",
    "country_of_origin",
    "sizes_in_stock",
    "sizes_total",
    "units_in_stock",
    "lowest_size_price_inr",
    "highest_size_price_inr",
    "sellers",
    "url",
]

SIZE_FIELDS = [
    "product_id",
    "size",
    "sku_id",
    "available",
    "seller",
    "seller_id",
    "price_inr",
    "mrp_inr",
    "units",
]


def extract_myx(html: str) -> Dict[str, Any]:
    """The ``window.__myx`` object of a Myntra page, or ``{}`` if the page has none."""
    match = _MYX_RE.search(html or "")
    if not match:
        return {}
    try:
        data, _ = _decoder.raw_decode(html, match.end())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _pct(price: Any, mrp: Any) -> int:
    if isinstance(price, (int, float)) and isinstance(mrp, (int, float)) and mrp > 0 and price <= mrp:
        return round((mrp - price) / mrp * 100)
    return 0


def _round(value: Any, digits: int = 2) -> Optional[float]:
    return round(value, digits) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def product_url(path_or_id: Any) -> str:
    """Absolute product URL from a ``landingPageUrl`` or a bare style id."""
    text = str(path_or_id or "").strip()
    if not text:
        return ""
    if text.startswith("http"):
        return text
    return f"{MYNTRA}/{text.lstrip('/')}"


def listing_info(html: str) -> Dict[str, Any]:
    """Total matches and paging flags of a listing page."""
    results = (extract_myx(html).get("searchData") or {}).get("results") or {}
    return {
        "total_count": results.get("totalCount"),
        "has_next_page": results.get("hasNextPage"),
        "products_on_page": len(results.get("products") or []),
        "sponsored_on_page": len(results.get("plaProducts") or []),
    }


def parse_products(items: List[Any]) -> List[Dict[str, Any]]:
    """Rows for a list of Myntra product cards (from the page or from the search API).

    Sponsored products carry ``isPLA: true`` (and normally sit in a separate
    ``plaProducts`` array); they are skipped so ads don't pose as results.
    """
    rows = []
    for item in items or []:
        if not isinstance(item, dict) or item.get("isPLA"):
            continue
        price, mrp = item.get("price"), item.get("mrp")
        article = item.get("articleType")
        rows.append(
            {
                "product_id": item.get("productId"),
                "name": item.get("productName"),
                "brand": item.get("brand"),
                "price_inr": price,
                "mrp_inr": mrp,
                "discount_pct": _pct(price, mrp),
                "rating": _round(item.get("rating")),
                "rating_count": item.get("ratingCount"),
                "sizes": item.get("sizes"),
                "gender": item.get("gender"),
                "article_type": article.get("typeName") if isinstance(article, dict) else article,
                "colour": item.get("primaryColour"),
                "image": item.get("searchImage"),
                "url": product_url(item.get("landingPageUrl")),
            }
        )
    return rows


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """One row per organic product on a listing page (the first 50 results)."""
    results = (extract_myx(html).get("searchData") or {}).get("results") or {}
    return parse_products(results.get("products") or [])


def parse_sizes(pdp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per size and seller: Myntra lists each seller's own price and stock count."""
    sellers = {s.get("sellerPartnerId"): s.get("sellerName") for s in pdp.get("sellers") or [] if isinstance(s, dict)}
    rows = []
    for size in pdp.get("sizes") or []:
        offers = size.get("sizeSellerData") or [{}]
        for offer in offers:
            seller_id = offer.get("sellerPartnerId")
            rows.append(
                {
                    "product_id": pdp.get("id"),
                    "size": size.get("label"),
                    "sku_id": size.get("skuId"),
                    "available": bool(size.get("available")),
                    "seller": sellers.get(seller_id),
                    "seller_id": seller_id,
                    "price_inr": offer.get("discountedPrice"),
                    "mrp_inr": offer.get("mrp"),
                    "units": offer.get("availableCount", 0) if size.get("available") else 0,
                }
            )
    return rows


def parse_product(html: str) -> Optional[Dict[str, Any]]:
    """Product summary plus per-size, per-seller rows (``sizes``) for one product page."""
    pdp = extract_myx(html).get("pdpData")
    if not isinstance(pdp, dict) or not pdp.get("id"):
        return None
    sizes = parse_sizes(pdp)
    price_block = pdp.get("price") or {}
    price, mrp = price_block.get("discounted"), price_block.get("mrp", pdp.get("mrp"))
    ratings = pdp.get("ratings") or {}
    analytics = pdp.get("analytics") or {}
    brand = pdp.get("brand")
    in_stock = [s for s in sizes if s["available"] and s["units"]]
    offer_prices = [s["price_inr"] for s in in_stock if isinstance(s["price_inr"], (int, float))]
    return {
        "product_id": pdp.get("id"),
        "name": pdp.get("name"),
        "brand": brand.get("name") if isinstance(brand, dict) else brand,
        "price_inr": price,
        "mrp_inr": mrp,
        "discount_pct": _pct(price, mrp),
        "rating": _round(ratings.get("averageRating")),
        "rating_count": ratings.get("totalCount"),
        "colour": pdp.get("baseColour"),
        "article_type": analytics.get("articleType"),
        "gender": analytics.get("gender"),
        "country_of_origin": pdp.get("countryOfOrigin"),
        "sizes_in_stock": len({s["size"] for s in in_stock}),
        "sizes_total": len(pdp.get("sizes") or []),
        "units_in_stock": sum(s["units"] for s in in_stock),
        "lowest_size_price_inr": min(offer_prices) if offer_prices else None,
        "highest_size_price_inr": max(offer_prices) if offer_prices else None,
        "sellers": " | ".join(sorted({s["seller"] for s in sizes if s["seller"]})),
        "url": product_url(pdp.get("landingPageUrl")) or product_url(pdp.get("id")),
        "attributes": pdp.get("articleAttributes") or {},
        "sizes": sizes,
    }
