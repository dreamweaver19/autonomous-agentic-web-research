"""Tests for the extractor module (HTML cleaning, date extraction, fallback extraction)."""
import pytest
from datetime import datetime

from extractor import clean_html, extract_date, _fallback_extract
from schemas import ExtractedRecord, ResearchPlan


def _make_plan(topic: str = "gaming laptop", fields: list[str] | None = None) -> ResearchPlan:
    return ResearchPlan(
        topic=topic,
        required_fields=fields or ["name", "price", "rating"],
        search_queries=[f"best {topic}"],
        max_pages=10,
    )


# ── HTML cleaning ────────────────────────────────

def test_clean_html_extracts_title():
    html = "<html><head><title>Best Laptops 2024</title></head><body><p>Content here</p></body></html>"
    title, text, meta = clean_html(html)
    assert title == "Best Laptops 2024"


def test_clean_html_uses_h1_when_no_title():
    html = "<html><body><h1>Fallback Title</h1><p>Some content text here for testing</p></body></html>"
    title, text, _ = clean_html(html)
    assert title == "Fallback Title"


def test_clean_html_removes_script_tags():
    html = """
    <html><head><title>Test</title></head>
    <body>
        <script>var x = 'secret';</script>
        <p>Visible content paragraph that is long enough to pass the filter</p>
    </body></html>
    """
    _, text, _ = clean_html(html)
    assert "secret" not in text
    assert "Visible content" in text


def test_clean_html_removes_style_tags():
    html = """
    <html><head><title>Test</title><style>body { color: red; }</style></head>
    <body><p>Visible content paragraph that is long enough to pass the filter</p></body></html>
    """
    _, text, _ = clean_html(html)
    assert "color" not in text
    assert "Visible content" in text


def test_clean_html_extracts_meta_tags():
    html = """
    <html><head>
        <title>Test</title>
        <meta name="description" content="A test page about laptops">
        <meta property="og:title" content="Laptops Guide">
    </head><body><p>Content paragraph here for testing purposes</p></body></html>
    """
    _, _, meta = clean_html(html)
    assert meta.get("description") == "A test page about laptops"
    assert meta.get("og:title") == "Laptops Guide"


def test_clean_html_truncates_long_text():
    html = "<html><head><title>T</title></head><body>" + "<p>" + "word " * 5000 + "</p></body></html>"
    _, text, _ = clean_html(html)
    assert len(text) <= 8000


# ── Date extraction ────────────────────────────────

def test_extract_date_from_meta():
    meta = {"article:published_time": "2024-03-15T10:00:00Z"}
    result = extract_date("", meta)
    assert result is not None
    assert "2024-03-15" in result


def test_extract_date_from_html_iso_format():
    html = '<html><body>Published on 2024-06-20</body></html>'
    result = extract_date(html, {})
    assert result == "2024-06-20"


def test_extract_date_from_html_human_format():
    html = '<html><body>January 15, 2024</body></html>'
    result = extract_date(html, {})
    assert result is not None
    assert "2024" in result


def test_extract_date_returns_none_when_absent():
    html = "<html><body>No dates here at all</body></html>"
    result = extract_date(html, {})
    assert result is None


# ── Fallback extraction ───────────────────────────

def test_fallback_extract_finds_price():
    plan = _make_plan()
    text = "The laptop costs $1,299.99 and has great specs."
    result = _fallback_extract(text, plan)
    assert "price" in result
    assert "$1,299.99" in result["price"] or "1,299" in result["price"]


def test_fallback_extract_finds_rating():
    plan = _make_plan()
    text = "Customer rating: 4.5/5 stars"
    result = _fallback_extract(text, plan)
    assert "rating" in result


def test_fallback_extract_empty_text():
    plan = _make_plan()
    result = _fallback_extract("No relevant data here", plan)
    assert result == {}
