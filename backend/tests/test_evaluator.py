"""Tests for the evaluator module."""
import pytest
from datetime import datetime

from evaluator import (
    compute_relevance,
    compute_freshness,
    compute_field_coverage,
    is_duplicate,
    should_stop,
    source_reliability_score,
)
from schemas import (
    CandidateURL, CrawlState, ExtractedRecord, ResearchPlan, TaskStatus
)


def _make_plan(topic: str, fields: list[str] | None = None) -> ResearchPlan:
    return ResearchPlan(
        topic=topic,
        required_fields=fields or ["name", "price", "rating"],
        search_queries=[f"best {topic}"],
        max_pages=10,
    )


def _make_record(
    url: str = "https://example.com/product",
    title: str = "Test Product",
    text: str = "",
    domain: str = "example.com",
    dynamic_fields: dict | None = None,
    published_date: str | None = None,
) -> ExtractedRecord:
    return ExtractedRecord(
        url=url,
        domain=domain,
        title=title,
        main_text=text,
        dynamic_fields=dynamic_fields or {},
        published_date=published_date,
        collected_at=datetime.utcnow(),
    )


# ── Relevance ────────────────────────────────

def test_relevance_high_for_matching_text():
    plan = _make_plan("gaming laptop")
    rec = _make_record(
        text="This gaming laptop has excellent performance. Best gaming laptop under 80000. Laptop review."
    )
    score = compute_relevance(rec, plan)
    assert score > 0.5


def test_relevance_low_for_unrelated_text():
    plan = _make_plan("gaming laptop")
    rec = _make_record(text="Today's weather forecast shows sunny skies in Mumbai.")
    score = compute_relevance(rec, plan)
    assert score < 0.3


# ── Freshness ────────────────────────────────

def test_freshness_high_for_recent_date():
    rec = _make_record(published_date="2026-09-01")
    score = compute_freshness(rec)
    assert score >= 0.8


def test_freshness_low_for_old_date():
    rec = _make_record(published_date="2018-01-01")
    score = compute_freshness(rec)
    assert score <= 0.5


def test_freshness_neutral_for_no_date():
    rec = _make_record(published_date=None)
    score = compute_freshness(rec)
    assert score == 0.5


# ── Field coverage ───────────────────────────

def test_field_coverage_full():
    plan = _make_plan("laptop", ["name", "price"])
    rec = _make_record(
        text="Product name: Dell XPS. Price: $999.",
        dynamic_fields={"name": "Dell XPS", "price": "$999"},
    )
    rec.field_coverage = {"name": True, "price": True}
    score = compute_field_coverage(rec, plan)
    assert score == 1.0


def test_field_coverage_partial():
    plan = _make_plan("laptop", ["name", "price", "rating"])
    rec = _make_record(dynamic_fields={"name": "Dell XPS"})
    rec.field_coverage = {"name": True, "price": False, "rating": False}
    score = compute_field_coverage(rec, plan)
    assert abs(score - 1/3) < 0.01


# ── Duplicate detection ──────────────────────

def test_duplicate_by_url():
    rec1 = _make_record(url="https://example.com/page")
    rec2 = _make_record(url="https://example.com/page")
    assert is_duplicate(rec2, [rec1])


def test_not_duplicate_different_content():
    rec1 = _make_record(url="https://a.com/x", text="A" * 200)
    rec2 = _make_record(url="https://b.com/y", text="B" * 200)
    assert not is_duplicate(rec2, [rec1])


def test_duplicate_by_content_hash():
    same_text = "Identical content repeated here " * 20
    rec1 = _make_record(url="https://site1.com/p1", text=same_text)
    rec2 = _make_record(url="https://site2.com/p2", text=same_text)
    assert is_duplicate(rec2, [rec1])


# ── Source reliability ───────────────────────

def test_wikipedia_high_reliability():
    score = source_reliability_score("en.wikipedia.org")
    assert score >= 0.85


def test_unknown_domain_moderate():
    score = source_reliability_score("randomtech.blog")
    assert 0.3 <= score <= 0.7


# ── Stopping criteria ────────────────────────

def _make_state(pages: int, max_pages: int, records: int = 0) -> CrawlState:
    plan = _make_plan("laptop")
    plan.max_pages = max_pages
    state = CrawlState(
        task_id="test",
        objective="test",
        plan=plan,
        pages_crawled=pages,
        status=TaskStatus.RUNNING,
    )
    return state


def test_stop_at_max_pages():
    state = _make_state(pages=20, max_pages=20)
    stop, reason = should_stop(state)
    assert stop
    assert "budget" in reason.lower() or "maximum" in reason.lower()


def test_continue_below_max_pages():
    state = _make_state(pages=5, max_pages=20)
    state.candidate_urls = [CandidateURL(url="https://example.com")]
    stop, _ = should_stop(state)
    assert not stop


def test_stop_no_candidates():
    state = _make_state(pages=5, max_pages=20)
    state.candidate_urls = []
    stop, reason = should_stop(state)
    assert stop
    assert "candidate" in reason.lower()
