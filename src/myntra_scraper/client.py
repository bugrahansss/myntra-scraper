"""Fetch Myntra pages through the Scrape.do API.

Myntra sits behind Akamai Bot Manager. A plain ``requests`` call or ``curl`` gets
no answer at all: the connection opens and hangs until the client times out.
Through Scrape.do a plain request (no extra parameters, 1 credit) returns the
full page in about 3 seconds.

Paging is the hard part. Listing pages ignore ``?p=2`` and return the same first
50 products every time. The site pages through its search API instead
(``/gateway/v4/search/<slug>``), which needs the session cookies from a page
visit and a ``pagination-context`` cursor: every response hands one back in a
header, and the next request has to send it.
"""

from __future__ import annotations

import os
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .parser import MYNTRA, extract_myx, listing_info, parse_listing, parse_product, parse_products, product_url

API_URL = "https://api.scrape.do/"
TOKEN_ENV = "SCRAPEDO_TOKEN"
PAGE_SIZE = 50
SEARCH_HEADERS = {
    "Accept": "application/json",
    "x-meta-app": "channel=web",
    "app": "web",
    "X-myntraweb": "Yes",
}


def _has_page_data(response: requests.Response) -> bool:
    return bool(extract_myx(response.text))


def _has_session_cookie(cookies: str) -> bool:
    return any(part.strip().startswith("at=") for part in (cookies or "").split(";"))


def _is_json(response: requests.Response) -> bool:
    try:
        return isinstance(response.json(), dict)
    except ValueError:
        return False


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched.

    ``from_target`` is True when the status came from Myntra (Scrape.do reports it in the
    ``scrape.do-initial-status-code`` header) and False when Scrape.do refused the request,
    for example a 401 for a wrong token.
    """

    def __init__(self, message: str, status_code: Optional[int] = None, from_target: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.from_target = from_target


def search_api_url(listing_url: str, page: int) -> str:
    """Myntra's search API URL for page ``page`` of a listing or search URL."""
    parsed = urllib.parse.urlparse(listing_url if "://" in listing_url else f"{MYNTRA}/{listing_url.lstrip('/')}")
    slug = parsed.path.strip("/")
    if not slug:
        raise ValueError("Pass a Myntra listing URL such as https://www.myntra.com/men-tshirts")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query) if k not in ("p", "o", "rows", "plaEnabled")]
    query += [
        ("rows", str(PAGE_SIZE)),
        ("o", str(max(0, (page - 1) * PAGE_SIZE - 1))),
        ("plaEnabled", "false"),
        ("p", str(page)),
    ]
    return f"{MYNTRA}/gateway/v4/search/{slug}?{urllib.parse.urlencode(query)}"


class MyntraScraper:
    """Fetch and parse Myntra listing and product pages.

    >>> scraper = MyntraScraper(token="YOUR_SCRAPEDO_TOKEN")
    >>> rows = scraper.get_listing("https://www.myntra.com/men-tshirts", max_pages=3)
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = 120.0,
        retries: int = 2,
        session: Optional[requests.Session] = None,
    ):
        self.token = token or os.environ.get(TOKEN_ENV, "")
        if not self.token:
            raise ValueError(f"A Scrape.do API token is required. Pass token=... or set {TOKEN_ENV}.")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()

    # ------------------------------------------------------------------ transport

    def request(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        valid: Optional[Callable[[requests.Response], bool]] = None,
    ) -> requests.Response:
        """One Scrape.do call, retried on 429/5xx and on a 200 that ``valid`` rejects
        (Akamai sometimes answers 200 with a page that has no data).
        ``headers`` are forwarded to Myntra through Scrape.do's ``extraHeaders``."""
        params = {"token": self.token, "url": url}
        send = None
        if headers:
            params["extraHeaders"] = "true"
            send = {f"sd-{k}": v for k, v in headers.items()}
        last_error: Optional[ScrapeError] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(API_URL, params=params, headers=send, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = ScrapeError(f"Request failed: {str(exc).replace(self.token, '***')}")
            else:
                if response.status_code == 200 and response.text:
                    if valid is None or valid(response):
                        return response
                    last_error = ScrapeError(f"{url} came back without Myntra's data", 200)
                    if attempt < self.retries:
                        time.sleep(2 * (attempt + 1))
                    continue
                from_target = "scrape.do-initial-status-code" in {k.lower() for k in response.headers}
                if response.status_code == 401 and not from_target:
                    raise ScrapeError("Scrape.do rejected the token (401): it is wrong or out of credits.", 401)
                who = "Myntra" if from_target else "Scrape.do"
                last_error = ScrapeError(
                    f"{who} returned {response.status_code} for {url}", response.status_code, from_target
                )
                # Client errors (bad token, bad URL, expired session) will not fix themselves
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.retries:
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def fetch(self, url: str) -> str:
        """Raw HTML of a Myntra page; a page without ``window.__myx`` counts as a failure."""
        return self.request(url, valid=_has_page_data).text

    # -------------------------------------------------------------------- listing

    def open_session(self, listing_url: str, attempts: int = 4) -> Tuple[str, str]:
        """Visit the listing page: returns (html, cookie header) for the search API.

        Some visits come back with a single cookie, and the search API answers 401 to that
        session, so the visit is repeated until Myntra's ``at`` cookie is there."""
        html, cookies = "", ""
        for _ in range(max(1, attempts)):
            response = self.request(listing_url, valid=_has_page_data)
            html, cookies = response.text, response.headers.get("scrape.do-cookies", "")
            if _has_session_cookie(cookies):
                break
        return html, cookies

    def search_page(self, listing_url: str, page: int, cookies: str, cursor: str = "") -> Tuple[Dict[str, Any], str]:
        """One page of the search API: (JSON body, cursor for the next page)."""
        headers = dict(SEARCH_HEADERS, Cookie=cookies)
        if cursor:
            headers["pagination-context"] = cursor
        response = self.request(search_api_url(listing_url, page), headers=headers, valid=_is_json)
        return response.json(), response.headers.get("pagination-context", "")

    def get_listing(self, url: str, max_pages: int = 1) -> List[dict]:
        """Organic products of a listing or search URL, ``max_pages`` pages of 50.

        ``max_pages=1`` reads the page itself (1 credit). More pages cost one visit
        for the cookies plus one search API call per page.
        """
        if max_pages <= 1:
            return parse_listing(self.fetch(url))
        _, cookies = self.open_session(url)
        rows: Dict[Any, dict] = {}
        cursor = ""
        refreshes = 0
        page = 1
        while page <= max_pages:
            try:
                body, cursor = self.search_page(url, page, cookies, cursor)
            except ScrapeError as exc:
                # Myntra answers 401 when it doesn't accept the session: get fresh cookies, retry the page.
                if exc.from_target and exc.status_code == 401 and refreshes < 2:
                    refreshes += 1
                    _, cookies = self.open_session(url)
                    continue
                raise
            page += 1
            new = parse_products(body.get("products") or [])
            for row in new:
                rows.setdefault(row["product_id"], row)
            if not new or not body.get("hasNextPage") or not cursor:
                break
        return list(rows.values())

    def get_listing_info(self, url: str) -> dict:
        return listing_info(self.fetch(url))

    # -------------------------------------------------------------------- product

    def get_product(self, url_or_id: Any) -> Optional[dict]:
        """Product summary plus one row per size and seller (``sizes``)."""
        return parse_product(self.fetch(product_url(url_or_id)))
