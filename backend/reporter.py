"""
reporter.py – Generate a structured ResearchReport from crawl results.
LLM is used for the executive summary and key findings when available.
The fallback produces a template-based report from the data.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from llm_client import generate
from schemas import (
    CrawlState, RankedResult, ResearchPlan, ResearchReport
)

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# LLM-assisted summary
# ──────────────────────────────────────────────

async def _llm_summary(objective: str, top_results: list[RankedResult], missing: list[str]) -> str | None:
    if not top_results:
        return None

    snippets = []
    for r in top_results[:5]:
        snippets.append(
            f"[{r.rank}] {r.title} ({r.domain}) – score {r.final_score:.2f}\n"
            f"  Fields: {r.dynamic_fields}\n"
            f"  Evidence: {r.evidence_snippets[0].text[:200] if r.evidence_snippets else 'N/A'}"
        )

    prompt = f"""You are a research synthesis agent. Based on the following web research results,
write a concise 3-5 sentence executive summary for the research objective.

Objective: {objective}

Top Results:
{chr(10).join(snippets)}

Missing Information: {', '.join(missing) if missing else 'None'}

Write ONLY the executive summary paragraph. Base it strictly on the provided results.
Do not invent prices, ratings, or specifications not present in the results."""

    return await generate(prompt)


async def _llm_findings(objective: str, top_results: list[RankedResult]) -> list[str] | None:
    if not top_results:
        return None

    data_points = []
    for r in top_results[:8]:
        for field, value in r.dynamic_fields.items():
            data_points.append(f"{r.title}: {field} = {value}")

    prompt = f"""Based on the research results below for "{objective}",
list 4-6 key findings or trends as short bullet points.
Base your findings ONLY on the data provided. Do not invent information.

Data points:
{chr(10).join(data_points[:30])}

Return one finding per line, starting with a dash (-)."""

    raw = await generate(prompt)
    if not raw:
        return None
    return [line.lstrip("-• ").strip() for line in raw.splitlines() if line.strip()]


# ──────────────────────────────────────────────
# Deterministic fallback
# ──────────────────────────────────────────────

def _fallback_summary(
    objective: str, ranked: list[RankedResult], state: CrawlState
) -> str:
    count = len(ranked)
    domains = list({r.domain for r in ranked[:5]})
    missing_note = (
        f" Some requested information was not found: {', '.join(state.missing_fields)}."
        if state.missing_fields else ""
    )
    return (
        f"Research completed for '{objective}'. "
        f"Crawled {state.pages_crawled} pages and collected {count} relevant results "
        f"from {len(domains)} unique sources including {', '.join(domains[:3])}."
        f"{missing_note} "
        f"Results are ranked by relevance, source quality, freshness, and completeness."
    )


def _fallback_findings(ranked: list[RankedResult], plan: ResearchPlan) -> list[str]:
    findings = []
    if ranked:
        top = ranked[0]
        findings.append(f"Top result: '{top.title}' from {top.domain} (score: {top.final_score:.2f})")
        # Field-based findings
        all_fields: dict[str, list[str]] = {}
        for r in ranked[:10]:
            for f, v in r.dynamic_fields.items():
                all_fields.setdefault(f, []).append(str(v))
        for field, values in list(all_fields.items())[:4]:
            unique = list(dict.fromkeys(values))[:3]
            findings.append(f"'{field}' values found: {', '.join(unique)}")
    return findings


# ──────────────────────────────────────────────
# Comparison table builder
# ──────────────────────────────────────────────

def _build_comparison_table(
    ranked: list[RankedResult], plan: ResearchPlan
) -> list[dict[str, Any]]:
    """Build a flat list of dicts for a tabular comparison."""
    rows = []
    for r in ranked[:15]:
        row: dict[str, Any] = {
            "rank": r.rank,
            "title": r.title[:80],
            "domain": r.domain,
            "score": r.final_score,
            "url": r.url,
        }
        # Add dynamic fields
        for field in plan.required_fields:
            row[field] = r.dynamic_fields.get(field, "—")
        rows.append(row)
    return rows


# ──────────────────────────────────────────────
# Main public function
# ──────────────────────────────────────────────

async def generate_report(
    state: CrawlState,
    ranked: list[RankedResult],
) -> ResearchReport:
    plan = state.plan
    objective = state.objective

    # Summary
    summary = await _llm_summary(objective, ranked[:5], state.missing_fields)
    if not summary:
        summary = _fallback_summary(objective, ranked, state)

    # Key findings
    findings = await _llm_findings(objective, ranked[:8])
    if not findings:
        findings = _fallback_findings(ranked, plan)

    # Comparison table
    comparison = _build_comparison_table(ranked, plan)

    # Limitations
    limitations: list[str] = []
    if state.missing_fields:
        limitations.append(f"Information for these fields was not found: {', '.join(state.missing_fields)}")
    if state.stopping_reason:
        limitations.append(f"Research stopped because: {state.stopping_reason}")
    if state.pages_crawled >= plan.max_pages:
        limitations.append("Crawl budget was reached; more sources may exist")
    limitations.append("Results reflect information publicly available at crawl time; prices and availability may have changed")

    # Sources
    sources = list({r.url for r in ranked[:20]})

    # Crawl stats
    crawl_stats = {
        "pages_crawled": state.pages_crawled,
        "records_collected": len(state.records),
        "results_ranked": len(ranked),
        "stopping_reason": state.stopping_reason or "Research completed",
        "failed_urls": len(state.failed_urls),
        "missing_fields": state.missing_fields,
    }

    # Confidence: based on coverage and source count
    coverage_avg = (
        sum(r.final_score for r in ranked) / len(ranked) if ranked else 0.0
    )
    confidence = round(min(coverage_avg * 1.2, 1.0), 3)

    # Determine whether LLM was used (at least one dynamic field was extracted via LLM)
    llm_used = any(r.dynamic_fields for r in ranked)

    methodology = (
        f"1. Parsed research objective into a structured plan with {len(plan.required_fields)} fields. "
        f"2. Generated {len(plan.search_queries)} search queries. "
        f"3. Adaptively crawled up to {plan.max_pages} pages, prioritising by relevance and coverage. "
        f"4. Extracted data using {'LLM-assisted' if llm_used else 'pattern-based'} extraction. "
        f"5. Ranked {len(ranked)} results using weighted scoring (relevance, reliability, freshness, completeness)."
    )

    return ResearchReport(
        task_id=state.task_id,
        objective=objective,
        executive_summary=summary,
        methodology=methodology,
        ranked_results=ranked,
        comparison_table=comparison,
        key_findings=findings,
        limitations=limitations,
        conflicting_information=state.conflicting_fields,
        sources=sources,
        crawl_stats=crawl_stats,
        generated_at=datetime.utcnow(),
        confidence_score=confidence,
    )
