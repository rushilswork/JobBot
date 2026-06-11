"""FastAPI backend for the JobBot dashboard."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Job, Company, JobStatus, UserSettings, get_session, init_db, mark_job
from src.background import ensure_running, get_status, trigger_now, get_progress, stop_discovery
from src.utils import load_config, load_profile
from src.autofill.profile_adapter import load_autofill_profile
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



@app.post("/api/discovery/pause")
def discovery_pause(current_user: dict = Depends(get_current_user)):
    stop_discovery()
    from src.background import _write_state
    _write_state({"status": "paused"})
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
        # Stop any running scan first, then reset state
        stop_discovery()
        from src.background import _write_state
        _write_state({"last_new_count": 0, "status": "idle"})
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


# ── AI Settings ───────────────────────────────────────────────────────────
from src.ai.service import GROQ_MODELS, GEMINI_MODELS, DEFAULT_MODEL

@app.get("/api/settings/ai")
def get_ai_settings(current_user: dict = Depends(get_current_user)):
    """Get current user's AI provider settings (API key masked)."""
    session = get_session()
    try:
        row = session.query(UserSettings).filter_by(username=current_user["username"]).first()
        if not row:
            return {
                "provider": "groq",
                "model": DEFAULT_MODEL["groq"],
                "api_key_set": False,
                "is_configured": False,
                "groq_models": GROQ_MODELS,
                "gemini_models": GEMINI_MODELS,
            }
        key = row.ai_api_key or ""
        configured = bool(key)
        return {
            "provider": row.ai_provider or "groq",
            "model": row.ai_model or DEFAULT_MODEL.get(row.ai_provider or "groq", ""),
            "api_key_set": configured,
            "is_configured": configured,
            "api_key_preview": (key[:8] + "..." + key[-4:]) if len(key) > 12 else ("****" if key else ""),
            "groq_models": GROQ_MODELS,
            "gemini_models": GEMINI_MODELS,
        }
    finally:
        session.close()


class AISettingsUpdate(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None

@app.put("/api/settings/ai")
def update_ai_settings(body: AISettingsUpdate, current_user: dict = Depends(get_current_user)):
    """Save AI provider settings for this user."""
    if body.provider not in ("groq", "gemini"):
        raise HTTPException(400, "Provider must be 'groq' or 'gemini'")
    session = get_session()
    try:
        row = session.query(UserSettings).filter_by(username=current_user["username"]).first()
        if not row:
            row = UserSettings(username=current_user["username"])
            session.add(row)
        row.ai_provider = body.provider
        if body.api_key is not None:
            row.ai_api_key = body.api_key.strip()
        if body.model is not None:
            row.ai_model = body.model.strip()
        elif row.ai_model is None or row.ai_model == "":
            row.ai_model = DEFAULT_MODEL[body.provider]
        row.updated_at = datetime.utcnow()
        session.commit()
        configured = bool(row.ai_api_key)
        return {"ok": True, "is_configured": configured}
    finally:
        session.close()


@app.post("/api/settings/ai/test")
def test_ai_connection(current_user: dict = Depends(get_current_user)):
    """Quick connectivity test for the configured AI provider."""
    from src.ai.service import AIService
    try:
        ai = AIService.for_user(current_user["username"])
        if not ai.is_configured():
            return {"ok": False, "error": "No API key configured"}
        result = ai.generate("Say 'OK' and nothing else.", max_tokens=10)
        return {"ok": True, "provider": ai.provider, "model": ai.model, "response": result[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── AI Job Analysis endpoints ──────────────────────────────────────────────

def _get_job_for_user(job_id: int, username: str):
    """Helper: fetch job and validate ownership. Returns (session, job)."""
    session = get_session()
    job = session.get(Job, job_id)
    if not job:
        session.close()
        raise HTTPException(404, "Job not found")
    if job.discovered_by != username:
        session.close()
        raise HTTPException(403, "Forbidden")
    return session, job


@app.post("/api/jobs/{job_id}/match-score")
def job_match_score(job_id: int, current_user: dict = Depends(get_current_user)):
    """AI-powered match score for this job vs. the user's profile."""
    from src.ai.service import AIService
    from src.ai.generator import generate_match_score

    session, job = _get_job_for_user(job_id, current_user["username"])
    try:
        # Return cached result if present
        if job.ai_match_data:
            return json.loads(job.ai_match_data)

        profile = load_autofill_profile(current_user["username"])
        ai = AIService.for_user(current_user["username"])
        if not ai.is_configured():
            raise HTTPException(400, "AI not configured. Go to AI Settings to add your API key.")

        result = generate_match_score(
            profile=profile,
            job_title=job.title,
            company_name=job.company.name,
            job_description=job.description or "",
            resume_skills=[],
            ai=ai,
        )
        # Cache in DB
        job.ai_match_score = result.get("score", 0)
        job.ai_match_data = json.dumps(result)
        session.commit()
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Match score failed: {str(e)}")
    finally:
        session.close()


@app.post("/api/jobs/{job_id}/skill-gap")
def job_skill_gap(job_id: int, current_user: dict = Depends(get_current_user)):
    """Detailed skill gap analysis for this job."""
    from src.ai.service import AIService
    from src.ai.generator import generate_skill_gap

    session, job = _get_job_for_user(job_id, current_user["username"])
    try:
        profile = load_autofill_profile(current_user["username"])
        ai = AIService.for_user(current_user["username"])
        if not ai.is_configured():
            raise HTTPException(400, "AI not configured. Go to AI Settings to add your API key.")

        result = generate_skill_gap(
            profile=profile,
            job_title=job.title,
            company_name=job.company.name,
            job_description=job.description or "",
            resume_skills=[],
            ai=ai,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Skill gap analysis failed: {str(e)}")
    finally:
        session.close()


@app.post("/api/jobs/{job_id}/interview-prep")
def job_interview_prep(job_id: int, current_user: dict = Depends(get_current_user)):
    """Generate interview preparation questions and tips."""
    from src.ai.service import AIService
    from src.ai.generator import generate_interview_prep

    session, job = _get_job_for_user(job_id, current_user["username"])
    try:
        profile = load_autofill_profile(current_user["username"])
        ai = AIService.for_user(current_user["username"])
        if not ai.is_configured():
            raise HTTPException(400, "AI not configured. Go to AI Settings to add your API key.")

        result = generate_interview_prep(
            profile=profile,
            job_title=job.title,
            company_name=job.company.name,
            job_description=job.description or "",
            ai=ai,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Interview prep failed: {str(e)}")
    finally:
        session.close()


@app.post("/api/jobs/{job_id}/cover-letter")
def job_cover_letter(job_id: int, current_user: dict = Depends(get_current_user)):
    """Generate or regenerate a cover letter for this job."""
    from src.ai.service import AIService
    from src.ai.generator import generate_cover_letter

    session, job = _get_job_for_user(job_id, current_user["username"])
    try:
        profile = load_autofill_profile(current_user["username"])
        ai = AIService.for_user(current_user["username"])
        if not ai.is_configured():
            raise HTTPException(400, "AI not configured. Go to AI Settings to add your API key.")


        letter = generate_cover_letter(
            profile=profile,
            job_title=job.title,
            company_name=job.company.name,
            job_description=job.description or "",
            ai=ai,
        )
        job.cover_letter = letter
        session.commit()
        return {"cover_letter": letter}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Cover letter generation failed: {str(e)}")
    finally:
        session.close()


# ── Resume Parser (AI-enhanced) ────────────────────────────────────────────

@app.post("/api/resume/parse-ai")
async def parse_resume_ai(request: Request, current_user: dict = Depends(get_current_user)):
    """Parse resume with AI — returns structured profile data."""
    from src.ai.service import AIService
    import io, json as _json

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No file uploaded")

    content = await file.read()
    filename = file.filename.lower()
    text = ""
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
    except Exception:
        raise HTTPException(500, "Could not parse resume file")

    if not text.strip():
        raise HTTPException(400, "Resume appears to be empty or unreadable")

    ai = AIService.for_user(current_user["username"])
    if not ai.is_configured():
        raise HTTPException(400, "AI not configured. Set up your API key in AI Settings first.")

    prompt = f"""Extract structured information from this resume text.

Resume:
{text[:4000]}

Return a JSON object with these exact keys:
{{
  "name": "<full name>",
  "email": "<email or empty string>",
  "phone": "<phone or empty string>",
  "location": "<city, country or empty string>",
  "current_title": "<most recent job title>",
  "years_experience": <integer total years>,
  "skills": ["<skill1>", "<skill2>"],
  "top_skills": ["<5 most prominent skills>"],
  "education": {{"degree": "<degree>", "field": "<field>", "university": "<uni or empty>", "year": <year or null>}},
  "experience_summary": "<2-sentence career summary>",
  "companies": ["<company1>"],
  "certifications": ["<cert1>"]
}}"""

    try:
        result = ai.generate_json(prompt)
        session = get_session()
        try:
            row = session.query(UserSettings).filter_by(username=current_user["username"]).first()
            if not row:
                row = UserSettings(username=current_user["username"])
                session.add(row)
            row.profile_summary = _json.dumps(result)
            session.commit()
        finally:
            session.close()
        return result
    except Exception as e:
        raise HTTPException(500, f"AI resume parsing failed: {str(e)}")



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


# ── Config management ──────────────────────────────────────────────────────
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
    session = get_session()
    try:
        deleted = session.query(Job).filter(Job.discovered_by == current_user["username"]).delete()
        session.commit()
        stop_discovery()
        from src.background import _write_state
        _write_state({"last_new_count": 0, "status": "idle"})
        return {"deleted": deleted}
    finally:
        session.close()


# ── Autofill / Auto-apply ──────────────────────────────────────────────────
import threading as _threading

@app.post("/api/jobs/{job_id}/apply")
def start_apply(job_id: int, current_user: dict = Depends(get_current_user)):
    """Start autofill for a job. Generates AI content first, then launches browser."""
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.discovered_by != current_user["username"]:
            raise HTTPException(403, "Forbidden")
        job_url    = job.job_url
        job_portal = job.portal or "generic"
        job_title  = job.title
        company    = job.company.name
        description = job.description or ""
        cover_letter = job.cover_letter or ""
        screening   = job.screening_answers or ""
    finally:
        session.close()

    from src.autofill.runner import run_autofill, _sessions
    # Clear stale terminal sessions
    if job_id in _sessions:
        st = _sessions[job_id].get("result", {}).get("status", "running")
        if st in ("error", "submitted", "cancelled", "starting"):
            _sessions.pop(job_id, None)
        else:
            raise HTTPException(400, "Autofill already in progress for this job")

    username = current_user["username"]

    # Pre-register so status endpoint always has something to return
    _sessions[job_id] = {"result": {"status": "starting", "filled": [], "needs_manual": []}}

    def _run():
        from src.utils import log as _log
        from src.autofill.profile_adapter import load_autofill_profile

        try:
            profile = load_autofill_profile(username)
            job_ctx = {
                "title":        job_title,
                "company":      company,
                "description":  description,
                "cover_letter": cover_letter,
            }

            ai = None
            try:
                from src.ai.service import AIService
                from src.ai.generator import generate_cover_letter, generate_screening_answers
                _ai = AIService.for_user(username)
                if _ai.is_configured():
                    ai = _ai
                    if not cover_letter:
                        try:
                            cl = generate_cover_letter(profile, job_title, company, description, ai)
                            _save_job_field(job_id, "cover_letter", cl)
                            job_ctx["cover_letter"] = cl
                        except Exception as e:
                            _log.warning(f"Cover letter skipped: {e}")
                    if not screening:
                        try:
                            common_qs = [
                                "Are you authorized to work in India?",
                                "Are you willing to relocate?",
                                "What is your notice period?",
                                "What are your salary expectations?",
                                "How many years of experience do you have?",
                            ]
                            answers = generate_screening_answers(profile, job_title, company, common_qs, ai)
                            _save_job_field(job_id, "screening_answers", json.dumps(answers))
                        except Exception as e:
                            _log.warning(f"Screening answers skipped: {e}")
            except Exception as e:
                _log.warning(f"AI setup skipped: {e}")

            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run_autofill(
                    job_id, job_url, job_portal,
                    username=username,
                    ai=ai,
                    job_context=job_ctx,
                ))
            finally:
                loop.close()

        except Exception as e:
            _log.error(f"[Autofill] Startup error for job {job_id}: {e}")
            if job_id in _sessions:
                _sessions[job_id]["result"]["status"] = "error"
                _sessions[job_id]["result"]["error"]  = str(e)

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id, "message": "Autofill started"}


def _save_job_field(job_id: int, field: str, value: str):
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if job:
            setattr(job, field, value)
            session.commit()
    finally:
        session.close()


@app.get("/api/jobs/{job_id}/apply/status")
def apply_status(job_id: int, current_user: dict = Depends(get_current_user)):
    from src.autofill.runner import get_session as get_af_session
    af = get_af_session(job_id)
    if not af:
        return {"status": "not_started"}
    r = af.get("result", {})
    ss = r.get("screenshot_path", "")
    if ss:
        ss = "/api/screenshots/" + __import__('pathlib').Path(ss).name
    return {
        "status": r.get("status", "running"),
        "screenshot_url": ss,
        "filled": r.get("filled", []),
        "needs_manual": r.get("needs_manual", []),
        "error": r.get("error"),
    }


@app.post("/api/jobs/{job_id}/apply/confirm")
def confirm_apply(job_id: int, current_user: dict = Depends(get_current_user)):
    from src.autofill.runner import confirm_apply as _confirm
    _confirm(job_id)
    session = get_session()
    try:
        mark_job(session, job_id, "applied", applied_at=datetime.utcnow())
    finally:
        session.close()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/apply/cancel")
def cancel_apply(job_id: int, current_user: dict = Depends(get_current_user)):
    from src.autofill.runner import cancel_apply as _cancel
    _cancel(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/apply/focus")
def focus_apply_window(job_id: int, current_user: dict = Depends(get_current_user)):
    """Bring the Playwright browser window to front."""
    from src.autofill.runner import _sessions
    sess = _sessions.get(job_id)
    if not sess:
        return {"ok": False, "reason": "no_session"}
    page = sess.get("page")
    if not page:
        return {"ok": False, "reason": "no_page"}
    loop = sess.get("loop")
    if loop and loop.is_running():
        import asyncio
        asyncio.run_coroutine_threadsafe(page.bring_to_front(), loop)
        return {"ok": True}
    return {"ok": False, "reason": "loop_not_running"}


@app.get("/api/screenshots/{filename}")
def serve_screenshot(filename: str, current_user: dict = Depends(get_current_user)):
    from fastapi.responses import FileResponse as FR
    import re
    if not re.match(r'^[\w\-\.]+\.png$', filename):
        raise HTTPException(400, "Invalid filename")
    path = PROJECT_ROOT / "data" / "screenshots" / filename
    if not path.exists():
        raise HTTPException(404, "Screenshot not found")
    return FR(str(path))



# ── Profile management ────────────────────────────────────────────────────────

@app.get("/api/profile")
def get_profile(current_user: dict = Depends(get_current_user)):
    """Get the current user's job application profile."""
    session = get_session()
    try:
        row = session.query(UserSettings).filter_by(username=current_user["username"]).first()
        if not row or not row.profile_summary:
            return _default_profile()
        try:
            return json.loads(row.profile_summary)
        except Exception:
            return _default_profile()
    finally:
        session.close()


def _default_profile() -> dict:
    return {
        "personal": {"first_name": "", "last_name": "", "email": "", "phone": "",
                     "linkedin": "", "github": "", "portfolio": "", "location": ""},
        "professional": {"current_title": "", "current_company": "", "years_experience": 0,
                         "target_roles": [], "work_mode_preference": "hybrid",
                         "willing_to_relocate": False, "notice_period": "30 days"},
        "skills": {"languages": [], "frameworks": [], "tools": [], "certifications": []},
        "education": {"degree": "", "field": "", "institution": "", "year": ""},
        "answers": {"salary_expectation": "", "work_authorization": "Authorized to work in India",
                    "notice_period": "30 days", "cover_letter_tone": "professional"},
    }


@app.put("/api/profile")
def update_profile(body: dict, current_user: dict = Depends(get_current_user)):
    """Save the user's job application profile."""
    session = get_session()
    try:
        row = session.query(UserSettings).filter_by(username=current_user["username"]).first()
        if not row:
            row = UserSettings(username=current_user["username"])
            session.add(row)
        row.profile_summary = json.dumps(body)
        row.updated_at = datetime.utcnow()
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/resume/parse-profile")
async def parse_resume_for_profile(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Finest resume parser — extracts a complete profile from uploaded resume.
    Multi-strategy: pdfplumber → python-docx → raw text, then regex + AI enhancement.
    """
    import re

    content = await file.read()
    filename = file.filename or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"

    # ── 1. Text extraction ────────────────────────────────────────────────
    raw_text = ""
    try:
        if ext == "pdf":
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                raw_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        elif ext in ("doc", "docx"):
            from docx import Document
            import io as _io
            doc = Document(_io.BytesIO(content))
            raw_text = "\n".join(p.text for p in doc.paragraphs)
        else:
            raw_text = content.decode("utf-8", errors="ignore")
    except Exception as e:
        raw_text = content.decode("utf-8", errors="ignore")

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from resume")

    profile = _default_profile()

    # ── 2. Regex extraction ────────────────────────────────────────────────
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    # Name: first non-empty line that looks like a name (2-4 words, title case, no @)
    for line in lines[:8]:
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha()) and "@" not in line and not any(c.isdigit() for c in line):
            parts = line.split()
            profile["personal"]["first_name"] = parts[0]
            profile["personal"]["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
            break

    # Email
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', raw_text)
    if emails: profile["personal"]["email"] = emails[0]

    # Phone
    phones = re.findall(r'(?:\+91[\s-]?)?(?:\(?\d{3,5}\)?[\s.-]?\d{3,4}[\s.-]?\d{4})', raw_text)
    if phones: profile["personal"]["phone"] = re.sub(r'[\s.-]', '', phones[0])

    # LinkedIn
    linkedin = re.findall(r'(?:linkedin\.com/in/|linkedin\.com/pub/)([^\s/,\)]+)', raw_text, re.I)
    if linkedin: profile["personal"]["linkedin"] = f"https://linkedin.com/in/{linkedin[0]}"

    # GitHub
    github = re.findall(r'(?:github\.com/)([^\s/,\)]+)', raw_text, re.I)
    if github: profile["personal"]["github"] = f"https://github.com/{github[0]}"

    # Portfolio/website
    portfolio = re.findall(r'https?://(?!linkedin|github)[\w.-]+\.[a-z]{2,}(?:/[\w/-]*)?', raw_text, re.I)
    if portfolio: profile["personal"]["portfolio"] = portfolio[0]

    # Location — city names
    CITIES = ["hyderabad", "bengaluru", "bangalore", "mumbai", "pune", "chennai",
              "delhi", "noida", "gurgaon", "kolkata", "ahmedabad", "new york",
              "san francisco", "london", "singapore", "remote"]
    lo = raw_text.lower()
    for city in CITIES:
        if city in lo:
            profile["personal"]["location"] = city.title()
            break

    # Years of experience — look for date ranges
    year_ranges = re.findall(r'(20\d{2})\s*[-–—]\s*(20\d{2}|present|current)', raw_text, re.I)
    if year_ranges:
        import datetime as _dt
        cur_year = _dt.datetime.utcnow().year
        total_months = 0
        for start_yr, end_yr in year_ranges:
            s = int(start_yr)
            e = cur_year if end_yr.lower() in ('present', 'current') else int(end_yr)
            total_months += max(0, (e - s) * 12)
        profile["professional"]["years_experience"] = max(0, round(total_months / 12))

    # Current title — look for common title patterns near the top
    TITLE_PATTERNS = [
        r'(senior|lead|principal|staff|associate|junior)?\s*'
        r'(software|frontend|backend|full.?stack|data|ml|ai|devops|platform|cloud|site reliability|sre)'
        r'\s*(engineer|developer|scientist|analyst|architect|manager|intern)',
        r'(sde|swe|sde[\s-]?[123]|software development engineer)',
        r'(product manager|engineering manager|technical lead|tech lead)',
    ]
    for p in TITLE_PATTERNS:
        m = re.search(p, raw_text[:2000], re.I)
        if m:
            profile["professional"]["current_title"] = m.group(0).strip().title()
            break

    # Skills extraction — comprehensive tech list
    TECH_SKILLS = {
        "languages": ["python", "java", "javascript", "typescript", "golang", "go", "rust",
                      "c++", "c#", "kotlin", "swift", "scala", "ruby", "php", "r", "matlab",
                      "bash", "shell", "powershell", "dart", "elixir", "haskell", "lua"],
        "frameworks": ["react", "vue", "angular", "next.js", "nuxt", "svelte", "django",
                       "flask", "fastapi", "spring", "express", "node.js", "nestjs", "rails",
                       "laravel", "asp.net", "pytorch", "tensorflow", "keras", "scikit-learn",
                       "langchain", "hugging face", "transformers", "pandas", "numpy", "spark",
                       "hadoop", "airflow", "celery", "graphql", "grpc", "rest", "tailwind",
                       "bootstrap", "material ui", "redux", "mobx", "zustand"],
        "tools": ["git", "docker", "kubernetes", "terraform", "ansible", "jenkins", "github actions",
                  "gitlab ci", "circleci", "aws", "gcp", "azure", "linux", "nginx", "apache",
                  "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka", "rabbitmq",
                  "prometheus", "grafana", "datadog", "jira", "confluence", "figma", "postman",
                  "intellij", "vscode", "vim", "jupyter", "airflow", "dbt", "snowflake", "bigquery",
                  "firebase", "supabase", "heroku", "vercel", "netlify"],
    }
    for category, skill_list in TECH_SKILLS.items():
        found = []
        for skill in skill_list:
            pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, raw_text, re.I):
                found.append(skill.title() if len(skill) > 3 else skill.upper())
        profile["skills"][category] = found

    # Certifications
    cert_patterns = re.findall(
        r'(aws certified|google cloud|azure [a-z]+|cka|ckad|pmp|scrum master|cissp|comptia [a-z+]+)',
        raw_text, re.I
    )
    profile["skills"]["certifications"] = list(set(c.title() for c in cert_patterns))

    # Education
    EDU_PATTERNS = [
        (r'\b(b\.?tech|bachelor of technology)\b', 'B.Tech'),
        (r'\b(b\.?e\.?|bachelor of engineering)\b', 'B.E.'),
        (r'\b(b\.?sc\.?|bachelor of science)\b', 'B.Sc.'),
        (r'\b(m\.?tech|master of technology)\b', 'M.Tech'),
        (r'\b(m\.?s\.?|master of science)\b', 'M.S.'),
        (r'\b(m\.?b\.?a\.?|master of business)\b', 'MBA'),
        (r'\b(ph\.?d\.?|doctor of philosophy)\b', 'Ph.D.'),
        (r'\b(b\.?c\.?a\.?|bachelor of computer applications)\b', 'BCA'),
        (r'\b(m\.?c\.?a\.?|master of computer applications)\b', 'MCA'),
    ]
    for pat, degree_label in EDU_PATTERNS:
        if re.search(pat, raw_text, re.I):
            profile["education"]["degree"] = degree_label
            break

    # Field of study
    FIELDS = ["computer science", "information technology", "electronics", "electrical",
              "mechanical", "civil", "data science", "artificial intelligence", "mathematics"]
    for field in FIELDS:
        if field in lo:
            profile["education"]["field"] = field.title()
            break

    # Grad year
    grad_years = re.findall(r'20(?:1[0-9]|2[0-4])', raw_text)
    if grad_years:
        profile["education"]["year"] = sorted(grad_years)[0]

    # ── 3. AI enhancement (if configured) ────────────────────────────────
    try:
        ai = AIService.for_user(current_user["username"])
        if ai.is_configured():
            prompt = f"""Extract structured job profile data from this resume text. Return JSON only.

Resume (first 3000 chars):
{raw_text[:3000]}

Current extraction (fix and enhance):
{json.dumps(profile, indent=2)[:1500]}

Return the same JSON structure with improved/corrected values. Rules:
- Keep existing values if already correct
- Fix or fill missing fields where text evidence exists
- target_roles: list 2-4 specific job titles this person would target
- years_experience: integer, calculated from work history dates
- salary_expectation: realistic range based on experience level and skills (India LPA or USD)
- Return ONLY valid JSON, no explanation"""
            enhanced = ai.generate_json(prompt)
            if isinstance(enhanced, dict) and "personal" in enhanced:
                # Merge: AI fills gaps but doesn't overwrite good regex extractions
                for section in profile:
                    if section in enhanced and isinstance(enhanced[section], dict):
                        for key, val in enhanced[section].items():
                            if key in profile[section]:
                                existing = profile[section][key]
                                if not existing or existing in ("", [], 0, False):
                                    profile[section][key] = val
    except Exception:
        pass  # AI enhancement is best-effort

    # ── 4. Save profile ────────────────────────────────────────────────────
    session = get_session()
    try:
        row = session.query(UserSettings).filter_by(username=current_user["username"]).first()
        if not row:
            row = UserSettings(username=current_user["username"])
            session.add(row)
        row.profile_summary = json.dumps(profile)
        row.updated_at = datetime.utcnow()
        session.commit()
    except Exception:
        pass
    finally:
        session.close()

    skill_count = sum(len(v) if isinstance(v, list) else 0 for v in profile["skills"].values())
    return {**profile, "_meta": {"skill_count": skill_count, "raw_chars": len(raw_text)}}
