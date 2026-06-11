"""
AI-powered content generation for job applications.
Uses the unified AIService (Groq or Gemini).
"""
from __future__ import annotations

from src.ai.service import AIService
from src.utils import log


def generate_cover_letter(
    profile: dict,
    job_title: str,
    company_name: str,
    job_description: str,
    ai: AIService,
) -> str:
    """Generate a tailored cover letter. Returns plain text."""
    personal = profile.get("personal", {})
    professional = profile.get("professional", {})
    education = profile.get("education", {})

    name = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
    skills_raw = profile.get("skills", [])
    if isinstance(skills_raw, dict):
        skills_list = skills_raw.get("languages", []) + skills_raw.get("frameworks", [])
    elif isinstance(skills_raw, list):
        skills_list = skills_raw
    else:
        skills_list = []

    prompt = f"""Write a concise, professional cover letter for a job application.

Candidate profile:
- Name: {name}
- Current role: {professional.get('current_title', 'Software Engineer')} at {professional.get('current_company', 'N/A')}
- Experience: {professional.get('years_experience', 1)} years
- Education: {education.get('degree', 'B.Tech')} in {education.get('field', 'Computer Science')}
- Key skills: {', '.join(skills_list[:12]) if skills_list else 'Python, Software Development'}

Role applying for: {job_title} at {company_name}

Job description excerpt:
{job_description[:1800]}

Instructions:
- Write exactly 3 paragraphs, under 240 words total
- Para 1: Specific enthusiasm for {company_name} and this exact role (avoid "I am writing to express my interest")
- Para 2: 1-2 most relevant experiences/skills from the profile matched to job requirements
- Para 3: Confident, brief call to action
- Tone: direct, professional, human - not templated
- Return ONLY the cover letter body text, no subject line, no salutation, no signature"""

    try:
        return ai.generate(prompt, max_tokens=600)
    except Exception as e:
        log.error(f"Cover letter generation failed: {e}")
        raise


def generate_screening_answers(
    profile: dict,
    job_title: str,
    company_name: str,
    questions: list[str],
    ai: AIService,
) -> dict[str, str]:
    """Answer a list of screening questions. Returns {question: answer}."""
    if not questions:
        return {}

    personal = profile.get("personal", {})
    professional = profile.get("professional", {})
    answers_cfg = profile.get("answers", {})

    questions_str = "\n".join(f"- {q}" for q in questions)

    prompt = f"""Answer these job application screening questions for the candidate below.
Keep each answer concise (1-3 sentences), professional, and honest.

Candidate:
- Name: {personal.get('first_name', '')} {personal.get('last_name', '')}
- Experience: {professional.get('years_experience', 1)} years
- Willing to relocate: {professional.get('willing_to_relocate', True)}
- Notice period: {answers_cfg.get('notice_period', '30 days')}
- Work authorization: {answers_cfg.get('work_authorization', 'Authorized to work in India')}
- Salary expectation: {answers_cfg.get('salary_expectation', 'As per company norms')}

Role: {job_title} at {company_name}

Questions:
{questions_str}

Return a JSON object where keys are the exact question text and values are the answers."""

    try:
        return ai.generate_json(prompt)
    except Exception as e:
        log.error(f"Screening answer generation failed: {e}")
        return {}


def generate_match_score(
    profile: dict,
    job_title: str,
    company_name: str,
    job_description: str,
    resume_skills: list[str],
    ai: AIService,
) -> dict:
    """Score job fit 0-100 with matched/missing skills and a recommendation."""
    professional = profile.get("professional", {})
    skills_raw = profile.get("skills", [])
    if isinstance(skills_raw, dict):
        profile_skills = skills_raw.get("languages", []) + skills_raw.get("frameworks", [])
    elif isinstance(skills_raw, list):
        profile_skills = skills_raw
    else:
        profile_skills = []

    all_skills = list(set(profile_skills + (resume_skills or [])))

    prompt = f"""Evaluate how well this candidate matches the job. Be realistic and precise.

Candidate:
- Role: {professional.get('current_title', 'Software Engineer')}
- Experience: {professional.get('years_experience', 1)} years
- Skills: {', '.join(all_skills[:20]) if all_skills else 'General software development'}

Job: {job_title} at {company_name}
Description:
{job_description[:2000]}

Return a JSON object with these exact keys:
{{
  "score": <integer 0-100, honest assessment>,
  "verdict": "<one of: Strong Match | Good Match | Partial Match | Weak Match>",
  "matched_skills": ["<skill1>"],
  "missing_skills": ["<skill1>"],
  "strengths": ["<strength1>", "<strength2>"],
  "gaps": ["<gap1>", "<gap2>"],
  "recommendation": "<2-sentence honest recommendation>"
}}"""

    try:
        return ai.generate_json(prompt)
    except Exception as e:
        log.error(f"Match score generation failed: {e}")
        raise


def generate_skill_gap(
    profile: dict,
    job_title: str,
    company_name: str,
    job_description: str,
    resume_skills: list[str],
    ai: AIService,
) -> dict:
    """Detailed skill gap analysis with learning path."""
    professional = profile.get("professional", {})
    skills_raw = profile.get("skills", [])
    if isinstance(skills_raw, dict):
        profile_skills = skills_raw.get("languages", []) + skills_raw.get("frameworks", [])
    else:
        profile_skills = skills_raw if isinstance(skills_raw, list) else []

    all_skills = list(set(profile_skills + (resume_skills or [])))

    prompt = f"""Perform a detailed skill gap analysis for this candidate and job.

Candidate:
- Title: {professional.get('current_title', 'Software Engineer')}
- Experience: {professional.get('years_experience', 1)} years
- Current skills: {', '.join(all_skills[:20]) if all_skills else 'General software development'}

Job: {job_title} at {company_name}
Description:
{job_description[:2000]}

Return a JSON object with these exact keys:
{{
  "required_skills": ["<all skills mentioned or implied in JD>"],
  "candidate_has": ["<skills candidate clearly has>"],
  "candidate_missing": ["<skills candidate lacks>"],
  "nice_to_have": ["<mentioned as bonus, not required>"],
  "learning_path": [
    {{"skill": "<missing skill>", "priority": "high|medium|low", "resource": "<best free resource>", "time_estimate": "<e.g. 1-2 weeks>"}}
  ],
  "overall_readiness": "<percentage string, e.g. 72%>",
  "summary": "<2-3 sentence honest summary of the gap and how to close it>"
}}"""

    try:
        return ai.generate_json(prompt)
    except Exception as e:
        log.error(f"Skill gap generation failed: {e}")
        raise


def generate_interview_prep(
    profile: dict,
    job_title: str,
    company_name: str,
    job_description: str,
    ai: AIService,
) -> dict:
    """Generate likely interview questions with suggested answers."""
    professional = profile.get("professional", {})
    skills_raw = profile.get("skills", [])
    if isinstance(skills_raw, dict):
        profile_skills = skills_raw.get("languages", []) + skills_raw.get("frameworks", [])
    else:
        profile_skills = skills_raw if isinstance(skills_raw, list) else []

    prompt = f"""Generate interview preparation material for this candidate.

Candidate:
- Title: {professional.get('current_title', 'Software Engineer')}
- Experience: {professional.get('years_experience', 1)} years
- Skills: {', '.join(profile_skills[:12]) if profile_skills else 'Software development'}

Job: {job_title} at {company_name}
Description:
{job_description[:1800]}

Return a JSON object with these exact keys:
{{
  "behavioral_questions": [
    {{"question": "<question>", "tip": "<brief answering tip>", "framework": "STAR|CAR|direct"}}
  ],
  "technical_questions": [
    {{"question": "<question>", "hint": "<what they are testing for>"}}
  ],
  "role_specific_questions": [
    {{"question": "<question specific to this role>", "hint": "<context>"}}
  ],
  "questions_to_ask": ["<good question to ask the interviewer>"],
  "prep_tips": ["<specific preparation tip for this role>"]
}}

Include 3-5 behavioral questions, 3-5 technical questions, 3 role-specific questions, \
3 questions to ask the interviewer, and 3 prep tips."""

    try:
        return ai.generate_json(prompt)
    except Exception as e:
        log.error(f"Interview prep generation failed: {e}")
        raise
