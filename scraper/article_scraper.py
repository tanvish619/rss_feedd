"""
scraper/article_scraper.py

Fetches and parses individual article detail pages to extract rich content,
high-resolution lead images, accurate publication dates, authors, categories,
and full HTML body representations.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import unescape
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from requests import Session

from scraper.dates import _safe_parse, parse_date_from_element, parse_date_from_page
from scraper.models import Article
from scraper.urls import normalize_url
from utils.http import fetch

logger = logging.getLogger(__name__)

# Boilerplate tags and classes to prune from article body
_DISALLOWED_TAGS = {"script", "style", "noscript", "iframe", "svg", "nav", "header", "footer", "form", "button", "input"}
_DISALLOWED_CLASSES_RE = re.compile(
    r"(comment|social|share|nav|footer|header|sidebar|related|newsletter|subscribe|ad-|banner|cookie|promo|modal|popup|widget)",
    re.IGNORECASE,
)


def enrich_article(
    article: Article,
    session: Session,
    timeout: float = 10.0,
) -> Article:
    """
    Fetch the article's detail URL and extract detailed metadata and content.
    Returns the enriched Article object.
    """
    if not article.url:
        return article

    try:
        response, error = fetch(article.url, session, timeout=timeout, delay=0.0)
        if error or response is None or response.status_code != 200:
            logger.debug("Failed to fetch detail page for %s: %s", article.url, error)
            return article

        html = response.text
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # ── 1. JSON-LD Structured Data ────────────────────────────────────────
        json_ld_list = _extract_json_ld(soup)
        article_schema = _find_article_schema(json_ld_list)

        # ── 2. Meta Tags (OpenGraph, Twitter, Standard) ───────────────────────
        meta = _extract_meta_tags(soup)

        # ── 3. Title ──────────────────────────────────────────────────────────
        extracted_title = (
            meta.get("og:title")
            or meta.get("twitter:title")
            or (article_schema.get("headline") if article_schema else None)
            or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)
            or (soup.title.string.strip() if soup.title and soup.title.string else None)
        )
        if extracted_title and (not article.title or len(extracted_title) > len(article.title) or article.title == "(No Title)"):
            article.title = _clean_title(extracted_title)

        # ── 4. Publication Date ───────────────────────────────────────────────
        if not article.date:
            extracted_date = _extract_article_date(soup, meta, article_schema)
            if extracted_date:
                article.date = extracted_date

        # ── 5. Author ─────────────────────────────────────────────────────────
        if not article.author:
            extracted_author = _extract_article_author(soup, meta, article_schema)
            if extracted_author:
                article.author = extracted_author

        # ── 6. Category / Tags ────────────────────────────────────────────────
        if not article.category:
            extracted_category = _extract_article_category(soup, meta, article_schema)
            if extracted_category:
                article.category = extracted_category

        # ── 7. Lead Image ─────────────────────────────────────────────────────
        if not article.image_url:
            extracted_image = _extract_article_image(soup, meta, article_schema, article.url)
            if extracted_image:
                article.image_url = extracted_image

        # ── 8. Detailed Description & Full Content HTML ───────────────────────
        body_html, text_desc = _extract_article_body(soup, article.url)

        if text_desc and (not article.description or len(text_desc) > len(article.description)):
            article.description = text_desc
        elif not article.description:
            meta_desc = meta.get("og:description") or meta.get("description") or meta.get("twitter:description")
            if meta_desc:
                article.description = unescape(meta_desc.strip())

        if body_html:
            article.content_html = body_html

    except Exception as exc:
        logger.warning("Error enriching article %s: %s", article.url, exc)

    return article


def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Parse all JSON-LD script blocks in the document."""
    results: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
            if isinstance(data, list):
                results.extend([x for x in data if isinstance(x, dict)])
            elif isinstance(data, dict):
                # Handle @graph
                if "@graph" in data and isinstance(data["@graph"], list):
                    results.extend([x for x in data["@graph"] if isinstance(x, dict)])
                else:
                    results.append(data)
        except Exception:
            continue
    return results


def _find_article_schema(json_ld_list: list[dict]) -> Optional[dict]:
    """Find the primary Article/NewsArticle/BlogPosting schema in JSON-LD."""
    article_types = {"article", "newsarticle", "blogposting", "report", "techarticle", "pressrelease"}
    for item in json_ld_list:
        if not isinstance(item, dict):
            continue
        item_type = item.get("@type", "")
        if isinstance(item_type, list):
            types_lower = {t.lower() for t in item_type if isinstance(t, str)}
            if types_lower & article_types:
                return item
        elif isinstance(item_type, str) and item_type.lower() in article_types:
            return item
    return None


def _extract_meta_tags(soup: BeautifulSoup) -> dict[str, str]:
    """Extract standard, og, and twitter meta tags."""
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        content = tag.get("content", "").strip()
        if not content:
            continue
        prop = tag.get("property", "").strip().lower()
        name = tag.get("name", "").strip().lower()
        if prop:
            meta[prop] = unescape(content)
        if name:
            meta[name] = unescape(content)
    return meta


def _clean_title(title: str) -> str:
    """Strip common site suffix badges like ' - ExampleSite' or ' | Blog'."""
    clean = re.sub(r"\s+[-–—|]\s+[^-–—|]+$", "", title).strip()
    return clean if len(clean) >= 5 else title


def _extract_article_date(
    soup: BeautifulSoup,
    meta: dict[str, str],
    schema: Optional[dict],
) -> Optional[datetime]:
    """Extract published date with priority: Schema -> Meta -> <time> -> Page."""
    # 1. Schema.org
    if schema:
        pub = schema.get("datePublished") or schema.get("dateModified")
        if pub and isinstance(pub, str):
            dt = _safe_parse(pub)
            if dt:
                return dt

    # 2. Meta tags
    date_props = [
        "article:published_time",
        "og:article:published_time",
        "publication_date",
        "date",
        "pubdate",
        "publishdate",
        "dc.date",
        "parsely-pub-date",
    ]
    for prop in date_props:
        if prop in meta:
            dt = _safe_parse(meta[prop])
            if dt:
                return dt

    # 3. <time> elements in header or article
    time_tags = soup.find_all("time")
    for tt in time_tags:
        dt = parse_date_from_element(tt)
        if dt:
            return dt

    # 4. Fallback: whole-page scanner
    return parse_date_from_page(soup)


def _extract_article_author(
    soup: BeautifulSoup,
    meta: dict[str, str],
    schema: Optional[dict],
) -> Optional[str]:
    """Extract article author name."""
    # 1. Schema.org
    if schema:
        author_val = schema.get("author")
        if isinstance(author_val, dict):
            name = author_val.get("name")
            if name and isinstance(name, str):
                return unescape(name.strip())
        elif isinstance(author_val, list) and author_val:
            first = author_val[0]
            if isinstance(first, dict) and "name" in first:
                return unescape(first["name"].strip())
            elif isinstance(first, str):
                return unescape(first.strip())
        elif isinstance(author_val, str):
            return unescape(author_val.strip())

    # 2. Meta tags
    for key in ("author", "article:author", "twitter:creator", "dc.creator", "parsely-author"):
        val = meta.get(key)
        if val and not val.startswith("http") and len(val) < 60:
            return val

    # 3. HTML byline selectors
    author_el = soup.find(class_=re.compile(r"\b(author|byline|posted-by|writer|post-info-author)\b", re.IGNORECASE))
    if author_el:
        txt = author_el.get_text(" ", strip=True)
        txt = re.sub(r"^(by|written by|posted by)\s+", "", txt, flags=re.IGNORECASE).strip()
        if 2 <= len(txt) <= 50:
            return unescape(txt)

    return None


def _extract_article_category(
    soup: BeautifulSoup,
    meta: dict[str, str],
    schema: Optional[dict],
) -> Optional[str]:
    """Extract article category/section."""
    # 1. Schema.org
    if schema:
        cat = schema.get("articleSection") or schema.get("keywords")
        if isinstance(cat, str) and cat.strip():
            return unescape(cat.split(",")[0].strip())
        elif isinstance(cat, list) and cat and isinstance(cat[0], str):
            return unescape(cat[0].strip())

    # 2. Meta tags
    for key in ("article:section", "category", "dc.subject", "parsely-section"):
        val = meta.get(key)
        if val and len(val) < 50:
            return val

    # 3. HTML breadcrumbs or category badge
    cat_el = soup.find(class_=re.compile(r"\b(category|tag|section|kicker|post-info-cat)\b", re.IGNORECASE))
    if cat_el:
        txt = cat_el.get_text(" ", strip=True)
        if 2 <= len(txt) <= 40:
            return unescape(txt)

    return None


def _extract_article_image(
    soup: BeautifulSoup,
    meta: dict[str, str],
    schema: Optional[dict],
    page_url: str,
) -> Optional[str]:
    """Extract lead article image URL."""
    # 1. OpenGraph / Twitter
    for key in ("og:image", "twitter:image", "og:image:url"):
        val = meta.get(key)
        if val and val.startswith(("http://", "https://")):
            return val

    # 2. Schema.org
    if schema:
        img_val = schema.get("image")
        if isinstance(img_val, dict):
            url = img_val.get("url")
            if url and isinstance(url, str):
                return urljoin(page_url, url)
        elif isinstance(img_val, list) and img_val:
            first = img_val[0]
            if isinstance(first, str):
                return urljoin(page_url, first)
            elif isinstance(first, dict) and "url" in first:
                return urljoin(page_url, first["url"])
        elif isinstance(img_val, str):
            return urljoin(page_url, img_val)

    # 3. Lead image in <article> or <main>
    container = soup.find("article") or soup.find("main")
    if container:
        img = container.find("img", src=True)
        if img:
            src = img.get("src", "").strip()
            if src and not src.startswith("data:") and not re.search(r"(icon|logo|avatar|tracker|pixel)", src, re.IGNORECASE):
                return urljoin(page_url, src)

    return None


def _extract_article_body(soup: BeautifulSoup, page_url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract the main article content container, clean boilerplate,
    and return (clean_html, excerpt_text).
    """
    # Priority selectors for main article body
    selector_pattern = re.compile(
        r"\b(entry-content|post-content|post__content|page__content|page-content|page-content-style|article-content|article__content|story-body|article__body|post-body|rich-text|prose)\b",
        re.IGNORECASE,
    )
    candidates = [
        soup.find("article"),
        soup.find(attrs={"itemprop": "articleBody"}),
        soup.find(class_=selector_pattern),
        soup.find("main"),
        soup.find(class_=re.compile(r"\b(content-area|blog-post|post|article)\b", re.IGNORECASE)),
    ]

    body_tag: Optional[Tag] = None
    for cand in candidates:
        if cand and isinstance(cand, Tag):
            # Must contain paragraphs or meaningful text
            if len(cand.find_all("p")) >= 1 or len(cand.get_text(strip=True)) > 80:
                body_tag = cand
                break

    # Fallback: container with highest paragraph count
    if not body_tag:
        best_div = None
        max_p = 0
        for div in soup.find_all(["div", "section"]):
            p_count = len(div.find_all("p", recursive=False))
            if p_count > max_p:
                max_p = p_count
                best_div = div
        if best_div and max_p >= 2:
            body_tag = best_div

    if not body_tag:
        return None, None

    # Clone tag to avoid mutating soup
    tag_copy = BeautifulSoup(str(body_tag), "html.parser").find()
    if not tag_copy or not isinstance(tag_copy, Tag):
        return None, None

    # Remove disallowed tags and classes
    for t in tag_copy.find_all(list(_DISALLOWED_TAGS)):
        t.decompose()

    for el in list(tag_copy.find_all(True)):
        if not isinstance(el, Tag):
            continue
        classes = " ".join(el.get("class", [])) if isinstance(el.get("class"), list) else el.get("class", "")
        el_id = el.get("id", "")
        if _DISALLOWED_CLASSES_RE.search(classes) or _DISALLOWED_CLASSES_RE.search(el_id):
            el.decompose()

    # Extract clean paragraphs, headings, figures, lists
    clean_blocks: list[str] = []
    text_paragraphs: list[str] = []

    for child in tag_copy.find_all(["p", "h2", "h3", "h4", "blockquote", "ul", "ol", "figure", "img"]):
        if child.name == "p":
            txt = child.get_text(" ", strip=True)
            if len(txt) > 15:
                text_paragraphs.append(txt)
                clean_blocks.append(f"<p>{escape_html_text(txt)}</p>")
        elif child.name in ("h2", "h3", "h4"):
            txt = child.get_text(" ", strip=True)
            if len(txt) > 3:
                clean_blocks.append(f"<{child.name}>{escape_html_text(txt)}</{child.name}>")
        elif child.name == "blockquote":
            txt = child.get_text(" ", strip=True)
            if txt:
                clean_blocks.append(f"<blockquote><p>{escape_html_text(txt)}</p></blockquote>")
        elif child.name in ("ul", "ol"):
            items = [li.get_text(" ", strip=True) for li in child.find_all("li") if li.get_text(" ", strip=True)]
            if items:
                lis = "".join(f"<li>{escape_html_text(it)}</li>" for it in items)
                clean_blocks.append(f"<{child.name}>{lis}</{child.name}>")
        elif child.name == "img":
            src = child.get("src", "")
            if src and not src.startswith("data:") and not re.search(r"(icon|logo|avatar|tracker|pixel)", src, re.IGNORECASE):
                full_src = urljoin(page_url, src)
                alt = child.get("alt", "")
                clean_blocks.append(f'<p><img src="{full_src}" alt="{escape_html_text(alt)}" style="max-width:100%; height:auto;" /></p>')

    if not clean_blocks and not text_paragraphs:
        raw_text = tag_copy.get_text(" ", strip=True)
        if len(raw_text) > 50:
            return f"<p>{escape_html_text(raw_text[:2000])}</p>", raw_text[:350]
        return None, None

    clean_html = "\n".join(clean_blocks)
    excerpt = " ".join(text_paragraphs[:2]) if text_paragraphs else None
    if excerpt and len(excerpt) > 350:
        excerpt = excerpt[:347] + "..."

    return clean_html, excerpt


def escape_html_text(text: str) -> str:
    """Safe escape for text content inside tags."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
