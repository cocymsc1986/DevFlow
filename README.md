# DevFlow

A fully agentic developer pipeline. Submit an issue, watch 9 AI agents process it in real-time — from intake through coding, PR creation, and human escalation.

## Stack

- **Backend**: Python, FastAPI, SQLite, Anthropic SDK, PyGithub
- **Frontend**: React, Vite, Tailwind CSS
- **Realtime**: WebSockets

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
| `GH_TOKEN` | No | GitHub personal access token |
| `GH_OWNER` | No | GitHub username or org |
| `DATABASE_URL` | No | SQLite path (default: `sqlite:///./devflow.db`) |

## Agent Pipeline

| Step | Agent | Model | Job |
|---|---|---|---|
| 1 | Issue Intake | Haiku | Normalise raw issue |
| 2 | Assessment & Refinement | Sonnet | Engineering specification |
| 3 | Refinement Review | Sonnet | Second-opinion review |
| 4 | Design Input | Sonnet | UX/UI guidance (if `has_ui`) |
| 5 | Sizing & Estimation | Haiku | XS/S/M/L/XL complexity |
| 6 | Model Router | Haiku | Select models for coding/review |
| 7 | Coding Agent | Router-selected | Full implementation |
| 8 | PR Review | Router-selected | Code review |
| 9 | Human Escalation | Haiku | Human-readable summary |

## API Endpoints

```
GET  /health
GET  /github/info
GET  /github/repos
POST /issues
GET  /issues
GET  /issues/{id}
POST /issues/{id}/retry
WS   /ws/{issue_id}
```
