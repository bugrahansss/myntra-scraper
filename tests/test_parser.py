import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from myntra_scraper import MyntraScraper, ScrapeError  # noqa: E402
from myntra_scraper.client import search_api_url  # noqa: E402
from myntra_scraper.parser import (  # noqa: E402
    extract_myx,
    listing_info,
    parse_listing,
    parse_product,
    product_url,
)

HERE = os.path.dirname(__file__)
LISTING = open(os.path.join(HERE, "fixtures", "listing_page.html"), encoding="utf-8").read()
PRODUCT = open(os.path.join(HERE, "fixtures", "product_page.html"), encoding="utf-8").read()
LIST_URL = "https://www.myntra.com/men-tshirts"


class FakeResponse:
    def __init__(self, status_code, text="", headers=None, body=None):
        self.status_code = status_code
        self.text = text if body is None else json.dumps(body)
        self.headers = headers or {}
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def api_page(ids, has_next=True):
    return {"hasNextPage": has_next, "products": [
        {"productId": i, "productName": f"Example {i}", "price": 100, "mrp": 200, "landingPageUrl": str(i)} for i in ids
    ] + [{"productId": 1, "isPLA": True}]}


class ParserTests(unittest.TestCase):
    def test_extract_myx_reads_the_right_script(self):
        data = extract_myx(LISTING)
        self.assertIn("searchData", data)
        self.assertEqual(extract_myx("<html>no data</html>"), {})

    def test_listing_skips_sponsored_products(self):
        ids = [r["product_id"] for r in parse_listing(LISTING)]
        self.assertEqual(ids, [90000001, 90000002, 90000003])

    def test_listing_fields(self):
        row = parse_listing(LISTING)[0]
        self.assertEqual(row["price_inr"], 449)
        self.assertEqual(row["mrp_inr"], 999)
        self.assertEqual(row["discount_pct"], 55)
        self.assertEqual(row["rating"], 4.31)
        self.assertEqual(row["sizes"], "S,M,L,XL")
        self.assertEqual(row["article_type"], "Tshirts")
        self.assertTrue(row["url"].startswith("https://www.myntra.com/tshirts/"))

    def test_no_discount_is_zero(self):
        self.assertEqual(parse_listing(LISTING)[1]["discount_pct"], 0)

    def test_listing_info(self):
        info = listing_info(LISTING)
        self.assertEqual(info["total_count"], 1234)
        self.assertEqual(info["sponsored_on_page"], 1)

    def test_product_summary(self):
        p = parse_product(PRODUCT)
        self.assertEqual(p["product_id"], 90000001)
        self.assertEqual(p["brand"], "Northwind Basics")
        self.assertEqual(p["price_inr"], 449)
        self.assertEqual(p["sizes_total"], 4)
        self.assertEqual(p["sizes_in_stock"], 3)
        self.assertEqual(p["units_in_stock"], 55)
        self.assertEqual(p["sellers"], "Example Retail One | Example Retail Two")

    def test_size_prices_differ_from_headline_price(self):
        p = parse_product(PRODUCT)
        self.assertEqual(p["lowest_size_price_inr"], 449)
        self.assertEqual(p["highest_size_price_inr"], 469)
        small = [s for s in p["sizes"] if s["size"] == "S"][0]
        self.assertEqual(small["price_inr"], 469)

    def test_one_row_per_size_and_seller(self):
        sizes = parse_product(PRODUCT)["sizes"]
        self.assertEqual(len(sizes), 5)
        medium = [s for s in sizes if s["size"] == "M"]
        self.assertEqual({s["seller"] for s in medium}, {"Example Retail One", "Example Retail Two"})

    def test_sold_out_size_has_zero_units(self):
        xl = [s for s in parse_product(PRODUCT)["sizes"] if s["size"] == "XL"][0]
        self.assertFalse(xl["available"])
        self.assertEqual(xl["units"], 0)

    def test_product_page_without_data(self):
        self.assertIsNone(parse_product(LISTING))

    def test_product_url(self):
        self.assertEqual(product_url("12027436"), "https://www.myntra.com/12027436")
        self.assertEqual(product_url("a/b/1/buy"), "https://www.myntra.com/a/b/1/buy")


class ClientTests(unittest.TestCase):
    def scraper(self, *responses):
        session = mock.Mock()
        session.get.side_effect = list(responses)
        return MyntraScraper(token="t", session=session, retries=2), session

    def test_requires_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                MyntraScraper()

    def test_plain_request_only_token_and_url(self):
        s, session = self.scraper(FakeResponse(200, LISTING))
        s.fetch(LIST_URL)
        self.assertEqual(session.get.call_args.kwargs["params"], {"token": "t", "url": LIST_URL})

    def test_retries_server_errors(self):
        with mock.patch("myntra_scraper.client.time.sleep"):
            s, session = self.scraper(FakeResponse(502), FakeResponse(200, LISTING))
            self.assertEqual(s.fetch(LIST_URL), LISTING)
            self.assertEqual(session.get.call_count, 2)

    def test_auth_error_is_not_retried(self):
        s, session = self.scraper(FakeResponse(401))
        with self.assertRaises(ScrapeError):
            s.fetch(LIST_URL)
        self.assertEqual(session.get.call_count, 1)

    def test_page_without_data_is_retried_then_an_error(self):
        with mock.patch("myntra_scraper.client.time.sleep"):
            s, session = self.scraper(*[FakeResponse(200, "<html>challenge</html>")] * 3)
            with self.assertRaises(ScrapeError):
                s.get_listing(LIST_URL)
            self.assertEqual(session.get.call_count, 3)

    def test_page_without_data_then_real_page(self):
        with mock.patch("myntra_scraper.client.time.sleep"):
            s, _ = self.scraper(FakeResponse(200, "<html>challenge</html>"), FakeResponse(200, LISTING))
            self.assertEqual(len(s.get_listing(LIST_URL)), 3)

    def test_single_page_listing(self):
        s, session = self.scraper(FakeResponse(200, LISTING))
        self.assertEqual(len(s.get_listing(LIST_URL)), 3)
        self.assertEqual(session.get.call_count, 1)

    def test_search_api_url_ignores_page_params_in_input(self):
        url = search_api_url("https://www.myntra.com/men-tshirts?sort=new&p=7", 3)
        self.assertTrue(url.startswith("https://www.myntra.com/gateway/v4/search/men-tshirts?"))
        self.assertIn("sort=new", url)
        self.assertIn("p=3", url)
        self.assertIn("o=99", url)
        self.assertNotIn("p=7", url)

    def test_cursor_is_passed_from_page_to_page(self):
        s, session = self.scraper(
            FakeResponse(200, LISTING, headers={"scrape.do-cookies": "at=abc; bm_sz=x"}),
            FakeResponse(200, body=api_page([11, 12]), headers={"pagination-context": "CUR1"}),
            FakeResponse(200, body=api_page([13, 14]), headers={"pagination-context": "CUR2"}),
            FakeResponse(200, body=api_page([15], has_next=False), headers={"pagination-context": "CUR3"}),
        )
        rows = s.get_listing(LIST_URL, max_pages=5)
        self.assertEqual([r["product_id"] for r in rows], [11, 12, 13, 14, 15])
        calls = session.get.call_args_list
        self.assertEqual(len(calls), 4)  # page visit + three API pages, stops at hasNextPage=false
        self.assertNotIn("sd-pagination-context", calls[1].kwargs["headers"])
        self.assertEqual(calls[2].kwargs["headers"]["sd-pagination-context"], "CUR1")
        self.assertEqual(calls[3].kwargs["headers"]["sd-pagination-context"], "CUR2")
        self.assertEqual(calls[1].kwargs["headers"]["sd-Cookie"], "at=abc; bm_sz=x")
        self.assertEqual(calls[1].kwargs["params"]["extraHeaders"], "true")

    def test_get_product(self):
        s, _ = self.scraper(FakeResponse(200, PRODUCT))
        self.assertEqual(s.get_product("90000001")["units_in_stock"], 55)


if __name__ == "__main__":
    unittest.main()
