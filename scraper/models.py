"""
scraper/models.py

Data models for the News RSS Builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Article:
    """Represents a single extracted news article from a listing page."""

    title: str
    url: str
    source_page: str

    date: Optional[datetime] = None
    category: Optional[str] = None
    description: Optional[str] = None
    content_html: Optional[str] = None
    image_url: Optional[str] = None
    author: Optional[str] = None

    # Internal scoring — not exposed in RSS output
    confidence: float = 0.0

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Article):
            return NotImplemented
        return self.url == other.url


@dataclass
class CrawlStats:
    """Tracks statistics for a single crawl run."""

    pages_discovered: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0
    articles_found: int = 0
    duplicates_removed: int = 0
    articles_filtered: int = 0
    articles_without_dates: int = 0

    # Extra diagnostic info
    pagination_type: Optional[str] = None   # e.g. "rel=next", "numeric", "pattern"
    robots_allowed: bool = True
    extraction_confidence_avg: float = 0.0
    canonical_url: Optional[str] = None
    error_messages: list = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.error_messages.append(msg)
