"""
scraper/dates.py

Date parsing and normalisation utilities.

Priority order for extraction:
  1. <time> element's datetime attribute
  2. Data attributes: data-date, data-published, published_time, article:published_time
  3. Regex over visible text via dateutil.parser
  4. Return None — never invent a date.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup, Tag
from dateutil import parser as dateutil_parser
from dateutil.parser import ParserError

# Regex patterns that hint at date-like strings in text
_DATE_PATTERNS: list[re.Pattern] = [
    # ISO-8601 variants: 2024-01-15, 2024/01/15
    re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"),
    # Month name: January 15, 2024 | 15 January 2024
    re.compile(
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})\b",
        re.IGNORECASE,
    ),
    # US style: 01/15/2024 or 1/15/2024
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
]

# Common HTML attributes that store dates
_DATE_ATTRIBUTES: tuple[str, ...] = (
    "datetime",
    "data-date",
    "data-published",
    "data-publish-date",
    "data-time",
    "content",
)

# Meta property names that carry dates
_META_DATE_PROPERTIES: tuple[str, ...] = (
    "article:published_time",
    "article:modified_time",
    "og:article:published_time",
    "datePublished",
    "dateModified",
)


def _to_utc(dt: datetime) -> datetime:
    """Convert a datetime to UTC. Assume UTC if already naïve."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_parse(text: str) -> Optional[datetime]:
    """Attempt to parse *text* with dateutil; return None on failure."""
    if not text or not text.strip():
        return None
    try:
        # Limit string length to avoid pathological inputs
        dt = dateutil_parser.parse(text.strip()[:100], fuzzy=True)
        # Sanity-check: year must be between 1990 and 2040
        if dt.year < 1990 or dt.year > 2040:
            return None
        return _to_utc(dt)
    except (ParserError, OverflowError, ValueError):
        return None


def parse_date_from_element(element: Tag) -> Optional[datetime]:
    """
    Try to extract a date from a single BeautifulSoup Tag.

    Priority:
      1. <time datetime="...">
      2. Known data-* attributes on the element itself
      3. Visible text of the element
    """
    # 1. <time> tags within the element
    time_tags = element.find_all("time") if element.name != "time" else [element]
    for tt in time_tags:
        dt_attr = tt.get("datetime", "").strip()
        if dt_attr:
            dt = _safe_parse(dt_attr)
            if dt:
                return dt
        # Fallback: visible text of <time>
        visible = tt.get_text(" ", strip=True)
        if visible:
            dt = _safe_parse(visible)
            if dt:
                return dt

    # 2. Data attributes on element and its children
    candidates_for_attrs = [element] + list(element.find_all(True))
    for tag in candidates_for_attrs:
        if not isinstance(tag, Tag):
            continue
        for attr in _DATE_ATTRIBUTES:
            val = tag.get(attr, "")
            if val and isinstance(val, str):
                dt = _safe_parse(val)
                if dt:
                    return dt

    # 3. Regex over visible text
    text = element.get_text(" ", strip=True)
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            dt = _safe_parse(m.group(1))
            if dt:
                return dt

    return None


def parse_date_from_page(soup: BeautifulSoup) -> Optional[datetime]:
    """
    Scan top-level page meta tags for a publication date.
    Used when per-element extraction fails.
    """
    # Meta property / name tags
    for prop_name in _META_DATE_PROPERTIES:
        # property= variant
        tag = soup.find("meta", property=prop_name, content=True)
        if tag:
            dt = _safe_parse(tag.get("content", ""))
            if dt:
                return dt
        # name= variant
        tag = soup.find("meta", attrs={"name": prop_name}, content=True)
        if tag:
            dt = _safe_parse(tag.get("content", ""))
            if dt:
                return dt

    return None


def parse_date(text: str) -> Optional[datetime]:
    """Parse a raw date string. Returns UTC datetime or None."""
    return _safe_parse(text)
