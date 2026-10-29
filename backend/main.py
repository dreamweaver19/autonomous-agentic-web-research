"""
main.py – FastAPI application with all API routes.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import database
from agent import cancel_research_task, start_research_task
from config import settings
from schemas import (
    CreateTaskRequest,
    ProgressResponse,
    RankedResult,
    ReportResponse,
    SourcesResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initialising database...")
    await database.init_db()
    log.info("Database ready.")
    yield


app = FastAPI(
    title="Autonomous Agentic Web Research System",
    description="An AI agent that autonomously converts research goals into adaptive crawling strategies.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS – allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/config", tags=["system"])
async def get_config() -> dict:
    """Return safe configuration info for the frontend."""
    return {
        "ollama_enabled": settings.ollama_enabled,
        "ollama_model": settings.ollama_model,
        "search_provider": settings.search_provider,
        "default_max_pages": settings.default_max_pages,
        "default_crawl_depth": settings.default_crawl_depth,
        "playwright_enabled": settings.playwright_enabled,
        "cloud_llm_enabled": settings.cloud_llm_enabled,
    }


# ──────────────────────────────────────────────
# Tasks
# ──────────────────────────────────────────────

@app.post("/api/tasks", response_model=TaskResponse, status_code=201, tags=["tasks"])
async def create_task(request: CreateTaskRequest) -> TaskResponse:
    """Create a new research task and start the autonomous agent."""
    task_id = str(uuid.uuid4())
    task = await database.create_task(
        task_id=task_id,
        objective=request.objective,
        max_pages=request.max_pages,
        crawl_depth=request.crawl_depth,
    )

    # Launch background agent
    await start_research_task(
        task_id=task_id,
        objective=request.objective,
        max_pages=request.max_pages,
        crawl_depth=request.crawl_depth,
    )

    return TaskResponse(
        task_id=task.id,
        status=TaskStatus(task.status),
        objective=task.objective,
        created_at=task.created_at,
        updated_at=task.updated_at,
        progress_percent=0.0,
        pages_crawled=0,
    )


@app.get("/api/tasks", response_model=TaskListResponse, tags=["tasks"])
async def list_tasks() -> TaskListResponse:
    """Return all research tasks ordered by creation date."""
    tasks = await database.get_all_tasks()
    items = []
    for t in tasks:
        plan = None
        if t.plan_json:
            from schemas import ResearchPlan
            try:
                plan = ResearchPlan.model_validate_json(t.plan_json)
            except Exception:
                pass
        items.append(
            TaskResponse(
                task_id=t.id,
                status=TaskStatus(t.status),
                objective=t.objective,
                created_at=t.created_at,
                updated_at=t.updated_at,
                progress_percent=t.progress_percent or 0.0,
                pages_crawled=t.pages_crawled or 0,
                stopping_reason=t.stopping_reason,
                plan=plan,
            )
        )
    return TaskListResponse(tasks=items, total=len(items))


@app.get("/api/tasks/{task_id}", response_model=TaskResponse, tags=["tasks"])
async def get_task(task_id: str) -> TaskResponse:
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    plan = None
    if task.plan_json:
        from schemas import ResearchPlan
        try:
            plan = ResearchPlan.model_validate_json(task.plan_json)
        except Exception:
            pass

    return TaskResponse(
        task_id=task.id,
        status=TaskStatus(task.status),
        objective=task.objective,
        created_at=task.created_at,
        updated_at=task.updated_at,
        progress_percent=task.progress_percent or 0.0,
        pages_crawled=task.pages_crawled or 0,
        stopping_reason=task.stopping_reason,
        plan=plan,
    )


@app.post("/api/tasks/{task_id}/cancel", tags=["tasks"])
async def cancel_task(task_id: str) -> dict:
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.RUNNING, TaskStatus.PLANNING, TaskStatus.PENDING):
        raise HTTPException(status_code=400, detail=f"Task is already {task.status}")
    await cancel_research_task(task_id)
    return {"message": "Cancellation requested", "task_id": task_id}


# ──────────────────────────────────────────────
# Progress
# ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}/progress", response_model=ProgressResponse, tags=["tasks"])
async def get_progress(task_id: str) -> ProgressResponse:
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = await database.load_state(task_id)
    if state:
        return ProgressResponse(
            task_id=task_id,
            status=TaskStatus(task.status),
            progress_percent=state.progress_percent,
            pages_crawled=state.pages_crawled,
            candidate_urls_count=len(state.candidate_urls),
            records_count=len(state.records),
            missing_fields=state.missing_fields,
            stopping_reason=state.stopping_reason,
            recent_urls=state.visited_urls[-5:] if state.visited_urls else [],
        )

    return ProgressResponse(
        task_id=task_id,
        status=TaskStatus(task.status),
        progress_percent=task.progress_percent or 0.0,
        pages_crawled=task.pages_crawled or 0,
        candidate_urls_count=0,
        records_count=0,
        missing_fields=[],
        stopping_reason=task.stopping_reason,
        recent_urls=[],
    )


# ──────────────────────────────────────────────
# Sources
# ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}/sources", response_model=SourcesResponse, tags=["results"])
async def get_sources(task_id: str) -> SourcesResponse:
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = await database.load_state(task_id)
    if not state:
        return SourcesResponse(
            task_id=task_id,
            visited_urls=[],
            failed_urls=[],
            candidate_urls=[],
            records=[],
        )

    return SourcesResponse(
        task_id=task_id,
        visited_urls=state.visited_urls,
        failed_urls=state.failed_urls,
        candidate_urls=state.candidate_urls[:20],
        records=state.records,
    )


# ──────────────────────────────────────────────
# Report & Results
# ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}/report", response_model=ReportResponse, tags=["results"])
async def get_report(task_id: str) -> ReportResponse:
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    report = await database.load_report(task_id)
    state = await database.load_state(task_id)

    ranked: list[RankedResult] = []
    if report:
        ranked = report.ranked_results

    return ReportResponse(
        task_id=task_id,
        report=report,
        ranked_results=ranked,
    )


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.app_port, reload=True)
