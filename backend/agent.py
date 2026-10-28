"""
agent.py – The adaptive research agent controller.
This is the core innovation: an autonomous crawl loop that:
  1. Selects the highest-priority URL
  2. Fetches and extracts content
  3. Updates research state
  4. Reprioritises remaining URLs based on missing info
  5. Decides to continue or stop
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

import database
from config import settings
from crawler import fetch_page
from discovery import (
    discover_candidate_urls,
    extract_links_from_html,
    normalize_url,
    score_link_relevance,
)
from evaluator import (
    compute_field_coverage,
    compute_relevance,
    evaluate_state,
    is_duplicate,
    should_stop,
)
from extractor import extract_page
from planner import create_research_plan
from ranking import rank_records
from reporter import generate_report
from schemas import (
    CandidateURL, CrawlState, ResearchPlan, TaskStatus
)

log = logging.getLogger(__name__)

# In-memory registry of active agent tasks (task_id -> asyncio.Task)
_active_tasks: dict[str, asyncio.Task] = {}


# ──────────────────────────────────────────────
# URL reprioritisation
# ──────────────────────────────────────────────

def _reprioritise_queue(state: CrawlState) -> CrawlState:
    """
    Reorder the candidate URL queue based on:
    - Current missing fields (boost URLs that might cover them)
    - Source diversity (penalise domains already heavily visited)
    """
    if not state.candidate_urls:
        return state

    visited_domains: dict[str, int] = {}
    for url in state.visited_urls:
        try:
            from urllib.parse import urlparse
            d = urlparse(url).netloc
            visited_domains[d] = visited_domains.get(d, 0) + 1
        except Exception:
            pass

    for candidate in state.candidate_urls:
        try:
            from urllib.parse import urlparse
            domain = urlparse(candidate.url).netloc
        except Exception:
            domain = ""

        # Penalise if we've already visited too many pages from this domain
        domain_count = visited_domains.get(domain, 0)
        domain_penalty = min(domain_count * 0.05, 0.3)

        # Boost if URL text hints at missing fields
        url_lower = candidate.url.lower()
        field_boost = 0.0
        for field in state.missing_fields:
            if field.lower() in url_lower:
                field_boost += 0.15

        candidate.priority = round(
            min(max(candidate.priority + field_boost - domain_penalty, 0.0), 1.0),
            3,
        )

    # Sort queue by priority descending
    state.candidate_urls.sort(key=lambda c: c.priority, reverse=True)
    return state


# ──────────────────────────────────────────────
# Single crawl step
# ──────────────────────────────────────────────

async def _crawl_step(state: CrawlState, depth_limit: int) -> CrawlState:
    """Process one URL from the priority queue and update the state."""
    if not state.candidate_urls:
        return state

    # Pop highest-priority URL
    candidate = state.candidate_urls.pop(0)
    url = candidate.url

    # Skip if already visited
    norm = normalize_url(url)
    if norm in [normalize_url(v) for v in state.visited_urls]:
        log.debug("Already visited, skipping: %s", url)
        return state

    state.visited_urls.append(url)
    state.pages_crawled += 1
    log.info(
        "[%d/%d] Crawling (priority=%.2f): %s",
        state.pages_crawled, state.plan.max_pages, candidate.priority, url
    )

    # Fetch page
    result = await fetch_page(url)
    if not result.ok:
        log.info("Fetch failed [%s]: %s", result.error, url)
        state.failed_urls.append(url)
        return state

    # Extract structured record
    record = await extract_page(
        url=url,
        final_url=result.final_url,
        html=result.html,
        plan=state.plan,
    )

    # Score relevance
    record.relevance_score = compute_relevance(record, state.plan)

    # Duplicate check
    if is_duplicate(record, state.records):
        log.debug("Duplicate content, skipping: %s", url)
        return state

    # Add record if it has some relevance
    if record.relevance_score >= 0.1 or compute_field_coverage(record, state.plan) >= 0.2:
        state.records.append(record)
        log.info(
            "  → Relevant (score=%.2f, coverage=%.2f, fields=%s)",
            record.relevance_score,
            compute_field_coverage(record, state.plan),
            list(record.dynamic_fields.keys())[:5],
        )
    else:
        log.debug("  → Low relevance (%.2f), not adding to records", record.relevance_score)

    # Link discovery: add promising child links to the queue (depth limit)
    if candidate.depth < depth_limit:
        child_links = extract_links_from_html(result.html, result.final_url)
        visited_set = {normalize_url(v) for v in state.visited_urls}
        queued_set = {normalize_url(c.url) for c in state.candidate_urls}

        new_candidates_added = 0
        for link in child_links:
            norm_link = normalize_url(link)
            if norm_link in visited_set or norm_link in queued_set:
                continue
            link_score = score_link_relevance(link, "", state.plan)
            if link_score >= 0.3:
                state.candidate_urls.append(
                    CandidateURL(
                        url=link,
                        priority=round(link_score * 0.8, 3),  # child pages get slightly lower priority
                        depth=candidate.depth + 1,
                        source="link",
                        reason=f"Link from {url[:60]}",
                    )
                )
                queued_set.add(norm_link)
                new_candidates_added += 1
                if new_candidates_added >= 5:  # max 5 new links per page
                    break

    return state


# ──────────────────────────────────────────────
# Main agent loop
# ──────────────────────────────────────────────

async def run_research_agent(task_id: str, objective: str, max_pages: int, crawl_depth: int) -> None:
    """
    Full autonomous research loop.
    Designed to run as a background asyncio task.
    """
    log.info("=== Research Agent START: %s ===", task_id)
    try:
        # Phase 1: Planning
        await database.update_task_status(task_id, TaskStatus.PLANNING, progress_percent=2.0)
        plan = await create_research_plan(objective, max_pages)
        await database.save_plan(task_id, plan)
        log.info("Plan created: topic=%s, fields=%s", plan.topic, plan.required_fields)

        # Phase 2: Source Discovery
        await database.update_task_status(task_id, TaskStatus.RUNNING, progress_percent=5.0)
        initial_candidates = await discover_candidate_urls(plan)

        # Initialise crawl state
        state = CrawlState(
            task_id=task_id,
            objective=objective,
            plan=plan,
            candidate_urls=initial_candidates,
            missing_fields=list(plan.required_fields),
            status=TaskStatus.RUNNING,
        )

        if not initial_candidates:
            log.warning("No initial URLs discovered. Using search queries as fallback seeds.")
            # If no search results, we can't proceed meaningfully
            state.stopping_reason = "No URLs discovered – check search provider configuration"
            state.status = TaskStatus.COMPLETED

        # Phase 3: Adaptive Crawl Loop
        while state.status == TaskStatus.RUNNING:
            # Check cancellation
            task_row = await database.get_task(task_id)
            if task_row and task_row.status == TaskStatus.CANCELLED:
                state.status = TaskStatus.CANCELLED
                state.stopping_reason = "Cancelled by user"
                break

            # Reprioritise queue
            state = _reprioritise_queue(state)

            # Should we stop?
            stop, reason = should_stop(state)
            if stop:
                state.stopping_reason = reason
                state.status = TaskStatus.COMPLETED
                log.info("Stopping: %s", reason)
                break

            # One crawl step
            state = await _crawl_step(state, crawl_depth)

            # Evaluate state (missing fields, conflicts)
            state = evaluate_state(state)

            # Update progress
            progress = min(99.0, (state.pages_crawled / max(plan.max_pages, 1)) * 85 + 10)
            state.progress_percent = round(progress, 1)

            # Persist state periodically (every 3 pages)
            if state.pages_crawled % 3 == 0:
                await database.save_state(task_id, state)
                log.debug("State saved at page %d", state.pages_crawled)

        # Phase 4: Ranking
        log.info("Ranking %d collected records...", len(state.records))
        ranked = rank_records(state.records, plan)

        # Phase 5: Report generation
        log.info("Generating report...")
        report = await generate_report(state, ranked)
        await database.save_report(task_id, report)

        # Final state save
        state.status = TaskStatus.COMPLETED if state.status != TaskStatus.CANCELLED else TaskStatus.CANCELLED
        state.progress_percent = 100.0
        await database.save_state(task_id, state)
        await database.update_task_status(
            task_id,
            state.status,
            progress_percent=100.0,
            pages_crawled=state.pages_crawled,
            stopping_reason=state.stopping_reason,
        )
        log.info("=== Research Agent DONE: %s (%d records, %d ranked) ===", task_id, len(state.records), len(ranked))

    except Exception as exc:
        log.exception("Agent failed for task %s: %s", task_id, exc)
        await database.update_task_status(
            task_id, TaskStatus.FAILED,
            stopping_reason=f"Internal error: {str(exc)[:200]}"
        )
    finally:
        _active_tasks.pop(task_id, None)


# ──────────────────────────────────────────────
# Task management
# ──────────────────────────────────────────────

async def start_research_task(
    task_id: str, objective: str, max_pages: int, crawl_depth: int
) -> None:
    """Spawn the agent as a background asyncio task."""
    coro = run_research_agent(task_id, objective, max_pages, crawl_depth)
    task = asyncio.create_task(coro, name=f"research-{task_id}")
    _active_tasks[task_id] = task


async def cancel_research_task(task_id: str) -> bool:
    """Request cancellation of a running research task."""
    await database.update_task_status(task_id, TaskStatus.CANCELLED)
    task = _active_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
