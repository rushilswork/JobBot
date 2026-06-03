"""FastAPI backend for the JobBot dashboard."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Job, Company, JobStatus, get_session, init_db, mark_job
from src.background import ensure_running, get_status, trigger_now, get_progress, stop_discovery
from src.utils import load_config
from src.auth import init_users, get_current_user, require_admin
from src.auth_routes import router as auth_router

FRONTEND       = PROJECT_ROOT / "dashboard" / "index.html"
CONFIG_YAML = PROJECT_ROOT / "config" / "config.yaml"

app = FastAPI(title="JobBot API")
app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    from src.utils import log
    log.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.on_event("startup")
def startup():
    init_db()
    init_users()
    # Reset stale running state from previous session
    from src.background import _write_state
    _write_state({"status": "idle", "error": None})
    # New tab filtering is handled by scan timestamp — no status changes needed on startup


# ── Frontend ──────────────────────────────────────────────────────────────
LOGIN  = PROJECT_ROOT / "dashboard" / "login.html"
HOME   = PROJECT_ROOT / "dashboard" / "home.html"
SIGNUP = PROJECT_ROOT / "dashboard" / "signup.html"

@app.get("/login")
def serve_login():
    return FileResponse(str(LOGIN))

@app.get("/signup")
def serve_signup():
    return FileResponse(str(SIGNUP))

@app.get("/")
def serve_home():
    return FileResponse(str(HOME))

@app.get("/dashboard")
def serve_frontend(request: Request):
    from fastapi.responses import RedirectResponse
    from src.auth import decode_token
    token = request.cookies.get("access_token")
    try:
        if token:
            decode_token(token)
            return FileResponse(str(FRONTEND))
    except Exception:
        pass
    return RedirectResponse(url="/login", status_code=302)




@app.post("/auth/signup")
def public_signup(body: dict):
    """Public signup — creates account. First user gets admin role, subsequent get viewer."""
    from src.auth import create_user, list_users
    from pydantic import BaseModel
    username = body.get("username","").strip()
    password = body.get("password","")
    if not username or not password:
        raise HTTPException(400, "Username and password required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    users = list_users()
    if not users:
        # First user — becomes admin
        role = "admin"
    else:
        # Check if any admin already exists — if yes, block public signup
        has_admin = any(u["role"] == "admin" for u in users)
        if has_admin:
            raise HTTPException(403, "Signup is disabled. Ask an admin to create your account.")
        role = "viewer"
    try:
        create_user(username, password, role)
        return {"ok": True, "role": role}
    except ValueError as e:
        raise HTTPException(400, str(e))

# ── Stats ─────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats(current_user: dict = Depends(get_current_user)):
    session = get_session()
    try:
        jobs = session.query(Job).filter(Job.discovered_by == current_user["username"]).all()
        counts = {s: 0 for s in ["new", "reviewed", "applied", "skipped", "failed"]}
        for j in jobs:
            if j.status in counts:
                counts[j.status] += 1
        counts["total"] = len(jobs)
        return counts
    finally:
        session.close()


# ── Discovery control ─────────────────────────────────────────────────────
@app.get("/api/discovery/status")
def discovery_status(current_user: dict = Depends(get_current_user)):
    return get_status()

@app.get("/api/discovery/progress")
def discovery_progress(current_user: dict = Depends(get_current_user)):
    return get_progress()

@app.post("/api/discovery/trigger")
def discovery_trigger(current_user: dict = Depends(get_current_user)):
    trigger_now(triggered_by=current_user["username"])
    return {"ok": True}

@app.post("/api/discovery/stop")
def discovery_stop(current_user: dict = Depends(get_current_user)):
    stop_discovery()
    return {"ok": True}

@app.post("/api/discovery/start")
def discovery_start(current_user: dict = Depends(get_current_user)):
    config = load_config()
    trigger_now(triggered_by=current_user["username"])
    ensure_running(interval_minutes=config.get("check_interval_minutes", 60))
    return {"ok": True}

@app.get("/api/discovery/stream")
async def discovery_stream(current_user: dict = Depends(get_current_user)):
    async def event_gen():
        sent = 0
        last_status_json = ""
        try:
            while True:
                progress = get_progress()
                for entry in progress[sent:]:
                    yield f"data: {json.dumps(entry)}\n\n"
                sent = len(progress)
                status = get_status()
                status_json = json.dumps(status)
                if status_json != last_status_json:
                    yield f"event: status\ndata: {status_json}\n\n"
                    last_status_json = status_json
                await asyncio.sleep(1.5)
        except asyncio.CancelledError:
            pass
    return StreamingResponse(event_gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ── Jobs ──────────────────────────────────────────────────────────────────
@app.get("/api/jobs")
def list_jobs(
    current_user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    mode: Optional[str] = None,
    portal: Optional[str] = None,
    search: Optional[str] = None,
    location: Optional[str] = None,
):
    if search:
        search = search.strip()[:200]

    def _mode(job):
        if job.notes and "work_mode:" in job.notes:
            return job.notes.split("work_mode:")[-1].strip().split()[0]
        return "unknown"

    session = get_session()
    try:
        q = session.query(Job).join(Company).filter(Job.discovered_by == current_user["username"])
        if status == "all_new":
            # Inbox: all new status jobs regardless of scan timestamp
            q = q.filter(Job.status == "new")
        elif status and status != "all":
            q = q.filter(Job.status == status)
            if status == "new":
                from datetime import timedelta
                from src.background import _read_state
                state = _read_state()
                scan_ts = state.get("last_scan_completed_at")
                if scan_ts:
                    try:
                        cutoff = datetime.fromisoformat(scan_ts)
                    except Exception:
                        cutoff = datetime.utcnow() - timedelta(hours=24)
                else:
                    cutoff = datetime.utcnow() - timedelta(hours=24)
                q = q.filter(Job.discovered_at >= cutoff)
        jobs = q.order_by(Job.discovered_at.desc()).limit(2000).all()
        result = []
        for j in jobs:
            work_mode = _mode(j)
            if mode and mode != "all" and work_mode != mode:
                continue
            if portal and portal != "all" and j.portal != portal:
                continue
            if location and location != "all":
                if location.lower() not in (j.location or "").lower():
                    continue
            if search:
                s = search.lower()
                if s not in j.title.lower() and s not in j.company.name.lower() and s not in (j.location or "").lower():
                    continue
            result.append({
                "id": j.id, "title": j.title, "company": j.company.name,
                "location": j.location or "", "portal": j.portal, "status": j.status,
                "work_mode": work_mode, "job_url": j.job_url,
                "discovered_at": j.discovered_at.isoformat() if j.discovered_at else None,
                "applied_at": j.applied_at.isoformat() if j.applied_at else None,
                "posted_at": j.posted_at.isoformat() if j.posted_at else None,
                "description": (j.description or "")[:600],
                "cover_letter": j.cover_letter or "",
            })
        return result
    finally:
        session.close()


class StatusUpdate(BaseModel):
    status: str

ALLOWED_STATUSES = ["new","reviewed","applied","skipped","failed"]

@app.delete("/api/jobs/purge-suspicious")
def purge_suspicious_jobs(current_user: dict = Depends(require_admin)):
    import re
    SUSPICIOUS = re.compile(
        r"\b(experience must|banking experience|insurance experience|years exp|notice period|"
        r"immediate joiner|serve notice|product based company|client hiring|mnc hiring|"
        r"hiring for|urgent requirement|walk[\s-]?in|staffing|recruitment agency|domain experience)\b",
        re.IGNORECASE)
    session = get_session()
    try:
        jobs = session.query(Job).filter(
            Job.status == "new",
            Job.discovered_by == current_user["username"]
        ).all()
        deleted = 0
        for j in jobs:
            if SUSPICIOUS.search(j.title or ""):
                session.delete(j); deleted += 1
        session.commit()
        return {"deleted": deleted}
    finally:
        session.close()

@app.delete("/api/jobs/clear-all")
def clear_all_jobs(current_user: dict = Depends(require_admin)):
    session = get_session()
    try:
        deleted = session.query(Job).filter(Job.discovered_by == current_user["username"]).delete()
        session.commit()
        trigger_now(triggered_by=current_user["username"])
        from src.background import _write_state
        _write_state({"last_new_count": 0})
        return {"deleted": deleted}
    finally:
        session.close()

@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, body: StatusUpdate, current_user: dict = Depends(get_current_user)):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {ALLOWED_STATUSES}")
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.discovered_by != current_user["username"]:
            raise HTTPException(403, "Forbidden")
        kwargs = {}
        if body.status == "reviewed":
            kwargs["reviewed_at"] = datetime.utcnow()
        elif body.status == "applied":
            kwargs["applied_at"] = datetime.utcnow()
            # Save previous status for undo
            prev = job.status
            notes = job.notes or ""
            import re
            if "prev_status:" in notes:
                notes = re.sub(r'prev_status:\w+', f'prev_status:{prev}', notes)
            else:
                notes = (notes + f" prev_status:{prev}").strip()
            kwargs["notes"] = notes
        elif body.status == "skipped":
            # Save previous status so we can restore later
            prev = job.status
            notes = job.notes or ""
            if "prev_status:" in notes:
                import re
                notes = re.sub(r'prev_status:\w+', f'prev_status:{prev}', notes)
            else:
                notes = (notes + f" prev_status:{prev}").strip()
            kwargs["notes"] = notes
        mark_job(session, job_id, body.status, **kwargs)
        return {"ok": True}
    finally:
        session.close()


# ── Resume parsing ────────────────────────────────────────────────────────
@app.post("/api/resume/parse")
async def parse_resume(request: Request, current_user: dict = Depends(get_current_user)):
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No file uploaded")
    content = await file.read()
    filename = file.filename.lower()
    text = ""
    import io, re
    try:
        if filename.endswith(".pdf"):
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        elif filename.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            text = content.decode("utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(500, "Could not parse resume file — ensure it is a valid PDF, DOCX, or TXT")
    SKILLS = ["python","java","javascript","typescript","golang","rust","c++","c#","kotlin","swift",
        "scala","react","vue","angular","next.js","node.js","django","flask","fastapi","spring",
        "sql","postgresql","mysql","mongodb","redis","elasticsearch","kafka","cassandra","dynamodb",
        "aws","gcp","azure","docker","kubernetes","terraform","ci/cd","machine learning","deep learning",
        "nlp","natural language processing","artificial intelligence","pytorch","tensorflow",
        "scikit-learn","pandas","numpy","spark","rest api","graphql","microservices","system design",
        "distributed systems","data structures","algorithms","linux","git","llm","transformers"]
    lo = text.lower()
    found = [s for s in SKILLS if re.search(r'\b' + re.escape(s) + r'\b', lo)]
    return {"skills": found, "char_count": len(text)}


# ── AI Search ─────────────────────────────────────────────────────────────
class AISearchBody(BaseModel):
    query: str
    top_n: int = 50

@app.post("/api/search/ai")
def ai_search_endpoint(body: AISearchBody, current_user: dict = Depends(get_current_user)):
    from src.ai_search import ai_search
    query = body.query.strip()[:500]
    if not query:
        raise HTTPException(400, "Query cannot be empty")
    session = get_session()
    try:
        jobs = session.query(Job).join(Company).filter(
            Job.discovered_by == current_user["username"]
        ).order_by(Job.discovered_at.desc()).limit(2000).all()
        def _mode(job):
            if job.notes and "work_mode:" in job.notes:
                return job.notes.split("work_mode:")[-1].strip().split()[0]
            return "unknown"
        job_dicts = [{"id":j.id,"title":j.title,"company":j.company.name,"location":j.location or "",
            "portal":j.portal,"status":j.status,"work_mode":_mode(j),"job_url":j.job_url,
            "discovered_at":j.discovered_at.isoformat() if j.discovered_at else None,
            "description":(j.description or "")[:600],"cover_letter":j.cover_letter or ""} for j in jobs]
    finally:
        session.close()
    results = ai_search(job_dicts, query, top_n=min(body.top_n, 100))
    return {"query": query, "results": results, "total": len(results)}


# ── Config management ─────────────────────────────────────────────────────
@app.get("/api/config")
def get_config(current_user: dict = Depends(get_current_user)):
    with open(CONFIG_YAML) as f:
        cfg = yaml.safe_load(f)
    return {"keywords": cfg.get("filters",{}).get("keywords",[]),
            "locations": cfg.get("filters",{}).get("locations",[]),
            "portals":   cfg.get("portals",{})}

class ConfigUpdate(BaseModel):
    keywords:  list[str] | None = None
    locations: list[str] | None = None
    portals:   dict | None = None

@app.patch("/api/config")
def update_config(body: ConfigUpdate, current_user: dict = Depends(require_admin)):
    with open(CONFIG_YAML) as f:
        cfg = yaml.safe_load(f)
    if body.keywords is not None:
        cfg.setdefault("filters",{})["keywords"] = [k.strip() for k in body.keywords if k.strip()]
    if body.locations is not None:
        cfg.setdefault("filters",{})["locations"] = [l.strip() for l in body.locations if l.strip()]
    if body.portals is not None:
        cfg["portals"] = body.portals
    with open(CONFIG_YAML, "w") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
    return {"ok": True}


@app.delete("/api/jobs/clear-only")
def clear_jobs_only(current_user: dict = Depends(require_admin)):
    """Delete all jobs without triggering a rescan."""
    session = get_session()
    try:
        deleted = session.query(Job).filter(Job.discovered_by == current_user["username"]).delete()
        session.commit()
        return {"deleted": deleted}
    finally:
        session.close()
