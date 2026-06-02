"""
AI-powered cover letter and screening question generator.
Uses the Anthropic API (claude-haiku for speed/cost).
"""

from __future__ import annotations

import json

import anthropic

from src.utils import load_credentials, log


def _client() -> anthropic.Anthropic:
    creds = load_credentials()
    api_key = creds.get("anthropic_api_key", "")
    if not api_key:
        raise ValueError(
            "Missing anthropic_api_key in config/credentials.yaml. "
            "Get one at https://console.anthropic.com"
        )
    return anthropic.Anthropic(api_key=api_key)


def generate_cover_letter(profile: dict, job_title: str, company_name: str, job_description: str) -> str:
    """Generate a tailored cover letter for a specific role."""
    client = _client()

    prompt = f"""
You are writing a concise, professional cover letter for a job application.

Candidate profile:
- Name: {profile['personal']['first_name']} {profile['personal']['last_name']}
- Current company: {profile['experience'][0]['company'] if profile.get('experience') else 'N/A'}
- Skills: {', '.join(profile.get('skills', {}).get('languages', []) + profile.get('skills', {}).get('frameworks', []))}
- Why they like this type of company: {profile.get('screening_answers', {}).get('why_this_company', '')}

Role: {job_title} at {company_name}
Job description excerpt: {job_description[:1500]}

Write a 3-paragraph cover letter (under 250 words total):
1. Opening — express specific enthusiasm for {company_name} and this role
2. Middle — highlight 1-2 most relevant experiences/skills from the profile
3. Closing — brief, confident call to action

Do NOT use generic phrases like "I am writing to express my interest". Be specific and direct.
Return ONLY the cover letter text, no subject line or sign-off.
""".strip()

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        log.error(f"Cover letter generation failed: {e}")
        return ""


def generate_screening_answers(
    profile: dict,
    job_title: str,
    company_name: str,
    questions: list[str],
) -> dict[str, str]:
    """
    Given a list of screening questions, return a dict of {question: answer}.
    """
    if not questions:
        return {}

    client = _client()

    questions_str = "\n".join(f"- {q}" for q in questions)

    prompt = f"""
Answer these job application screening questions for the candidate below.
Keep answers concise (1-3 sentences each), professional, and honest.

Candidate:
- Name: {profile['personal']['first_name']} {profile['personal']['last_name']}
- Years of experience: {profile.get('screening_answers', {}).get('years_of_experience', 2)}
- Skills: {', '.join(profile.get('skills', {}).get('languages', []))}
- Willing to relocate: {profile.get('screening_answers', {}).get('willing_to_relocate', False)}
- Requires sponsorship: {profile.get('work_authorization', {}).get('requires_sponsorship', False)}
- Desired salary range: ${profile.get('salary', {}).get('desired_min', 0):,} - ${profile.get('salary', {}).get('desired_max', 0):,}

Role: {job_title} at {company_name}

Questions to answer:
{questions_str}

Return a JSON object where keys are the exact question text and values are the answers.
Return ONLY valid JSON, no other text.
""".strip()

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Screening answer generation failed: {e}")
        return {}
