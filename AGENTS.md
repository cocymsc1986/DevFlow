# DevFlow — Agent Guide

## What This Is

A fully agentic developer pipeline. Users submit issues through a web UI; 9 AI agents process them in real-time (intake → coding → PR creation → human escalation). Built with FastAPI + React + SQLite + Anthropic SDK.

## Project Structure

```
backend/
  main.py              # FastAPI app, all routes, WebSocket manager
  database.py          # SQLAlchemy models: Issue, PipelineRun, AgentStep
  pipeline.py          # Pipeline orchestration — runs 9 agents sequentially
  github_client.py     # PyGithub wrapper: branches, file push, PR creation
  agents/
    __init__.py         # Re-exports all agent classes
    base.py             # BaseAgent: Anthropic API call, retry, JSON parse
    intake.py           # Step 1 — normalise raw issue (Haiku)
    assessment.py       # Step 2 — engineering spec (Sonnet)
    refinement_review.py # Step 3 — spec review (Sonnet)
    design.py           # Step 4 — UX/UI guidance, conditional on has_ui (Sonnet)
    sizing.py           # Step 5 — XS/S/M/L/XL estimate (Haiku)
    router.py           # Step 6 — pick models for coding/review (Haiku)
    coding.py           # Step 7 — full implementation (router-selected)
    pr_review.py        # Step 8 — code review, may REQUEST_CHANGES (router-selected)
    escalation.py       # Step 9 — human-readable summary (Haiku)
  requirements.txt
  .env.example

frontend/
  src/
    App.jsx             # Router: / → Dashboard, /issues/:id → IssueDetailPage
    main.jsx            # React entry point
    index.css           # Tailwind config + custom component classes (panel, btn-primary, etc.)
    api/
      client.js         # API client (fetch wrapper) + WebSocket factory
    components/
      IssueForm.jsx     # Modal for creating issues
      IssueList.jsx     # Table view of all issues on dashboard
      IssueDetail.jsx   # Issue detail page: info sidebar + pipeline audit trail
      AgentStep.jsx     # Timeline component for each agent execution
      StatusBadge.jsx   # Status-colored badge component
  package.json
  vite.config.js        # Vite dev server proxies /api → localhost:8000
  tailwind.config.js
```

## Database (SQLite + SQLAlchemy)

Three models in `backend/database.py`:

- **Issue** — `id, title, description, issue_type, has_ui, status, github_repo, github_pr_url, github_branch, created_at, updated_at`
  - `status`: `pending` | `running` | `awaiting_review` | `failed`
  - `pipeline_runs` relationship with `cascade="all, delete-orphan"`

- **PipelineRun** — `id, issue_id (FK), status, started_at, completed_at`
  - `status`: `running` | `completed` | `failed`
  - `agent_steps` relationship with `cascade="all, delete-orphan"`

- **AgentStep** — `id, pipeline_run_id (FK), agent_name, agent_label, step_number, status, input_data (JSON text), output_data (JSON text), model_used, tokens_used, error_message, started_at, completed_at, duration_seconds`
  - `status`: `pending` | `running` | `completed` | `skipped` | `failed`

Cascade deletes: deleting an Issue cascades to PipelineRun → AgentStep.

DB is initialised via `init_db()` (calls `create_all`) in the FastAPI lifespan.

## API Endpoints (backend/main.py)

```
GET    /health                    # { status, github_configured }
GET    /github/info               # Repo info (if configured)
GET    /github/repos              # List accessible repos
POST   /issues                    # Create issue + auto-start pipeline
GET    /issues                    # List all issues (includes sizing from latest run)
GET    /issues/{id}               # Full issue with pipeline_runs and agent_steps
POST   /issues/{id}/retry         # Retry failed issue pipeline
POST   /issues/{id}/rerun         # Re-run any non-running issue through pipeline
DELETE /issues/{id}               # Delete issue + all pipeline data (blocked if running)
WS     /ws/{issue_id}             # Real-time agent updates
```

## Pipeline Flow (backend/pipeline.py)

Sequential 9-step pipeline with conditional logic:

1. **Intake** (Haiku) → normalised issue
2. **Assessment** (Sonnet) → technical spec
3. **Refinement Review** (Sonnet) → spec review
4. **Design** (Sonnet) → UX guidance — **skipped if `has_ui=false`**
5. **Sizing** (Haiku) → XS/S/M/L/XL
6. **Router** (Haiku) → selects `coding_model_id` + `review_model_id`
7. **Coding** (router-selected) → implementation files
8. **PR Review** (router-selected) → verdict: APPROVE / REQUEST_CHANGES / COMMENT
   - If REQUEST_CHANGES: revision loop (max 2), creates new coding + review steps
9. **Escalation** (Haiku) → human summary

GitHub integration (optional): after step 7, pushes to branch and creates PR. Revision loop updates the branch.

If any step fails, the pipeline halts and issue status → `failed`.

## Agent Architecture (backend/agents/)

All agents extend `BaseAgent` in `base.py`:

- Override `get_system_prompt()` → system message string
- Override `format_input(context)` → user message string
- `parse_output(raw)` → strips markdown fences, parses JSON
- `run(context)` → calls Anthropic API with retry (3 attempts, exponential backoff)
- Default model: `claude-haiku-4-5-20251001`; CodingAgent and PRReviewAgent accept model override from RouterAgent
- API timeout: 120s, max_tokens: 8192

## Frontend Architecture

- **React 18** + **React Router** (two routes: `/` and `/issues/:id`)
- **Vite** dev server on port 5173, proxies `/api` → `http://localhost:8000`
- **Tailwind CSS** dark theme with CSS custom properties (`--bg-base`, `--bg-surface`, `--text-primary`, `--accent`, etc.)
- Custom CSS component classes in `index.css`: `.panel`, `.panel-elevated`, `.btn-primary`, `.btn-ghost`, `.input`, `.label`

### API Client (`frontend/src/api/client.js`)

- `request(path, options)` — fetch wrapper, prepends `/api`, throws on non-ok, handles 204 no-content
- All API methods exported as `api` object
- `createWebSocket(issueId)` — connects to `ws://localhost:8000/ws/{issueId}` (or WSS in production)

### Key Components

- **IssueForm** — modal with title, description, type dropdown, has_ui toggle, optional github_repo select
- **IssueList** — table with columns: Title, Type, Size, Status, Created, PR link; rows navigate to detail
- **IssueDetail** — two-column layout: left = issue info + actions, right = pipeline audit trail
  - Actions: Retry (failed only), Re-run (completed/failed/awaiting_review), Delete (with confirmation)
  - Real-time updates via WebSocket, polling fallback every 5s
- **AgentStep** — collapsible timeline entry with status, model, tokens, duration, input/output JSON
- **StatusBadge** — color-coded status indicator (pending=gray, running=amber+pulse, completed=green, failed=rose, etc.)

### WebSocket Events

Emitted from pipeline, consumed by IssueDetail:
- `pipeline_start` / `pipeline_complete` / `pipeline_error`
- `agent_start` / `agent_complete` / `agent_skipped` / `agent_error`
- `github_error` (non-fatal)

## Running Locally

```bash
# Backend
cd backend && pip install -r requirements.txt
cp .env.example .env   # set ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `GITHUB_TOKEN` | No | GitHub PAT for PR creation |
| `GITHUB_OWNER` | No | GitHub username or org |
| `DATABASE_URL` | No | Default: `sqlite:///./devflow.db` |
| `FRONTEND_URL` | No | Additional CORS origin |

## Conventions

- Backend: Python, FastAPI, async handlers, SQLAlchemy ORM (not async), Pydantic for request validation
- Frontend: React functional components with hooks, no TypeScript, no state management library
- Styling: Tailwind utility classes + custom component classes defined in `index.css`
- No test suite currently exists
- All agent I/O is JSON stored as text columns
- Pipeline state changes broadcast via WebSocket in real-time
- Issues cannot be edited after creation — only retried, re-run, or deleted
