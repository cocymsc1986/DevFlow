# DevFlow — Agent Guide

## What This Is

A fully agentic developer pipeline. Users submit issues through a web UI; a chain of AI agents process them in real-time across ten sequential stages (intake → coding → PR creation → QA → human escalation). Built with FastAPI + React + SQLite + Anthropic SDK.

## Project Structure

```
backend/
  main.py              # FastAPI app, all routes, WebSocket manager
  database.py          # SQLAlchemy models: Issue, PipelineRun, AgentStep
  pipeline.py          # Pipeline orchestration — runs the 10 stages sequentially
  observability.py     # Langfuse trace/score helpers (optional)
  github_client.py     # PyGithub wrapper: branches, file push, PR creation, workflow_dispatch
  qa_callback.py       # HMAC-authenticated /qa/callback endpoint + async coord
  qa_worker/           # QA agent package — runs in GH Actions, NOT on EC2
    __main__.py        # CLI entrypoint: python -m qa_worker
    runner.py          # LocalRunner: subprocess-based, runs on the GH runner
    boot_detector.py   # Heuristic stack detection (root + backend/frontend/apps/*)
    agent.py           # QAAgent multi-turn tool loop
    callback.py        # HMAC-signed POST helper for events back to DevFlow
  agents/
    __init__.py         # Re-exports all agent classes
    base.py             # BaseAgent: Anthropic API call, retry, JSON parse
    intake.py           # Step 1 — normalise raw issue (Haiku)
    assessment.py       # Step 2 — engineering spec (Sonnet)
    refinement_review.py # Step 3 — spec review (Sonnet)
    design.py           # Step 4 — UX/UI guidance, conditional on intake's requires_design_input (Sonnet)
    sizing.py           # Step 5 — XS/S/M/L/XL estimate (Haiku)
    router.py           # RouterAgent (LLM) — LEGACY: exported but unused; the pipeline
                        #   uses deterministic _resolve_models() for Step 6 instead
    coding.py           # Step 7 — full implementation (router-selected)
    pr_review.py        # Step 8 — code review, may REQUEST_CHANGES (router-selected)
    escalation.py       # Step 10 — human-readable summary (Haiku)
  eval/                 # Offline eval harness (cases, scorer, run.py) — see eval/README.md
  requirements.txt
  .env.example

.github/workflows/
  deploy.yml           # Push to EC2 via SSH on push to main
  qa.yml               # workflow_dispatch — boots target PR branch, runs qa_worker, posts back

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

- **Issue** — `id, title, description, issue_type, has_ui, status, github_repo, github_pr_url, github_branch, github_error, created_at, updated_at`
  - `status`: `pending` | `running` | `awaiting_review` | `failed` | `cancelled`
  - `pipeline_runs` relationship with `cascade="all, delete-orphan"`

- **PipelineRun** — `id, issue_id (FK), status, started_at, completed_at`
  - `status`: `running` | `completed` | `failed` | `cancelled`
  - `agent_steps` relationship with `cascade="all, delete-orphan"`

- **AgentStep** — `id, pipeline_run_id (FK), agent_name, agent_label, step_number, status, input_data (JSON text), output_data (JSON text), model_used, tokens_used, error_message, started_at, completed_at, duration_seconds`
  - `status`: `pending` | `running` | `completed` | `skipped` | `failed` | `cancelled`

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
POST   /issues/{id}/retry         # Reset GitHub fields + re-run whole pipeline (new run)
POST   /issues/{id}/rerun         # Re-run any non-running issue through pipeline
POST   /issues/{id}/retry-stage   # Resume from a specific stage on the same run (body: stage_name)
POST   /issues/{id}/cancel        # Cancel a running/pending pipeline
DELETE /issues/{id}               # Delete issue + all pipeline data (blocked if running)
GET    /artifacts/{issue_id}/{step_id}/{path}   # Serve QA artifacts (screenshots, traces)
POST   /qa/callback/{step_id}     # HMAC-signed QA worker callback (not user-facing)
WS     /ws/{issue_id}             # Real-time agent updates
```

## Pipeline Flow (backend/pipeline.py)

Sequential 10-stage pipeline (`STAGE_ORDER`) with conditional logic:

1. **Intake** (Haiku) → normalised issue (emits `requires_design_input`)
2. **Assessment** (Sonnet) → technical spec (repo tree injected if a GitHub repo is attached)
3. **Refinement Review** (Sonnet) → spec review — **fails the pipeline if `ready_to_proceed` is false**
4. **Design** (Sonnet) → UX guidance — **skipped unless intake set `requires_design_input`** (not `has_ui`)
5. **Sizing** (Haiku) → XS/S/M/L/XL
6. **Router** (deterministic — *no LLM call*) → `_resolve_models(size)` maps size to
   `coding_model_id` + `review_model_id` via a fixed table; recorded as a `skipped` step
   whose `output_data` holds the routing result
7. **Coding** (router-selected) → implementation files (repo context fetched first)
8. **PR Review** (router-selected) → verdict: APPROVE / REQUEST_CHANGES / COMMENT
   - If REQUEST_CHANGES: revision loop (max 2), creates new coding + review steps
9. **QA** (Opus, off-box in GitHub Actions) → boots the PR build and runs adversarial probes
   - **Skipped** unless `QA_ENABLED`, PR review verdict was `APPROVE`, a GitHub branch exists,
     and `QA_WORKFLOW_REPO` + `PUBLIC_BASE_URL` are configured
   - If `QA_FAIL`: one coding + QA revision (`QA_MAX_REVISIONS = 1`)
10. **Escalation** (Haiku) → human summary

GitHub integration (optional): after step 7, pushes to branch and creates PR (push failures are
non-fatal and recorded in `github_error`). Revision loops update the same branch.

If any step fails, the pipeline halts and issue status → `failed`. On success, status →
`awaiting_review`. See `docs/ARCHITECTURE.md` for the full flow diagram, and `run_from_stage()`
for stage-level retry that reuses prior outputs.

## Agent Architecture (backend/agents/)

All agents extend `BaseAgent` in `base.py`:

- Override `get_system_prompt()` → system message string
- Override `format_input(context)` → user message string
- `parse_output(raw)` → strips markdown fences and picks the **largest** valid JSON object (models sometimes preface the real payload with analysis prose)
- `run(context)` → calls Anthropic API with retry (`MAX_RETRIES = 2`, exponential backoff); timeouts are **not** retried
- `BaseAgent.default_model` is `claude-haiku-4-5-20251001`, but most agents override it: Assessment / Refinement Review / Design / PR Review default to Sonnet, Coding defaults to Sonnet. Coding and PR Review take a model override from the deterministic router (step 6)
- Default `api_timeout`: 300s, default `max_tokens`: 8192. CodingAgent raises both per model (`CODING_MODEL_CONFIG` — up to 64000 tokens / 1200s for Opus)
- Truncation (`stop_reason == "max_tokens"`) raises by default unless `allow_truncation` is set

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
  - Actions: Cancel (while running), Re-run, per-stage Retry (`retry-stage`), Delete (with confirmation)
  - Real-time updates via WebSocket, polling fallback every 5s
- **AgentStep** — collapsible timeline entry with status, model, tokens, duration, input/output JSON
- **StatusBadge** — color-coded status indicator (pending=gray, running=amber+pulse, completed=green, failed=rose, etc.)

### WebSocket Events

Emitted from pipeline, consumed by IssueDetail:
- `pipeline_start` / `pipeline_complete` / `pipeline_error` / `pipeline_cancelled`
- `agent_start` / `agent_complete` / `agent_skipped` / `agent_error`
- `github_push_success` / `github_error` / `github_skipped` (all non-fatal)
- QA stage (rebroadcast from the off-box worker via `/qa/callback`): `qa_workflow_dispatched`,
  `qa_boot_detected`, `qa_tool_use`, `qa_finding`, `qa_complete`

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
| `GH_TOKEN` | No | GitHub PAT for PR creation + workflow_dispatch |
| `GH_OWNER` | No | GitHub username or org |
| `DATABASE_URL` | No | Default: `sqlite:///./devflow.db` |
| `FRONTEND_URL` | No | Additional CORS origin |
| `QA_ENABLED` | No | Set `true` to run the QA stage |
| `QA_WORKFLOW_REPO` | If QA enabled | `owner/name` of repo hosting `qa.yml` (this one) |
| `QA_CALLBACK_SECRET` | If QA enabled | HMAC secret — must match the GH Actions secret |
| `PUBLIC_BASE_URL` | If QA enabled | Public URL the GH runner reaches DevFlow on |

## QA Architecture

The QA stage is the only agent that runs **off** the EC2 control plane. The
worker is dispatched as a GitHub Actions `workflow_dispatch` event:

```
EC2 (pipeline)
  └─ GitHubClient.dispatch_workflow(qa.yml, inputs)
        │
        ▼
  GH Actions runner (ubuntu-latest, 30 min cap)
    ├─ checkout cocymsc1986/devflow @ main         → devflow/
    ├─ checkout target_repo @ target_branch        → target/  (persist-credentials: false)
    ├─ python -m qa_worker --source-dir target …
    │     ├─ detect boot config (backend/ → frontend/ → apps/*)
    │     ├─ run setup_cmds, boot app, health probe
    │     ├─ QAAgent multi-turn loop (read_file/bash/http/playwright/record_finding)
    │     └─ POST each event → DevFlow /qa/callback/{step_id}  (HMAC-signed)
    └─ upload qa_artifacts/ (Playwright traces, app log) as artifact (7d retention)
```

Pipeline awaits an `asyncio.Event` keyed by `step_id`; the callback handler
sets it on `qa_complete`. Hard timeout `QA_WORKFLOW_TIMEOUT_SECONDS` (default
35 min, > the workflow's own 30 min cap).

## Conventions

- Backend: Python, FastAPI, async handlers, SQLAlchemy ORM (not async), Pydantic for request validation
- Frontend: React functional components with hooks, no TypeScript, no state management library
- Styling: Tailwind utility classes + custom component classes defined in `index.css`
- Tests: `pytest` suites for the QA worker (`backend/test_qa_worker.py`), PR creation (`backend/test_pr_creation.py`), and the eval scorer (`backend/eval/test_scorer.py`). There is also an offline eval harness in `backend/eval/` (`python -m eval.run`) that scores the coding agent and PR reviewer against fixture cases without GitHub or a running server
- All agent I/O is JSON stored as text columns
- Pipeline state changes broadcast via WebSocket in real-time
- Issues cannot be edited after creation — only re-run, retried from a stage, cancelled, or deleted
