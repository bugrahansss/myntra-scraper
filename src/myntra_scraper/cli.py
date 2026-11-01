"""Command line entry point: ``myntra-scraper listing URL`` / ``myntra-scraper product URL ...``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import List, Optional

from . import __version__
from .client import TOKEN_ENV, MyntraScraper, ScrapeError
from .parser import LISTING_FIELDS, PRODUCT_FIELDS, SIZE_FIELDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myntra-scraper",
        description="Scrape Myntra listings and product pages (price, MRP, sizes, stock per seller) into JSON or CSV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    lst = sub.add_parser("listing", help="Products of a listing or search page, 50 per page")
    lst.add_argument("url", help="A Myntra listing or search URL, e.g. https://www.myntra.com/men-tshirts?sort=new")
    lst.add_argument("--pages", type=int, default=1, help="Pages of 50 to read (default 1)")

    prod = sub.add_parser("product", help="Product pages: summary, or one row per size and seller with --sizes")
    prod.add_argument("urls", nargs="*", help="Myntra product URLs or style ids")
    prod.add_argument("-i", "--input", help="Text file with one URL per line, or a CSV with a 'url' column")
    prod.add_argument("--limit", type=int, default=0, help="Stop after this many products (0 = all)")
    prod.add_argument("--sizes", action="store_true", help="Output one row per size and seller")

    for p in (lst, prod):
        p.add_argument("-t", "--token", help=f"Scrape.do API token (default: ${TOKEN_ENV})")
        p.add_argument("-f", "--format", choices=("json", "csv"), default="json")
        p.add_argument("-o", "--output", help="Write to this file instead of stdout")
    return parser


def _read_urls(args: argparse.Namespace) -> List[str]:
    urls = list(args.urls)
    if args.input:
        with open(args.input, encoding="utf-8", newline="") as handle:
            if args.input.endswith(".csv"):
                urls.extend(row["url"] for row in csv.DictReader(handle) if row.get("url"))
            else:
                urls.extend(line.strip() for line in handle if line.strip() and not line.startswith("#"))
    return urls[: args.limit] if args.limit else urls


def _write(rows: List[dict], fields: List[str], fmt: str, stream) -> None:
    if fmt == "csv":
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        json.dump(rows, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scraper = MyntraScraper(token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    failures = 0
    if args.command == "listing":
        fields = LISTING_FIELDS
        try:
            rows = scraper.get_listing(args.url, max_pages=max(1, args.pages))
        except (ScrapeError, ValueError) as exc:
            print(f"fail  {args.url}: {exc}", file=sys.stderr)
            return 1
        print(f"{len(rows)} products", file=sys.stderr)
    else:
        fields = SIZE_FIELDS if args.sizes else PRODUCT_FIELDS
        urls = _read_urls(args)
        if not urls:
            print("No URLs given. Pass product URLs or --input FILE.", file=sys.stderr)
            return 2
        rows = []
        for url in urls:
            try:
                product = scraper.get_product(url)
            except (ScrapeError, ValueError) as exc:
                failures += 1
                print(f"fail  {url}: {exc}", file=sys.stderr)
                continue
            if not product:
                failures += 1
                print(f"fail  {url}: no product data", file=sys.stderr)
                continue
            rows.extend(product["sizes"] if args.sizes else [product])
            print(f"ok    {url}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="" if args.format == "csv" else None) as handle:
            _write(rows, fields, args.format, handle)
        print(f"Saved {len(rows)} rows to {args.output}", file=sys.stderr)
    else:
        _write(rows, fields, args.format, sys.stdout)
    return 1 if failures and not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
