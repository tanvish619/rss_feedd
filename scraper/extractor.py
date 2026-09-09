"""
scraper/extractor.py

Heuristic article extraction and candidate scoring.

IMPORTANT: No CMS-specific selectors are hardcoded.
The extractor tries multiple extraction layers and scores each candidate
element to filter out navigation / footer noise.

Scoring rubric (per candidate element):
  +30  has a non-empty title
  +20  has a valid article URL
  +20  has a date
  +10  has a description
  +10  has a category
  -40  element is inside <nav> or <footer>
  -20  element is inside <header>
  -10  element has very short text (< 20 chars)

Minimum score to be included: 30
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from scraper.dates import parse_date_from_element
from scraper.models import Article
from scraper.urls import is_valid_article_url, normalize_url

logger = logging.getLogger(__name__)

# Minimum confidence score for an element to be considered an article candidate
_MIN_SCORE: float = 30.0

# Class/ID patterns that hint at article containers (case-insensitive substring match)
_ARTICLE_CLASS_PATTERNS: tuple[str, ...] = (
    "post",
    "news",
    "card",
    "press",
    "entry",
    "item",
    "release",
    "story",
    "article",
    "blog",
    "event",
    "update",
    "media",
    "listing",
    "result",
    "row",
    "tile",
    "grid-item",
    "feed-item",
    "content-block",
)

# Class/ID patterns for category labels
_CATEGORY_CLASS_PATTERNS: tuple[str, ...] = (
    "category",
    "cat",
    "tag",
    "label",
    "section",
    "topic",
    "type",
    "badge",
    "pill",
)

# Heading tags
_HEADING_TAGS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6")

# Layout tags that should never be collected as single article items
_CONTAINER_TAGS: frozenset[str] = frozenset(
    {"html", "body", "main", "header", "footer", "nav", "aside"}
)

# Generic action text on buttons/anchors that is NOT a title
_GENERIC_LINK_TEXTS: frozenset[str] = frozenset(
    {
        "read more",
        "readmore",
        "read",
        "click here",
        "learn more",
        "view more",
        "continue reading",
        "full story",
        "more",
        "details",
        "view",
        "explore",
        "see more",
        "link",
        "permalink",
        "download",
        "read article",
        "view article",
        "get started",
        "next",
        "previous",
        "share",
        "comment",
        "comments",
    }
)

# Max description length (chars)
_MAX_DESC_LEN = 500

# Contexts that penalise a candidate
_PENALISE_TAGS: dict[str, float] = {
    "nav": -40,
    "footer": -40,
    "header": -20,
    "aside": -10,
}

# OG/meta properties for image fallback
_OG_IMAGE_PROPERTIES = ("og:image", "twitter:image")


def _is_generic_text(text: str) -> bool:
    """Return True if text is a generic call-to-action rather than an article title."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text).lower().strip()
    return cleaned in _GENERIC_LINK_TEXTS or len(cleaned) < 3


def _class_or_id_matches(tag: Tag, patterns: tuple[str, ...]) -> bool:
    """Return True if any of *patterns* appear in the tag's class list or id attribute."""
    classes = " ".join(tag.get("class", [])).lower()
    tag_id = (tag.get("id") or "").lower()
    combined = classes + " " + tag_id
    return any(p in combined for p in patterns)


def _is_inside(element: Tag, tag_names: tuple[str, ...]) -> bool:
    """Return True if *element* has any ancestor whose tag name is in *tag_names*."""
    for ancestor in element.parents:
        if isinstance(ancestor, Tag) and ancestor.name in tag_names:
            return True
    return False


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip a string."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(candidate: Tag) -> Optional[str]:
    """
    Extract the best title from *candidate*.
    Priority:
      1. Heading tags inside candidate (h1-h6)
      2. Non-generic anchor text
      3. Elements with title/headline/name in class
      4. Strong/bold/prominent text in candidate
    """
    # 1. Heading tags
    for htag in _HEADING_TAGS:
        heading = candidate.find(htag)
        if heading:
            text = _clean_text(heading.get_text(" ", strip=True))
            if text and len(text) > 3 and not _is_generic_text(text):
                return text

    # 2. Non-generic <a> text
    anchors = candidate.find_all("a", href=True) if candidate.name != "a" else [candidate]
    for a in anchors:
        text = _clean_text(a.get_text(" ", strip=True))
        if text and len(text) > 5 and not _is_generic_text(text):
            return text

    # 3. Dedicated title/headline classes
    for tag in candidate.find_all(True):
        if not isinstance(tag, Tag):
            continue
        classes = " ".join(tag.get("class", [])).lower()
        if any(p in classes for p in ("title", "headline", "name", "subject", "heading")):
            text = _clean_text(tag.get_text(" ", strip=True))
            if text and len(text) > 5 and not _is_generic_text(text):
                if not parse_date_from_element(tag):
                    return text

    # 4. Longest non-date, non-category text block inside candidate
    best_candidate_text: Optional[str] = None
    for tag in candidate.find_all(["span", "div", "p", "td", "strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"]):
        if not isinstance(tag, Tag):
            continue
        # Skip tags with dates or category classes
        if parse_date_from_element(tag) or _class_or_id_matches(tag, _CATEGORY_CLASS_PATTERNS):
            continue
        # Also skip if tag is purely an anchor with generic text
        if tag.name == "a" and _is_generic_text(tag.get_text(" ", strip=True)):
            continue
        # If tag has children tags, prefer leaf text to avoid whole-row text
        if tag.find(["div", "p", "td", "span"]):
            continue
        text = _clean_text(tag.get_text(" ", strip=True))
        if len(text) >= 10 and not _is_generic_text(text):
            if best_candidate_text is None or len(text) > len(best_candidate_text):
                best_candidate_text = text

    if best_candidate_text:
        return best_candidate_text

    # 5. Longest text in candidate
    full_text = _clean_text(candidate.get_text(" ", strip=True))
    if len(full_text) > 10 and not _is_generic_text(full_text):
        parts = re.split(r"[\n|•·]+", full_text)
        for part in parts:
            p_clean = part.strip()
            if len(p_clean) >= 10 and not _is_generic_text(p_clean) and not parse_date_from_element(candidate):
                if best_candidate_text is None or len(p_clean) > len(best_candidate_text):
                    best_candidate_text = p_clean

    return best_candidate_text


def _extract_url(candidate: Tag, base_url: str, page_url: str) -> Optional[str]:
    """
    Extract the primary article URL from *candidate*.
    Prefers the anchor inside a heading; falls back to non-generic article anchors or 'read more' links.
    """
    norm_page = normalize_url(page_url)

    # 1. Prefer anchor inside a heading
    for htag in _HEADING_TAGS:
        heading = candidate.find(htag)
        if heading:
            a = heading.find("a", href=True)
            if a:
                href = a.get("href", "").strip()
                norm = normalize_url(href, base_url)
                if is_valid_article_url(norm) and norm != norm_page:
                    return norm

    # 2. Check all anchors in candidate
    anchors = candidate.find_all("a", href=True) if candidate.name != "a" else [candidate]
    valid_candidates: list[tuple[str, str]] = []

    for a in anchors:
        href = a.get("href", "").strip()
        norm = normalize_url(href, base_url)
        if not is_valid_article_url(norm) or norm == norm_page:
            continue
        a_text = _clean_text(a.get_text(" ", strip=True))
        valid_candidates.append((norm, a_text))

    if not valid_candidates:
        return None

    # Prefer non-generic anchor text first
    for norm, a_text in valid_candidates:
        if a_text and not _is_generic_text(a_text):
            return norm

    # Fallback to the first valid article URL (e.g. from "Read more" link)
    return valid_candidates[0][0]


def _extract_category(candidate: Tag) -> Optional[str]:
    """Look for category/tag/label text in common class patterns."""
    for tag in candidate.find_all(True):
        if not isinstance(tag, Tag):
            continue
        # Avoid select / option / dropdown elements
        if tag.name in ("select", "option", "ul", "ol") or "dropdown" in " ".join(tag.get("class", [])).lower():
            continue
        if _class_or_id_matches(tag, _CATEGORY_CLASS_PATTERNS):
            text = _clean_text(tag.get_text(" ", strip=True))
            # Sanity: reasonable category length, no long dropdown list text, and not a date
            if text and 2 <= len(text) <= 50 and not parse_date_from_element(tag):
                if not any(sep in text for sep in ("\n", "\t")):
                    return text
    return None


def _extract_description(candidate: Tag) -> Optional[str]:
    """Extract the best paragraph-level description text from *candidate*."""
    # Try explicit <p> tags
    for p in candidate.find_all("p"):
        text = _clean_text(p.get_text(" ", strip=True))
        if text and len(text) >= 20 and not _is_generic_text(text):
            return text[:_MAX_DESC_LEN]

    # Fallback: all visible text minus the title
    full_text = _clean_text(candidate.get_text(" ", strip=True))
    if len(full_text) >= 20:
        return full_text[:_MAX_DESC_LEN]

    return None


def _extract_image(candidate: Tag, base_url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
    """Extract the first meaningful image URL from *candidate*, with OG fallback."""
    img = candidate.find("img", src=True)
    if img:
        src = img.get("src", "").strip()
        if src:
            norm = normalize_url(src, base_url)
            if norm and norm.startswith("http"):
                return norm

    # OG image from page-level meta (via soup)
    if soup:
        for prop in _OG_IMAGE_PROPERTIES:
            tag = soup.find("meta", property=prop, content=True)
            if tag:
                content = tag.get("content", "").strip()
                if content:
                    return normalize_url(content, base_url)

    return None


def _extract_author(candidate: Tag) -> Optional[str]:
    """Look for author byline patterns."""
    author_patterns = ("author", "byline", "by-line", "writer", "contributor")
    for tag in candidate.find_all(True):
        if not isinstance(tag, Tag):
            continue
        classes_id = " ".join(tag.get("class", [])).lower() + " " + (tag.get("id") or "").lower()
        if any(p in classes_id for p in author_patterns):
            text = _clean_text(tag.get_text(" ", strip=True))
            text = re.sub(r"(?i)^(by|author):?\s*", "", text).strip()
            if text and 2 <= len(text) <= 100:
                return text

    full_text = candidate.get_text(" ", strip=True)
    m = re.search(r"\bBy\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})", full_text)
    if m:
        return m.group(1).strip()

    return None


def _score_candidate(candidate: Tag) -> float:
    """Compute and return the heuristic score for *candidate*."""
    score: float = 0.0

    # Title
    if _extract_title(candidate):
        score += 30

    # Date
    if parse_date_from_element(candidate):
        score += 20

    # Category
    if _extract_category(candidate):
        score += 10

    # Description / has enough text
    text_len = len(_clean_text(candidate.get_text(" ", strip=True)))
    if text_len >= 20:
        score += 10
    elif text_len < 20:
        score -= 10

    # Penalise placement in nav/footer/header/aside
    for tag_name, penalty in _PENALISE_TAGS.items():
        if _is_inside(candidate, (tag_name,)):
            score += penalty

    # Penalise candidates that are themselves nav/footer/header
    if candidate.name in ("nav", "footer", "header"):
        score -= 40

    return score


def _collect_candidates(soup: BeautifulSoup) -> list[Tag]:
    """
    Collect candidate elements using heuristic discovery layers.

    Layer 1: <article> elements
    Layer 2: <li> elements containing links
    Layer 3: <tr> / table rows containing links
    Layer 4: Elements with class/ID matching common patterns
    Layer 5: Heading tags (h1-h6) that contain an <a> — wrapped in parent
    Layer 6: Direct <a> tags with descriptive titles (> 15 chars)
    """
    seen_ids: set[int] = set()
    candidates: list[Tag] = []

    def _add(tag: Tag) -> None:
        if not isinstance(tag, Tag):
            return
        if tag.name in _CONTAINER_TAGS:
            return

        # Disallow major layout ancestors
        if _is_inside(tag, ("nav", "footer", "header")):
            return

        # If an element contains many distinct link URLs (> 8), it is a wrapper/container,
        # not an individual article card/row. Skip it and let its children be collected.
        links = tag.find_all("a", href=True)
        distinct_links = {a.get("href") for a in links}
        if len(distinct_links) > 8:
            return

        tag_id = id(tag)
        if tag_id not in seen_ids:
            seen_ids.add(tag_id)
            candidates.append(tag)

    # Layer 1: <article>
    for tag in soup.find_all("article"):
        _add(tag)

    # Layer 2: <li> with links
    for tag in soup.find_all("li"):
        if tag.find("a", href=True):
            _add(tag)

    # Layer 3: <tr> with links
    for tag in soup.find_all("tr"):
        if tag.find("a", href=True):
            _add(tag)

    # Layer 4: Common class/ID patterns on container elements that contain links
    for tag in soup.find_all(["div", "section", "article", "li", "tr", "td", "aside"]):
        if not isinstance(tag, Tag) or tag.name in ("article", "li", "tr", "html", "body"):
            continue
        if not tag.find("a", href=True):
            continue
        if _class_or_id_matches(tag, _ARTICLE_CLASS_PATTERNS):
            _add(tag)

    # Layer 5: Headings with links
    for htag in _HEADING_TAGS:
        for heading in soup.find_all(htag):
            if heading.find("a", href=True):
                parent = heading.parent
                if parent and isinstance(parent, Tag) and parent.name not in _CONTAINER_TAGS:
                    _add(parent)
                else:
                    _add(heading)

    # Layer 6: Direct <a> with descriptive titles
    for a in soup.find_all("a", href=True):
        text = _clean_text(a.get_text(" ", strip=True))
        if len(text) > 15 and not _is_generic_text(text):
            _add(a)

    # Step 1: Filter out macro containers that wrap multiple candidate items (e.g. tables/sections)
    non_containers: list[Tag] = []
    for c in candidates:
        child_count = sum(
            1
            for other in candidates
            if other is not c and isinstance(other, Tag) and any(p is c for p in other.parents)
        )
        if child_count < 2:
            non_containers.append(c)

    # Step 2: Filter out inner sub-elements (e.g. <a>, <h2>) if their parent card/row is already present
    pruned: list[Tag] = []
    for c in non_containers:
        has_card_parent = any(
            any(p is parent for p in c.parents)
            for parent in non_containers
            if parent is not c and isinstance(parent, Tag)
        )
        if not has_card_parent:
            pruned.append(c)

    return pruned if pruned else candidates


def extract_articles(
    soup: BeautifulSoup,
    page_url: str,
    base_url: str,
) -> list[Article]:
    """
    Main entry point. Extract and score article candidates from *soup*.

    Returns a list of Article objects with confidence >= _MIN_SCORE.
    Results are deduplicated by normalised URL (highest confidence wins).
    """
    candidates = _collect_candidates(soup)
    logger.debug("Collected %d raw candidates from %s", len(candidates), page_url)

    url_to_article: dict[str, Article] = {}

    for candidate in candidates:
        score = _score_candidate(candidate)
        if score < _MIN_SCORE:
            continue

        title = _extract_title(candidate)
        if not title:
            continue

        url = _extract_url(candidate, base_url, page_url)
        if not url:
            continue

        # URL validation: must not be the listing page itself
        if normalize_url(url) == normalize_url(page_url):
            continue

        # URL-only validity boost
        score += 20

        date = parse_date_from_element(candidate)
        category = _extract_category(candidate)
        description = _extract_description(candidate)
        image_url = _extract_image(candidate, base_url, soup)
        author = _extract_author(candidate)

        article = Article(
            title=title,
            url=url,
            source_page=page_url,
            date=date,
            category=category,
            description=description,
            image_url=image_url,
            author=author,
            confidence=score,
        )

        norm_url = normalize_url(url)
        existing = url_to_article.get(norm_url)
        if existing is None:
            url_to_article[norm_url] = article
        elif article.confidence > existing.confidence:
            if not article.date and existing.date:
                article.date = existing.date
            if not article.category and existing.category:
                article.category = existing.category
            if not article.description and existing.description:
                article.description = existing.description
            if not article.image_url and existing.image_url:
                article.image_url = existing.image_url
            if not article.author and existing.author:
                article.author = existing.author
            url_to_article[norm_url] = article
        else:
            # Existing has higher confidence, but merge missing fields from this candidate
            if not existing.date and article.date:
                existing.date = article.date
            if not existing.category and article.category:
                existing.category = article.category
            if not existing.description and article.description:
                existing.description = article.description

    result = list(url_to_article.values())
    logger.debug("Extracted %d articles from %s", len(result), page_url)
    return result


def apply_keyword_filter(
    articles: list[Article],
    keywords: list[str],
    match_mode: str,  # "any" or "all"
) -> list[Article]:
    """
    Filter *articles* by *keywords* across title, category, and description.

    match_mode="any"  — article passes if ANY keyword matches
    match_mode="all"  — article passes if ALL keywords match
    """
    if not keywords:
        return articles

    kw_lower = [k.lower().strip() for k in keywords if k.strip()]
    if not kw_lower:
        return articles

    filtered: list[Article] = []
    for article in articles:
        search_text = " ".join(
            filter(
                None,
                [
                    article.title,
                    article.category,
                    article.description,
                ],
            )
        ).lower()

        matches = [kw in search_text for kw in kw_lower]

        if match_mode == "all":
            if all(matches):
                filtered.append(article)
        else:  # "any"
            if any(matches):
                filtered.append(article)

    return filtered
