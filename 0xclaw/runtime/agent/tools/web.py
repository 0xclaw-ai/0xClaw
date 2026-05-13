"""Web tools: web_search and web_fetch."""

import html
import ipaddress
import json
import os
import re
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx
from loguru import logger
from runtime.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks

# Hostnames that must never be fetched directly (cloud metadata, obvious local names).
_BLOCKED_FETCH_HOSTNAMES: frozenset[str] = frozenset({
    "metadata.google.internal",
    "metadata",
    "metadata.azure.com",
    "instance-data.ec2.internal",
})


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _blocked_fetch_host(hostname: str | None) -> str | None:
    """Return a human-readable block reason, or None if the host is allowed.

    Blocks literal loopback/private/link-local/reserved/multicast IPs and a few
    well-known metadata hostnames. Public DNS names are not resolved here, so
    this is a best-effort SSRF guard for direct-to-IP and obvious local URLs.
    """
    if not hostname:
        return "Missing hostname"
    h = hostname.lower().rstrip(".")
    if h in _BLOCKED_FETCH_HOSTNAMES:
        return f"Blocked hostname '{h}'"
    if "%" in h:
        h = h.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    if ip.version == 4 and ip == ipaddress.IPv4Address("0.0.0.0"):
        return "Blocked address 0.0.0.0"
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        return f"Blocked non-public address {ip}"
    return None


def _canonical_redirect_url(url: str) -> str:
    """Stable key for redirect-loop detection (scheme/host lowercased, no fragment)."""
    base, _frag = urldefrag(url.strip())
    p = urlparse(base)
    path = p.path or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with a fetchable public host (best-effort)."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        host_reason = _blocked_fetch_host(p.hostname)
        if host_reason:
            return False, host_reason
        return True, ""
    except Exception as e:
        return False, str(e)


def _fetch_error_json(error: str, url: str) -> str:
    """JSON error body for web_fetch (stable keys: error, url)."""
    return json.dumps({"error": error, "url": url}, ensure_ascii=False)


async def _fetch_with_redirect_guard(
    client: httpx.AsyncClient,
    start_url: str,
    original_url: str,
    max_attempts: int,
) -> httpx.Response | str:
    """Follow redirects manually with SSRF checks and a hard cap.

    Returns the final ``httpx.Response`` on success, or a JSON error string
    (same shape/messages as ``WebFetchTool.execute``) on validation / redirect
    failures.
    """
    current = start_url
    visited: set[str] = set()
    r: httpx.Response | None = None
    for _ in range(max_attempts):
        sig = _canonical_redirect_url(current)
        if sig in visited:
            return _fetch_error_json("Redirect loop (revisited a previous URL)", current)
        visited.add(sig)

        is_valid, error_msg = _validate_url(current)
        if not is_valid:
            return _fetch_error_json(f"URL validation failed: {error_msg}", current)
        r = await client.get(current, headers={"User-Agent": USER_AGENT})
        if r.is_redirect:
            loc = (r.headers.get("location") or "").strip()
            if not loc:
                return _fetch_error_json("Redirect response missing Location header", current)
            next_url = urljoin(str(r.request.url), loc)
            if _canonical_redirect_url(next_url) == sig:
                return _fetch_error_json(
                    "Redirect loop (Location resolves to same canonical URL)",
                    current,
                )
            current = next_url
            continue
        break
    else:
        return _fetch_error_json(f"Too many redirects (>{MAX_REDIRECTS})", original_url)

    if r is None:
        return _fetch_error_json("No response received from server", original_url)
    return r


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5, proxy: str | None = None):
        self._init_api_key = api_key
        self.max_results = max_results
        self.proxy = proxy

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return (
                "Error: Brave Search API key not configured. Set it under "
                "tools.web.search.apiKey in your agents config "
                "(hackathon default: <repo>/0xclaw/config/config.json), "
                "or in ~/.0xclaw/config.json for runtime-only / gateway installs, "
                "or export BRAVE_API_KEY, then restart the gateway."
            )

        try:
            n = min(max(count or self.max_results, 1), 10)
            logger.debug("WebSearch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])[:n]
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except httpx.ProxyError as e:
            logger.error("WebSearch proxy error: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }

    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        self.max_chars = max_chars
        self.proxy = proxy

    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        max_chars = maxChars or self.max_chars

        try:
            logger.debug("WebFetch: {}", "proxy enabled" if self.proxy else "direct connection")
            max_attempts = MAX_REDIRECTS + 1  # initial GET + up to MAX_REDIRECTS redirects (httpx-compatible cap)

            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                fetched = await _fetch_with_redirect_guard(
                    client,
                    url.strip(),
                    url,
                    max_attempts,
                )
                if isinstance(fetched, str):
                    return fetched
                r = fetched
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps(
                {
                    "url": url,
                    "finalUrl": str(r.url),
                    "status": r.status_code,
                    "extractor": extractor,
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                },
                ensure_ascii=False,
            )
        except httpx.ProxyError as e:
            logger.error("WebFetch proxy error for {}: {}", url, e)
            return _fetch_error_json(f"Proxy error: {e}", url)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return _fetch_error_json(str(e), url)

    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
