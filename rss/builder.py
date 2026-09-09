"""
rss/builder.py

Build richly formatted, RFC-compliant RSS 2.0 XML, JSON Feed v1.1, and standalone HTML readers
from a list of extracted Article objects.

Enhancements:
  1. CDATA Encapsulation: All string-based XML nodes (<title>, <category>, <description>, <content:encoded>)
     are encapsulated in <![CDATA[...]]> tags to protect against special characters (&, <, >).
  2. Rich HTML Descriptions: <description> contains clean HTML snippets (<p>, <img>) rather than raw text.
  3. Full Content Encoding: Root <rss> includes xmlns:content="http://purl.org/rss/1.0/modules/content/" and
     every <item> includes a <content:encoded> block.
  4. Strict Structural Completeness: Every <item> has a valid RFC-822 <pubDate> (using intelligent fallback for
     undated articles preserving crawl order).
  5. URL Normalization: All <link> and <guid> fields use clean, normalized URLs with tracking parameters stripped.
"""

from __future__ import annotations

import email.utils
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from urllib.parse import urlparse

from lxml import etree

from scraper.models import Article
from scraper.urls import normalize_url

logger = logging.getLogger(__name__)

_FEED_LANGUAGE = "en"
_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
_ATOM_NS = "http://www.w3.org/2005/Atom"
_DC_NS = "http://purl.org/dc/elements/1.1/"

NSMAP = {
    "content": _CONTENT_NS,
    "atom": _ATOM_NS,
    "dc": _DC_NS,
}


def _auto_feed_title(source_url: str) -> str:
    """Generate a readable feed title from the source URL."""
    parsed = urlparse(source_url)
    domain = parsed.netloc.lower()
    domain = re.sub(r"^www\.", "", domain)
    path = parsed.path.strip("/").replace("/", " › ")
    if path:
        return f"{domain} — {path}"
    return f"{domain} — News"


def _auto_feed_description(source_url: str) -> str:
    """Generate a readable feed description from the source URL."""
    parsed = urlparse(source_url)
    domain = re.sub(r"^www\.", "", parsed.netloc.lower())
    return f"Auto-generated RSS feed of news articles from {domain}"


def _guess_mime(url: str) -> str:
    """Guess MIME type from image URL extension."""
    url_lower = url.lower()
    if url_lower.endswith(".png"):
        return "image/png"
    if url_lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if url_lower.endswith(".webp"):
        return "image/webp"
    if url_lower.endswith(".gif"):
        return "image/gif"
    if url_lower.endswith(".svg"):
        return "image/svg+xml"
    return "image/jpeg"


def _build_rich_description_html(article: Article) -> str:
    """
    Build a clean, rich HTML snippet for the <description> tag.
    Provides visual preview with <img> and <p> elements.
    """
    parts: list[str] = []

    # 1. Lead Image Preview
    if article.image_url:
        parts.append(
            f'<p><img src="{escape(article.image_url, quote=True)}" '
            f'alt="{escape(article.title, quote=True)}" '
            f'style="max-width: 100%; height: auto; border-radius: 6px;" /></p>'
        )

    # 2. Metadata subtitle if present
    meta_line: list[str] = []
    if article.category:
        meta_line.append(f'<strong>Category:</strong> {escape(article.category)}')
    if article.author:
        meta_line.append(f'<strong>Author:</strong> {escape(article.author)}')
    if meta_line:
        parts.append(f'<p><small style="color: #64748b;">{" | ".join(meta_line)}</small></p>')

    # 3. Clean paragraph text
    body_text = article.description if article.description else article.title
    if body_text:
        # Split multiline descriptions into distinct clean paragraphs
        paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [body_text]
        for p in paragraphs:
            parts.append(f'<p>{escape(p)}</p>')

    return "\n".join(parts)


def _build_full_content_html(article: Article) -> str:
    """
    Build a comprehensive rich HTML representation for <content:encoded>.
    Includes figure, meta headers, structured paragraphs, and clean source link.
    """
    parts: list[str] = ['<div class="article-body">']

    # 1. Hero / Lead Figure
    if article.image_url:
        parts.append(
            f'  <figure style="margin: 0 0 1.25rem 0;">\n'
            f'    <img src="{escape(article.image_url, quote=True)}" '
            f'alt="{escape(article.title, quote=True)}" '
            f'style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" />\n'
            f'  </figure>'
        )

    # 2. Metadata Bar
    meta_items: list[str] = []
    if article.category:
        meta_items.append(f'<span>🏷️ <strong>{escape(article.category)}</strong></span>')
    if article.author:
        meta_items.append(f'<span>✍️ <em>{escape(article.author)}</em></span>')
    if article.date:
        meta_items.append(f'<span>🗓️ {article.date.strftime("%B %d, %Y")}</span>')

    if meta_items:
        parts.append(
            f'  <p style="color: #64748b; font-size: 0.9em; margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid #e2e8f0;">'
            f'{" &bull; ".join(meta_items)}</p>'
        )

    # 3. Body Content: use full extracted content_html if available
    if article.content_html:
        parts.append(f'  <div class="article-rich-text">\n{article.content_html}\n  </div>')
    else:
        body_text = article.description if article.description else article.title
        if body_text:
            paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [body_text]
            for p in paragraphs:
                parts.append(f'  <p style="line-height: 1.6; margin-bottom: 1rem;">{escape(p)}</p>')

    # 4. Source / Read More Link
    norm_url = normalize_url(article.url)
    parts.append(
        f'  <p style="margin-top: 1.25rem;">\n'
        f'    <a href="{escape(norm_url, quote=True)}" target="_blank" rel="noopener" style="color: #4f46e5; font-weight: 600; text-decoration: underline;">'
        f'Read full article at source &rarr;</a>\n'
        f'  </p>'
    )
    parts.append('</div>')

    return "\n".join(parts)


def build_feed(
    articles: list[Article],
    source_url: str,
    feed_title: Optional[str] = None,
    feed_description: Optional[str] = None,
) -> str:
    """
    Build and return an RFC-compliant RSS 2.0 XML string with:
      - CDATA encapsulation for all string nodes (<title>, <category>, <description>, <content:encoded>)
      - Rich HTML in <description> and <content:encoded>
      - Full namespace support (xmlns:content, xmlns:atom, xmlns:dc)
      - Strict RFC-822 <pubDate> for every item (with fallback preserving crawl order)
      - Clean, normalized URLs for <link> and <guid>
    """
    feed_url = normalize_url(source_url)
    title_text = feed_title or _auto_feed_title(source_url)
    desc_text = feed_description or _auto_feed_description(source_url)
    now_utc = datetime.now(timezone.utc)

    # ── Root & Channel ────────────────────────────────────────────────────────
    rss = etree.Element("rss", version="2.0", nsmap=NSMAP)
    channel = etree.SubElement(rss, "channel")

    # Channel Title (wrapped in CDATA)
    ch_title = etree.SubElement(channel, "title")
    ch_title.text = etree.CDATA(title_text)

    # Channel Link
    ch_link = etree.SubElement(channel, "link")
    ch_link.text = feed_url

    # Atom self-reference link
    atom_link = etree.SubElement(
        channel,
        f"{{{_ATOM_NS}}}link",
        href=feed_url,
        rel="self",
        type="application/rss+xml",
    )

    # Channel Description (wrapped in CDATA)
    ch_desc = etree.SubElement(channel, "description")
    ch_desc.text = etree.CDATA(desc_text)

    # Channel Language & Generator
    ch_lang = etree.SubElement(channel, "language")
    ch_lang.text = _FEED_LANGUAGE

    ch_gen = etree.SubElement(channel, "generator")
    ch_gen.text = "NewsRSSBuilder/2.0"

    # Channel lastBuildDate (RFC-822)
    ch_lbd = etree.SubElement(channel, "lastBuildDate")
    ch_lbd.text = email.utils.format_datetime(now_utc)

    # ── Sort articles & assign robust publication dates ───────────────────────
    dated = [a for a in articles if a.date is not None]
    undated = [a for a in articles if a.date is None]

    # Newest dated first
    dated.sort(key=lambda a: a.date, reverse=True)

    # Determine baseline timestamp for undated items so they stay ordered after dated
    if dated:
        oldest_date = dated[-1].date
        if oldest_date.tzinfo is None:
            oldest_date = oldest_date.replace(tzinfo=timezone.utc)
        else:
            oldest_date = oldest_date.astimezone(timezone.utc)
        baseline_dt = oldest_date
    else:
        baseline_dt = now_utc

    sorted_articles = dated + undated
    undated_counter = 0

    # ── Add items ─────────────────────────────────────────────────────────────
    for article in sorted_articles:
        item = etree.SubElement(channel, "item")
        norm_article_url = normalize_url(article.url)

        # 1. Title (CDATA encapsulated)
        item_title = etree.SubElement(item, "title")
        item_title.text = etree.CDATA(article.title or "(No Title)")

        # 2. Link & GUID (Normalized URL)
        item_link = etree.SubElement(item, "link")
        item_link.text = norm_article_url

        item_guid = etree.SubElement(item, "guid", isPermaLink="true")
        item_guid.text = norm_article_url

        # 3. Publication Date (Strict RFC-822)
        if article.date is not None:
            dt = article.date
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            pub_dt = dt
        else:
            undated_counter += 1
            # Decrement slightly per undated item to maintain stable crawl order
            pub_dt = baseline_dt - timedelta(minutes=undated_counter)

        item_pubdate = etree.SubElement(item, "pubDate")
        item_pubdate.text = email.utils.format_datetime(pub_dt)

        # 4. Category (CDATA encapsulated if present)
        if article.category:
            item_cat = etree.SubElement(item, "category")
            item_cat.text = etree.CDATA(article.category)

        # 5. Author / dc:creator (CDATA encapsulated if present)
        if article.author:
            item_author = etree.SubElement(item, "author")
            item_author.text = etree.CDATA(article.author)

            item_dc_creator = etree.SubElement(item, f"{{{_DC_NS}}}creator")
            item_dc_creator.text = etree.CDATA(article.author)

        # 6. Rich HTML Description (CDATA encapsulated)
        rich_desc = _build_rich_description_html(article)
        item_desc = etree.SubElement(item, "description")
        item_desc.text = etree.CDATA(rich_desc)

        # 7. Full Content Encoding <content:encoded> (CDATA encapsulated)
        full_content = _build_full_content_html(article)
        item_content = etree.SubElement(item, f"{{{_CONTENT_NS}}}encoded")
        item_content.text = etree.CDATA(full_content)

        # 8. Media Enclosure (if image URL present)
        if article.image_url:
            etree.SubElement(
                item,
                "enclosure",
                url=article.image_url,
                length="0",
                type=_guess_mime(article.image_url),
            )

    # ── Output XML String ─────────────────────────────────────────────────────
    xml_bytes = etree.tostring(
        rss,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    )
    return xml_bytes.decode("utf-8")


def build_json_feed(
    articles: list[Article],
    source_url: str,
    feed_title: Optional[str] = None,
    feed_description: Optional[str] = None,
) -> str:
    """
    Build and return a JSON Feed (v1.1 compliant) formatted string.
    """
    dated = [a for a in articles if a.date is not None]
    undated = [a for a in articles if a.date is None]
    dated.sort(key=lambda a: a.date, reverse=True)
    sorted_articles = dated + undated

    title = feed_title or _auto_feed_title(source_url)
    desc = feed_description or _auto_feed_description(source_url)
    norm_source = normalize_url(source_url)

    items = []
    for a in sorted_articles:
        item = {
            "id": normalize_url(a.url),
            "url": normalize_url(a.url),
            "title": a.title,
            "content_html": _build_full_content_html(a),
            "content_text": a.description or a.title or "",
            "date_published": a.date.isoformat() if a.date else None,
            "category": a.category or None,
            "author": {"name": a.author} if a.author else None,
            "image": a.image_url or None,
            "source_page": a.source_page,
        }
        items.append(item)

    feed_data = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": title,
        "home_page_url": norm_source,
        "feed_url": f"{norm_source}/feed.json",
        "description": desc,
        "item_count": len(items),
        "items": items,
    }
    return json.dumps(feed_data, indent=2, ensure_ascii=False)


def build_html_feed(
    articles: list[Article],
    source_url: str,
    feed_title: Optional[str] = None,
) -> str:
    """
    Build a standalone, beautifully formatted HTML reader page for the feed.
    """
    dated = [a for a in articles if a.date is not None]
    undated = [a for a in articles if a.date is None]
    dated.sort(key=lambda a: a.date, reverse=True)
    sorted_articles = dated + undated

    title = feed_title or _auto_feed_title(source_url)
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M UTC")

    cards_html = ""
    for idx, a in enumerate(sorted_articles):
        date_badge = (
            f'<span class="badge date">🗓️ {a.date.strftime("%b %d, %Y")}</span>'
            if a.date
            else '<span class="badge undated">🗓️ Undated</span>'
        )
        cat_badge = (
            f'<span class="badge category">🏷️ {escape(a.category)}</span>'
            if a.category
            else ""
        )
        desc_p = (
            f'<p class="desc">{escape(a.description)}</p>'
            if a.description
            else ""
        )

        cards_html += f"""
        <article class="article-card">
            <div class="card-meta">
                <div class="badges">{date_badge} {cat_badge}</div>
                <span class="index">#{idx + 1}</span>
            </div>
            <h2 class="title"><a href="{escape(a.url)}" target="_blank" rel="noopener">{escape(a.title)}</a></h2>
            {desc_p}
            <div class="card-footer">
                <a href="{escape(a.url)}" target="_blank" rel="noopener" class="read-link">Read full story &rarr;</a>
            </div>
        </article>
        """

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)} — Feed Reader</title>
    <style>
        :root {{
            --bg: #090b10;
            --surface: #131722;
            --surface-hover: #1a2030;
            --border: rgba(255, 255, 255, 0.08);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #6366f1;
            --accent-light: #818cf8;
            --cyan: #38bdf8;
            --emerald: #34d399;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            line-height: 1.6;
            padding: 2.5rem 1rem;
        }}
        .container {{
            max-width: 860px;
            margin: 0 auto;
        }}
        header {{
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(14, 165, 233, 0.05) 100%);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
        }}
        header h1 {{
            font-size: 1.85rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        header p {{
            color: var(--text-muted);
            font-size: 0.92rem;
        }}
        .meta-stats {{
            display: flex;
            gap: 1.5rem;
            margin-top: 1rem;
            font-size: 0.85rem;
            color: var(--emerald);
            font-weight: 600;
        }}
        .article-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 1.5rem;
            margin-bottom: 1.25rem;
            transition: all 0.2s ease;
        }}
        .article-card:hover {{
            background: var(--surface-hover);
            border-color: rgba(99, 102, 241, 0.4);
            transform: translateY(-2px);
        }}
        .card-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.6rem;
        }}
        .badges {{
            display: flex;
            gap: 0.5rem;
            align-items: center;
            flex-wrap: wrap;
        }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.65rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge.date {{
            background: rgba(99, 102, 241, 0.12);
            color: var(--accent-light);
            border: 1px solid rgba(99, 102, 241, 0.25);
        }}
        .badge.category {{
            background: rgba(56, 189, 248, 0.12);
            color: var(--cyan);
            border: 1px solid rgba(56, 189, 248, 0.25);
        }}
        .badge.undated {{
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-muted);
        }}
        .index {{
            color: #475569;
            font-size: 0.8rem;
            font-family: monospace;
        }}
        h2.title {{
            font-size: 1.2rem;
            font-weight: 700;
            line-height: 1.4;
            margin-bottom: 0.5rem;
        }}
        h2.title a {{
            color: var(--text-main);
            text-decoration: none;
        }}
        h2.title a:hover {{
            color: var(--accent-light);
        }}
        .desc {{
            color: var(--text-muted);
            font-size: 0.92rem;
            margin-bottom: 0.8rem;
        }}
        .read-link {{
            color: var(--accent-light);
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        .read-link:hover {{
            text-decoration: underline;
        }}
        footer {{
            text-align: center;
            color: #475569;
            font-size: 0.8rem;
            margin-top: 3rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{escape(title)}</h1>
            <p>Source: <a href="{escape(source_url)}" target="_blank" style="color:var(--accent-light); text-decoration:none;">{escape(source_url)}</a></p>
            <div class="meta-stats">
                <span>✓ {len(sorted_articles)} Articles Indexed</span>
                <span>• Generated on {now_str}</span>
            </div>
        </header>
        <main>
            {cards_html}
        </main>
        <footer>
            Generated by News RSS Builder &bull; Standalone HTML Feed Reader
        </footer>
    </div>
</body>
</html>
"""
    return html_doc
