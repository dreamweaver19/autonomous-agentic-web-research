"""
discovery.py – Source discovery via configurable search providers and
link extraction from already-fetched HTML.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config import settings
from schemas import CandidateURL, ResearchPlan

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# URL helpers
# ──────────────────────────────────────────────

def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    # Drop fragments and trailing slashes from path
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, "")
    )


def is_valid_http_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


# ──────────────────────────────────────────────
# Search providers
# ──────────────────────────────────────────────

async def _search_duckduckgo_html(query: str, max_results: int = 10) -> list[str]:
    """Scrape DuckDuckGo HTML results page (no API key required)."""
    urls: list[str] = []
    try:
        encoded = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(search_url, headers=headers)
            if resp.status_code != 200:
                return urls
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a.result__url, a.result__a"):
                href = a.get("href", "")
                # DuckDuckGo HTML uses redirect links – extract real URL
                if "uddg=" in href:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    real = qs.get("uddg", [""])[0]
                    if real:
                        href = urllib.parse.unquote(real)
                if href and is_valid_http_url(href):
                    urls.append(normalize_url(href))
                if len(urls) >= max_results:
                    break
    except Exception as exc:
        log.warning("DuckDuckGo search failed: %s", exc)
    return urls


async def _search_serper(query: str, max_results: int = 10) -> list[str]:
    """Use Serper.dev API (requires SERPER_API_KEY)."""
    if not settings.serper_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["link"] for item in data.get("organic", [])[:max_results]]
    except Exception as exc:
        log.warning("Serper search failed: %s", exc)
        return []


async def search_urls(query: str, max_results: int = 10) -> list[str]:
    """
    Dispatch to the configured search provider.
    Returns a list of URLs (may be empty if provider unavailable or unconfigured).
    """
    provider = settings.search_provider.lower()
    if provider == "serper":
        results = await _search_serper(query, max_results)
    elif provider == "duckduckgo_html":
        results = await _search_duckduckgo_html(query, max_results)
    elif provider == "none":
        log.info("Search provider set to 'none'. No web search performed.")
        results = []
    else:
        log.warning("Unknown search provider '%s', falling back to none.", provider)
        results = []
    return results


# ──────────────────────────────────────────────
# Link discovery from fetched HTML
# ──────────────────────────────────────────────

def extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Extract all <a href> links from HTML, resolved relative to base_url."""
    links: list[str] = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        base_parsed = urllib.parse.urlparse(base_url)
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # Resolve relative URLs
            resolved = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlparse(resolved)
            # Stay on http/https and remove fragments
            if parsed.scheme in ("http", "https") and parsed.netloc:
                clean = urllib.parse.urlunparse(
                    (parsed.scheme, parsed.netloc.lower(), parsed.path, "", parsed.query, "")
                )
                links.append(clean)
    except Exception as exc:
        log.debug("Link extraction error: %s", exc)
    return links


# ──────────────────────────────────────────────
# Candidate URL builder
# ──────────────────────────────────────────────

async def discover_candidate_urls(plan: ResearchPlan) -> list[CandidateURL]:
    """
    Run all search queries and return a prioritised list of CandidateURLs.
    URLs from the first query get higher priority.
    """
    seen: set[str] = set()
    candidates: list[CandidateURL] = []
    total_queries = len(plan.search_queries)

    for idx, query in enumerate(plan.search_queries):
        log.info("Search query [%d/%d]: %s", idx + 1, total_queries, query)
        urls = await search_urls(query, max_results=12)
        # Higher priority for results from earlier / more specific queries
        base_priority = 1.0 - (idx / max(total_queries, 1)) * 0.3
        for url in urls:
            norm = normalize_url(url)
            if norm not in seen:
                seen.add(norm)
                candidates.append(
                    CandidateURL(
                        url=norm,
                        priority=round(base_priority, 3),
                        depth=0,
                        source="discovery",
                        reason=f"Search result for: {query[:60]}",
                    )
                )

    log.info("Discovered %d unique candidate URLs", len(candidates))
    return candidates


def score_link_relevance(url: str, anchor_text: str, plan: ResearchPlan) -> float:
    """
    Heuristic relevance score for a link discovered during crawling.
    Used to decide whether to add it to the crawl queue.
    """
    score = 0.3  # base
    url_lower = url.lower()
    text_lower = (anchor_text or "").lower()
    topic_words = plan.topic.lower().split()

    # Boost if topic words appear in URL or anchor
    for word in topic_words:
        if len(word) > 3:
            if word in url_lower:
                score += 0.15
            if word in text_lower:
                score += 0.10

    # Penalty for likely non-content pages
    skip_patterns = [
        r"/login", r"/signin", r"/register", r"/cart", r"/checkout",
        r"/privacy", r"/terms", r"/cookie", r"/about-us", r"/contact",
        r"\.pdf$", r"\.zip$", r"\.exe$", r"\.dmg$",
        r"/tag/", r"/category/", r"/author/",
    ]
    for pattern in skip_patterns:
        if re.search(pattern, url_lower):
            score -= 0.2

    return max(0.0, min(1.0, score))
