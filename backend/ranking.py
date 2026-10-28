"""
ranking.py – Configurable weighted ranking of extracted records.
Score = w1*Relevance + w2*SourceReliability + w3*Freshness + w4*Completeness + w5*ConstraintMatch - Penalties
"""
from __future__ import annotations

import logging
import re
from typing import Any

from evaluator import (
    compute_field_coverage,
    compute_freshness,
    compute_relevance,
    source_reliability_score,
)
from schemas import ExtractedRecord, RankedResult, ResearchPlan

log = logging.getLogger(__name__)

# Default weights (sum to 1.0)
DEFAULT_WEIGHTS = {
    "relevance": 0.30,
    "source_reliability": 0.20,
    "freshness": 0.15,
    "completeness": 0.25,
    "constraint_match": 0.10,
}


def _compute_constraint_match(record: ExtractedRecord, plan: ResearchPlan) -> float:
    """
    Score how well a record's content satisfies the explicit constraints
    (e.g. price under X, location = Y).
    """
    if not plan.constraints:
        return 1.0

    text = (record.title + " " + record.main_text + " " + str(record.dynamic_fields)).lower()
    matches = 0
    for constraint in plan.constraints:
        words = re.findall(r"\w+", constraint.lower())
        word_hits = sum(1 for w in words if len(w) > 3 and w in text)
        if word_hits >= len([w for w in words if len(w) > 3]) * 0.5:
            matches += 1

    return round(matches / len(plan.constraints), 3)


def _explain_score(breakdown: dict[str, float], weights: dict[str, float]) -> str:
    """Build a human-readable score explanation."""
    parts = []
    for key, weight in weights.items():
        score = breakdown.get(key, 0.0)
        contribution = round(score * weight, 3)
        label = key.replace("_", " ").title()
        parts.append(f"{label}: {score:.2f} × {weight:.2f} = {contribution:.3f}")
    return " | ".join(parts)


def rank_records(
    records: list[ExtractedRecord],
    plan: ResearchPlan,
    weights: dict[str, float] | None = None,
) -> list[RankedResult]:
    """
    Rank records and return a sorted list of RankedResult objects.
    Different objectives can pass custom weights.
    """
    if not records:
        return []

    # Adjust default weights based on ranking priorities from the plan
    w = dict(DEFAULT_WEIGHTS)
    priorities = [p.lower() for p in plan.ranking_priorities]
    if "freshness" in priorities or "latest" in priorities or "recent" in priorities:
        w["freshness"] = 0.25
        w["relevance"] = 0.25
    if "price" in priorities or "cheapest" in priorities:
        w["constraint_match"] = 0.20
        w["completeness"] = 0.20
    if "quality" in priorities or "academic" in priorities:
        w["source_reliability"] = 0.30
        w["relevance"] = 0.30

    # Override with caller-provided weights if any
    if weights:
        w.update(weights)

    # Normalise weights to sum to 1.0
    total = sum(w.values())
    if total > 0:
        w = {k: v / total for k, v in w.items()}

    scored: list[tuple[float, dict, ExtractedRecord]] = []
    for rec in records:
        relevance = compute_relevance(rec, plan)
        reliability = source_reliability_score(rec.domain)
        freshness = compute_freshness(rec)
        completeness = compute_field_coverage(rec, plan)
        constraint = _compute_constraint_match(rec, plan)

        breakdown = {
            "relevance": relevance,
            "source_reliability": reliability,
            "freshness": freshness,
            "completeness": completeness,
            "constraint_match": constraint,
        }

        # Penalty: very short content
        penalty = 0.0
        if len(rec.main_text) < 200:
            penalty += 0.1
        # Penalty: no dynamic fields extracted
        if not rec.dynamic_fields:
            penalty += 0.05

        raw_score = sum(breakdown[k] * w.get(k, 0.0) for k in breakdown)
        final_score = round(max(0.0, raw_score - penalty), 4)

        scored.append((final_score, breakdown, rec))

    # Sort descending
    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[RankedResult] = []
    for rank, (final_score, breakdown, rec) in enumerate(scored, start=1):
        explanation = _explain_score(breakdown, w)
        results.append(
            RankedResult(
                rank=rank,
                url=rec.url,
                title=rec.title,
                domain=rec.domain,
                final_score=final_score,
                score_breakdown=breakdown,
                score_explanation=explanation,
                dynamic_fields=rec.dynamic_fields,
                evidence_snippets=rec.evidence_snippets[:5],
                published_date=rec.published_date,
            )
        )
    return results
