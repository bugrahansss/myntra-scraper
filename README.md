# myntra-scraper

[![PyPI](https://img.shields.io/pypi/v/myntra-scraper)](https://pypi.org/project/myntra-scraper/)
[![Python](https://img.shields.io/pypi/pyversions/myntra-scraper)](https://pypi.org/project/myntra-scraper/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Python scraper for [Myntra](https://www.myntra.com), India's largest fashion marketplace. Two jobs:

- **Listings and search:** any listing or search URL (`/men-tshirts`, `/levis?rawQuery=levis`, with sort and filters) → name, brand, price, MRP, discount, rating, rating count, sizes, colour, image and URL. **Real pagination**, 50 products per page, sponsored products left out.
- **Product pages:** price, MRP, rating and attributes, plus **one row per size and seller with that seller's price and the exact units in stock**.

Output as Python dicts, JSON or CSV. One dependency (`requests`), no browser.

```bash
pip install myntra-scraper
```

## Why a plain request fails

Myntra sits behind Akamai Bot Manager (`_abck`, `bm_sz` cookies). A script doesn't get an error, it gets nothing:

| Request | Result |
| --- | --- |
| `requests`, default or Chrome user agent | connection opens, no bytes, timeout after 20 s |
| `curl` (HTTP/2) | `stream was not closed cleanly: INTERNAL_ERROR` |
| Through Scrape.do, no parameters | 200 in ~3 s, full page, 1 credit |

Pages are fetched through the [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=myntra-scraper) API with a plain request: no `render`, no `super`, 1 credit per page. You need a Scrape.do API token; the free plan includes 1,000 credits a month.

## Quick start

```python
from myntra_scraper import MyntraScraper

scraper = MyntraScraper(token="YOUR_SCRAPEDO_TOKEN")  # or set SCRAPEDO_TOKEN

# 3 pages of 50 = 150 products (4 credits: one page visit + three API pages)
rows = scraper.get_listing("https://www.myntra.com/men-tshirts?sort=new", max_pages=3)
for row in rows[:3]:
    print(row["brand"], row["name"], row["price_inr"], row["mrp_inr"], row["discount_pct"])

product = scraper.get_product(rows[0]["url"])
print(product["units_in_stock"], product["sizes_in_stock"], "/", product["sizes_total"], "sizes in stock")
for size in product["sizes"]:
    print(size["size"], size["seller"], size["price_inr"], size["units"])
```

### Command line

```bash
export SCRAPEDO_TOKEN=your_token

# 3 pages of a listing, CSV
myntra-scraper listing "https://www.myntra.com/men-tshirts?sort=new" --pages 3 -f csv -o myntra-listing.csv

# product summaries for the first 10 products from that file
myntra-scraper product -i myntra-listing.csv --limit 10 -f csv -o myntra-products.csv

# one row per size and seller
myntra-scraper product -i myntra-listing.csv --limit 10 --sizes -f csv -o myntra-sizes.csv
```

`product` reads the `url` column of the listing CSV, so the commands chain.

### Output

Size rows (from the fictional test page in [`tests/fixtures`](tests/fixtures/product_page.html)):

```json
[
  {"product_id": 90000001, "size": "M", "sku_id": 900000012, "available": true,
   "seller": "Example Retail Two", "seller_id": 202, "price_inr": 449, "mrp_inr": 999, "units": 5},
  {"product_id": 90000001, "size": "M", "sku_id": 900000012, "available": true,
   "seller": "Example Retail One", "seller_id": 101, "price_inr": 469, "mrp_inr": 999, "units": 30}
]
```

Listing columns: `product_id, name, brand, price_inr, mrp_inr, discount_pct, rating, rating_count, sizes, gender, article_type, colour, image, url`.

Product columns: `product_id, name, brand, price_inr, mrp_inr, discount_pct, rating, rating_count, colour, article_type, gender, country_of_origin, sizes_in_stock, sizes_total, units_in_stock, lowest_size_price_inr, highest_size_price_inr, sellers, url` (plus `attributes` and `sizes` in Python/JSON).

## How it works

**The data is one JSON object.** Myntra renders every page on the server and puts the data in an inline script, `window.__myx = {...}`. Listings keep their products in `searchData.results.products`, product pages keep everything in `pdpData`. The scraper finds the assignment and reads the object with `json.JSONDecoder.raw_decode`. No CSS selectors.

**Sponsored products are separate.** A listing page carries the organic results in `products` and the ads in `plaProducts` (18 of them on a men's T-shirts page). Only the organic products are returned.

**`?p=2` is ignored.** Ask the HTML for page 2, 3 or 50 and you get the first 50 products again. In our test, page 2 of a listing sorted by newest shared 49 of 50 products with page 1. The site pages through its search API, `/gateway/v4/search/<slug>`, which:

1. returns 401 without the cookies a page visit sets (`at`, `_abck`, `bm_sz` and others), and
2. ignores `p` and `o` as well, unless the request carries a `pagination-context` header. Every API response returns a new `pagination-context` header; sending it back moves to the next 50.

Not every visit hands out a usable session: in our tests roughly one visit in four came back with a single cookie, and the API answered 401 to it. The scraper repeats the visit until Myntra's `at` cookie is there, and gets fresh cookies if the API still says 401.

So `get_listing(max_pages=N)` visits the listing once for its cookies, then calls the search API N times, passing the cursor from each response to the next request (Scrape.do forwards the cookie and cursor headers with `extraHeaders=true`). In our test, four API pages returned 200 distinct products.

**Listing price vs size price.** A listing card has one price. On the product page every size lists its sellers, each with its own price and stock count. On a Levi's T-shirt listed at ₹389, sizes M and XL had a seller at ₹389 while sizes S and L were only available from a second seller at ₹402. The `sizes` rows keep that split.

## Limits

- **One location.** Prices and stock are what Myntra shows without a delivery pincode.
- **Credits.** `max_pages=1` reads the listing HTML (1 credit). More pages cost one page visit plus one credit per API page.
- **Errors.** Non-200 responses raise `ScrapeError` with the status code; `from_target` tells a Myntra status from a Scrape.do one (a wrong token is a Scrape.do 401). A 200 without Myntra's data (an Akamai page) is treated as a failure. Server errors, 429s and empty pages are retried twice; client errors are not.

## Responsible use

The scraper reads listing, product and search pages, which Myntra's robots.txt allows (`Allow: /`); it does not touch cart, checkout, account or size-chart paths. Product data is not personal data. Read Myntra's terms for your use case and keep request rates modest. This is not legal advice.

## Development

```bash
git clone https://github.com/bugrahansss/myntra-scraper
cd myntra-scraper
pip install -e .
python -m unittest discover -s tests -v
```

The tests run offline against fictional fixture pages.

## License

MIT

---

Built and tested with [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=myntra-scraper), November 2026.
