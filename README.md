# DevFlow

A fully agentic developer pipeline. Submit an issue, watch a chain of AI agents process it in real-time — from intake through coding, PR creation, QA, and human escalation.

> 📐 **Architecture & flow diagrams:** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for system context, the agent pipeline, the off-box QA flow, deployment, and the data model.

## Stack

- **Backend**: Python, FastAPI, SQLite (SQLAlchemy), Anthropic SDK, PyGithub
- **Frontend**: React, Vite, Tailwind CSS
- **Realtime**: WebSockets
- **QA**: off-box agent dispatched as a GitHub Actions workflow (see [QA flow](docs/ARCHITECTURE.md#6-qa-off-box-execution))
- **Observability**: Langfuse (optional)
- **Deploy**: GitHub Actions → EC2 (nginx + systemd), provisioned with Terraform

## Backend Setup

```bash
cd backend
cp .env.example .env
# Fill in ANTHROPIC_API_KEY (required)
# Fill in GH_TOKEN and GH_OWNER (optional — enables PR creation)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `GH_TOKEN` | No | GitHub personal access token (enables branch/PR creation + QA dispatch) |
| `GH_OWNER` | No | GitHub username or org |
| `DATABASE_URL` | No | SQLite path (default: `sqlite:///./devflow.db`) |
| `FRONTEND_URL` | No | Additional CORS origin |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | No | Enable Langfuse tracing |
| `QA_ENABLED` | No | Set `true` to run the off-box QA stage |
| `QA_WORKFLOW_REPO` | If QA enabled | `owner/name` of the repo hosting `qa.yml` |
| `QA_CALLBACK_SECRET` | If QA enabled | HMAC secret — must match the GitHub Actions secret |
| `PUBLIC_BASE_URL` | If QA enabled | Public URL the GitHub runner uses to reach DevFlow |

## Agent Pipeline

Ten sequential stages with conditional logic. Stages 7–8 are the only ones whose model is
chosen at runtime (by the deterministic router); the rest use fixed models.

| Step | Stage | Model | Job |
|---|---|---|---|
| 1 | Issue Intake | Haiku | Normalise raw issue; flag `requires_design_input` |
| 2 | Assessment & Refinement | Sonnet | Engineering specification |
| 3 | Refinement Review | Sonnet | Second-opinion review — **fails the pipeline** if the spec isn't ready |
| 4 | Design Input | Sonnet | UX/UI guidance — **skipped** unless intake set `requires_design_input` |
| 5 | Sizing & Estimation | Haiku | XS/S/M/L/XL complexity |
| 6 | Model Router | *deterministic* | Maps size → coding/review model IDs (no LLM call) |
| 7 | Coding Agent | Router-selected | Full implementation; pushes branch + opens PR |
| 8 | PR Review | Router-selected | Code review; `REQUEST_CHANGES` triggers a revision loop (max 2) |
| 9 | QA Agent | Opus (off-box) | Boots the PR build in GitHub Actions and runs adversarial probes — **skipped** unless `QA_ENABLED`, PR review `APPROVE`, and a branch exists; `QA_FAIL` triggers one revision |
| 10 | Human Escalation | Haiku | Human-readable summary |

## API Endpoints

```
GET    /health                     # { status, github_configured }
GET    /github/info
GET    /github/repos
POST   /issues                     # create issue + auto-start pipeline
GET    /issues                     # list (includes sizing from latest run)
GET    /issues/{id}                # full issue with pipeline runs + agent steps
POST   /issues/{id}/retry          # reset GitHub fields, re-run whole pipeline (new run)
POST   /issues/{id}/rerun          # re-run any non-running issue
POST   /issues/{id}/retry-stage    # resume from a specific stage on the same run
POST   /issues/{id}/cancel         # cancel a running pipeline
DELETE /issues/{id}                # delete issue + all pipeline data (blocked if running)
GET    /artifacts/{issue_id}/{step_id}/{path}   # QA artifacts (screenshots, traces)
POST   /qa/callback/{step_id}      # HMAC-signed QA worker callback
WS     /ws/{issue_id}              # real-time agent updates
```
