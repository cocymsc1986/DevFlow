import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import init_db, get_db, SessionLocal, Issue, PipelineRun, AgentStep
from github_client import GitHubClient
from pipeline import Pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _resume_interrupted_pipelines():
    """Re-enqueue any issues that were running when the server last stopped."""
    db = SessionLocal()
    try:
        stuck = db.query(Issue).filter(Issue.status == "running").all()
        for issue in stuck:
            logger.info("Resuming interrupted pipeline for issue %s: %s", issue.id, issue.title)
            issue.status = "pending"
            db.commit()
            asyncio.create_task(_run_pipeline_task(issue.id))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await _resume_interrupted_pipelines()
    yield


app = FastAPI(title="DevFlow", lifespan=lifespan)

_frontend_url = os.getenv("FRONTEND_URL", "")
_origins = ["http://localhost:5173", "http://localhost:3000"]
if _frontend_url:
    _origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active: dict[int, list[WebSocket]] = {}

    async def connect(self, issue_id: int, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(issue_id, []).append(ws)

    def disconnect(self, issue_id: int, ws: WebSocket):
        if issue_id in self.active:
            try:
                self.active[issue_id].remove(ws)
            except ValueError:
                pass

    async def broadcast(self, issue_id: int, event: dict):
        connections = self.active.get(issue_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception as e:
                logger.debug("WebSocket send failed for issue %s: %s", issue_id, e)
                dead.append(ws)
        for ws in dead:
            try:
                self.active[issue_id].remove(ws)
            except ValueError:
                pass


manager = ConnectionManager()


async def _run_pipeline_task(issue_id: int):
    """Run the pipeline for an issue as a standalone async task."""
    pipeline_db = SessionLocal()
    try:
        pipeline = Pipeline(db=pipeline_db, broadcast=manager.broadcast)
        await pipeline.run(issue_id)
    except Exception as e:
        logger.exception("Pipeline task failed for issue %s: %s", issue_id, e)
    finally:
        pipeline_db.close()


# Pydantic models
class IssueCreate(BaseModel):
    title: str
    description: str
    issue_type: str = "feature"
    has_ui: bool = False
    github_repo: Optional[str] = None


def serialize_step(step: AgentStep) -> dict:
    return {
        "id": step.id,
        "agent_name": step.agent_name,
        "agent_label": step.agent_label,
        "step_number": step.step_number,
        "status": step.status,
        "input_data": json.loads(step.input_data) if step.input_data else None,
        "output_data": json.loads(step.output_data) if step.output_data else None,
        "model_used": step.model_used,
        "tokens_used": step.tokens_used,
        "error_message": step.error_message,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "duration_seconds": step.duration_seconds,
    }


def serialize_run(run: PipelineRun) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "agent_steps": [serialize_step(s) for s in sorted(run.agent_steps, key=lambda x: x.step_number)],
    }


def serialize_issue(issue: Issue, full: bool = False) -> dict:
    data = {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "issue_type": issue.issue_type,
        "has_ui": issue.has_ui,
        "status": issue.status,
        "github_repo": issue.github_repo,
        "github_pr_url": issue.github_pr_url,
        "github_branch": issue.github_branch,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }
    if full:
        data["pipeline_runs"] = [serialize_run(r) for r in sorted(issue.pipeline_runs, key=lambda x: x.id)]
    return data


# Routes

@app.get("/health")
def health():
    github = GitHubClient()
    return {"status": "ok", "github_configured": github.is_configured}


@app.get("/github/info")
def github_info():
    github = GitHubClient()
    if not github.is_configured:
        return {"configured": False}
    info = github.get_repo_info()
    return info


@app.get("/github/repos")
def github_repos():
    github = GitHubClient()
    return github.list_repos()


@app.post("/issues", status_code=201)
async def create_issue(body: IssueCreate, db: Session = Depends(get_db)):
    issue = Issue(
        title=body.title,
        description=body.description,
        issue_type=body.issue_type,
        has_ui=body.has_ui,
        status="pending",
        github_repo=body.github_repo,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    asyncio.create_task(_run_pipeline_task(issue.id))

    return serialize_issue(issue)


@app.get("/issues")
def list_issues(db: Session = Depends(get_db)):
    issues = db.query(Issue).order_by(Issue.created_at.desc()).all()
    result = []
    for issue in issues:
        data = serialize_issue(issue)
        # Include sizing from latest run if available
        latest_run = max(issue.pipeline_runs, key=lambda r: r.id, default=None)
        if latest_run:
            for step in latest_run.agent_steps:
                if step.agent_name == "sizing" and step.output_data:
                    try:
                        sizing = json.loads(step.output_data)
                        data["size"] = sizing.get("size")
                    except Exception:
                        pass
        result.append(data)
    return result


@app.get("/issues/{issue_id}")
def get_issue(issue_id: int, db: Session = Depends(get_db)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return serialize_issue(issue, full=True)


@app.post("/issues/{issue_id}/retry")
async def retry_issue(issue_id: int, db: Session = Depends(get_db)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = "pending"
    issue.github_pr_url = None
    issue.github_branch = None
    issue.updated_at = datetime.utcnow()
    db.commit()

    asyncio.create_task(_run_pipeline_task(issue_id))
    return {"status": "retrying", "issue_id": issue_id}


@app.delete("/issues/{issue_id}", status_code=204)
def delete_issue(issue_id: int, db: Session = Depends(get_db)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running issue")
    db.delete(issue)
    db.commit()


@app.post("/issues/{issue_id}/rerun")
async def rerun_issue(issue_id: int, db: Session = Depends(get_db)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status == "running":
        raise HTTPException(status_code=409, detail="Issue is already running")

    issue.status = "pending"
    issue.github_pr_url = None
    issue.github_branch = None
    issue.updated_at = datetime.utcnow()
    db.commit()

    asyncio.create_task(_run_pipeline_task(issue_id))
    return {"status": "rerunning", "issue_id": issue_id}


@app.websocket("/ws/{issue_id}")
async def websocket_endpoint(issue_id: int, ws: WebSocket):
    await manager.connect(issue_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(issue_id, ws)
