"""
tests/test_rss.py

Tests for RSS feed generation and validation:
  - CDATA encapsulation (<title>, <description>, <content:encoded>, <category>)
  - Rich HTML formatting in <description> and <content:encoded>
  - content:encoded namespace presence
  - Strict RFC-822 pubDate presence on all items (including undated fallback)
  - Correct sort order (dated first, newest-first; undated last)
  - Stable normalized GUIDs
  - XML validation
  - Malformed entity detection outside CDATA
  - JSON and HTML feed builders
"""

import pytest
from datetime import datetime, timezone

from scraper.models import Article
from rss.builder import build_feed, _auto_feed_title, _auto_feed_description
from rss.validator import validate_feed, get_feed_summary, _find_malformed_entities


PAGE_URL = "https://example.com/news/"


def _make_dated_articles() -> list[Article]:
    return [
        Article(
            title="Oldest Article & Highlights",
            url="https://example.com/oldest?utm_source=rss",
            source_page=PAGE_URL,
            date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            category="Tech & AI",
            description="The oldest article in the set with <special> characters.",
            image_url="https://example.com/img1.jpg",
        ),
        Article(
            title="Newest Article <Exclusive>",
            url="https://example.com/newest",
            source_page=PAGE_URL,
            date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            category="News",
            description="The newest article in the set.",
            author="Jane Doe",
        ),
        Article(
            title="Middle Article — Growth & Strategy",
            url="https://example.com/middle",
            source_page=PAGE_URL,
            date=datetime(2024, 3, 20, tzinfo=timezone.utc),
            category="Business",
            description="A middle-dated article.",
        ),
    ]


def _make_undated_articles() -> list[Article]:
    return [
        Article(
            title="Undated Article One",
            url="https://example.com/undated-1",
            source_page=PAGE_URL,
            date=None,
            description="No date on this one.",
        ),
        Article(
            title="Undated Article Two",
            url="https://example.com/undated-2",
            source_page=PAGE_URL,
            date=None,
            description="Also no date.",
        ),
    ]


class TestFeedGeneration:
    def test_valid_rss_generated(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        valid, error = validate_feed(xml)
        assert valid, f"Feed validation failed: {error}"

    def test_rss_root_element_and_namespaces(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        assert "<rss" in xml
        assert 'xmlns:content="http://purl.org/rss/1.0/modules/content/"' in xml
        assert 'xmlns:atom="http://www.w3.org/2005/Atom"' in xml

    def test_cdata_encapsulation(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        assert "<title><![CDATA[Oldest Article & Highlights]]></title>" in xml
        assert "<title><![CDATA[Newest Article <Exclusive>]]></title>" in xml
        assert "<category><![CDATA[Tech & AI]]></category>" in xml
        assert "<description><![CDATA[" in xml
        assert "<content:encoded><![CDATA[" in xml

    def test_rich_html_in_description_and_content(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        # Verify <img>, <p>, and structured elements exist in the CDATA
        assert '<img src="https://example.com/img1.jpg"' in xml
        assert "<p>" in xml
        assert "<content:encoded>" in xml
        assert "Read full article at source" in xml

    def test_channel_element_present(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        assert "<channel>" in xml

    def test_items_present(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        assert xml.count("<item>") == 3

    def test_guid_is_normalized_url(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        # Tracking parameter utm_source should be stripped
        assert "https://example.com/oldest" in xml
        assert "utm_source" not in xml
        assert 'isPermaLink="true"' in xml

    def test_language_is_en(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        assert "<language>en</language>" in xml

    def test_utf8_encoding(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        assert 'encoding="utf-8"' in xml.lower() or "encoding='utf-8'" in xml.lower()


class TestSortOrderAndPubDate:
    def test_newest_dated_first(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        newest_pos = xml.find("Newest Article")
        oldest_pos = xml.find("Oldest Article")
        middle_pos = xml.find("Middle Article")
        assert newest_pos < middle_pos < oldest_pos

    def test_undated_articles_last(self):
        dated = _make_dated_articles()
        undated = _make_undated_articles()
        xml = build_feed(dated + undated, PAGE_URL)
        newest_pos = xml.find("Newest Article")
        undated_pos = xml.find("Undated Article One")
        assert newest_pos < undated_pos

    def test_all_items_have_valid_pubdate_fallback(self):
        articles = _make_undated_articles()
        xml = build_feed(articles, PAGE_URL)
        valid, error = validate_feed(xml)
        assert valid, f"Feed with undated articles failed validation: {error}"
        summary = get_feed_summary(xml)
        assert summary["item_count"] == 2
        assert summary["has_dates_count"] == 2  # Every item is guaranteed a pubDate


class TestFeedMetadata:
    def test_auto_title_contains_domain(self):
        title = _auto_feed_title("https://mathco.com/news/")
        assert "mathco.com" in title.lower()

    def test_auto_description_contains_domain(self):
        desc = _auto_feed_description("https://mathco.com/news/")
        assert "mathco.com" in desc.lower()

    def test_auto_title_strips_www(self):
        title = _auto_feed_title("https://www.example.com/news/")
        assert "www" not in title.lower()


class TestValidation:
    def test_valid_feed_passes(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        valid, error = validate_feed(xml)
        assert valid
        assert error is None

    def test_empty_string_fails(self):
        valid, error = validate_feed("")
        assert not valid
        assert error

    def test_malformed_xml_fails(self):
        bad_xml = "<?xml version='1.0'?><rss><channel><title>Test</title>"
        valid, error = validate_feed(bad_xml)
        assert not valid

    def test_missing_channel_fails(self):
        bad_xml = '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"></rss>'
        valid, error = validate_feed(bad_xml)
        assert not valid
        assert "channel" in error.lower()

    def test_no_items_fails(self):
        bad_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test</title>
    <link>https://example.com</link>
    <description>Test</description>
  </channel>
</rss>"""
        valid, error = validate_feed(bad_xml)
        assert not valid
        assert "item" in error.lower()


class TestMalformedEntities:
    def test_valid_xml_entities_not_flagged(self):
        assert _find_malformed_entities("&amp; &lt; &gt; &apos; &quot;") is None

    def test_numeric_entities_not_flagged(self):
        assert _find_malformed_entities("&#169; &#xA9;") is None

    def test_cdata_with_bare_ampersand_not_flagged(self):
        cdata_xml = "<title><![CDATA[MathCo & Co <News>]]></title>"
        assert _find_malformed_entities(cdata_xml) is None

    def test_bare_ampersand_outside_cdata_flagged(self):
        result = _find_malformed_entities("<title>Hello & World</title>")
        assert result is not None

    def test_clean_xml_not_flagged(self):
        assert _find_malformed_entities("<title>Clean Title</title>") is None


class TestFeedSummary:
    def test_summary_item_count(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        summary = get_feed_summary(xml)
        assert summary["item_count"] == 3

    def test_summary_dates_count(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        summary = get_feed_summary(xml)
        assert summary["has_dates_count"] == 3

    def test_summary_channel_link(self):
        articles = _make_dated_articles()
        xml = build_feed(articles, PAGE_URL)
        summary = get_feed_summary(xml)
        assert "example.com" in summary["channel_link"]


class TestJsonAndHtmlFeedGeneration:
    def test_json_feed_valid(self):
        import json
        from rss.builder import build_json_feed

        articles = _make_dated_articles()
        json_str = build_json_feed(articles, PAGE_URL)
        data = json.loads(json_str)

        assert data["version"] == "https://jsonfeed.org/version/1.1"
        assert len(data["items"]) == 3
        assert data["items"][0]["title"] == "Newest Article <Exclusive>"
        assert data["items"][2]["title"] == "Oldest Article & Highlights"

    def test_html_feed_valid(self):
        from rss.builder import build_html_feed

        articles = _make_dated_articles()
        html_str = build_html_feed(articles, PAGE_URL)

        assert "<!DOCTYPE html>" in html_str
        assert "Newest Article" in html_str
        assert "Oldest Article" in html_str
        assert "https://example.com/newest" in html_str
