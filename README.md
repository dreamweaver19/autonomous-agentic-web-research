# Autonomous Agentic Web Research & Crawling System

An AI-powered system that converts natural-language research goals into adaptive web crawling strategies, extracts structured evidence, ranks results, and generates evidence-grounded research reports.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Module Explanations](#module-explanations)
- [Research Workflow](#research-workflow)
- [API Documentation](#api-documentation)
- [Environment Variables](#environment-variables)
- [LLM Configuration](#llm-configuration)
- [Security](#security)
- [Testing](#testing)
- [Known Limitations](#known-limitations)
- [Academic Q&A](#academic-qa)

---

## Quick Start

### Prerequisites

- Python 3.11+ (tested on Python 3.14)
- Node.js 18+ (tested on Node 22)
- Optional: [Ollama](https://ollama.com) for local LLM (improves quality)

### 1. Copy the environment file

```
copy .env.example .env
```

Edit `.env` if you want to enable Ollama, change the search provider, or adjust limits. The defaults work without any changes.

### 2. Install backend dependencies

```
cd backend
pip install -r requirements.txt
```

### 3. Install frontend dependencies

```
cd frontend
npm install
```

### 4. Start the backend

```
start_backend.bat
```

Or manually:
```
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Start the frontend (separate terminal)

```
start_frontend.bat
```

Or manually:
```
cd frontend
npm run dev
```

### 6. Open the app

Visit **http://localhost:5173** in your browser.

---

## Architecture

```
frontend (React + Vite + Tailwind)
    ↕  HTTP / proxy
backend (Python + FastAPI)
    ├── planner.py       ← NL → ResearchPlan (LLM + deterministic fallback)
    ├── discovery.py     ← Search provider + link extraction
    ├── crawler.py       ← Safe HTTP fetcher (SSRF guard, rate limiting, robots.txt)
    ├── extractor.py     ← HTML → structured ExtractedRecord
    ├── evaluator.py     ← Relevance, coverage, duplicate detection, stop criteria
    ├── ranking.py       ← Weighted scoring (relevance, reliability, freshness, completeness)
    ├── reporter.py      ← Report generation (LLM + template fallback)
    ├── agent.py         ← Adaptive crawl loop controller
    ├── main.py          ← FastAPI routes
    ├── database.py      ← SQLite/PostgreSQL via SQLAlchemy async
    ├── llm_client.py    ← Ollama + cloud LLM wrapper
    ├── schemas.py       ← Pydantic models
    └── config.py        ← Centralised settings from .env
```

### Data Flow

```
User submits objective (frontend)
    ↓
POST /api/tasks → database.create_task → agent.start_research_task
    ↓
Phase 1: PLANNING
    planner.create_research_plan(objective)
        → tries LLM (Ollama/cloud) for structured plan
        → falls back to deterministic keyword-based planner
    → database.save_plan
    ↓
Phase 2: DISCOVERY
    discovery.discover_candidate_urls(plan)
        → runs each search query via search_urls()
        → DuckDuckGo HTML scraping OR Serper API
        → returns prioritised list of CandidateURL objects
    ↓
Phase 3: ADAPTIVE CRAWL LOOP (repeats until stopping criteria met)
    agent._reprioritise_queue(state)
        → boosts URLs matching missing fields
        → penalises over-visited domains
    → evaluator.should_stop(state) checks:
        - max page budget reached?
        - all required fields covered?
        - no more candidates?
        - diminishing returns?
    → agent._crawl_step(state, depth_limit):
        a. Pop highest-priority URL
        b. crawler.fetch_page(url) — SSRF check, robots.txt, rate limit
        c. extractor.extract_page(html, plan) — clean HTML, extract fields
        d. evaluator.compute_relevance + is_duplicate check
        e. discovery.extract_links_from_html → add child links to queue
    → evaluator.evaluate_state(state)
        → recompute relevance, field coverage, missing fields, conflicts
    → database.save_state (every 3 pages)
    ↓
Phase 4: RANKING
    ranking.rank_records(records, plan)
        → weighted score = relevance×0.30 + reliability×0.20 + freshness×0.15
          + completeness×0.25 + constraint_match×0.10 - penalties
        → weights adjusted based on plan.ranking_priorities
    ↓
Phase 5: REPORT GENERATION
    reporter.generate_report(state, ranked)
        → LLM summary + findings (if available)
        → fallback template-based summary + findings
        → comparison table, limitations, crawl stats, confidence score
    → database.save_report
    ↓
Frontend polls GET /api/tasks/{id}/progress and /report
    → displays live progress, sources, ranked results, full report
```

---

## Module Explanations

### config.py — Centralised Settings

Uses `pydantic-settings` to load configuration from a `.env` file or environment variables. The `Settings` class defines all configurable parameters with sensible defaults. The `blocked_domains` property merges a built-in SSRF blocklist with user-configured extra domains.

Key design decision: a single `settings` instance is created at module load time and imported everywhere, avoiding repeated file reads.

### schemas.py — Pydantic Data Models

Defines all data structures used across the system:

- **`TaskStatus`** enum: pending → planning → running → completed/failed/cancelled
- **`ResearchPlan`**: the output of the planner (topic, constraints, required fields, search queries, ranking priorities, extraction schema)
- **`ExtractedRecord`**: structured data from a single crawled page (title, text, metadata, dynamic fields, evidence snippets, relevance score, field coverage)
- **`CrawlState`**: the complete state of a research task at any point (candidate URLs, visited URLs, failed URLs, records, missing fields, conflicting fields, progress)
- **`RankedResult`**: a record with its final score and breakdown
- **`ResearchReport`**: the final output (executive summary, methodology, ranked results, comparison table, key findings, limitations, confidence score)

### main.py — FastAPI Routes

All HTTP endpoints. CORS is configured to allow the Vite dev server. On startup, the database tables are created via the `lifespan` context manager.

Endpoints: health check, config info, create task, list tasks, get task, cancel task, get progress, get sources, get report.

### agent.py — Adaptive Crawl Loop Controller

This is the core innovation of the project. The `run_research_agent` function runs as a background asyncio task and orchestrates the full research pipeline:

1. **Planning**: calls `planner.create_research_plan()`
2. **Discovery**: calls `discovery.discover_candidate_urls()` to get initial URLs
3. **Crawl loop**: repeatedly calls `_reprioritise_queue` → `should_stop` → `_crawl_step` → `evaluate_state`
4. **Ranking**: calls `ranking.rank_records()`
5. **Report**: calls `reporter.generate_report()`

The `_reprioritise_queue` function reorders the URL queue based on what information is still missing and which domains have been over-visited. This adaptive behaviour is what makes the agent "agentic" rather than a simple breadth-first crawler.

### planner.py — Research Planning

Converts a natural-language objective into a structured `ResearchPlan`. Two paths:

- **LLM path** (`plan_with_llm`): sends a structured prompt to the LLM asking for topic, constraints, required fields, search queries, etc.
- **Deterministic fallback** (`plan_deterministic`): uses regex to extract price constraints and location, infers fields from keyword matching (e.g., "laptop" → name, price, cpu, gpu, ram), and generates search queries by cleaning the objective text.

The deterministic fallback is important because it ensures the system works without any LLM dependency.

### discovery.py — Source Discovery

Two responsibilities:

1. **Search provider dispatch**: `search_urls()` routes to DuckDuckGo HTML scraping or Serper API based on config. DuckDuckGo scraping parses result links from the HTML results page, handling DDG's redirect URLs.
2. **Link extraction**: `extract_links_from_html()` parses `<a href>` tags from crawled pages and resolves relative URLs. `score_link_relevance()` gives a heuristic 0-1 score based on topic word matching and penalties for non-content pages (login, cart, PDFs).

### crawler.py — Safe HTTP Fetcher

Fetches web pages with multiple safety layers:

1. **SSRF protection** (`_is_safe_url`): blocks non-HTTP schemes, checks domain blocklist, resolves DNS and checks if the IP falls in private/reserved ranges
2. **robots.txt**: checks per-domain robots.txt (cached per origin)
3. **Rate limiting**: per-domain delay to avoid hammering servers
4. **Response size limit**: truncates large responses
5. **Redirect safety**: re-validates the final URL after redirects
6. **Content-type filtering**: only processes HTML/text responses

### extractor.py — Content Extraction

Converts raw HTML into `ExtractedRecord` objects:

1. **`clean_html()`**: removes script/style/nav/footer tags, extracts title and meta tags, collapses whitespace, truncates to 8000 chars
2. **`extract_date()`**: checks common meta tags and regex patterns for publication dates
3. **`extract_dynamic_fields()`**: sends cleaned text to the LLM with the plan's field schema. Falls back to `_fallback_extract()` which uses regex to find prices and ratings.
4. **`extract_page()`**: orchestrates the above, builds field coverage map and evidence snippets

### evaluator.py — Evaluation Engine

Multiple evaluation functions:

- **`source_reliability_score()`**: heuristic 0-1 based on domain (Wikipedia/Reuters = 0.9, e-commerce = 0.65, forums = 0.3, .edu/.gov = 0.85)
- **`compute_relevance()`**: keyword overlap between page content and research topic/constraints
- **`compute_field_coverage()`**: fraction of required fields found
- **`compute_freshness()`**: 0-1 based on publication date (recent = 1.0, >2 years = 0.2)
- **`is_duplicate()`**: URL match or SHA-256 content hash match
- **`detect_conflicts()`**: finds fields with different values across sources
- **`evaluate_state()`**: recomputes all scores, updates missing fields and conflicts
- **`should_stop()`**: checks stopping criteria (max pages, sufficient coverage, no candidates, diminishing returns)

### ranking.py — Weighted Ranking

Scores and sorts records using configurable weights:

```
final_score = relevance×0.30 + source_reliability×0.20 + freshness×0.15
            + completeness×0.25 + constraint_match×0.10 - penalties
```

Weights are adjusted based on `plan.ranking_priorities` (e.g., "freshness" priority boosts the freshness weight). Penalties apply for very short content and missing dynamic fields. Each result includes a human-readable score breakdown.

### reporter.py — Report Generation

Produces a `ResearchReport` with:

- **Executive summary**: LLM-generated (or template-based fallback) paragraph
- **Key findings**: LLM-generated (or data-driven fallback) bullet points
- **Comparison table**: flat list of dicts with rank, title, domain, score, and dynamic fields
- **Methodology**: describes the 5-phase pipeline
- **Limitations**: missing fields, stopping reason, crawl budget, data freshness caveat
- **Confidence score**: based on average final scores of ranked results

### database.py — Persistence Layer

SQLAlchemy async ORM with SQLite (default) or PostgreSQL. Each task row stores the plan, crawl state, and report as JSON blobs. This simplifies the schema (single table) while allowing complex nested data.

### llm_client.py — LLM Integration

Thin wrapper around two providers:

1. **Ollama** (primary): local LLM via `/api/generate` endpoint
2. **Cloud LLM** (fallback): OpenAI-compatible `/chat/completions` endpoint

Both `generate()` and `generate_json()` return `None` on failure, allowing callers to apply deterministic fallbacks. Never raises exceptions for LLM unavailability.

---

## Research Workflow

1. User enters a research objective in the frontend (e.g., "Find the best gaming laptops under 80000")
2. Frontend sends `POST /api/tasks` with the objective, max_pages, and crawl_depth
3. Backend creates a task in the database and launches the agent as a background task
4. **Planning phase**: the planner converts the objective into a structured plan with required fields, search queries, and stopping criteria
5. **Discovery phase**: search queries are executed to find initial candidate URLs
6. **Crawl phase**: the agent adaptively crawls pages, extracting structured data and reprioritising the URL queue based on what's still missing
7. **Evaluation phase**: after each page, the agent evaluates relevance, coverage, duplicates, and conflicts, then checks stopping criteria
8. **Ranking phase**: collected records are scored and ranked using weighted criteria
9. **Report phase**: a structured report is generated with summary, findings, comparison table, and confidence score
10. Frontend polls progress endpoints and displays live updates, then the final report

---

## API Documentation

### System Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check, returns `{"status": "ok", "timestamp": "..."}` |
| GET | `/api/config` | Safe config info for frontend (no secrets) |

### Task Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tasks` | Create a research task and start the agent |
| GET | `/api/tasks` | List all tasks (newest first) |
| GET | `/api/tasks/{id}` | Get a single task |
| POST | `/api/tasks/{id}/cancel` | Cancel a running task |
| GET | `/api/tasks/{id}/progress` | Get live progress (pages, records, missing fields) |
| GET | `/api/tasks/{id}/sources` | Get visited/failed URLs and extracted records |
| GET | `/api/tasks/{id}/report` | Get the research report and ranked results |

### Create Task Request

```json
{
  "objective": "Find the best gaming laptops under 80000",
  "max_pages": 20,
  "crawl_depth": 2
}
```

Validation: `objective` must be 10-2000 characters, `max_pages` 3-100, `crawl_depth` 1-5.

### Create Task Response

```json
{
  "task_id": "uuid-string",
  "status": "pending",
  "objective": "Find the best gaming laptops under 80000",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00",
  "progress_percent": 0.0,
  "pages_crawled": 0
}
```

### Progress Response

```json
{
  "task_id": "uuid",
  "status": "running",
  "progress_percent": 45.5,
  "pages_crawled": 9,
  "candidate_urls_count": 15,
  "records_count": 5,
  "missing_fields": ["warranty", "availability"],
  "stopping_reason": null,
  "recent_urls": ["https://example.com/page1", "..."]
}
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment label |
| `APP_PORT` | `8000` | Backend port |
| `FRONTEND_URL` | `http://localhost:5173` | Frontend URL for CORS |
| `DATABASE_URL` | `sqlite:///./research.db` | SQLite or PostgreSQL URL |
| `OLLAMA_ENABLED` | `true` | Use local Ollama for LLM tasks |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Model name |
| `CLOUD_LLM_ENABLED` | `false` | Enable OpenAI-compatible cloud LLM |
| `CLOUD_LLM_BASE_URL` | `https://api.openai.com/v1` | Cloud LLM endpoint |
| `CLOUD_LLM_API_KEY` | _(empty)_ | API key (never committed to git) |
| `CLOUD_LLM_MODEL` | `gpt-4o-mini` | Cloud model name |
| `SEARCH_PROVIDER` | `duckduckgo_html` | `duckduckgo_html`, `serper`, or `none` |
| `SERPER_API_KEY` | _(empty)_ | Required if `SEARCH_PROVIDER=serper` |
| `DEFAULT_MAX_PAGES` | `20` | Default crawl budget |
| `DEFAULT_CRAWL_DEPTH` | `2` | Max link-following depth |
| `DEFAULT_REQUEST_TIMEOUT` | `15` | HTTP timeout in seconds |
| `DEFAULT_MAX_RESPONSE_SIZE_KB` | `2048` | Max response size |
| `DEFAULT_RATE_LIMIT_DELAY` | `1.5` | Seconds between requests to same domain |
| `EXTRA_BLOCKED_DOMAINS` | _(empty)_ | Comma-separated additional blocked domains |
| `PLAYWRIGHT_ENABLED` | `false` | Enable JS rendering (not installed by default) |

---

## LLM Configuration

### Ollama (local, free, recommended for academic use)

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull llama3.2`
3. Ensure `.env` has `OLLAMA_ENABLED=true` and `OLLAMA_MODEL=llama3.2`
4. The system automatically uses Ollama for planning, extraction, and report generation

### Cloud LLM (optional, requires API key)

1. Set `CLOUD_LLM_ENABLED=true` in `.env`
2. Set `CLOUD_LLM_API_KEY` to your key (never commit this to git)
3. Set `CLOUD_LLM_MODEL` to your model (e.g., `gpt-4o-mini`)
4. Cloud LLM is used as a fallback when Ollama is unavailable

### No LLM available

The system works entirely without any LLM. The planner uses keyword-based field inference, the extractor uses regex patterns for prices and ratings, and the reporter uses template-based summaries. Quality is lower but all features function.

---

## Security

- **SSRF protection**: Blocks requests to localhost, loopback IPs, private ranges (10.x, 172.16-31.x, 192.168.x, 169.254.x, 0.0.0.0/8), and AWS/cloud metadata endpoints. DNS resolution is checked before fetching.
- **Redirect safety**: Final URL after redirects is re-validated against the SSRF blocklist.
- **robots.txt**: Respected per-domain with caching.
- **Rate limiting**: Configurable delay per domain prevents hammering servers.
- **Response size limits**: Responses are truncated to prevent memory exhaustion.
- **No secrets in code**: API keys are loaded from environment variables via `.env` (which is gitignored).
- **Input validation**: All API requests are validated by Pydantic models with length and range constraints.
- **Content safety**: Webpage content is treated as untrusted data and never executed as instructions.

---

## Testing

```
cd backend
python -m pytest tests/ -v
```

**91 tests** cover:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_api.py` | 9 | API endpoints, validation, 404/422 errors |
| `test_crawler.py` | 8 | SSRF protection, scheme blocking, private IP blocking |
| `test_discovery.py` | 18 | URL normalisation, link extraction, link relevance scoring |
| `test_evaluator.py` | 14 | Relevance, freshness, coverage, duplicates, stop criteria, reliability |
| `test_extractor.py` | 13 | HTML cleaning, date extraction, fallback extraction |
| `test_planner.py` | 6 | Deterministic planner structure, constraints, fields, queries |
| `test_ranking.py` | 7 | Ranking count, sequential ranks, descending scores, breakdown, explanation |
| `test_reporter.py` | 16 | Fallback summary, findings, comparison table, full report generation |

Quick smoke test (no pytest needed):
```
python check.py
```

Live API test (requires running backend):
```
cd backend
python api_test.py
```

---

## Known Limitations

- Works best with public, freely accessible web pages.
- JavaScript-heavy single-page apps require Playwright (`PLAYWRIGHT_ENABLED=true`) which is not installed by default.
- The DuckDuckGo HTML search provider may return fewer results or be temporarily blocked under heavy use.
- DNS rebinding attacks could theoretically bypass the SSRF check (the check resolves DNS, but httpx does its own resolution). This is a known limitation documented in security literature.
- The content hash duplicate detection uses the first 500 characters of cleaned text, which may miss duplicates with different introductory text.
- `datetime.utcnow()` is used in several places and is deprecated in Python 3.12+ (still functional, produces warnings).
- The system does not bypass paywalls, CAPTCHAs, or authentication.

---

## Academic Q&A

### Q: What makes this system "agentic" rather than a simple crawler?

A: The agent adapts its behaviour based on what it has already found. The `_reprioritise_queue` function reorders the URL queue based on missing fields and domain diversity. The `should_stop` function uses adaptive criteria (not just a fixed page count). The evaluator detects conflicts and missing information, which influences which URLs are prioritised next.

### Q: How does the ranking algorithm work?

A: Each record gets a weighted score across five dimensions: relevance (keyword overlap with topic), source reliability (domain-based heuristic), freshness (publication date age), completeness (fraction of required fields found), and constraint match (how well content matches explicit constraints like price). Weights default to 0.30/0.20/0.15/0.25/0.10 but are adjusted based on the plan's ranking priorities. Penalties are applied for very short content and missing dynamic fields.

### Q: What happens when the LLM is unavailable?

A: Every LLM-dependent function has a deterministic fallback: the planner uses keyword-based field inference, the extractor uses regex patterns for prices and ratings, and the reporter uses template-based summaries. The system degrades gracefully rather than failing.

### Q: How is SSRF prevented?

A: The `_is_safe_url` function checks the URL scheme (only http/https allowed), checks the hostname against a domain blocklist (localhost, 127.0.0.1, metadata endpoints, etc.), resolves the hostname via DNS, and checks if the resulting IP falls in private/reserved ranges. After redirects, the final URL is re-checked.

### Q: How are duplicates detected?

A: Two methods: URL comparison (case-insensitive, trailing slash normalised) and content hash (SHA-256 of the first 500 characters of cleaned text). If either matches an existing record, it's considered a duplicate.

### Q: What database is used and why?

A: SQLite via aiosqlite (async driver) by default. Each task stores its plan, crawl state, and report as JSON blobs in a single table. This keeps the schema simple while supporting complex nested data. PostgreSQL can be used by changing `DATABASE_URL`.

### Q: How does the crawl loop decide to stop?

A: Four stopping criteria: (1) page budget reached, (2) sufficient records with good coverage and no missing fields, (3) no more candidate URLs in the queue, (4) diminishing returns (last 5 pages all had relevance < 0.15).

### Q: What is the role of the ResearchPlan?

A: The plan is the central data structure that guides the entire research. It defines what fields to extract, what search queries to run, what sources to prioritise, how to rank results, and when to stop. It's generated once at the start and referenced throughout the pipeline.

### Q: How does the frontend communicate with the backend?

A: The Vite dev server proxies `/api` and `/health` requests to the backend on port 8000 (configured in `vite.config.js`). The frontend polls progress every 4 seconds while a task is active. CORS is configured on the backend to allow the frontend origin.

### Q: What are the key design trade-offs?

A: (1) JSON blobs in SQLite vs. normalised tables — simpler schema but harder to query. (2) Single-file modules vs. packages — simpler for an academic project but doesn't scale. (3) DuckDuckGo HTML scraping vs. search API — free but fragile. (4) Deterministic fallback quality — ensures functionality but produces lower-quality results than LLM.
