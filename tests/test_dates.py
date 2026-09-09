"""
tests/test_dates.py

Tests for date parsing: <time datetime>, data attrs, regex patterns,
multiple formats, and None for unparseable inputs.
"""

import pytest
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from scraper.dates import parse_date, parse_date_from_element, parse_date_from_page


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


class TestParseDateFromElement:
    def test_time_datetime_iso(self):
        soup = make_soup('<div><time datetime="2024-03-15T10:30:00Z">March 15, 2024</time></div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_time_datetime_date_only(self):
        soup = make_soup('<article><time datetime="2023-11-20">Nov 20</time></article>')
        tag = soup.find("article")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2023
        assert result.month == 11

    def test_time_visible_text_fallback(self):
        soup = make_soup('<div><time>January 5, 2024</time></div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1

    def test_data_date_attribute(self):
        soup = make_soup('<div data-date="2022-07-04"><span>Article Title</span></div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2022

    def test_regex_iso_date_in_text(self):
        soup = make_soup('<div>Published: 2021-06-15. Read more...</div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2021
        assert result.month == 6
        assert result.day == 15

    def test_regex_us_date_format(self):
        soup = make_soup('<div>Date: 12/25/2023</div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2023

    def test_regex_month_name_format(self):
        soup = make_soup('<div>September 10, 2024</div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.year == 2024
        assert result.month == 9
        assert result.day == 10

    def test_no_date_returns_none(self):
        soup = make_soup('<div>No date information here at all.</div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is None

    def test_garbage_text_returns_none(self):
        soup = make_soup('<div>abc xyz 123 foo bar baz</div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is None

    def test_result_is_utc_aware(self):
        soup = make_soup('<div><time datetime="2024-01-01T00:00:00+05:30">Jan 1</time></div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.tzinfo is not None
        # Should be converted to UTC
        assert result.utcoffset().total_seconds() == 0

    def test_naive_datetime_treated_as_utc(self):
        soup = make_soup('<div><time datetime="2024-06-15T12:00:00">June 15</time></div>')
        tag = soup.find("div")
        result = parse_date_from_element(tag)
        assert result is not None
        assert result.tzinfo == timezone.utc


class TestParseDateFromPage:
    def test_og_article_published_time(self):
        html = """<html><head>
        <meta property="article:published_time" content="2024-05-20T08:00:00Z" />
        </head><body></body></html>"""
        soup = make_soup(html)
        result = parse_date_from_page(soup)
        assert result is not None
        assert result.year == 2024
        assert result.month == 5

    def test_no_meta_returns_none(self):
        html = "<html><head><title>No date</title></head><body></body></html>"
        soup = make_soup(html)
        result = parse_date_from_page(soup)
        assert result is None


class TestParseDate:
    def test_iso_string(self):
        result = parse_date("2024-08-15")
        assert result is not None
        assert result.year == 2024
        assert result.month == 8

    def test_human_readable(self):
        result = parse_date("August 15, 2024")
        assert result is not None
        assert result.year == 2024
        assert result.month == 8

    def test_empty_string(self):
        assert parse_date("") is None

    def test_non_date_string(self):
        assert parse_date("hello world") is None

    def test_out_of_range_year(self):
        # Year before 1990 should return None
        result = parse_date("1885-01-01")
        assert result is None

    def test_multiple_date_formats(self):
        formats = [
            "2024-01-15",
            "01/15/2024",
            "January 15, 2024",
            "15 January 2024",
            "2024/01/15",
        ]
        for fmt in formats:
            result = parse_date(fmt)
            assert result is not None, f"Failed to parse: {fmt}"
            assert result.year == 2024
            assert result.month == 1
