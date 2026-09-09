"""
scraper/crawler.py

Orchestrates the crawl loop.
1. Visits listing/pagination pages to discover article candidate links.
2. Follows each candidate link into its article detail page to extract rich content,
   full body HTML, author, category, publication date, and lead image.
3. Tracks statistics and yields live progress updates for the Streamlit UI.

Safety stops:
  - Max pages limit reached
  - Max articles limit reached
  - URL already visited
  - Identical normalised page content (MD5 hash loop trap)
  - HTTP 404 / permanent error
  - No new URLs found after pagination detection
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Generator, Optional

from bs4 import BeautifulSoup
from requests import Session

from scraper.article_scraper import enrich_article
from scraper.extractor import extract_articles
from scraper.models import Article, CrawlStats
from scraper.pagination import _content_hash, detect_next_page, get_pattern_test_urls
from scraper.urls import base_url as get_base_url, normalize_url, same_domain
from utils.http import build_session, fetch
from utils.robots import check_robots

logger = logging.getLogger(__name__)

# Yield type: (list of new articles from this page, updated stats, status_message)
CrawlYield = tuple[list[Article], CrawlStats, str]


def crawl(
    start_url: str,
    max_pages: int = 100,
    max_articles: int = 1000,
    timeout: float = 15.0,
    delay: float = 0.5,
    session: Optional[Session] = None,
    enrich_details: bool = True,
) -> Generator[CrawlYield, None, None]:
    """
    Generator that crawls *start_url*, extracts article candidates, follows article
    links to retrieve full rich content, and yields (new_articles, stats, message).
    """
    if session is None:
        session = build_session()

    stats = CrawlStats()
    visited_urls: set[str] = set()
    content_hashes: set[str] = set()
    all_articles: dict[str, Article] = {}  # normalised_url → Article

    base = get_base_url(start_url)
    current_url: Optional[str] = normalize_url(start_url)
    first_page_html: Optional[str] = None
    page1_hash: Optional[str] = None

    # ── Robots.txt check ──────────────────────────────────────────────────────
    yield [], stats, "🤖 Checking robots.txt…"
    allowed, crawl_delay = check_robots(start_url, session)
    if not allowed:
        stats.robots_allowed = False
        stats.add_error(f"robots.txt disallows access to {start_url}")
        yield [], stats, "🚫 robots.txt blocks this URL."
        return

    # Respect site-specified crawl delay (use max of configured and robots.txt)
    effective_delay = max(delay, crawl_delay or 0.0)
    stats.pages_discovered = 1

    # ── Main crawl loop ────────────────────────────────────────────────────────
    while current_url and stats.pages_crawled < max_pages:
        norm_current = normalize_url(current_url)

        # Safety: skip if already visited
        if norm_current in visited_urls:
            logger.debug("Skipping already-visited URL: %s", current_url)
            break

        visited_urls.add(norm_current)
        yield [], stats, f"📄 Fetching listing page {stats.pages_crawled + 1}: {current_url}"

        # ── Fetch page ─────────────────────────────────────────────────────────
        response, error = fetch(current_url, session, timeout=timeout, delay=effective_delay)

        if error or response is None:
            stats.pages_failed += 1
            stats.add_error(f"Failed to fetch {current_url}: {error}")
            yield [], stats, f"⚠️ Failed: {current_url} — {error}"
            break

        stats.pages_crawled += 1
        html = response.text

        # ── Duplicate-content detection ────────────────────────────────────────
        content_hash = _content_hash(html)
        if content_hash in content_hashes:
            logger.info("Duplicate content detected at %s — stopping.", current_url)
            yield [], stats, "🔁 Duplicate page content detected — stopping pagination."
            break
        content_hashes.add(content_hash)

        if first_page_html is None:
            first_page_html = html
            page1_hash = content_hash

        # ── Parse HTML ────────────────────────────────────────────────────────
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as exc:
            logger.warning("lxml parse failed for %s, falling back to html.parser: %s", current_url, exc)
            soup = BeautifulSoup(html, "html.parser")

        # ── Extract candidate article links ───────────────────────────────────
        page_articles = extract_articles(soup, current_url, base)
        new_on_page: list[Article] = []
        page_dupes = 0

        for article in page_articles:
            stats.articles_found += 1
            norm = normalize_url(article.url)
            existing = all_articles.get(norm)
            if existing:
                stats.duplicates_removed += 1
                page_dupes += 1
            else:
                all_articles[norm] = article
                new_on_page.append(article)

        # ── Deep Article Enrichment (Follow each link into detail page) ────────
        if enrich_details and new_on_page:
            for idx, article in enumerate(new_on_page):
                yield [], stats, f"🔍 Inspecting article {idx + 1}/{len(new_on_page)}: {article.title[:45]}…"
                try:
                    enriched = enrich_article(article, session, timeout=timeout)
                    all_articles[normalize_url(article.url)] = enriched
                except Exception as enrich_err:
                    logger.warning("Could not enrich article %s: %s", article.url, enrich_err)

        # Update stats
        total_articles = len(all_articles)
        dated = sum(1 for a in all_articles.values() if a.date is not None)
        stats.articles_without_dates = total_articles - dated

        if all_articles:
            stats.extraction_confidence_avg = sum(
                a.confidence for a in all_articles.values()
            ) / len(all_articles)

        msg = (
            f"✅ Page {stats.pages_crawled}: found {len(page_articles)} articles "
            f"({len(new_on_page)} new deep-extracted, {page_dupes} dupes)"
        )
        yield new_on_page, stats, msg

        # ── Max articles stop ─────────────────────────────────────────────────
        if total_articles >= max_articles:
            yield [], stats, f"🛑 Max articles limit ({max_articles}) reached."
            break

        # ── Pagination detection ──────────────────────────────────────────────
        next_url, pagination_type = detect_next_page(
            soup, current_url, visited_urls, base, page1_hash
        )

        if stats.pagination_type in (None, "none"):
            stats.pagination_type = pagination_type

        if next_url is None and stats.pages_crawled == 1:
            # Try pattern-based fallback on the first page only
            next_url, pagination_type = _try_pattern_pagination(
                current_url, visited_urls, session, timeout, effective_delay, html, stats
            )
            if next_url:
                stats.pagination_type = pagination_type

        if next_url is None:
            yield [], stats, "📋 No further pages detected — crawl complete."
            break

        stats.pages_discovered += 1
        current_url = next_url

    # Final yield with complete stats
    yield [], stats, f"🏁 Crawl finished. {stats.pages_crawled} pages, {len(all_articles)} unique articles fully enriched."


def _try_pattern_pagination(
    listing_url: str,
    visited: set[str],
    session: Session,
    timeout: float,
    delay: float,
    page1_html: str,
    stats: CrawlStats,
) -> tuple[Optional[str], str]:
    """
    Test common URL patterns for page 2 and compare content to page 1.
    Returns (next_url, pattern_name) if a valid page 2 is found.
    """
    page1_hash = _content_hash(page1_html)
    candidates = get_pattern_test_urls(listing_url, page_num=2)

    for url, pattern in candidates:
        norm = normalize_url(url)
        if norm in visited:
            continue

        response, error = fetch(url, session, timeout=timeout, delay=delay)
        if error or response is None:
            continue

        if response.status_code == 404:
            continue

        page2_hash = _content_hash(response.text)

        # Different content means this is a real page 2
        if page2_hash != page1_hash and len(response.text.strip()) > 200:
            logger.info("Pattern pagination found: %s via %s", url, pattern)
            return normalize_url(url), f"pattern ({pattern})"

    return None, "none"
