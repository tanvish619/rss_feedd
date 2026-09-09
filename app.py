"""
app.py — RSS & Feed Generator with Automated GitHub Pages Hosting

Crawls listing pages heuristically, extracts rich article metadata and body HTML,
generates RFC-compliant RSS 2.0 XML with CDATA encapsulation, and automatically
publishes live to GitHub Pages via PyGithub with unique permalinks.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
import streamlit as st
from dotenv import load_dotenv

# Load local .env file
load_dotenv()

from rss.builder import build_feed, build_html_feed, build_json_feed
from rss.publisher import publish_to_github
from rss.validator import get_feed_summary, validate_feed
from scraper.crawler import crawl
from scraper.extractor import apply_keyword_filter
from scraper.models import Article, CrawlStats
from scraper.urls import is_http_url, normalize_url
from utils.http import build_session

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Export directory ──────────────────────────────────────────────────────────
EXPORTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "exports"))
os.makedirs(EXPORTS_DIR, exist_ok=True)

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Feed Engine · Crawl & GitHub Pages Publisher",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom Luxury Tech Style CSS ──────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
}

h1, h2, h3, .brand-font {
    font-family: 'Space Grotesk', sans-serif !important;
}

/* Background */
.stApp {
    background-color: #08090d;
    background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.08) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(14, 165, 233, 0.08) 0px, transparent 50%),
        radial-gradient(at 50% 100%, rgba(168, 85, 247, 0.05) 0px, transparent 50%);
    color: #f1f5f9;
}

/* GitHub Pages Live Banner Card */
.github-live-card {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(99, 102, 241, 0.1) 100%);
    border: 1px solid rgba(52, 211, 153, 0.35);
    border-radius: 16px;
    padding: 1.5rem 1.8rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 8px 32px rgba(16, 185, 129, 0.15);
}

.github-live-url {
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(52, 211, 153, 0.3);
    border-radius: 10px;
    padding: 0.75rem 1.25rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.05rem;
    color: #34d399;
    word-break: break-all;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 0.8rem;
    gap: 1rem;
}

/* Download Format Cards */
.download-card {
    background: rgba(18, 22, 38, 0.7);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 1.25rem 1.4rem;
    text-align: left;
    transition: all 0.2s ease;
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    margin-bottom: 0.75rem;
}
.download-card:hover {
    border-color: rgba(99, 102, 241, 0.5);
    transform: translateY(-2px);
    box-shadow: 0 8px 30px -4px rgba(99, 102, 241, 0.25);
}

/* Article Card */
.article-item {
    background: rgba(15, 18, 30, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 1.3rem 1.5rem;
    margin-bottom: 0.85rem;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.article-item:hover {
    border-color: rgba(129, 140, 248, 0.35);
    background: rgba(22, 27, 46, 0.85);
    transform: translateX(3px);
}

/* Pills & Tags */
.tag-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.65rem;
    border-radius: 6px;
    font-size: 0.74rem;
    font-weight: 600;
    letter-spacing: 0.3px;
    text-transform: uppercase;
}
.tag-date {
    background: rgba(99, 102, 241, 0.12);
    color: #a5b4fc;
    border: 1px solid rgba(165, 180, 252, 0.2);
}
.tag-category {
    background: rgba(56, 189, 248, 0.12);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.25);
}

/* Metric Boxes */
div[data-testid="stMetric"] {
    background: rgba(15, 18, 30, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 0.85rem 1.1rem;
}
div[data-testid="stMetricLabel"] p {
    color: #64748b !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
div[data-testid="stMetricValue"] div {
    color: #f8fafc !important;
    font-weight: 700 !important;
}

/* Primary buttons */
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.25rem !important;
    box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35) !important;
    transition: all 0.2s ease !important;
}
div.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5) !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# ── Session state ─────────────────────────────────────────────────────────────
def _init_state() -> None:
    defaults = {
        "crawl_done": False,
        "articles": [],
        "stats": None,
        "feed_xml": None,
        "feed_json": None,
        "feed_html": None,
        "feed_valid": False,
        "feed_error": None,
        "log_messages": [],
        "crawl_error": None,
        "exports_saved": False,
        "github_published": False,
        "github_pages_url": None,
        "github_error": None,
        "feed_file_name": "feed.xml",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_secret(key: str, default: str = "") -> str:
    """Safely get a secret from environment (.env), Streamlit secrets, or return default."""
    env_val = os.getenv(key)
    if env_val and env_val.strip() and not env_val.startswith("your_"):
        return env_val.strip()
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return default


def _generate_unique_feed_path(source_url: str, ext: str = "xml") -> str:
    """Generate a unique file path for each crawl, e.g. feeds/domain_YYYYMMDD_HHMMSS.xml"""
    parsed = urlparse(source_url)
    domain = parsed.netloc.lower()
    domain = re.sub(r"^www\.", "", domain)
    domain_clean = re.sub(r"[^a-zA-Z0-9]+", "_", domain).strip("_")
    if not domain_clean:
        domain_clean = "news"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"feeds/{domain_clean}_{ts}.{ext}"


def _validate_url(url: str) -> Optional[str]:
    url = url.strip()
    if not url:
        return "Please provide a valid web URL."
    if not is_http_url(url):
        return "URL must start with http:// or https://"
    parsed = urlparse(url)
    if not parsed.netloc:
        return "Invalid domain name in URL."
    return None


def _check_reachable(url: str, session: requests.Session, timeout: float = 10.0) -> Optional[str]:
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 405:
            resp = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
            resp.close()
        if resp.status_code in (401, 403):
            return f"Access forbidden (HTTP {resp.status_code})."
        if resp.status_code == 404:
            return "Page not found (HTTP 404)."
        if resp.status_code >= 500:
            return f"Remote server error (HTTP {resp.status_code})."
    except requests.exceptions.ConnectionError:
        return "Failed to establish connection. Check your network or URL."
    except requests.exceptions.Timeout:
        return "Request timed out."
    except requests.exceptions.RequestException as exc:
        return f"Network error: {exc}"
    return None


def _make_data_uri(content: str, mime: str) -> str:
    """Generate a client-side base64 data URI for instant browser download."""
    b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    return f"data:{mime};charset=utf-8;base64,{b64}"


# ── Header & Main Input Form ──────────────────────────────────────────────────
st.markdown(
    """
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; padding-bottom:1rem; border-bottom:1px solid rgba(255,255,255,0.08);">
    <div>
        <h1 style="font-size:2rem; font-weight:800; letter-spacing:-0.5px; margin:0; color:#ffffff;">
            ⚡ RSS Feed & Live GitHub Publisher
        </h1>
        <p style="color:#94a3b8; font-size:0.9rem; margin-top:0.3rem; margin-bottom:0;">
            Deep crawl news listings, enrich article metadata, and automatically host unique live feeds on GitHub Pages.
        </p>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# Main Search & Execution Bar
with st.container():
    col_input, col_kw, col_btn = st.columns([4, 2, 1.6])

    with col_input:
        target_url = st.text_input(
            "Listing Page URL",
            placeholder="https://example.com/news/ or https://example.com/blog",
            label_visibility="collapsed",
            key="url_main_input",
        )

    with col_kw:
        kw_filter = st.text_input(
            "Keywords (optional)",
            placeholder="Filter keywords: e.g. AI, Cloud",
            label_visibility="collapsed",
            key="kw_main_input",
        )

    with col_btn:
        start_crawl = st.button(
            "⚡ Generate & Publish RSS Feed",
            type="primary",
            use_container_width=True,
            key="start_crawl_btn",
        )

    # Clean Crawler Options
    with st.expander("⚙️ Crawler Options (Max Pages, Limit, Match Mode)", expanded=False):
        c_opt1, c_opt2, c_opt3, c_opt4 = st.columns(4)
        with c_opt1:
            max_pages = st.number_input("Max Listing Pages", min_value=1, max_value=100, value=5, step=1)
        with c_opt2:
            max_articles = st.number_input("Max Articles Limit", min_value=1, max_value=500, value=50, step=10)
        with c_opt3:
            match_mode = st.selectbox("Keyword Matching", ["Any keyword", "All keywords"])
        with c_opt4:
            crawl_delay = st.slider("Crawl Delay (s)", min_value=0.0, max_value=5.0, value=0.5, step=0.1)


# ── Execution Loop ────────────────────────────────────────────────────────────
if start_crawl:
    st.session_state.update(
        {
            "crawl_done": False,
            "articles": [],
            "stats": None,
            "feed_xml": None,
            "feed_json": None,
            "feed_html": None,
            "feed_valid": False,
            "feed_error": None,
            "log_messages": [],
            "crawl_error": None,
            "exports_saved": False,
            "github_published": False,
            "github_pages_url": None,
            "github_error": None,
            "feed_file_name": "feed.xml",
        }
    )

    url = target_url.strip()

    # Validate
    url_err = _validate_url(url)
    if url_err:
        st.error(f"❌ {url_err}")
        st.stop()

    session = build_session()

    # Reachability
    with st.spinner(f"Connecting to {url}…"):
        reach_err = _check_reachable(url, session)

    if reach_err:
        st.error(f"🔌 {reach_err}")
        st.stop()

    # Keywords
    keywords = [k.strip() for k in kw_filter.split(",") if k.strip()] if kw_filter else []
    match_mode_key = "all" if match_mode == "All keywords" else "any"

    # Progress HUD
    st.markdown("<br>", unsafe_allow_html=True)
    hud_prog = st.progress(0.0, text="Initializing crawl & extraction engine…")
    hud_status = st.empty()
    hud_metrics = st.empty()

    collected_articles: list[Article] = []
    last_stats: Optional[CrawlStats] = None
    log_messages: list[str] = []

    with st.spinner("Crawling listing, extracting articles, building RSS feed, and publishing to GitHub Pages..."):
        try:
            for new_articles, stats, message in crawl(
                start_url=url,
                max_pages=int(max_pages),
                max_articles=int(max_articles),
                timeout=15.0,
                delay=float(crawl_delay),
                session=session,
                enrich_details=True,
            ):
                if not stats.robots_allowed:
                    st.error("🚫 Access blocked by site's robots.txt policy.")
                    st.stop()

                collected_articles.extend(new_articles)
                last_stats = stats
                log_messages.append(message)

                hud_status.markdown(f"`{message}`")

                if stats.pages_discovered > 0:
                    prog = min(stats.pages_crawled / max(stats.pages_discovered, 1), 1.0)
                    hud_prog.progress(prog, text=f"Processing page {stats.pages_crawled} of {stats.pages_discovered}…")

                with hud_metrics.container():
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Pages Visited", stats.pages_crawled)
                    m2.metric("Raw Found", stats.articles_found)
                    m3.metric("Unique Items", len(collected_articles))
                    m4.metric("Dupes Merged", stats.duplicates_removed)

            hud_prog.progress(1.0, text="Crawl & Enrichment Complete!")

        except Exception as exc:
            st.session_state["crawl_error"] = str(exc)
            logger.exception("Crawl error")

    # Deduplicate
    seen_urls: set[str] = set()
    final_articles: list[Article] = []
    for a in collected_articles:
        norm = normalize_url(a.url)
        if norm not in seen_urls:
            seen_urls.add(norm)
            final_articles.append(a)

    # Keywords filter
    if keywords:
        pre_count = len(final_articles)
        final_articles = apply_keyword_filter(final_articles, keywords, match_mode_key)
        if last_stats:
            last_stats.articles_filtered = pre_count - len(final_articles)

    if last_stats:
        last_stats.articles_without_dates = sum(1 for a in final_articles if a.date is None)

    # Build all 3 export formats: XML, JSON, HTML
    if final_articles:
        try:
            feed_xml = build_feed(final_articles, url)
            feed_json = build_json_feed(final_articles, url)
            feed_html = build_html_feed(final_articles, url)

            # Generate a unique file path for this crawl
            unique_rel_path = _generate_unique_feed_path(url, "xml")
            st.session_state["feed_file_name"] = os.path.basename(unique_rel_path)

            # Auto-save directly to local disk in exports/ folder
            try:
                with open(os.path.join(EXPORTS_DIR, "feed.xml"), "w", encoding="utf-8") as f:
                    f.write(feed_xml)
                with open(os.path.join(EXPORTS_DIR, os.path.basename(unique_rel_path)), "w", encoding="utf-8") as f:
                    f.write(feed_xml)
                with open(os.path.join(EXPORTS_DIR, "feed.json"), "w", encoding="utf-8") as f:
                    f.write(feed_json)
                with open(os.path.join(EXPORTS_DIR, "feed.html"), "w", encoding="utf-8") as f:
                    f.write(feed_html)
                st.session_state["exports_saved"] = True
            except Exception as save_err:
                logger.warning("Could not auto-save export files to disk: %s", save_err)

            valid, feed_err = validate_feed(feed_xml)
            st.session_state["feed_xml"] = feed_xml
            st.session_state["feed_json"] = feed_json
            st.session_state["feed_html"] = feed_html
            st.session_state["feed_valid"] = valid
            st.session_state["feed_error"] = feed_err

            # ── Automated GitHub Pages Publishing (Reads credentials from .env) ─
            token_to_use = _get_secret("GITHUB_TOKEN", "")
            repo_to_use = _get_secret("GITHUB_REPO", "tanvish619/rss_feedd")
            branch_to_use = _get_secret("GITHUB_BRANCH", "main")

            if token_to_use and repo_to_use:
                hud_status.markdown(f"🚀 `Publishing {unique_rel_path} to GitHub Pages ({repo_to_use})…`")
                published, pages_url, gh_err = publish_to_github(
                    xml_content=feed_xml,
                    repo_name=repo_to_use,
                    file_path=unique_rel_path,
                    token=token_to_use,
                    branch=branch_to_use,
                )
                st.session_state["github_published"] = published
                st.session_state["github_pages_url"] = pages_url
                st.session_state["github_error"] = gh_err
            else:
                st.session_state["github_published"] = False
                st.session_state["github_pages_url"] = None
                st.session_state["github_error"] = (
                    "GITHUB_TOKEN is missing in .env file. "
                    "Feed generated locally. Add GITHUB_TOKEN to .env to enable automatic live hosting."
                )

        except Exception as exc:
            st.session_state["feed_error"] = str(exc)
            logger.exception("Feed generation failed")
    else:
        st.session_state["feed_valid"] = False

    st.session_state["articles"] = final_articles
    st.session_state["stats"] = last_stats
    st.session_state["log_messages"] = log_messages
    st.session_state["crawl_done"] = True
    st.rerun()


# ── Results Presentation ───────────────────────────────────────────────────────
if st.session_state.get("crawl_done"):
    articles: list[Article] = st.session_state.get("articles", [])
    stats: Optional[CrawlStats] = st.session_state.get("stats")
    feed_xml: Optional[str] = st.session_state.get("feed_xml")
    feed_json: Optional[str] = st.session_state.get("feed_json")
    feed_html: Optional[str] = st.session_state.get("feed_html")
    feed_valid: bool = st.session_state.get("feed_valid", False)
    feed_error: Optional[str] = st.session_state.get("feed_error")
    crawl_error: Optional[str] = st.session_state.get("crawl_error")
    log_messages: list[str] = st.session_state.get("log_messages", [])
    feed_file_name: str = st.session_state.get("feed_file_name", "feed.xml")

    gh_published: bool = st.session_state.get("github_published", False)
    gh_pages_url: Optional[str] = st.session_state.get("github_pages_url")
    gh_error: Optional[str] = st.session_state.get("github_error")

    if crawl_error:
        st.error(f"Crawl error: {crawl_error}")

    if not articles:
        st.warning("No articles were found on this listing URL. Verify the URL renders HTML articles.")
        st.stop()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Live GitHub Pages Success Banner ──────────────────────────────────────
    if gh_published and gh_pages_url:
        st.markdown(
            f"""
<div class="github-live-card">
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
        <div>
            <span class="tag-pill" style="background:rgba(52,211,153,0.2); color:#34d399; border:1px solid rgba(52,211,153,0.4); margin-bottom:0.4rem;">
                🚀 LIVE PERMANENT FEED ON GITHUB PAGES
            </span>
            <h3 style="font-size:1.45rem; font-weight:800; color:#ffffff; margin:0.3rem 0 0.2rem 0;">
                🎉 RSS Feed Published Successfully!
            </h3>
            <p style="color:#cbd5e1; font-size:0.92rem; margin:0;">
                Unique public URL generated and hosted. Copy or open this link in Feedly, NetNewsWire, Apple News, or any RSS app:
            </p>
        </div>
    </div>
    <div class="github-live-url">
        <span>🔗 <a href="{gh_pages_url}" target="_blank" rel="noopener" style="color:#34d399; text-decoration:none; font-weight:600;">{gh_pages_url}</a></span>
        <a href="{gh_pages_url}" target="_blank" rel="noopener" style="background:#10b981; color:#ffffff; padding:6px 16px; border-radius:6px; text-decoration:none; font-size:0.88rem; font-weight:600; white-space:nowrap;">Open Feed ↗</a>
    </div>
</div>
""",
            unsafe_allow_html=True,
        )
    elif gh_error:
        st.info(f"ℹ️ **GitHub Hosting Note**: {gh_error}")

    # ── 3-Format Download Center ──────────────────────────────────────────────
    st.markdown(
        f"""
<div style="display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:1rem; flex-wrap:wrap; gap:0.5rem;">
    <div>
        <h3 style="font-size:1.35rem; font-weight:700; color:#ffffff; margin:0;">
            📥 Export & Download Feed Files
        </h3>
        <p style="color:#94a3b8; font-size:0.88rem; margin-top:0.2rem; margin-bottom:0;">
            Direct instant downloads · Also saved locally to: <code style="color:#818cf8; background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:4px;">{EXPORTS_DIR}</code>
        </p>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    col_json, col_html, col_xml = st.columns(3)

    # 1. JSON Feed Download Card
    with col_json:
        st.markdown(
            f"""
<div class="download-card">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
        <span style="font-weight:700; color:#38bdf8; font-size:1.05rem;">📄 JSON Feed</span>
        <span class="tag-pill" style="background:rgba(56,189,248,0.15); color:#38bdf8; border:1px solid rgba(56,189,248,0.3);">feed.json</span>
    </div>
    <p style="color:#94a3b8; font-size:0.84rem; margin-bottom:1rem; line-height:1.4;">
        Structured JSON dataset (JSON Feed v1.1). Open in any code/text editor or JSON viewer.
    </p>
</div>
""",
            unsafe_allow_html=True,
        )
        if feed_json:
            st.download_button(
                label="⬇️ Download feed.json",
                data=feed_json,
                file_name="feed.json",
                mime="application/json",
                use_container_width=True,
                type="primary",
                key="dl_json_btn",
            )
            json_uri = _make_data_uri(feed_json, "application/json")
            st.markdown(
                f'<a href="{json_uri}" download="feed.json" style="color:#38bdf8; font-size:0.8rem; text-decoration:none; display:block; text-align:center; margin-top:4px;">Direct Browser Link (feed.json) ↗</a>',
                unsafe_allow_html=True,
            )

    # 2. HTML Reader Download Card
    with col_html:
        st.markdown(
            f"""
<div class="download-card">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
        <span style="font-weight:700; color:#34d399; font-size:1.05rem;">🌐 HTML Reader</span>
        <span class="tag-pill" style="background:rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3);">feed.html</span>
    </div>
    <p style="color:#94a3b8; font-size:0.84rem; margin-bottom:1rem; line-height:1.4;">
        Standalone web page. <b>Double-click to open in Chrome, Edge, Safari</b> or any browser!
    </p>
</div>
""",
            unsafe_allow_html=True,
        )
        if feed_html:
            st.download_button(
                label="⬇️ Download feed.html",
                data=feed_html,
                file_name="feed.html",
                mime="text/html",
                use_container_width=True,
                type="primary",
                key="dl_html_btn",
            )
            html_uri = _make_data_uri(feed_html, "text/html")
            st.markdown(
                f'<a href="{html_uri}" download="feed.html" style="color:#34d399; font-size:0.8rem; text-decoration:none; display:block; text-align:center; margin-top:4px;">Direct Browser Link (feed.html) ↗</a>',
                unsafe_allow_html=True,
            )

    # 3. RSS 2.0 XML Download Card
    with col_xml:
        st.markdown(
            f"""
<div class="download-card">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
        <span style="font-weight:700; color:#a5b4fc; font-size:1.05rem;">📡 RSS 2.0 XML</span>
        <span class="tag-pill" style="background:rgba(165,180,252,0.15); color:#a5b4fc; border:1px solid rgba(165,180,252,0.3);">{feed_file_name}</span>
    </div>
    <p style="color:#94a3b8; font-size:0.84rem; margin-bottom:1rem; line-height:1.4;">
        RFC-compliant RSS 2.0 XML with CDATA & content:encoded. Works in any RSS reader.
    </p>
</div>
""",
            unsafe_allow_html=True,
        )
        if feed_xml:
            st.download_button(
                label=f"⬇️ Download {feed_file_name}",
                data=feed_xml,
                file_name=feed_file_name,
                mime="application/rss+xml",
                use_container_width=True,
                type="primary",
                key="dl_xml_btn",
            )
            xml_uri = _make_data_uri(feed_xml, "application/rss+xml")
            st.markdown(
                f'<a href="{xml_uri}" download="{feed_file_name}" style="color:#a5b4fc; font-size:0.8rem; text-decoration:none; display:block; text-align:center; margin-top:4px;">Direct Browser Link ({feed_file_name}) ↗</a>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Summary Metrics Bar ───────────────────────────────────────────────────
    with_dates = sum(1 for a in articles if a.date)
    with_cats = sum(1 for a in articles if a.category)
    dated_pct = int((with_dates / len(articles)) * 100) if articles else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Articles Extracted", len(articles))
    m2.metric("With Dates", f"{with_dates} ({dated_pct}%)")
    m3.metric("With Categories", with_cats)
    m4.metric("Pages Visited", stats.pages_crawled if stats else 1)

    st.markdown("<br>", unsafe_allow_html=True)

    sorted_articles = sorted(
        [a for a in articles if a.date], key=lambda a: a.date, reverse=True
    ) + [a for a in articles if not a.date]

    # ── Multi-Tab Explorer ────────────────────────────────────────────────────
    tab_cards, tab_table, tab_json_view, tab_html_view, tab_xml_view, tab_logs = st.tabs(
        [
            "🎴 Visual Cards",
            "📋 Data Table",
            "📄 JSON Feed",
            "🌐 HTML Preview",
            "📡 RSS XML",
            "🔍 Crawl Diagnostics",
        ]
    )

    with tab_cards:
        search_filter = st.text_input(
            "Filter items in view",
            placeholder="Type keyword to filter titles, categories, or excerpts…",
            key="card_filter_input",
        )

        display_list = sorted_articles
        if search_filter.strip():
            q = search_filter.strip().lower()
            display_list = [
                a
                for a in sorted_articles
                if q in a.title.lower()
                or (a.category and q in a.category.lower())
                or (a.description and q in a.description.lower())
            ]

        for idx, art in enumerate(display_list):
            date_badge = (
                f'<span class="tag-pill tag-date">🗓️ {art.date.strftime("%b %d, %Y")}</span>'
                if art.date
                else '<span class="tag-pill" style="background:rgba(255,255,255,0.05); color:#64748b;">🗓️ Undated</span>'
            )
            cat_badge = (
                f'<span class="tag-pill tag-category">🏷️ {art.category}</span>'
                if art.category
                else ""
            )
            desc_html = (
                f'<p style="color:#94a3b8; font-size:0.9rem; margin:0.5rem 0 0.6rem 0; line-height:1.5;">{art.description[:220]}…</p>'
                if art.description
                else ""
            )

            st.markdown(
                f"""
<div class="article-item">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
        <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap;">
            {date_badge}
            {cat_badge}
        </div>
        <span style="color:#475569; font-size:0.78rem; font-family:'JetBrains Mono',monospace;">#{idx + 1}</span>
    </div>
    <div style="font-size:1.12rem; font-weight:700; color:#f8fafc; margin-bottom:0.25rem; line-height:1.35;">
        <a href="{art.url}" target="_blank" style="color:#f8fafc; text-decoration:none;">
            {art.title}
        </a>
    </div>
    {desc_html}
    <div style="margin-top:0.4rem;">
        <a href="{art.url}" target="_blank" style="color:#818cf8; text-decoration:none; font-size:0.84rem; font-weight:600;">
            Read Story ↗
        </a>
    </div>
</div>
""",
                unsafe_allow_html=True,
            )

    with tab_table:
        table_rows = [
            {
                "Date": a.date.strftime("%Y-%m-%d") if a.date else "—",
                "Category": a.category or "—",
                "Title": a.title,
                "URL": a.url,
            }
            for a in sorted_articles
        ]
        st.dataframe(
            table_rows,
            column_config={
                "URL": st.column_config.LinkColumn("Article URL"),
                "Title": st.column_config.TextColumn("Headline", width="large"),
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Category": st.column_config.TextColumn("Category", width="medium"),
            },
            use_container_width=True,
            hide_index=True,
        )

    with tab_json_view:
        if feed_json:
            st.markdown("#### 📄 Structured JSON Feed (JSON Feed v1.1)")
            st.code(feed_json, language="json")

    with tab_html_view:
        if feed_html:
            st.markdown("#### 🌐 HTML Reader Source (standalone offline reader)")
            st.code(feed_html, language="html")

    with tab_xml_view:
        if feed_xml:
            st.markdown("#### 📡 RSS 2.0 XML (with CDATA & content:encoded)")
            st.code(feed_xml, language="xml")

    with tab_logs:
        if stats:
            st.markdown(f"- **Pagination Detected:** `{stats.pagination_type or 'none'}`")
            st.markdown(f"- **Robots.txt:** `{'Allowed ✅' if stats.robots_allowed else 'Disallowed 🚫'}`")
            st.markdown(f"- **Pages Crawled:** {stats.pages_crawled}")
            st.markdown(f"- **Total Articles Found:** {len(articles)}")
        if log_messages:
            st.code("\n".join(log_messages), language=None)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:#475569; font-size:0.8rem; padding:1.5rem 0;'>"
    "Feed Engine · Crawls server-rendered pages · Complies with RFC RSS 2.0 & JSON Feed v1.1 · Automated GitHub Hosting"
    "</div>",
    unsafe_allow_html=True,
)
