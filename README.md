# ⚡ News RSS & Feed Generator

A local Python Streamlit engine that crawls paginated news and blog listing pages, follows article candidate links to perform deep detail extraction (full body HTML, accurate publication dates, lead images, authors, categories), and exports rich feeds in multiple formats (**RSS 2.0 XML with CDATA**, **JSON Feed v1.1**, and **Standalone HTML Reader**).

---

## 🚀 Key Features

- **Deep Detail Extraction**: Discovers candidate links from listing pages, follows each link to extract full article body content, OpenGraph / Schema.org metadata, lead images, and author bylines.
- **CDATA Encapsulation**: String-based XML nodes (`<title>`, `<category>`, `<description>`, `<content:encoded>`) are wrapped in `<![CDATA[...]]>` tags to protect special characters (`&`, `<`, `>`).
- **Rich HTML Descriptions**: Clean visual previews with lead image thumbnails and formatted paragraphs.
- **Full Content Encoding (`content:encoded`)**: Complete HTML article body with figures, metadata bar, and clean source links.
- **Strict RFC-822 `<pubDate>`**: Strict schema compliance with intelligent chronological fallbacks for undated articles.
- **Multi-Format Export**:
  - `feed.xml`: RFC-compliant RSS 2.0 with `xmlns:content` namespace.
  - `feed.json`: JSON Feed v1.1 structured dataset.
  - `feed.html`: Self-contained offline visual reader with modern dark mode UI.
- **URL Normalization**: Strips tracking query parameters (`utm_*`, `fbclid`, etc.) for clean `<link>` and `<guid>` identifiers.
- **Heuristic & Robust**: Multi-layer pagination detection and heuristic content extraction with no hardcoded site-specific selectors.

---

## 📂 Project Architecture

```
news-rss-builder/
├── app.py                  # Streamlit UI with live progress HUD & multi-format export center
├── requirements.txt        # Python package dependencies
├── README.md               # Project documentation
├── .gitignore              # Git ignore rules for caches & exports
│
├── scraper/
│   ├── models.py           # Article & CrawlStats dataclasses
│   ├── urls.py             # URL normalization, validation, tracking-param removal
│   ├── dates.py            # Multi-layer date parsing & UTC normalization
│   ├── extractor.py        # Heuristic listing extraction + scoring + keyword filter
│   ├── article_scraper.py  # Deep article detail extractor (body HTML, JSON-LD, OpenGraph)
│   ├── pagination.py       # 5-layer pagination detection (rel=next, numbered, patterns)
│   └── crawler.py          # Generator-based crawl and enrichment loop
│
├── rss/
│   ├── builder.py          # RSS 2.0 XML (CDATA & content:encoded), JSON Feed & HTML builder
│   └── validator.py        # lxml-based XML validation with CDATA-safe entity checks
│
├── utils/
│   ├── http.py             # Reusable session with browser headers, retries & exponential backoff
│   └── robots.py           # Strict robots.txt compliance
│
├── exports/                # Local export folder (git-ignored)
└── tests/                  # Pytest test suite covering all modules
```

---

## 📦 Setup & Installation

### Prerequisites
- Python 3.11+
- pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 💻 Running the Application

```bash
streamlit run app.py
```

The application will open in your browser at `http://localhost:8501`.

### Usage:
1. Enter a listing URL (e.g. `https://mathco.com/news/` or `https://jamesclear.com/articles`).
2. (Optional) Enter keyword filters to match specific topics.
3. Click **⚡ Extract Feed**.
4. View real-time crawling and deep extraction progress.
5. Download your feeds in **XML**, **JSON**, or **HTML** format!

---

## 🧪 Running Tests

```bash
pytest
```
