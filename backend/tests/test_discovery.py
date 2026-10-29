"""Tests for the discovery module (URL normalisation, link extraction, link scoring)."""
import pytest

from discovery import normalize_url, is_valid_http_url, extract_links_from_html, score_link_relevance
from schemas import ResearchPlan


def _make_plan(topic: str = "gaming laptop") -> ResearchPlan:
    return ResearchPlan(
        topic=topic,
        required_fields=["name", "price"],
        search_queries=[f"best {topic}"],
        max_pages=10,
    )


# ── URL normalisation ────────────────────────────────

def test_normalize_url_strips_fragment():
    assert normalize_url("https://example.com/page#section") == "https://example.com/page"


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("https://example.com/page/") == "https://example.com/page"


def test_normalize_url_lowercases_host():
    assert normalize_url("https://EXAMPLE.COM/Page") == "https://example.com/Page"


def test_normalize_url_preserves_query():
    assert normalize_url("https://example.com/search?q=laptop") == "https://example.com/search?q=laptop"


def test_normalize_url_root():
    assert normalize_url("https://example.com/") == "https://example.com/"


# ── URL validation ───────────────────────────────────

def test_is_valid_http_url_accepts_http():
    assert is_valid_http_url("http://example.com/page") is True


def test_is_valid_http_url_accepts_https():
    assert is_valid_http_url("https://example.com/page") is True


def test_is_valid_http_url_rejects_ftp():
    assert is_valid_http_url("ftp://files.example.com/file.txt") is False


def test_is_valid_http_url_rejects_javascript():
    assert is_valid_http_url("javascript:alert(1)") is False


def test_is_valid_http_url_rejects_empty():
    assert is_valid_http_url("") is False


# ── Link extraction ───────────────────────────────────

def test_extract_links_absolute():
    html = '<html><body><a href="https://other.com/page">Link</a></body></html>'
    links = extract_links_from_html(html, "https://example.com")
    assert "https://other.com/page" in links


def test_extract_links_relative():
    html = '<html><body><a href="/about-us">About</a></body></html>'
    links = extract_links_from_html(html, "https://example.com")
    assert "https://example.com/about-us" in links


def test_extract_links_strips_fragment():
    html = '<html><body><a href="https://example.com/page#section">Link</a></body></html>'
    links = extract_links_from_html(html, "https://example.com")
    clean = [l for l in links if "example.com/page" in l]
    assert len(clean) == 1
    assert "#" not in clean[0]


def test_extract_links_ignores_mailto():
    html = '<html><body><a href="mailto:test@example.com">Email</a></body></html>'
    links = extract_links_from_html(html, "https://example.com")
    assert len(links) == 0


def test_extract_links_ignores_javascript():
    html = '<html><body><a href="javascript:void(0)">Click</a></body></html>'
    links = extract_links_from_html(html, "https://example.com")
    assert len(links) == 0


# ── Link relevance scoring ───────────────────────────

def test_score_link_relevance_topic_in_url():
    plan = _make_plan("laptop")
    score = score_link_relevance("https://example.com/best-laptop-review", "best laptop", plan)
    assert score > 0.3


def test_score_link_relevance_penalty_for_login():
    plan = _make_plan("laptop")
    score = score_link_relevance("https://example.com/login", "", plan)
    assert score < 0.3


def test_score_link_relevance_penalty_for_pdf():
    plan = _make_plan("laptop")
    score = score_link_relevance("https://example.com/document.pdf", "", plan)
    assert score < 0.3


def test_score_link_relevance_base_score():
    plan = _make_plan("random topic")
    score = score_link_relevance("https://example.com/some-page", "", plan)
    assert 0.2 <= score <= 0.5


def test_score_link_relevance_clamped_to_range():
    plan = _make_plan("a")
    score = score_link_relevance("https://example.com/a-a-a-a-a-a-a-a", "a a a a a a a a", plan)
    assert 0.0 <= score <= 1.0
