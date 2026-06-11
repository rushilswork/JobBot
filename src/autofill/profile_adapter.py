"""
Profile Adapter — loads the user's profile from the database (UserSettings.profile_summary)
and normalises it into the flat dict that all autofill handlers expect.

Priority:  DB  >  config/profile.yaml  >  empty defaults
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.utils import log

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Public entry point ────────────────────────────────────────────────────────

def load_autofill_profile(username: str) -> dict:
    """Return a normalised flat profile dict ready for autofill field resolution."""
    raw = _load_raw(username)
    return _normalise(raw)


# ── Raw loader ────────────────────────────────────────────────────────────────

def _load_raw(username: str) -> dict:
    """Load raw profile from DB first, YAML as fallback."""
    # 1. DB
    try:
        from src.database import get_session
        from src.models import UserSettings
        session = get_session()
        try:
            row = session.query(UserSettings).filter_by(username=username).first()
            if row and row.profile_summary:
                data = json.loads(row.profile_summary)
                if data and any(data.get(k) for k in ("personal", "professional", "skills")):
                    log.info(f"[Profile] Loaded from DB for {username}")
                    return data
        finally:
            session.close()
    except Exception as e:
        log.warning(f"[Profile] DB load failed: {e}")

    # 2. YAML fallback
    try:
        import yaml
        yaml_path = PROJECT_ROOT / "config" / "profile.yaml"
        if yaml_path.exists():
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
            log.info("[Profile] Loaded from profile.yaml (fallback)")
            return _yaml_to_db_format(data)
    except Exception as e:
        log.warning(f"[Profile] YAML load failed: {e}")

    return {}


def _yaml_to_db_format(y: dict) -> dict:
    """Convert old YAML profile format into the DB profile structure."""
    p   = y.get("personal", {})
    pro = y.get("professional", {})
    edu = y.get("education", {})
    ans = y.get("answers", {})
    sk  = y.get("skills", {})
    return {
        "personal": {
            "first_name": p.get("first_name", ""),
            "last_name":  p.get("last_name", ""),
            "email":      p.get("email", ""),
            "phone":      p.get("phone", ""),
            "linkedin":   p.get("linkedin_url", ""),
            "github":     p.get("github_url", ""),
            "portfolio":  p.get("portfolio_url", ""),
            "location":   p.get("location", {}).get("city", "") if isinstance(p.get("location"), dict) else p.get("location", ""),
        },
        "professional": {
            "current_title":      pro.get("current_title", ""),
            "current_company":    pro.get("current_company", ""),
            "years_experience":   pro.get("years_experience", 0),
            "willing_to_relocate": pro.get("willing_to_relocate", False),
            "notice_period":      f"{pro.get('notice_period_days', 30)} days",
        },
        "education": {
            "degree":      edu.get("degree", ""),
            "field":       edu.get("field", ""),
            "institution": edu.get("university", ""),
            "year":        str(edu.get("graduation_year", "")),
        },
        "skills": {
            "languages":  sk.get("languages", []),
            "frameworks": sk.get("frameworks", []),
            "tools":      sk.get("tools", []),
        },
        "answers": {
            "salary_expectation":  ans.get("salary_expectation", ""),
            "work_authorization":  ans.get("work_authorization", "Authorized to work in India"),
            "notice_period":       ans.get("notice_period", "30 days"),
        },
    }


# ── Normaliser ────────────────────────────────────────────────────────────────

def _normalise(raw: dict) -> dict:
    """Flatten the DB profile into a single-level dict autofill handlers can use."""
    p   = raw.get("personal", {})
    pro = raw.get("professional", {})
    edu = raw.get("education", {})
    ans = raw.get("answers", {})
    sk  = raw.get("skills", {})
    lnk = raw.get("links", {})

    first = p.get("first_name", "")
    last  = p.get("last_name", "")
    full  = f"{first} {last}".strip() or p.get("full_name", "")

    linkedin  = p.get("linkedin")  or p.get("linkedin_url")  or lnk.get("linkedin", "")
    github    = p.get("github")    or p.get("github_url")    or lnk.get("github", "")
    portfolio = p.get("portfolio") or p.get("portfolio_url") or lnk.get("portfolio", "")

    all_skills = (
        sk.get("languages", []) +
        sk.get("frameworks", []) +
        sk.get("tools", []) +
        sk.get("databases", [])
    )

    notice_raw = pro.get("notice_period") or ans.get("notice_period") or "30 days"
    try:
        notice_days = int("".join(filter(str.isdigit, str(notice_raw)))) if notice_raw != "Immediate" else 0
    except Exception:
        notice_days = 30

    city = p.get("location") if isinstance(p.get("location"), str) else ""

    return {
        # Identity
        "first_name":         first,
        "last_name":          last,
        "full_name":          full,
        "email":              p.get("email", ""),
        "phone":              p.get("phone", ""),
        "linkedin_url":       linkedin,
        "github_url":         github,
        "portfolio_url":      portfolio,

        # Location
        "city":    city or "",
        "state":   "",
        "country": "India",
        "zip":     "",

        # Professional
        "current_title":       pro.get("current_title", ""),
        "current_company":     pro.get("current_company", ""),
        "years_experience":    str(pro.get("years_experience", "")),
        "notice_period":       notice_raw,
        "notice_period_days":  str(notice_days),
        "willing_to_relocate": "Yes" if pro.get("willing_to_relocate") else "No",
        "work_mode":           pro.get("work_mode_preference", "hybrid"),
        "target_roles":        ", ".join(pro.get("target_roles", [])),

        # Education
        "degree":      edu.get("degree", ""),
        "field":       edu.get("field", ""),
        "institution": edu.get("institution", "") or edu.get("university", ""),
        "grad_year":   str(edu.get("year", "") or edu.get("graduation_year", "")),

        # Screening
        "salary_expectation": ans.get("salary_expectation", ""),
        "work_authorization": ans.get("work_authorization", "Authorized to work in India"),
        "cover_letter_tone":  ans.get("cover_letter_tone", "professional"),

        # Skills
        "all_skills":  all_skills,
        "skills_str":  ", ".join(all_skills),
        "languages":   ", ".join(sk.get("languages", [])),
        "frameworks":  ", ".join(sk.get("frameworks", [])),
        "tools":       ", ".join(sk.get("tools", [])),

        # Resume file path (from upload or fallback scan)
        "resume_path": _find_resume(raw),

        # Raw for deep access
        "_raw": raw,
    }


# ── Resume finder ─────────────────────────────────────────────────────────────

def _find_resume(raw: dict) -> Optional[str]:
    """
    Locate the resume file:
    1. resume_meta.file_path stored in DB profile (set when user uploads via Profile page)
    2. Most-recently-modified file in data/resumes/
    3. Generic fallback paths
    """
    # 1. DB-stored path
    if raw:
        fp = raw.get("resume_meta", {}).get("file_path", "")
        if fp and Path(fp).exists():
            return fp

    # 2. data/resumes/ directory — pick newest
    resumes_dir = PROJECT_ROOT / "data" / "resumes"
    if resumes_dir.exists():
        candidates = sorted(
            (f for f in resumes_dir.iterdir() if f.suffix.lower() in (".pdf", ".docx", ".doc", ".txt")),
            key=lambda x: x.stat().st_mtime, reverse=True,
        )
        if candidates:
            return str(candidates[0])

    # 3. Generic fallbacks
    for p in [
        PROJECT_ROOT / "data" / "resume.pdf",
        PROJECT_ROOT / "data" / "resume.docx",
        PROJECT_ROOT / "config" / "resume.pdf",
    ]:
        if p.exists():
            return str(p)

    return None
