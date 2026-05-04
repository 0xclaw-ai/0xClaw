"""Sitemap-driven doc URL discovery for the research phase.

Replaces the previous in-skill Python heredoc that asked the LLM to run
`exec("python3 -c ...")` to fetch a sitemap and keyword-filter its URLs.
That step was unreliable because LLMs frequently skip multi-step procedural
shell calls when an "obvious" tool (firecrawl_scrape) is available.

Moving the sitemap fetch + keyword filter into Python code makes it
deterministic and surfaces the filtered URLs directly into the spawn task
so the agent only needs to do what it's actually good at: reading scraped
pages and synthesising context.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

# Generic doc-page keywords. Most SDK docs use at least one of these in
# their URL paths, so this catches `/api-reference/...`, `/cli/...`,
# `/guides/...`, `/introduction`, etc. Tune in this file, not at call sites.
DEFAULT_KEYWORDS: tuple[str, ...] = (
    "introduction",
    "quickstart",
    "getting-started",
    "api",
    "sdk",
    "guides",
    "cli",
    "reference",
    "how-to",
    "tutorial",
)

DEFAULT_MAX_URLS = 15
DEFAULT_TIMEOUT_S = 10
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _normalize_root(doc_root: str) -> str:
    """Strip query/fragment, drop trailing slash. Preserves scheme+host+path."""
    parsed = urlparse(doc_root)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid doc root URL: {doc_root!r}")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _sitemap_candidates(doc_root: str) -> list[str]:
    """Plausible sitemap.xml locations for a given doc root."""
    parsed = urlparse(doc_root)
    host_root = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        f"{host_root}/sitemap.xml",
        f"{host_root}/sitemap_index.xml",
    ]
    if parsed.path.strip("/"):
        candidates.insert(0, f"{_normalize_root(doc_root)}/sitemap.xml")
    return list(dict.fromkeys(candidates))  # dedup, preserve order


def _fetch(url: str, timeout_s: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "0xclaw-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - public sitemap fetch
        return resp.read()


def _parse_sitemap_urls(xml_bytes: bytes) -> list[str]:
    """Return all <loc> URLs from a sitemap or sitemap-index document."""
    try:
        tree = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    locs = [el.text for el in tree.findall(".//sm:loc", SITEMAP_NS) if el.text]
    return [u.strip() for u in locs if u and u.strip()]


def _filter_by_keywords(urls: list[str], keywords: tuple[str, ...]) -> list[str]:
    lowered = [(u, u.lower()) for u in urls]
    out = [u for u, low in lowered if any(k in low for k in keywords)]
    seen: set[str] = set()
    deduped = []
    for u in out:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def _harvest_links_from_html(html: str, host_root: str) -> list[str]:
    """Cheap HTML link extraction for the no-sitemap fallback path.

    Returns absolute URLs whose host matches ``host_root``. Intentionally
    simple — we just want path-level coverage, not a full HTML parse.
    """
    href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    parsed_root = urlparse(host_root)
    base = f"{parsed_root.scheme}://{parsed_root.netloc}"
    out: list[str] = []
    for href in href_pattern.findall(html):
        if href.startswith("//"):
            url = f"{parsed_root.scheme}:{href}"
        elif href.startswith("/"):
            url = f"{base}{href}"
        elif href.startswith("http://") or href.startswith("https://"):
            url = href
        else:
            continue
        if urlparse(url).netloc == parsed_root.netloc:
            out.append(url.split("#", 1)[0])
    seen: set[str] = set()
    deduped = []
    for u in out:
        if u and u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def fetch_filtered_doc_urls(
    doc_root: str,
    *,
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS,
    max_n: int = DEFAULT_MAX_URLS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> list[str]:
    """Return up to ``max_n`` doc URLs under ``doc_root`` matching keywords.

    Tries sitemap.xml first (canonical, fast, usually unblocked by anti-bot
    walls). Falls back to fetching the doc root HTML and harvesting links
    when no sitemap is reachable.

    Returns an empty list rather than raising on failure — the caller
    should treat this as "tell the agent to scrape the doc root only" and
    record the gap in unresolved.open_questions if needed.
    """
    try:
        normalized = _normalize_root(doc_root)
    except ValueError:
        return []

    for sitemap_url in _sitemap_candidates(normalized):
        try:
            payload = _fetch(sitemap_url, timeout_s)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        urls = _parse_sitemap_urls(payload)
        if urls:
            filtered = _filter_by_keywords(urls, keywords)
            if filtered:
                return filtered[:max_n]

    # Sitemap unavailable — fall back to doc root HTML link harvesting.
    try:
        payload = _fetch(normalized + "/", timeout_s)
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    try:
        html = payload.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return []
    harvested = _harvest_links_from_html(html, normalized)
    filtered = _filter_by_keywords(harvested, keywords)
    return filtered[:max_n]


def expand_doc_urls(doc_roots: list[str], *, max_per_root: int = DEFAULT_MAX_URLS) -> dict[str, list[str]]:
    """Convenience wrapper: map each doc root to its filtered URL list."""
    return {root: fetch_filtered_doc_urls(root, max_n=max_per_root) for root in doc_roots}
