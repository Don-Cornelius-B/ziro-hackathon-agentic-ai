"""
Dual-layer Ingestion Engine for Competitor Changelog Scout.
Handles static HTTP fetching with BeautifulSoup, dynamic SPA rendering with Playwright,
and zero-latency local mock fixtures.
"""

import logging
import re
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from core.schemas import RawScrapedItem, utc_now
from fixtures.mock_data import MOCK_FIXTURES, get_mock_item

logger = logging.getLogger(__name__)


def clean_html(html_text: str) -> str:
    """Extract clean readable text from HTML by removing boilerplate tags."""
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["head", "script", "style", "nav", "footer", "header", "noscript", "aside", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    # Collapse multiple whitespaces
    return " ".join(text.split())


def extract_title(html_text: str, fallback_url: str = "") -> str:
    """Extract feature headline from HTML, avoiding boilerplate navigation and site titles."""
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    headline = None
    article_header = soup.find(["article", "main", "div"], class_=re.compile(r'(entry|post|release|changelog)', re.I))
    if article_header:
        h = article_header.find(["h1", "h2", "h3"])
        if h:
            headline = h.get_text(strip=True)

    if not headline:
        h1 = soup.find("h1")
        headline = h1.get_text(strip=True) if h1 else None

    if headline:
        return headline

    if soup.title and soup.title.string:
        return soup.title.string.strip()

    if fallback_url:
        slug = fallback_url.rstrip("/").split("/")[-1].replace("-", " ").capitalize()
        if slug:
            return slug
    return "Changelog Update"


def fetch_page(
    url: str,
    is_changelog: bool = True,
    force_mock: bool = False,
    mock_key: Optional[str] = None,
) -> RawScrapedItem:
    """
    Fetch and parse page content using static HTTP with fallback to mock fixtures.
    Gracefully catches network timeouts and HTTP errors without throwing.
    """
    if force_mock:
        key = mock_key or "tc1_changelog"
        if key in MOCK_FIXTURES:
            return get_mock_item(key)
        logger.warning(f"Mock key '{key}' not found, falling back to tc1_changelog.")
        return get_mock_item("tc1_changelog")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 CompetitorChangelogScout/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            status_code = response.status_code

            if status_code >= 400:
                return RawScrapedItem(
                    source_url=url,
                    title=f"HTTP {status_code} Error",
                    raw_content="",
                    is_changelog=is_changelog,
                    http_status=status_code,
                    fetch_error=f"HTTP error {status_code}: {response.reason_phrase}",
                    scraped_at=utc_now(),
                )

            html = response.text
            title = extract_title(html, url)
            clean_content = clean_html(html)

            return RawScrapedItem(
                source_url=str(response.url),
                title=title,
                raw_content=clean_content,
                is_changelog=is_changelog,
                http_status=status_code,
                fetch_error=None,
                scraped_at=utc_now(),
            )

    except httpx.TimeoutException as exc:
        logger.error(f"Timeout fetching {url}: {exc}")
        return RawScrapedItem(
            source_url=url,
            title="Connection Timeout",
            raw_content="",
            is_changelog=is_changelog,
            http_status=504,
            fetch_error=f"Timeout after 8.0 seconds: {str(exc)}",
            scraped_at=utc_now(),
        )
    except httpx.RequestError as exc:
        logger.error(f"Network error fetching {url}: {exc}")
        return RawScrapedItem(
            source_url=url,
            title="Network Error",
            raw_content="",
            is_changelog=is_changelog,
            http_status=503,
            fetch_error=f"Network connection failed: {str(exc)}",
            scraped_at=utc_now(),
        )
    except Exception as exc:
        logger.error(f"Unexpected error fetching {url}: {exc}")
        return RawScrapedItem(
            source_url=url,
            title="Ingestion Error",
            raw_content="",
            is_changelog=is_changelog,
            http_status=500,
            fetch_error=f"Internal ingestion exception: {str(exc)}",
            scraped_at=utc_now(),
        )


def fetch_dynamic_page(url: str, is_changelog: bool = True) -> RawScrapedItem:
    """
    Dynamic page fetcher using Playwright headless browser for JavaScript-heavy SPAs.
    Falls back gracefully to static fetch if browser binary is unavailable.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(url, wait_until="networkidle", timeout=12000)
            status_code = response.status if response else 200

            if status_code >= 400:
                browser.close()
                return RawScrapedItem(
                    source_url=url,
                    title=f"HTTP {status_code} Error (SPA)",
                    raw_content="",
                    is_changelog=is_changelog,
                    http_status=status_code,
                    fetch_error=f"Dynamic fetch returned HTTP {status_code}",
                    scraped_at=utc_now(),
                )

            content = page.content()
            title = extract_title(content, url) or page.title() or "Changelog Update"
            clean_content = clean_html(content)
            browser.close()

            return RawScrapedItem(
                source_url=url,
                title=title,
                raw_content=clean_content,
                is_changelog=is_changelog,
                http_status=status_code,
                fetch_error=None,
                scraped_at=utc_now(),
            )
    except Exception as exc:
        logger.warning(f"Playwright dynamic fetch failed for {url} ({exc}). Falling back to static.")
        return fetch_page(url, is_changelog=is_changelog)
