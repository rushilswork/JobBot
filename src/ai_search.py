"""
AI-powered natural language job search.

No external APIs — runs entirely locally.
Parses a free-text query into structured intent and scores
every job in the DB against that intent.

Example queries:
  "remote python backend engineer, not fintech"
  "SDE at a product company in Bengaluru, 0-2 years"
  "full stack react node.js hybrid"
  "AI/ML engineer, startup, remote"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Vocabulary maps ───────────────────────────────────────────────────────

ROLE_KEYWORDS = [
    "software engineer", "software developer", "software technologist",
    "backend engineer", "backend developer", "frontend engineer", "frontend developer",
    "full stack", "fullstack", "platform engineer", "site reliability", "sre",
    "devops", "data engineer", "ml engineer", "ai engineer", "machine learning",
    "deep learning", "nlp engineer", "computer vision", "data scientist",
    "product manager", "engineering manager", "sde", "sde1", "sde2", "sde3",
    "associate engineer", "junior developer", "senior engineer",
]

SKILL_KEYWORDS = [
    "python", "java", "javascript", "typescript", "golang", "go", "rust",
    "c++", "c#", "kotlin", "swift", "scala", "ruby", "php", "react", "vue",
    "angular", "next.js", "node.js", "django", "flask", "fastapi", "spring",
    "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "graphql",
    "pytorch", "tensorflow", "llm", "openai", "langchain", "vector", "embedding",
    "microservices", "distributed", "system design", "api", "rest",
]

LOCATION_KEYWORDS = {
    "hyderabad": "hyderabad", "hyd": "hyderabad",
    "bengaluru": "bengaluru", "bangalore": "bengaluru", "blr": "bengaluru",
    "mumbai": "mumbai", "bombay": "mumbai",
    "delhi": "delhi", "ncr": "delhi", "gurgaon": "delhi", "noida": "delhi",
    "pune": "pune", "chennai": "chennai", "kolkata": "kolkata",
    "india": "india", "remote": "remote", "anywhere": "remote",
    "us": "united states", "usa": "united states", "uk": "united kingdom",
}

MODE_KEYWORDS = {
    "remote": "remote", "wfh": "remote", "work from home": "remote",
    "hybrid": "hybrid", "onsite": "onsite", "in-office": "onsite", "office": "onsite",
}

LEVEL_KEYWORDS = {
    "junior": "junior", "entry": "junior", "fresher": "junior", "0-2": "junior",
    "0-3": "junior", "1-2": "junior", "1-3": "junior",
    "mid": "mid", "2-4": "mid", "2-5": "mid", "3-5": "mid",
    "senior": "senior", "sr": "senior", "lead": "senior", "5+": "senior",
    "staff": "senior", "principal": "senior",
}

COMPANY_TYPE_KEYWORDS = {
    "startup": "startup", "early stage": "startup", "series a": "startup",
    "series b": "startup", "seed": "startup",
    "product": "product", "product company": "product", "product based": "product",
    "service": "service", "services": "service", "it services": "service",
    "mnc": "mnc", "faang": "faang", "big tech": "faang",
    "fintech": "fintech", "banking": "banking", "insurance": "insurance",
    "healthcare": "healthcare", "edtech": "edtech", "saas": "saas",
}

EXCLUDE_SIGNALS = [
    "not", "no", "avoid", "except", "excluding", "without", "don't want",
    "dont want", "skip", "ignore",
]


@dataclass
class ParsedQuery:
    raw: str
    roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    company_types: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)


def parse_query(query: str) -> ParsedQuery:
    """Parse a natural language job search query into structured intent."""
    pq = ParsedQuery(raw=query)
    lo = query.lower().strip()

    # Extract exclusions first (phrases after "not", "no", "avoid", etc.)
    exclude_matches = []
    for sig in EXCLUDE_SIGNALS:
        pattern = rf'\b{re.escape(sig)}\s+([a-z0-9\s/&+]+?)(?:\s*,|\s*$|\s+(?:and|or|but)\b)'
        for m in re.finditer(pattern, lo):
            exclude_matches.append(m.group(1).strip())
    pq.exclude_terms = exclude_matches

    # Remove excluded phrases from lo for positive matching
    lo_clean = lo
    for ex in exclude_matches:
        lo_clean = lo_clean.replace(ex, "")

    # Match roles (longest match first)
    for role in sorted(ROLE_KEYWORDS, key=len, reverse=True):
        if re.search(r'\b' + re.escape(role) + r'\b', lo_clean):
            pq.roles.append(role)

    # Match skills
    for skill in SKILL_KEYWORDS:
        if re.search(r'\b' + re.escape(skill) + r'\b', lo_clean):
            pq.skills.append(skill)

    # Match locations
    for kw, canonical in LOCATION_KEYWORDS.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', lo_clean):
            if canonical not in pq.locations:
                pq.locations.append(canonical)

    # Match work modes
    for kw, canonical in MODE_KEYWORDS.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', lo_clean):
            if canonical not in pq.work_modes:
                pq.work_modes.append(canonical)

    # Match levels
    for kw, canonical in LEVEL_KEYWORDS.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', lo_clean) or kw in lo_clean:
            if canonical not in pq.levels:
                pq.levels.append(canonical)

    # Match company types
    for kw, canonical in COMPANY_TYPE_KEYWORDS.items():
        if kw in lo_clean:
            if canonical not in pq.company_types:
                pq.company_types.append(canonical)

    return pq


def score_job(job: dict, pq: ParsedQuery) -> tuple[float, list[str]]:
    """
    Score a job dict against a parsed query.
    Returns (score 0-100, list of match reasons).
    """
    score = 0.0
    reasons = []

    title_lo  = job.get("title", "").lower()
    company_lo = job.get("company", "").lower()
    loc_lo    = job.get("location", "").lower()
    desc_lo   = job.get("description", "").lower()
    mode      = job.get("work_mode", "unknown")
    haystack  = f"{title_lo} {desc_lo}"

    # ── Exclusion check (hard filter) ────────────────────────────────────
    for ex in pq.exclude_terms:
        if ex in title_lo or ex in company_lo or ex in desc_lo:
            return -1.0, [f"excluded: {ex}"]

    # ── Role match (35 pts max) ───────────────────────────────────────────
    if pq.roles:
        role_hits = [r for r in pq.roles if r in title_lo]
        if role_hits:
            score += min(35, 15 * len(role_hits))
            reasons.append(f"role: {', '.join(role_hits)}")
    else:
        # No role specified — mild baseline so anything can show up
        score += 10

    # ── Skill match (30 pts max) ──────────────────────────────────────────
    if pq.skills:
        skill_hits = [s for s in pq.skills if s in haystack]
        if skill_hits:
            pts = min(30, 8 * len(skill_hits))
            score += pts
            reasons.append(f"skills: {', '.join(skill_hits[:4])}")

    # ── Work mode match (15 pts) ──────────────────────────────────────────
    if pq.work_modes:
        if mode in pq.work_modes:
            score += 15
            reasons.append(f"mode: {mode}")
        elif mode == "unknown":
            score += 5  # partial credit for unknown
    else:
        score += 10  # no preference → neutral

    # ── Location match (15 pts) ───────────────────────────────────────────
    if pq.locations:
        loc_hit = any(loc in loc_lo for loc in pq.locations if loc != "remote")
        remote_wanted = "remote" in pq.locations
        if loc_hit:
            score += 15
            reasons.append(f"location match")
        elif remote_wanted and mode == "remote":
            score += 15
            reasons.append("remote match")
        elif remote_wanted and "remote" in loc_lo:
            score += 12
    else:
        score += 8

    # ── Level match (5 pts) ───────────────────────────────────────────────
    if pq.levels:
        level_map = {
            "junior": ["junior", "associate", "entry", "graduate", "fresher", "sde1", "sde i"],
            "mid":    ["mid", "sde2", "sde ii", "software engineer ii"],
            "senior": ["senior", "sr.", "lead", "staff", "principal", "sde3"],
        }
        for wanted_level in pq.levels:
            if any(kw in title_lo for kw in level_map.get(wanted_level, [])):
                score += 5
                reasons.append(f"level: {wanted_level}")
                break

    return round(score, 1), reasons


def ai_search(jobs: list[dict], query: str, top_n: int = 50) -> list[dict]:
    """
    Run AI-powered search over a list of job dicts.
    Returns top_n results sorted by relevance score, with score and reasons attached.
    """
    if not query.strip():
        return jobs[:top_n]

    pq = parse_query(query)
    scored = []
    for job in jobs:
        s, reasons = score_job(job, pq)
        if s >= 0:  # -1 = excluded
            job_copy = dict(job)
            job_copy["ai_score"] = s
            job_copy["ai_reasons"] = reasons
            scored.append(job_copy)

    scored.sort(key=lambda j: j["ai_score"], reverse=True)
    return scored[:top_n]
