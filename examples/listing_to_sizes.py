"""Read a few pages of a Myntra listing, then stock and price per size for the first products.

Usage:
    export SCRAPEDO_TOKEN=your_token
    python listing_to_sizes.py "https://www.myntra.com/men-tshirts?sort=new" 3 10

Writes myntra-listing.csv (price, MRP, discount, rating per product) and
myntra-sizes.csv (one row per size and seller: price, MRP, units in stock).
"""

import csv
import sys

from myntra_scraper import LISTING_FIELDS, SIZE_FIELDS, MyntraScraper, ScrapeError


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(listing_url: str, pages: int = 3, max_products: int = 10) -> None:
    scraper = MyntraScraper()  # reads SCRAPEDO_TOKEN
    listing = scraper.get_listing(listing_url, max_pages=pages)
    write("myntra-listing.csv", LISTING_FIELDS, listing)
    print(f"Saved {len(listing)} products to myntra-listing.csv")

    sizes = []
    for row in listing[:max_products]:
        try:
            product = scraper.get_product(row["url"])
        except ScrapeError as exc:
            print(f"skipped {row['url']}: {exc}")
            continue
        if not product:
            continue
        sizes.extend(product["sizes"])
        print(
            f"{product['name'][:50]} | listed Rs {row['price_inr']} | sizes Rs "
            f"{product['lowest_size_price_inr']}-{product['highest_size_price_inr']} | "
            f"{product['units_in_stock']} units, {product['sizes_in_stock']}/{product['sizes_total']} sizes in stock"
        )
    write("myntra-sizes.csv", SIZE_FIELDS, sizes)
    print(f"Saved {len(sizes)} size rows to myntra-sizes.csv")


if __name__ == "__main__":
    main(
        sys.argv[1],
        int(sys.argv[2]) if len(sys.argv) > 2 else 3,
        int(sys.argv[3]) if len(sys.argv) > 3 else 10,
    )
