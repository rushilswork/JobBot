"""
Apply engine — takes a reviewed job from the queue, generates AI content,
and runs the appropriate auto-filler. Stages the application for human review.

NOTE: The primary apply path is now triggered via the dashboard API
(POST /api/jobs/{job_id}/apply → src/autofill/runner.py).
This module's prepare_and_stage() is kept for CLI / scripted use.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from src.ai.service import AIService
from src.ai.generator import generate_cover_letter, generate_screening_answers
from src.autofill import run_autofill
from src.autofill.profile_adapter import load_autofill_profile
from src.database import Application, Job, JobStatus, get_session, mark_job
from src.utils import load_config, log


async def prepare_and_stage(job_id: int, username: str) -> bool:
    """
    Given a job_id in REVIEWED status:
    1. Generate cover letter + screening answers via the user's AI provider
    2. Run auto-fill (no submit) via autofill/runner.py
    3. Move job to APPLYING status, save Application record

    Returns True on success.
    """
    session = get_session()
    job: Job = session.get(Job, job_id)

    if not job:
        log.error(f"Job {job_id} not found")
        session.close()
        return False

    if job.status not in (JobStatus.REVIEWED, JobStatus.NEW):
        log.warning(f"Job {job_id} is in status {job.status!r}, expected reviewed/new")

    profile = load_autofill_profile(username)

    log.info(f"Preparing application for: {job.title} @ {job.company.name}")

    # --- AI content generation ---
    ai = AIService.for_user(username)
    cover_letter = ""
    screening_answers: dict = {}

    if ai.is_configured():
        log.info("  Generating cover letter...")
        try:
            cover_letter = generate_cover_letter(
                profile=profile,
                job_title=job.title,
                company_name=job.company.name,
                job_description=job.description or "",
                ai=ai,
            )
        except Exception as e:
            log.warning(f"  Cover letter generation skipped: {e}")

        common_questions = [
            "Why do you want to work at this company?",
            "How many years of experience do you have?",
            "Are you authorized to work in India?",
            "Do you require visa sponsorship?",
            "What are your salary expectations?",
            "When are you available to start?",
            "Are you willing to relocate?",
        ]
        log.info("  Generating screening answers...")
        try:
            screening_answers = generate_screening_answers(
                profile=profile,
                job_title=job.title,
                company_name=job.company.name,
                questions=common_questions,
                ai=ai,
            )
        except Exception as e:
            log.warning(f"  Screening answer generation skipped: {e}")
    else:
        log.warning("  AI not configured — skipping content generation")

    # Save generated content to DB
    job.cover_letter = cover_letter
    job.screening_answers = json.dumps(screening_answers)
    mark_job(session, job_id, JobStatus.APPLYING)
    session.close()

    # --- Browser auto-fill via the current runner ---
    job_context = {
        "title":        job.title,
        "company":      job.company.name,
        "description":  job.description or "",
        "cover_letter": cover_letter,
    }

    result = await run_autofill(
        job_id=job_id,
        job_url=job.job_url,
        portal=job.portal,
        username=username,
        ai=ai if ai.is_configured() else None,
        job_context=job_context,
    )

    # Record the attempt
    new_session = get_session()
    app = Application(
        job_id=job_id,
        portal=job.portal,
        submitted_at=None,      # not submitted yet — awaiting manual confirm
        success=result.get("status") == "waiting_confirm",
        error_message=result.get("error", ""),
        screenshot_path=result.get("screenshot_path", ""),
    )
    new_session.add(app)

    if result.get("status") == "waiting_confirm":
        mark_job(new_session, job_id, JobStatus.APPLIED,
                 notes="Staged — awaiting manual review before submit")
        log.info(f"  ✓ Application staged. Review screenshot: {result.get('screenshot_path')}")
    else:
        mark_job(new_session, job_id, JobStatus.FAILED, notes=result.get("error", ""))
        log.error(f"  ✗ Auto-fill failed: {result.get('error')}")

    new_session.commit()
    new_session.close()
    return result.get("status") == "waiting_confirm"
