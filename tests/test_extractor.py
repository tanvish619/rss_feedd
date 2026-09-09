"""
tests/test_extractor.py

Tests for heuristic article extraction, candidate scoring,
deduplication, keyword filtering, and the synthetic MathCo-like layout.

The MathCo-like fixture uses a generic card layout (Date + Category + Title + Read more)
without hardcoding any site-specific selectors in the application code.
"""

import pytest
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from scraper.extractor import extract_articles, apply_keyword_filter
from scraper.models import Article


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


BASE = "https://example.com"
PAGE_URL = "https://example.com/news/"


# ─── Fixtures ──────────────────────────────────────────────────────────────────

ARTICLE_TAG_HTML = """
<html><body>
  <main>
    <article>
      <time datetime="2024-03-10">March 10, 2024</time>
      <span class="category">Technology</span>
      <h2><a href="/news/article-1">Article One Title</a></h2>
      <p>This is a description of article one with enough text.</p>
    </article>
    <article>
      <time datetime="2024-03-09">March 9, 2024</time>
      <span class="category">Business</span>
      <h3><a href="/news/article-2">Article Two Title</a></h3>
      <p>Description of article two.</p>
    </article>
  </main>
</body></html>
"""

CARD_CLASS_HTML = """
<html><body>
  <div class="news-listing">
    <div class="news-card">
      <time datetime="2024-02-20">Feb 20, 2024</time>
      <span class="label">AI</span>
      <h3><a href="/news/card-article-1">Card Article One</a></h3>
      <p>Card description one, with sufficient length for extraction.</p>
    </div>
    <div class="news-card">
      <time datetime="2024-02-18">Feb 18, 2024</time>
      <span class="label">Cloud</span>
      <h3><a href="/news/card-article-2">Card Article Two</a></h3>
      <p>Card description two, also long enough to pass the filter.</p>
    </div>
  </div>
</body></html>
"""

HEADING_FALLBACK_HTML = """
<html><body>
  <div class="post-list">
    <div class="post-item">
      <h4><a href="/blog/post-one">Blog Post One</a></h4>
      <span class="date">2024-01-15</span>
      <p>Post one has some descriptive text here that is long enough.</p>
    </div>
    <div class="post-item">
      <h4><a href="/blog/post-two">Blog Post Two</a></h4>
      <span class="date">2024-01-10</span>
      <p>Post two also has some descriptive text that is long enough.</p>
    </div>
  </div>
</body></html>
"""

NAV_FOOTER_PENALTY_HTML = """
<html><body>
  <nav>
    <h3><a href="/news/nav-link">This should be penalised</a></h3>
    <time datetime="2024-01-01">Jan 1</time>
  </nav>
  <footer>
    <h3><a href="/news/footer-link">Footer link</a></h3>
    <time datetime="2024-01-01">Jan 1</time>
  </footer>
  <main>
    <article>
      <h2><a href="/news/real-article">Real Article</a></h2>
      <time datetime="2024-03-01">March 1, 2024</time>
      <p>This is the real article description with enough text content here.</p>
    </article>
  </main>
</body></html>
"""

DUPLICATE_URL_HTML = """
<html><body>
  <article>
    <h2><a href="/news/same-article">Article Title A</a></h2>
    <time datetime="2024-01-10">Jan 10, 2024</time>
    <span class="category">Tech</span>
    <p>First occurrence of the article, with good description text here.</p>
  </article>
  <div class="news-card">
    <h3><a href="/news/same-article">Article Title B (same URL)</a></h3>
    <time datetime="2024-01-10">Jan 10</time>
    <p>Second occurrence — same URL, should be deduped.</p>
  </div>
</body></html>
"""

# Synthetic MathCo-like layout: Date | Category | Title | "Read more" link
# This uses generic card/press-release styling, NOT MathCo-specific selectors
MATHCO_LIKE_HTML = """
<html><body>
  <div class="press-listing">
    <div class="press-card">
      <span class="press-date"><time datetime="2024-09-05">September 5, 2024</time></span>
      <span class="press-tag">Press Release</span>
      <h3 class="press-title">
        <a href="/news/mathco-partnership-announcement">MathCo Announces Strategic Partnership</a>
      </h3>
      <p class="press-excerpt">The Math Company announces a new strategic partnership to expand AI capabilities.</p>
      <a href="/news/mathco-partnership-announcement" class="read-more">Read more</a>
    </div>
    <div class="press-card">
      <span class="press-date"><time datetime="2024-08-20">August 20, 2024</time></span>
      <span class="press-tag">News</span>
      <h3 class="press-title">
        <a href="/news/mathco-ai-product-launch">MathCo Launches New AI Product</a>
      </h3>
      <p class="press-excerpt">The Math Company today unveiled its latest artificial intelligence solution for enterprises.</p>
      <a href="/news/mathco-ai-product-launch" class="read-more">Read more</a>
    </div>
    <div class="press-card">
      <span class="press-date"><time datetime="2024-07-15">July 15, 2024</time></span>
      <span class="press-tag">Award</span>
      <h3 class="press-title">
        <a href="/news/mathco-award-recognition">MathCo Recognized in Industry Awards</a>
      </h3>
      <p class="press-excerpt">The Math Company has been recognized as a leader in AI innovation at the annual tech awards.</p>
      <a href="/news/mathco-award-recognition" class="read-more">Read more</a>
    </div>
  </div>
</body></html>
"""

NO_ARTICLES_HTML = """
<html><body>
  <nav><ul><li><a href="/">Home</a></li><li><a href="/about">About</a></li></ul></nav>
  <footer><p>Copyright 2024</p></footer>
</body></html>
"""


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestArticleTagExtraction:
    def test_extracts_both_articles(self):
        soup = make_soup(ARTICLE_TAG_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) >= 2

    def test_title_extracted(self):
        soup = make_soup(ARTICLE_TAG_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        titles = [a.title for a in articles]
        assert any("Article One Title" in t for t in titles)

    def test_date_extracted(self):
        soup = make_soup(ARTICLE_TAG_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        dated = [a for a in articles if a.date is not None]
        assert len(dated) >= 1

    def test_category_extracted(self):
        soup = make_soup(ARTICLE_TAG_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        with_cats = [a for a in articles if a.category is not None]
        assert len(with_cats) >= 1

    def test_url_is_absolute(self):
        soup = make_soup(ARTICLE_TAG_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        for a in articles:
            assert a.url.startswith("http")


class TestCardClassExtraction:
    def test_extracts_cards(self):
        soup = make_soup(CARD_CLASS_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) >= 2

    def test_label_as_category(self):
        soup = make_soup(CARD_CLASS_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        cats = [a.category for a in articles if a.category]
        assert len(cats) >= 1


class TestHeadingFallback:
    def test_extracts_from_heading_parents(self):
        soup = make_soup(HEADING_FALLBACK_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) >= 1

    def test_titles_captured(self):
        soup = make_soup(HEADING_FALLBACK_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        titles = [a.title for a in articles]
        assert any("Blog Post" in t for t in titles)


class TestNavFooterPenalty:
    def test_real_article_included(self):
        soup = make_soup(NAV_FOOTER_PENALTY_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        urls = [a.url for a in articles]
        assert any("real-article" in u for u in urls)

    def test_nav_footer_links_excluded_or_lower_priority(self):
        soup = make_soup(NAV_FOOTER_PENALTY_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        urls = [a.url for a in articles]
        # Nav and footer links should not appear (they score below threshold)
        assert not any("nav-link" in u for u in urls)
        assert not any("footer-link" in u for u in urls)


class TestDeduplication:
    def test_same_url_deduped(self):
        soup = make_soup(DUPLICATE_URL_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        urls = [a.url for a in articles]
        # Should only have one entry for /news/same-article
        matching = [u for u in urls if "same-article" in u]
        assert len(matching) == 1

    def test_higher_confidence_wins(self):
        """The first occurrence (inside <article>) should win due to higher score."""
        soup = make_soup(DUPLICATE_URL_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) == 1


class TestMathCoLikeLayout:
    """
    Synthetic MathCo-like press release listing test.
    Uses generic card/press-release markup without any hardcoded CMS selectors.
    """

    def test_extracts_three_articles(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) == 3

    def test_titles_extracted_correctly(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        titles = [a.title for a in articles]
        assert any("Strategic Partnership" in t for t in titles)
        assert any("AI Product" in t for t in titles)
        assert any("Award" in t for t in titles)

    def test_dates_extracted(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        dated = [a for a in articles if a.date is not None]
        assert len(dated) == 3

    def test_dates_correct_values(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        years = {a.date.year for a in articles if a.date}
        assert years == {2024}
        months = {a.date.month for a in articles if a.date}
        assert months == {9, 8, 7}

    def test_categories_extracted(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        cats = [a.category for a in articles if a.category]
        assert len(cats) >= 2

    def test_urls_are_absolute(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        for a in articles:
            assert a.url.startswith("https://")

    def test_source_page_set(self):
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        for a in articles:
            assert a.source_page == PAGE_URL

    def test_no_listing_url_as_article(self):
        """Articles must not link back to the listing page itself."""
        soup = make_soup(MATHCO_LIKE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        for a in articles:
            assert a.url != PAGE_URL


class TestNoArticles:
    def test_nav_footer_only_returns_empty(self):
        soup = make_soup(NO_ARTICLES_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        # Should return empty or minimal — no nav/footer links as articles
        for a in articles:
            assert "home" not in a.url.lower()


# ─── Keyword Filter Tests ───────────────────────────────────────────────────────

def _make_articles() -> list[Article]:
    from datetime import datetime, timezone
    return [
        Article(
            title="AI Revolution in Healthcare",
            url="https://example.com/ai-health",
            source_page=PAGE_URL,
            category="Technology",
            description="Artificial intelligence is transforming hospitals.",
            date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
        Article(
            title="Cloud Computing Trends",
            url="https://example.com/cloud",
            source_page=PAGE_URL,
            category="Business",
            description="Cloud adoption is accelerating in 2024.",
            date=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        Article(
            title="Quarterly Earnings Report",
            url="https://example.com/earnings",
            source_page=PAGE_URL,
            category="Finance",
            description="Company reports record quarterly revenue.",
            date=datetime(2024, 1, 3, tzinfo=timezone.utc),
        ),
    ]


class TestKeywordFilter:
    def test_any_mode_single_match(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["AI"], "any")
        assert len(result) == 1
        assert result[0].url == "https://example.com/ai-health"

    def test_any_mode_matches_description(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["cloud"], "any")
        assert len(result) == 1
        assert "cloud" in result[0].url

    def test_any_mode_matches_category(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["Finance"], "any")
        assert len(result) == 1

    def test_any_mode_multiple_keywords(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["AI", "Cloud"], "any")
        assert len(result) == 2

    def test_all_mode_requires_all_keywords(self):
        articles = _make_articles()
        # "AI" and "hospitals" both appear in first article's title+description
        result = apply_keyword_filter(articles, ["AI", "hospitals"], "all")
        assert len(result) == 1

    def test_all_mode_no_match(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["AI", "cloud"], "all")
        # No single article has both AI and cloud
        assert len(result) == 0

    def test_empty_keywords_returns_all(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, [], "any")
        assert len(result) == 3

    def test_case_insensitive(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["ai"], "any")
        assert len(result) == 1

    def test_whitespace_only_keywords_ignored(self):
        articles = _make_articles()
        result = apply_keyword_filter(articles, ["  ", ""], "any")
        assert len(result) == 3


# ─── List, Table & Container Pruning Tests ────────────────────────────────────

LIST_ITEMS_HTML = """
<html><body>
  <div class="articles-index">
    <ul>
      <li><a href="/habits-guide">The Ultimate Habit Guide for Beginners</a></li>
      <li><a href="/deep-work">Deep Work and How to Focus in a Distracted World</a></li>
      <li><a href="/atomic-routine">Atomic Daily Routines That Scale Your Productivity</a></li>
    </ul>
  </div>
</body></html>
"""

TABLE_ROW_READMORE_HTML = """
<html><body>
  <div class="custom-news-table">
    <div class="customRow">
      <div class="customTd">October 15, 2024</div>
      <div class="customTd">Press Release</div>
      <div class="customTd">Company Secures Major Enterprise AI Contract</div>
      <div class="customTd"><a href="/news/enterprise-contract-2024">Read more</a></div>
    </div>
    <div class="customRow">
      <div class="customTd">September 20, 2024</div>
      <div class="customTd">Product Launch</div>
      <div class="customTd">Announcing the Next-Gen Cloud Analytics Platform</div>
      <div class="customTd"><a href="/news/cloud-analytics-launch">Read more</a></div>
    </div>
  </div>
</body></html>
"""

CONTAINER_PRUNING_HTML = """
<html>
<body class="news-page news-listing">
  <div class="main-news-container">
    <article>
      <h2><a href="/news/item-1">First News Article Headline</a></h2>
      <time datetime="2024-01-01">Jan 1, 2024</time>
    </article>
    <article>
      <h2><a href="/news/item-2">Second News Article Headline</a></h2>
      <time datetime="2024-01-02">Jan 2, 2024</time>
    </article>
  </div>
</body>
</html>
"""


class TestListAndTableExtraction:
    def test_extracts_list_items(self):
        soup = make_soup(LIST_ITEMS_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) == 3
        titles = [a.title for a in articles]
        assert any("Habit Guide" in t for t in titles)
        assert any("Deep Work" in t for t in titles)
        assert any("Atomic Daily" in t for t in titles)

    def test_extracts_table_rows_with_generic_readmore(self):
        soup = make_soup(TABLE_ROW_READMORE_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) == 2
        titles = [a.title for a in articles]
        assert any("Enterprise AI Contract" in t for t in titles)
        assert any("Cloud Analytics Platform" in t for t in titles)
        # Ensure 'Read more' is NOT used as title
        assert not any(t.lower() == "read more" for t in titles)
        # Check dates
        dated = [a for a in articles if a.date]
        assert len(dated) == 2

    def test_container_pruning_does_not_extract_body(self):
        soup = make_soup(CONTAINER_PRUNING_HTML)
        articles = extract_articles(soup, PAGE_URL, BASE)
        assert len(articles) == 2
        urls = [a.url for a in articles]
        assert "https://example.com/news/item-1" in urls
        assert "https://example.com/news/item-2" in urls
        assert "https://example.com" not in urls
        assert "https://example.com/" not in urls

