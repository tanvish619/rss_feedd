"""
utils/robots.py

Strict robots.txt enforcement.

Fetches robots.txt at the root of the target domain, parses it using
urllib.robotparser, and checks whether the NewsRSSBuilder user-agent
is allowed to access the requested URL.

Returns (allowed, crawl_delay) to the caller so the crawl loop
can respect site-specified delays.
"""

from __future__ import annotations

import logging
import urllib.robotparser
from typing import Optional, Tuple

import requests
from requests import Session

logger = logging.getLogger(__name__)

_USER_AGENT = "NewsRSSBuilder"
_ROBOTS_TIMEOUT = 10.0


def check_robots(
    url: str,
    session: Session,
) -> Tuple[bool, Optional[float]]:
    """
    Fetch robots.txt for the domain of *url* and check access.

    Returns:
        (True,  crawl_delay)   — access is allowed
        (False, None)          — access is disallowed
        (True,  None)          — robots.txt not found (treat as permissive)

    The caller MUST abort the crawl if this returns (False, ...).
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    except Exception as exc:
        logger.warning("Could not build robots URL for %s: %s", url, exc)
        return True, None

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)

    try:
        response = session.get(robots_url, timeout=_ROBOTS_TIMEOUT, allow_redirects=True)

        if response.status_code == 404:
            # No robots.txt — all access permitted
            logger.debug("No robots.txt at %s — proceeding.", robots_url)
            return True, None

        if response.status_code != 200:
            # Unexpected status — be conservative and allow
            logger.warning(
                "robots.txt returned HTTP %d at %s — treating as permissive.",
                response.status_code,
                robots_url,
            )
            return True, None

        rp.parse(response.text.splitlines())

    except requests.exceptions.RequestException as exc:
        # Cannot reach robots.txt — be conservative and allow
        logger.warning("Could not fetch robots.txt at %s: %s — treating as permissive.", robots_url, exc)
        return True, None

    allowed: bool = rp.can_fetch(_USER_AGENT, url) or rp.can_fetch("*", url)

    # If our specific UA is explicitly disallowed, honour it
    if not rp.can_fetch(_USER_AGENT, url):
        # Check if the wildcard agent is also disallowed
        if not rp.can_fetch("*", url):
            allowed = False
        else:
            # Wildcard allows but our UA doesn't — honour the specific rule
            allowed = False

    crawl_delay: Optional[float] = None
    try:
        cd = rp.crawl_delay(_USER_AGENT) or rp.crawl_delay("*")
        if cd is not None:
            crawl_delay = float(cd)
    except Exception:
        pass

    if not allowed:
        logger.info("robots.txt disallows NewsRSSBuilder access to %s", url)

    return allowed, crawl_delay
