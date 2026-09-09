"""
rss/validator.py

Validates RSS 2.0 XML output before enabling download or displaying feeds.

Checks:
  - XML is well-formed (parses without error via lxml)
  - Root element is <rss> with version 2.0
  - Contains at least one <channel>
  - Channel contains required metadata: <title>, <link>, <description>
  - Contains at least one <item>
  - Every <item> has <title> or <description>
  - Every <item> has a valid <pubDate>
  - No malformed character entities outside CDATA blocks
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from lxml import etree


def validate_feed(xml_str: str) -> Tuple[bool, Optional[str]]:
    """
    Validate *xml_str* as a well-formed, complete RSS 2.0 document.

    Returns:
        (True, None)          — valid feed
        (False, error_msg)    — invalid; error_msg describes the problem
    """
    if not xml_str or not xml_str.strip():
        return False, "Feed XML is empty."

    # ── 1. Check for malformed HTML/XML entities (outside CDATA) ───────────
    malformed = _find_malformed_entities(xml_str)
    if malformed:
        return False, f"Malformed entity reference found outside CDATA: {malformed}"

    # ── 2. Parse with lxml ─────────────────────────────────────────────────
    try:
        xml_bytes = xml_str.encode("utf-8")
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        return False, f"XML parse error: {exc}"
    except Exception as exc:
        return False, f"Unexpected parse error: {exc}"

    # ── 3. Root element must be <rss> ──────────────────────────────────────
    local_name = etree.QName(root.tag).localname if root.tag.startswith("{") else root.tag
    if local_name != "rss":
        return False, f"Root element is <{local_name}>, expected <rss>."

    # ── 4. Must have a <channel> ──────────────────────────────────────────
    channels = root.findall("channel")
    if not channels:
        return False, "RSS feed is missing a <channel> element."

    channel = channels[0]

    # ── 5. Channel must have <title>, <link>, <description> ───────────────
    required_channel_elements = ("title", "link", "description")
    for elem_name in required_channel_elements:
        if channel.find(elem_name) is None:
            return False, f"<channel> is missing required <{elem_name}> element."

    # ── 6. Must have at least one <item> ──────────────────────────────────
    items = channel.findall("item")
    if not items:
        return False, "RSS feed contains no <item> elements."

    # ── 7. Item integrity checks ──────────────────────────────────────────
    for i, item in enumerate(items):
        has_title = item.find("title") is not None
        has_desc = item.find("description") is not None
        if not has_title and not has_desc:
            return False, f"Item #{i + 1} is missing both <title> and <description>."

        pubdate_el = item.find("pubDate")
        if pubdate_el is None or not (pubdate_el.text and pubdate_el.text.strip()):
            return False, f"Item #{i + 1} is missing a required <pubDate> tag."

    return True, None


def _find_malformed_entities(xml_str: str) -> Optional[str]:
    """
    Look for malformed HTML entity references outside CDATA blocks that would break XML parsing.
    Returns the offending string snippet or None.
    """
    # Strip CDATA sections first — CDATA safely contains raw characters like &, <, >
    cleaned = re.sub(r"<!\[CDATA\[.*?\]\]>", "", xml_str, flags=re.DOTALL)

    # Pattern: & followed by non-semicolon chars that don't form a valid entity reference
    # Valid XML entities: &amp; &lt; &gt; &apos; &quot; and numeric &#NNN; &#xHHH;
    pattern = re.compile(r"&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9A-Fa-f]+);)")
    m = pattern.search(cleaned)
    if m:
        start = max(0, m.start() - 10)
        end = min(len(cleaned), m.end() + 20)
        return repr(cleaned[start:end])
    return None


def get_feed_summary(xml_str: str) -> dict:
    """
    Parse a valid RSS XML string and return a summary dict with:
      - item_count
      - channel_title
      - channel_link
      - has_dates_count
    """
    summary = {
        "item_count": 0,
        "channel_title": "",
        "channel_link": "",
        "has_dates_count": 0,
    }
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
        channel = root.find("channel")
        if channel is None:
            return summary

        title_el = channel.find("title")
        link_el = channel.find("link")
        summary["channel_title"] = title_el.text or "" if title_el is not None else ""
        summary["channel_link"] = link_el.text or "" if link_el is not None else ""

        items = channel.findall("item")
        summary["item_count"] = len(items)
        summary["has_dates_count"] = sum(
            1 for item in items if item.find("pubDate") is not None and item.find("pubDate").text
        )
    except Exception:
        pass

    return summary
