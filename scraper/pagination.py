"""
scraper/pagination.py

Pagination detection for listing pages.

Detection priority (highest to lowest):
  1. <link rel="next"> in <head>
  2. <a rel="next"> in body
  3. Anchor with class/aria containing "next"
  4. Explicit "Page X of Y" text → increment X
  5. Numeric link sequences (max valid page number)
  6. Pattern fallback: test /page/2/, ?page=2, ?paged=2 against page 1 content hash

Existing query parameters are preserved when building the next URL.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from scraper.urls import normalize_url, same_domain

logger = logging.getLogger(__name__)

# Patterns for "Page X of Y" style pagination text
_PAGE_OF_PATTERN = re.compile(
    r"[Pp]age\s+(\d+)\s+of\s+(\d+)",
    re.IGNORECASE,
)

# Class/aria-label patterns that hint at a "next page" link
_NEXT_INDICATORS: tuple[str, ...] = (
    "next",
    "next-page",
    "nextpage",
    "pagination-next",
    "pager-next",
    "arrow-next",
    "nav-next",
)

# Pattern-based pagination suffixes to try when no explicit pagination found
_PATTERN_TEMPLATES: list[str] = [
    "/page/{n}/",
    "/page/{n}",
    "?page={n}",
    "?paged={n}",
    "?p={n}",
    "?pagenum={n}",
    "?pg={n}",
    "?start={(n-1)*10}",
]


def _normalise_href(href: str, base_url: str) -> Optional[str]:
    """Convert *href* to an absolute, normalised URL."""
    if not href or href.strip().startswith(("#", "javascript:", "mailto:")):
        return None
    try:
        return normalize_url(href, base_url)
    except Exception:
        return None


def _has_next_class_or_aria(tag: Tag) -> bool:
    """Return True if tag's class list or aria-label looks like a 'next' control."""
    classes = " ".join(tag.get("class", [])).lower()
    aria = (tag.get("aria-label") or "").lower()
    text = tag.get_text(" ", strip=True).lower().strip()
    combined = f"{classes} {aria} {text}"
    return any(ind in combined for ind in _NEXT_INDICATORS)


def _is_disabled(tag: Tag) -> bool:
    """Return True if the tag appears to be a disabled pagination element."""
    classes = " ".join(tag.get("class", [])).lower()
    aria_disabled = (tag.get("aria-disabled") or "").lower()
    return "disabled" in classes or aria_disabled == "true"


def _content_hash(html: str) -> str:
    """Return an MD5 hex digest of normalised HTML content for duplicate detection."""
    # Strip whitespace variations to reduce false positives
    normalised = re.sub(r"\s+", " ", html.strip())
    return hashlib.md5(normalised.encode("utf-8", errors="replace")).hexdigest()


def detect_next_page(
    soup: BeautifulSoup,
    current_url: str,
    visited: set[str],
    base_url: str,
    page1_hash: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """
    Attempt to detect the next pagination URL.

    Returns:
        (next_url, pagination_type)  if found
        (None, "none")               if no next page detected
    """

    # --- 1. <link rel="next"> in <head> ---
    link_next = soup.find("link", rel="next", href=True)
    if link_next:
        href = _normalise_href(link_next.get("href", ""), base_url)
        if href and href not in visited and same_domain(href, base_url):
            logger.debug("Pagination: rel=next link -> %s", href)
            return href, "rel=next (link)"

    # --- 2. <a rel="next"> in body ---
    a_rel_next = soup.find("a", rel="next", href=True)
    if a_rel_next:
        href = _normalise_href(a_rel_next.get("href", ""), base_url)
        if href and href not in visited and same_domain(href, base_url):
            logger.debug("Pagination: <a rel=next> -> %s", href)
            return href, "rel=next (anchor)"

    # --- 3. Anchors with class/aria-label hinting at "next" ---
    for a in soup.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        if _is_disabled(a):
            continue
        if _has_next_class_or_aria(a):
            href = _normalise_href(a.get("href", ""), base_url)
            if href and href not in visited and same_domain(href, base_url):
                logger.debug("Pagination: class/aria next -> %s", href)
                return href, "class/aria-label next"

    # --- 4. "Page X of Y" pattern ---
    full_text = soup.get_text(" ", strip=True)
    m = _PAGE_OF_PATTERN.search(full_text)
    if m:
        current_page_num = int(m.group(1))
        total_pages = int(m.group(2))
        if current_page_num < total_pages:
            next_num = current_page_num + 1
            url = _build_page_url(current_url, next_num)
            if url and url not in visited:
                logger.debug("Pagination: Page X of Y -> %s", url)
                return url, f"page-of-total ({current_page_num}/{total_pages})"

    # --- 5. Numeric link sequences ---
    next_url = _detect_numeric_sequence(soup, current_url, visited, base_url)
    if next_url:
        return next_url, "numeric sequence"

    return None, "none"


def _build_page_url(current_url: str, page_num: int) -> Optional[str]:
    """
    Attempt to construct a URL for *page_num* based on patterns found in *current_url*.
    Handles: /page/N/, ?page=N, ?paged=N.
    Falls back to appending ?page=N if no existing page indicator found.
    """
    parsed = urlparse(current_url)
    path = parsed.path

    # Path-based: /page/N/
    path_match = re.match(r"^(.*?/page/)(\d+)(/?)", path)
    if path_match:
        new_path = f"{path_match.group(1)}{page_num}{path_match.group(3)}"
        return urlunparse(
            (parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, "")
        )

    # Query-based: replace existing page param
    qs = parse_qs(parsed.query, keep_blank_values=True)
    for param in ("page", "paged", "p", "pg", "pagenum"):
        if param in qs:
            qs[param] = [str(page_num)]
            new_query = urlencode(qs, doseq=True)
            return urlunparse(
                (parsed.scheme, parsed.netloc, path, parsed.params, new_query, "")
            )

    # Fallback: append ?page=N preserving existing query params
    qs["page"] = [str(page_num)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, path, parsed.params, new_query, "")
    )


def _detect_numeric_sequence(
    soup: BeautifulSoup,
    current_url: str,
    visited: set[str],
    base_url: str,
) -> Optional[str]:
    """
    Find the next page by looking for consecutive numeric page links.
    Strategy: find all integer-looking links in pagination containers,
    determine the current page number, return current+1 URL.
    """
    parsed_current = urlparse(current_url)

    # Collect numeric candidate links
    # Look for anchors near pagination containers
    pagination_containers: list[Tag] = []
    page_container_patterns = (
        "paginat",
        "pager",
        "page-nav",
        "nav-pages",
        "pagenum",
        "page-list",
        "wp-pagenavi",
    )
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        classes_id = " ".join(tag.get("class", [])).lower() + " " + (tag.get("id") or "").lower()
        if any(p in classes_id for p in page_container_patterns):
            pagination_containers.append(tag)

    # If no containers found, search all links
    search_root: list[Tag] = pagination_containers if pagination_containers else [soup]

    # Determine current page number from URL
    current_page = _extract_current_page_number(current_url)

    best_next: Optional[str] = None
    best_next_num = float("inf")

    for root in search_root:
        for a in root.find_all("a", href=True):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)

            # Must be purely numeric
            if not re.match(r"^\d+$", text):
                continue

            page_num = int(text)
            if page_num <= current_page:
                continue

            # Build absolute URL
            abs_href = _normalise_href(href, base_url)
            if not abs_href or abs_href in visited:
                continue
            if not same_domain(abs_href, base_url):
                continue

            if page_num < best_next_num:
                best_next_num = page_num
                best_next = abs_href

    return best_next


def _extract_current_page_number(url: str) -> int:
    """Extract the current page number from a URL, defaulting to 1."""
    parsed = urlparse(url)

    # /page/N/
    m = re.search(r"/page/(\d+)", parsed.path)
    if m:
        return int(m.group(1))

    # ?page=N or ?paged=N etc.
    qs = parse_qs(parsed.query)
    for param in ("page", "paged", "p", "pg", "pagenum"):
        if param in qs:
            try:
                return int(qs[param][0])
            except (ValueError, IndexError):
                pass

    return 1


def get_pattern_test_urls(listing_url: str, page_num: int = 2) -> list[tuple[str, str]]:
    """
    Generate candidate URLs to test for pattern-based pagination.
    Returns list of (url, pattern_name) tuples.
    Preserves existing query params when appending query-based patterns.
    """
    parsed = urlparse(listing_url)
    base_path = parsed.path.rstrip("/")
    existing_qs = parse_qs(parsed.query, keep_blank_values=True)

    candidates: list[tuple[str, str]] = []

    # Path-based patterns
    for template in ["/page/{n}/", "/page/{n}"]:
        new_path = base_path + template.format(n=page_num)
        new_query = urlencode(existing_qs, doseq=True)
        url = urlunparse((parsed.scheme, parsed.netloc, new_path, "", new_query, ""))
        candidates.append((url, template))

    # Query-based patterns
    for param in ("page", "paged", "p", "pg", "pagenum"):
        qs = dict(existing_qs)
        qs[param] = [str(page_num)]
        new_query = urlencode(qs, doseq=True)
        url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))
        candidates.append((url, f"?{param}={page_num}"))

    return candidates
