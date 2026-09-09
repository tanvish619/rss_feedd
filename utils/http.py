"""
utils/http.py

Reusable HTTP session with realistic User-Agent, retry logic with
exponential back-off, Retry-After support, and jittered rate limiting.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional, Tuple

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsRSSBuilder/1.0; "
    "+https://github.com/newsrssbuilder)"
)

# Status codes that should NEVER be retried
_NO_RETRY_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 405, 410})

# Status codes eligible for retry
_RETRY_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Maximum number of retries per request
_MAX_RETRIES = 3

# Base back-off in seconds (doubles each attempt)
_BASE_BACKOFF = 1.0


def build_session() -> Session:
    """
    Build and return a reusable requests.Session with:
    - Realistic browser-like headers
    - TCP connection pooling
    - No automatic urllib3 retries (we handle retries manually for finer control)
    """
    session = Session()
    session.headers.update(
        {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
    )
    # Mount adapter without urllib3-level retries
    adapter = HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch(
    url: str,
    session: Session,
    timeout: float = 15.0,
    delay: float = 0.5,
) -> Tuple[Optional[Response], Optional[str]]:
    """
    Fetch *url* with the given *session*.

    Returns:
        (response, None)   on success
        (None, error_msg)  on unrecoverable failure

    Behaviour:
    - Applies jittered *delay* before every request
    - Retries up to _MAX_RETRIES times for _RETRY_CODES
    - Respects Retry-After header on 429
    - Does NOT retry _NO_RETRY_CODES
    - Catches all network exceptions without raising
    """
    _jittered_sleep(delay)

    attempt = 0
    last_error: str = ""

    while attempt <= _MAX_RETRIES:
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
        except requests.exceptions.TooManyRedirects:
            return None, f"Too many redirects: {url}"
        except requests.exceptions.ConnectionError as exc:
            last_error = f"Connection error: {exc}"
            logger.warning("Connection error on %s (attempt %d): %s", url, attempt + 1, exc)
        except requests.exceptions.Timeout:
            last_error = f"Timeout after {timeout}s: {url}"
            logger.warning("Timeout on %s (attempt %d)", url, attempt + 1)
        except requests.exceptions.RequestException as exc:
            return None, f"Request error: {exc}"
        else:
            # Got a response
            if response.status_code in _NO_RETRY_CODES:
                return None, f"HTTP {response.status_code}: {url}"

            if response.status_code in _RETRY_CODES:
                wait = _retry_wait(response, attempt)
                logger.warning(
                    "HTTP %d on %s — waiting %.1fs before retry %d",
                    response.status_code,
                    url,
                    wait,
                    attempt + 1,
                )
                time.sleep(wait)
                attempt += 1
                continue

            # Success (2xx, 3xx handled by allow_redirects)
            return response, None

        # Network-level error — back-off and retry
        wait = _backoff(attempt)
        time.sleep(wait)
        attempt += 1

    return None, last_error or f"Failed after {_MAX_RETRIES} retries: {url}"


def _jittered_sleep(base_delay: float) -> None:
    """Sleep for base_delay ± 20% jitter."""
    if base_delay <= 0:
        return
    jitter = base_delay * 0.2
    time.sleep(base_delay + random.uniform(-jitter, jitter))


def _backoff(attempt: int) -> float:
    """Exponential back-off with jitter: 1s, 2s, 4s …"""
    wait = _BASE_BACKOFF * (2 ** attempt)
    wait += random.uniform(0, 0.5)
    return min(wait, 30.0)  # cap at 30 seconds


def _retry_wait(response: Response, attempt: int) -> float:
    """Determine how long to wait before retrying, respecting Retry-After."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return _backoff(attempt)
