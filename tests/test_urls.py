"""
tests/test_urls.py

Tests for URL normalization, validation, tracking param removal,
fragment stripping, and same-domain checks.
"""

import pytest
from scraper.urls import (
    normalize_url,
    is_valid_article_url,
    same_domain,
    base_url,
    is_http_url,
    add_page_param_to_url,
)


class TestNormalizeUrl:
    def test_relative_to_absolute(self):
        result = normalize_url("/news/article-1", "https://example.com/news/")
        assert result == "https://example.com/news/article-1"

    def test_relative_with_dot_dot(self):
        result = normalize_url("../article-1", "https://example.com/news/page/")
        assert result == "https://example.com/news/article-1"

    def test_strip_fragment(self):
        result = normalize_url("https://example.com/news#section")
        assert "#" not in result
        assert result == "https://example.com/news"

    def test_strip_utm_params(self):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=123"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=123" in result

    def test_strip_fbclid(self):
        url = "https://example.com/article?fbclid=abc123&page=1"
        result = normalize_url(url)
        assert "fbclid" not in result
        assert "page=1" in result

    def test_strip_gclid(self):
        url = "https://example.com/article?gclid=xyz&ref=homepage"
        result = normalize_url(url)
        assert "gclid" not in result

    def test_lowercase_scheme_and_host(self):
        result = normalize_url("HTTPS://Example.COM/news")
        assert result.startswith("https://example.com")

    def test_preserve_valid_query_params(self):
        url = "https://example.com/news?category=ai&page=2"
        result = normalize_url(url)
        assert "category=ai" in result
        assert "page=2" in result

    def test_empty_input(self):
        assert normalize_url("") == ""

    def test_absolute_url_unchanged(self):
        url = "https://example.com/news/article-slug"
        result = normalize_url(url)
        assert result == url


class TestIsValidArticleUrl:
    def test_valid_https_url(self):
        assert is_valid_article_url("https://example.com/news/my-article") is True

    def test_valid_http_url(self):
        assert is_valid_article_url("http://example.com/press/release-1") is True

    def test_reject_javascript(self):
        assert is_valid_article_url("javascript:void(0)") is False

    def test_reject_mailto(self):
        assert is_valid_article_url("mailto:user@example.com") is False

    def test_reject_tel(self):
        assert is_valid_article_url("tel:+1234567890") is False

    def test_reject_anchor_only(self):
        assert is_valid_article_url("#section") is False

    def test_reject_login_path(self):
        assert is_valid_article_url("https://example.com/login") is False

    def test_reject_pdf(self):
        assert is_valid_article_url("https://example.com/document.pdf") is False

    def test_reject_image(self):
        assert is_valid_article_url("https://example.com/image.jpg") is False

    def test_reject_empty(self):
        assert is_valid_article_url("") is False

    def test_reject_css_js_files(self):
        assert is_valid_article_url("https://example.com/style.css") is False
        assert is_valid_article_url("https://example.com/app.js") is False


class TestSameDomain:
    def test_same_domain(self):
        assert same_domain("https://example.com/a", "https://example.com/b") is True

    def test_different_domain(self):
        assert same_domain("https://example.com/a", "https://other.com/b") is False

    def test_different_scheme(self):
        assert same_domain("http://example.com/a", "https://example.com/b") is False


class TestBaseUrl:
    def test_extracts_scheme_host(self):
        assert base_url("https://example.com/news/page/2") == "https://example.com"

    def test_http(self):
        assert base_url("http://blog.example.org/posts") == "http://blog.example.org"


class TestIsHttpUrl:
    def test_https(self):
        assert is_http_url("https://example.com") is True

    def test_http(self):
        assert is_http_url("http://example.com") is True

    def test_ftp(self):
        assert is_http_url("ftp://example.com") is False

    def test_relative(self):
        assert is_http_url("/news/article") is False

    def test_empty(self):
        assert is_http_url("") is False


class TestAddPageParam:
    def test_adds_new_param(self):
        url = "https://example.com/news"
        result = add_page_param_to_url(url, "page", 3)
        assert "page=3" in result

    def test_replaces_existing_param(self):
        url = "https://example.com/news?page=1"
        result = add_page_param_to_url(url, "page", 2)
        assert "page=2" in result
        assert "page=1" not in result

    def test_preserves_other_params(self):
        url = "https://example.com/news?category=ai&page=1"
        result = add_page_param_to_url(url, "page", 2)
        assert "category=ai" in result
        assert "page=2" in result
