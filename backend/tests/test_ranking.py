"""Tests for the ranking module."""
import pytest
from datetime import datetime

from ranking import rank_records
from schemas import ExtractedRecord, ResearchPlan


def _make_plan() -> ResearchPlan:
    return ResearchPlan(
        topic="gaming laptop",
        required_fields=["name", "price", "rating"],
        search_queries=["best gaming laptop"],
        max_pages=10,
        ranking_priorities=["relevance", "price"],
    )


def _make_record(
    url: str,
    title: str,
    text: str,
    domain: str = "example.com",
    dynamic_fields: dict | None = None,
    published_date: str | None = None,
) -> ExtractedRecord:
    rec = ExtractedRecord(
        url=url,
        domain=domain,
        title=title,
        main_text=text,
        dynamic_fields=dynamic_fields or {},
        published_date=published_date,
        collected_at=datetime.utcnow(),
    )
    rec.relevance_score = 0.5
    rec.field_coverage = {"name": True, "price": True, "rating": False}
    return rec


def test_ranking_returns_correct_count():
    plan = _make_plan()
    records = [
        _make_record(f"https://site{i}.com", f"Laptop {i}", f"gaming laptop review {i} price rating")
        for i in range(5)
    ]
    results = rank_records(records, plan)
    assert len(results) == 5


def test_ranking_assigns_sequential_ranks():
    plan = _make_plan()
    records = [
        _make_record(f"https://site{i}.com", f"Laptop {i}", "gaming laptop")
        for i in range(3)
    ]
    results = rank_records(records, plan)
    ranks = [r.rank for r in results]
    assert ranks == [1, 2, 3]


def test_ranking_scores_descending():
    plan = _make_plan()
    records = [
        _make_record(f"https://site{i}.com", f"Laptop {i}", "gaming laptop review price")
        for i in range(4)
    ]
    results = rank_records(records, plan)
    scores = [r.final_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_ranking_empty_input():
    plan = _make_plan()
    results = rank_records([], plan)
    assert results == []


def test_ranking_includes_score_breakdown():
    plan = _make_plan()
    records = [
        _make_record("https://example.com", "Gaming Laptop X", "gaming laptop with RTX GPU price rating")
    ]
    results = rank_records(records, plan)
    assert len(results) == 1
    breakdown = results[0].score_breakdown
    assert "relevance" in breakdown
    assert "source_reliability" in breakdown
    assert "freshness" in breakdown
    assert "completeness" in breakdown


def test_ranking_has_explanation():
    plan = _make_plan()
    records = [
        _make_record("https://example.com", "Gaming Laptop", "gaming laptop performance")
    ]
    results = rank_records(records, plan)
    assert results[0].score_explanation != ""


def test_wikipedia_ranked_higher_than_unknown():
    plan = _make_plan()
    wiki_rec = _make_record(
        "https://en.wikipedia.org/wiki/Laptop",
        "Gaming Laptop",
        "gaming laptop specifications price rating",
        domain="en.wikipedia.org",
    )
    unknown_rec = _make_record(
        "https://sketchy-blog.xyz/laptops",
        "Gaming Laptop",
        "gaming laptop specifications price rating",
        domain="sketchy-blog.xyz",
    )
    results = rank_records([unknown_rec, wiki_rec], plan)
    wiki_result = next(r for r in results if "wikipedia" in r.domain)
    unknown_result = next(r for r in results if "wikipedia" not in r.domain)
    assert wiki_result.final_score >= unknown_result.final_score
