# Autonomous Agentic Web Research & Crawling System

An AI-powered system that converts natural-language research goals into adaptive web crawling strategies, extracts structured evidence, ranks results, and generates evidence-grounded research reports.

---

## Quick Start

### 1. Copy the environment file
```
copy .env.example .env
```
Edit `.env` if you want to enable Ollama, change the search provider, or adjust limits.

### 2. Start the backend
```
start_backend.bat
```
Or manually:
```
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start the frontend (separate terminal)
```
start_frontend.bat
```
Or manually:
```
cd frontend
npm run dev
```

### 4. Open the app
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
    └── schemas.py       ← Pydantic models
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_ENABLED` | `true` | Use local Ollama for LLM tasks |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Model name (any Ollama-supported model) |
| `SEARCH_PROVIDER` | `duckduckgo_html` | `duckduckgo_html`, `serper`, or `none` |
| `SERPER_API_KEY` | _(empty)_ | Required if `SEARCH_PROVIDER=serper` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./research.db` | Switch to PostgreSQL URL for production |
| `DEFAULT_MAX_PAGES` | `20` | Default crawl budget per task |
| `DEFAULT_CRAWL_DEPTH` | `2` | Max link-following depth |
| `DEFAULT_RATE_LIMIT_DELAY` | `1.5` | Seconds between requests to the same domain |
| `CLOUD_LLM_ENABLED` | `false` | Enable OpenAI-compatible cloud LLM fallback |
| `CLOUD_LLM_API_KEY` | _(empty)_ | API key for cloud LLM |

---

## LLM / AI Behaviour

- **Ollama available**: Planning, field extraction, and report generation use the configured local model.
- **Ollama unavailable**: The system uses a deterministic keyword-based planner and pattern-based extractor. All features work; quality is lower.
- **Cloud LLM**: Set `CLOUD_LLM_ENABLED=true` and supply `CLOUD_LLM_API_KEY` for OpenAI-compatible endpoints.

---

## Search Provider Notes

| Provider | Setup needed | Notes |
|---|---|---|
| `duckduckgo_html` | None | Scrapes DDG HTML results. No API key. May be rate-limited under heavy use. |
| `serper` | `SERPER_API_KEY` | Reliable Google results via Serper.dev. Free tier available. |
| `none` | — | Disables web search. No URLs will be discovered. |

---

## Running Tests

```
cd backend
python -m pytest tests/ -v
```

**45 tests** cover: planner (deterministic + LLM), SSRF/crawl safety, evaluator (relevance, freshness, coverage, duplicates, stop criteria), ranking, and API integration.

---

## Security

- **SSRF protection**: Blocks requests to localhost, loopback IPs, private ranges (10.x, 172.16–31.x, 192.168.x), and AWS metadata endpoint.
- **robots.txt**: Respected per-domain.
- **Rate limiting**: Configurable delay per domain.
- **Content safety**: Webpage content is treated as untrusted data. It is never executed as agent instructions.
- **No auth bypass**: The system will not attempt to bypass paywalls, CAPTCHAs, or authentication.

---

## Limitations

- Works best with public, freely accessible web pages.
- JavaScript-heavy single-page apps require Playwright (`PLAYWRIGHT_ENABLED=true`) — not installed by default because it requires C++ build tools on Windows.
- The DuckDuckGo HTML search provider may return fewer results during periods of high scraping traffic.
- Python 3.14 is used; `lxml` is not yet available for it, so `html.parser` (stdlib) is used instead.
- Results and reports are only as good as the publicly available sources found.

---

## Project Structure

```
AI/
├── backend/
│   ├── main.py, agent.py, planner.py, ...  ← Python backend
│   ├── tests/                               ← pytest suite (45 tests)
│   └── requirements.txt
├── frontend/                                ← React app
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       ├── pages/
│       │   ├── Dashboard.jsx
│       │   └── TaskDetail.jsx
│       └── components/
│           ├── ResearchForm.jsx
│           ├── StatusBadge.jsx
│           ├── ProgressBar.jsx
│           └── Icons.jsx
├── .env.example
├── .gitignore
├── start_backend.bat
├── start_frontend.bat
└── README.md
```
