"""Tests for the deterministic planning fallback."""
import pytest
from planner import plan_deterministic


def test_plan_has_required_structure():
    plan = plan_deterministic("Find the best RTX 4060 laptops under 80000", 20)
    assert plan.topic
    assert isinstance(plan.required_fields, list)
    assert len(plan.required_fields) > 0
    assert isinstance(plan.search_queries, list)
    assert len(plan.search_queries) > 0
    assert plan.max_pages == 20


def test_plan_extracts_price_constraint():
    plan = plan_deterministic("Find laptops under $90000 in India", 15)
    constraints_text = " ".join(plan.constraints).lower()
    assert "under" in constraints_text or "90000" in constraints_text


def test_plan_infers_laptop_fields():
    plan = plan_deterministic("Compare the best gaming laptops", 10)
    lower_fields = [f.lower() for f in plan.required_fields]
    assert "price" in lower_fields or "name" in lower_fields


def test_plan_generates_search_queries():
    plan = plan_deterministic("Best Python books for beginners", 10)
    assert len(plan.search_queries) >= 1
    assert all(isinstance(q, str) and len(q) > 0 for q in plan.search_queries)


def test_plan_stopping_criteria_mention_budget():
    plan = plan_deterministic("Research electric vehicles", 25)
    criteria_text = " ".join(plan.stopping_criteria)
    assert "25" in criteria_text


def test_plan_extraction_schema_matches_fields():
    plan = plan_deterministic("Find the best smartphones under 30000", 10)
    for field in plan.required_fields:
        assert field in plan.extraction_schema
