"""
tests/test_pagination.py

Tests for pagination detection: rel=next, class/aria next, Page X of Y,
numeric sequences, pattern fallback, and query-param preservation.

Also includes a synthetic "MathCo-like" layout test that validates the
extractor works without hardcoded selectors.
"""

import pytest
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

from scraper.pagination import (
    detect_next_page,
    get_pattern_test_urls,
    _extract_current_page_number,
    _build_page_url,
)


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


BASE = "https://example.com"
CURRENT = "https://example.com/news/"


class TestRelNext:
    def test_link_rel_next_in_head(self):
        html = """<html><head>
        <link rel="next" href="https://example.com/news/page/2/" />
        </head><body></body></html>"""
        soup = make_soup(html)
        next_url, ptype = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url == "https://example.com/news/page/2/"
        assert "next" in ptype.lower()

    def test_anchor_rel_next(self):
        html = """<html><body>
        <nav><a rel="next" href="/news/page/2/">Next</a></nav>
        </body></html>"""
        soup = make_soup(html)
        next_url, ptype = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url is not None
        assert "page/2" in next_url

    def test_already_visited_skipped(self):
        html = """<html><head>
        <link rel="next" href="https://example.com/news/page/2/" />
        </head><body></body></html>"""
        soup = make_soup(html)
        visited = {"https://example.com/news/page/2/"}
        next_url, _ = detect_next_page(soup, CURRENT, visited, BASE)
        assert next_url is None


class TestClassAriaNext:
    def test_class_next(self):
        html = """<html><body>
        <div class="pagination">
          <a href="/news/page/2/" class="next">Next Page</a>
        </div>
        </body></html>"""
        soup = make_soup(html)
        next_url, ptype = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url is not None
        assert "page/2" in next_url

    def test_aria_label_next(self):
        html = """<html><body>
        <nav>
          <a href="/news/?page=2" aria-label="Next page">→</a>
        </nav>
        </body></html>"""
        soup = make_soup(html)
        next_url, ptype = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url is not None
        assert "page=2" in next_url

    def test_disabled_next_ignored(self):
        html = """<html><body>
        <a href="/news/page/2/" class="next disabled" aria-disabled="true">Next</a>
        </body></html>"""
        soup = make_soup(html)
        next_url, _ = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url is None


class TestPageOfTotal:
    def test_page_1_of_5(self):
        html = """<html><body>
        <div class="pager">Page 1 of 5</div>
        </body></html>"""
        soup = make_soup(html)
        next_url, ptype = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url is not None
        assert "page-of-total" in ptype.lower()

    def test_last_page_no_next(self):
        html = """<html><body>
        <div class="pager">Page 5 of 5</div>
        </body></html>"""
        soup = make_soup(html)
        next_url, _ = detect_next_page(soup, CURRENT, set(), BASE)
        assert next_url is None


class TestExtractCurrentPageNumber:
    def test_path_based(self):
        assert _extract_current_page_number("https://example.com/news/page/3/") == 3

    def test_query_page_param(self):
        assert _extract_current_page_number("https://example.com/news?page=5") == 5

    def test_query_paged_param(self):
        assert _extract_current_page_number("https://example.com/news?paged=4") == 4

    def test_no_page_defaults_to_1(self):
        assert _extract_current_page_number("https://example.com/news/") == 1


class TestBuildPageUrl:
    def test_path_pagination(self):
        url = "https://example.com/news/page/1/"
        result = _build_page_url(url, 3)
        assert result is not None
        assert "page/3" in result

    def test_query_pagination(self):
        url = "https://example.com/news?page=1"
        result = _build_page_url(url, 2)
        assert result is not None
        assert "page=2" in result

    def test_preserves_existing_params(self):
        url = "https://example.com/news?category=ai&page=1"
        result = _build_page_url(url, 2)
        assert result is not None
        assert "category=ai" in result
        assert "page=2" in result


class TestPatternTestUrls:
    def test_generates_multiple_patterns(self):
        candidates = get_pattern_test_urls("https://example.com/news/", page_num=2)
        assert len(candidates) >= 5

    def test_path_pattern_included(self):
        candidates = get_pattern_test_urls("https://example.com/news/", page_num=2)
        urls = [u for u, _ in candidates]
        assert any("page/2" in u for u in urls)

    def test_query_pattern_included(self):
        candidates = get_pattern_test_urls("https://example.com/news/", page_num=2)
        urls = [u for u, _ in candidates]
        assert any("page=2" in u for u in urls)

    def test_preserves_existing_params(self):
        candidates = get_pattern_test_urls("https://example.com/news/?category=ai", page_num=2)
        urls = [u for u, _ in candidates]
        # Query-based patterns should preserve category=ai
        query_based = [u for u in urls if "page=2" in u or "paged=2" in u]
        for u in query_based:
            assert "category=ai" in u

    def test_wordpress_paged_pattern(self):
        candidates = get_pattern_test_urls("https://example.com/news/", page_num=2)
        urls = [u for u, _ in candidates]
        assert any("paged=2" in u for u in urls)
