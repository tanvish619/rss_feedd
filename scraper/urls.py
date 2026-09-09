"""
scraper/urls.py

URL normalization, validation, and utility functions.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import (
    ParseResult,
    parse_qs,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

from bs4 import BeautifulSoup

# Tracking parameters to strip from all URLs
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "msclkid",
        "twclid",
        "mc_eid",
        "mc_cid",
        "_ga",
        "_gl",
        "ref",
        "referrer",
        "source",
    }
)

# URL schemes / patterns we never want as article links
_REJECT_SCHEMES: frozenset[str] = frozenset({"javascript", "mailto", "tel", "data", "ftp"})

# Path segments that indicate non-article pages
_REJECT_PATH_SEGMENTS: tuple[str, ...] = (
    "/login",
    "/logout",
    "/register",
    "/signup",
    "/signin",
    "/cart",
    "/checkout",
    "/account",
    "/admin",
    "/wp-admin",
    "/wp-login",
    "/feed",
    "/rss",
    "/sitemap",
    "/search",
    "/tag/",
    "/author/",
    "/page/",
    "/category/",
)

# File extensions that are not article pages
_REJECT_EXTENSIONS: tuple[str, ...] = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".mp3",
    ".zip",
    ".tar",
    ".gz",
    ".css",
    ".js",
    ".xml",
    ".json",
)


# Social media domains to reject as article links
_REJECT_DOMAINS: frozenset[str] = frozenset(
    {
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "pinterest.com",
        "tiktok.com",
        "github.com",
    }
)


def normalize_url(url: str, base: str = "") -> str:
    """
    Normalise a URL:
    - Convert relative to absolute (using *base*)
    - Resolve ../ and ./ segments
    - Lowercase scheme and host
    - Strip URL fragments (#...)
    - Remove known tracking query parameters
    - Preserve all other query parameters
    """
    if not url:
        return ""

    url = url.strip()

    # Make absolute
    if base:
        url = urljoin(base, url)

    try:
        parsed: ParseResult = urlparse(url)
    except Exception:
        return ""

    # Lowercase scheme + host
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Strip fragment
    fragment = ""

    # Filter tracking query params
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        filtered_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(filtered_qs, doseq=True)
    else:
        new_query = ""

    normalised = urlunparse((scheme, netloc, parsed.path, parsed.params, new_query, fragment))
    return normalised


def is_valid_article_url(url: str, base_domain: str = "") -> bool:
    """
    Return True if *url* looks like a valid, crawlable article link.
    """
    if not url:
        return False

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Reject bad schemes
    if parsed.scheme and parsed.scheme.lower() in _REJECT_SCHEMES:
        return False

    # Must have http(s) scheme if scheme is present
    if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
        return False

    # Reject pure anchors
    if not parsed.netloc and not parsed.path:
        return False
    if url.startswith("#"):
        return False

    # Reject root / home page URLs (e.g. https://domain.com or https://domain.com/)
    clean_path = parsed.path.strip("/")
    if not clean_path:
        return False

    # Reject social domains
    netloc_clean = re.sub(r"^www\.", "", parsed.netloc.lower())
    if netloc_clean in _REJECT_DOMAINS:
        return False

    path_lower = "/" + clean_path.lower() + "/"

    # Reject paths matching non-article segments with segment boundary checks
    for seg in _REJECT_PATH_SEGMENTS:
        s = seg.strip("/")
        if f"/{s}/" in path_lower or path_lower.startswith(f"/{s}/"):
            return False

    # Reject non-HTML file extensions
    if any(parsed.path.lower().endswith(ext) for ext in _REJECT_EXTENSIONS):
        return False

    # If base_domain is supplied, optionally enforce same domain
    if base_domain:
        parsed_base = urlparse(base_domain)
        if parsed.netloc and parsed.netloc.lower() != parsed_base.netloc.lower():
            return False

    return True


def get_canonical(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Extract the canonical URL from <link rel='canonical'>, if present."""
    tag = soup.find("link", rel="canonical", href=True)
    if tag:
        href = tag.get("href", "").strip()
        if href:
            return normalize_url(href, base_url)
    return None


def same_domain(url1: str, url2: str) -> bool:
    """Return True if two URLs share the same scheme+host."""
    try:
        p1 = urlparse(url1)
        p2 = urlparse(url2)
        return p1.scheme.lower() == p2.scheme.lower() and p1.netloc.lower() == p2.netloc.lower()
    except Exception:
        return False


def base_url(url: str) -> str:
    """Return scheme://host for a URL."""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def add_page_param_to_url(url: str, param: str, value: int) -> str:
    """Add or replace a single query parameter on *url*."""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs[param] = [str(value)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))


def is_http_url(url: str) -> bool:
    """Return True if *url* is an absolute http(s) URL."""
    try:
        p = urlparse(url)
        return p.scheme.lower() in ("http", "https") and bool(p.netloc)
    except Exception:
        return False
