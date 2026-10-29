"""Tests for the reporter module (fallback summary, comparison table, findings)."""
import pytest
from datetime import datetime

from reporter import _fallback_summary, _fallback_findings, _build_comparison_table, generate_report
from schemas import (
    CrawlState, ExtractedRecord, RankedResult, ResearchPlan, TaskStatus,
)


def _make_plan(topic: str = "gaming laptop", fields: list[str] | None = None) -> ResearchPlan:
    return ResearchPlan(
        topic=topic,
        required_fields=fields or ["name", "price", "rating"],
        search_queries=[f"best {topic}"],
        max_pages=10,
    )


def _make_state(
    records: int = 0,
    pages: int = 5,
    plan: ResearchPlan | None = None,
) -> CrawlState:
    p = plan or _make_plan()
    return CrawlState(
        task_id="test-task",
        objective="Find gaming laptops",
        plan=p,
        pages_crawled=pages,
        status=TaskStatus.COMPLETED,
        records=[],
        missing_fields=[],
    )


def _make_ranked_result(rank: int = 1, domain: str = "example.com") -> RankedResult:
    return RankedResult(
        rank=rank,
        url=f"https://{domain}/page{rank}",
        title=f"Result {rank}",
        domain=domain,
        final_score=0.75,
        score_breakdown={"relevance": 0.8, "source_reliability": 0.7},
        score_explanation="relevance: 0.80 x 0.30 = 0.240",
        dynamic_fields={"name": f"Item {rank}", "price": f"${rank * 100}"},
    )


# ── Fallback summary ────────────────────────────────

def test_fallback_summary_mentions_objective():
    state = _make_state()
    ranked = [_make_ranked_result()]
    summary = _fallback_summary("Find gaming laptops", ranked, state)
    assert "gaming laptops" in summary.lower()


def test_fallback_summary_mentions_page_count():
    state = _make_state(pages=15)
    ranked = [_make_ranked_result()]
    summary = _fallback_summary("test", ranked, state)
    assert "15" in summary


def test_fallback_summary_mentions_missing_fields():
    state = _make_state()
    state.missing_fields = ["availability", "warranty"]
    ranked = [_make_ranked_result()]
    summary = _fallback_summary("test", ranked, state)
    assert "availability" in summary


def test_fallback_summary_no_missing_fields():
    state = _make_state()
    state.missing_fields = []
    ranked = [_make_ranked_result()]
    summary = _fallback_summary("test", ranked, state)
    assert "not found" not in summary.lower() or "no" in summary.lower()


# ── Fallback findings ───────────────────────────────

def test_fallback_findings_with_results():
    plan = _make_plan()
    ranked = [_make_ranked_result(1), _make_ranked_result(2)]
    findings = _fallback_findings(ranked, plan)
    assert len(findings) > 0
    assert "Result 1" in findings[0]


def test_fallback_findings_empty():
    plan = _make_plan()
    findings = _fallback_findings([], plan)
    assert findings == []


def test_fallback_findings_includes_field_values():
    plan = _make_plan()
    ranked = [_make_ranked_result()]
    findings = _fallback_findings(ranked, plan)
    text = " ".join(findings)
    assert "name" in text.lower() or "price" in text.lower()


# ── Comparison table ─────────────────────────────────

def test_comparison_table_has_correct_columns():
    plan = _make_plan(fields=["name", "price"])
    ranked = [_make_ranked_result()]
    table = _build_comparison_table(ranked, plan)
    assert len(table) == 1
    row = table[0]
    assert "rank" in row
    assert "title" in row
    assert "domain" in row
    assert "score" in row
    assert "name" in row
    assert "price" in row


def test_comparison_table_truncates_to_15():
    plan = _make_plan()
    ranked = [_make_ranked_result(i) for i in range(1, 21)]
    table = _build_comparison_table(ranked, plan)
    assert len(table) == 15


def test_comparison_table_uses_dash_for_missing_fields():
    plan = _make_plan(fields=["name", "price", "warranty"])
    ranked = [_make_ranked_result()]  # has name and price, not warranty
    table = _build_comparison_table(ranked, plan)
    assert table[0]["warranty"] == "—"


# ── Full report generation ──────────────────────────

async def test_generate_report_produces_complete_report():
    plan = _make_plan(fields=["name", "price"])
    state = _make_state(plan=plan)
    state.records = []
    ranked = [_make_ranked_result(1), _make_ranked_result(2)]

    report = await generate_report(state, ranked)

    assert report.task_id == "test-task"
    assert report.objective == "Find gaming laptops"
    assert len(report.executive_summary) > 0
    assert len(report.methodology) > 0
    assert len(report.ranked_results) == 2
    assert len(report.comparison_table) == 2
    assert len(report.sources) > 0
    assert report.crawl_stats["pages_crawled"] == 5
    assert 0.0 <= report.confidence_score <= 1.0


async def test_generate_report_with_no_results():
    plan = _make_plan()
    state = _make_state(plan=plan)
    ranked = []

    report = await generate_report(state, ranked)

    assert report.task_id == "test-task"
    assert len(report.executive_summary) > 0
    assert report.ranked_results == []
    assert report.comparison_table == []
    assert report.confidence_score == 0.0


async def test_generate_report_includes_limitations():
    plan = _make_plan()
    state = _make_state(pages=10, plan=plan)
    state.missing_fields = ["availability"]
    state.stopping_reason = "Reached maximum page budget (10)"
    ranked = [_make_ranked_result()]

    report = await generate_report(state, ranked)

    assert len(report.limitations) > 0
    limitations_text = " ".join(report.limitations)
    assert "availability" in limitations_text or "budget" in limitations_text.lower()
