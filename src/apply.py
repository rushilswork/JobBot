"""
Apply engine — takes a reviewed job from the queue, generates AI content,
and runs the appropriate auto-filler. Stages the application for human review.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from playwright.async_api import async_playwright

from src.ai import generate_cover_letter, generate_screening_answers
from src.autofill import GreenhouseAutoFiller, LinkedInAutoFiller
from src.database import Application, Job, JobStatus, get_session, mark_job
from src.utils import load_config, load_credentials, load_profile, log


async def prepare_and_stage(job_id: int) -> bool:
    """
    Given a job_id in REVIEWED status:
    1. Generate cover letter + screening answers
    2. Run auto-fill (no submit)
    3. Move job to APPLYING status, save Application record

    Returns True on success.
    """
    session = get_session()
    job: Job = session.get(Job, job_id)

    if not job:
        log.error(f"Job {job_id} not found")
        return False

    if job.status not in (JobStatus.REVIEWED, JobStatus.NEW):
        log.warning(f"Job {job_id} is in status {job.status!r}, expected reviewed/new")

    profile = load_profile()
    config = load_config()

    log.info(f"Preparing application for: {job.title} @ {job.company.name}")

    # --- AI content generation ---
    log.info("  Generating cover letter...")
    cover_letter = generate_cover_letter(
        profile=profile,
        job_title=job.title,
        company_name=job.company.name,
        job_description=job.description or "",
    )

    # For screening answers we'd ideally extract questions from the form first.
    # Here we pre-generate answers to common question patterns.
    common_questions = [
        "Why do you want to work at this company?",
        "How many years of experience do you have?",
        "Are you authorized to work in the United States?",
        "Do you require visa sponsorship?",
        "What are your salary expectations?",
        "When are you available to start?",
        "Are you willing to relocate?",
    ]
    log.info("  Generating screening answers...")
    screening_answers = generate_screening_answers(
        profile=profile,
        job_title=job.title,
        company_name=job.company.name,
        questions=common_questions,
    )

    # Save to DB
    job.cover_letter = cover_letter
    job.screening_answers = json.dumps(screening_answers)
    mark_job(session, job_id, JobStatus.APPLYING)

    # --- Browser auto-fill ---
    creds = load_credentials()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,   # Always headed for apply — user may need to verify
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        # Login to LinkedIn if needed
        if job.portal == "linkedin":
            await _linkedin_login(context, creds)
            filler = LinkedInAutoFiller(cover_letter=cover_letter, screening_answers=screening_answers)
        elif job.portal in ("greenhouse", "lever"):
            filler = GreenhouseAutoFiller(cover_letter=cover_letter, screening_answers=screening_answers)
        else:
            log.warning(f"No auto-filler for portal {job.portal!r}")
            await browser.close()
            return False

        result = await filler.fill(context, job.job_url, job_id)
        await browser.close()

    # Record the attempt
    app = Application(
        job_id=job_id,
        portal=job.portal,
        submitted_at=None,      # not submitted yet
        success=result["success"],
        error_message=result.get("error", ""),
        screenshot_path=result.get("screenshot_path", ""),
    )
    session.add(app)

    if result["success"]:
        mark_job(session, job_id, JobStatus.REVIEWING if hasattr(JobStatus, "REVIEWING") else JobStatus.APPLIED,
                 notes="Staged — awaiting manual review before submit")
        log.info(f"  ✓ Application staged. Review screenshot: {result['screenshot_path']}")
    else:
        mark_job(session, job_id, JobStatus.FAILED, notes=result.get("error", ""))
        log.error(f"  ✗ Auto-fill failed: {result.get('error')}")

    session.commit()
    session.close()
    return result["success"]


async def _linkedin_login(context, creds: dict) -> None:
    """Log in to LinkedIn if not already authenticated."""
    page = await context.new_page()
    await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

    # Check if already logged in
    if "feed" in page.url or "mynetwork" in page.url:
        await page.close()
        return

    email = creds.get("linkedin", {}).get("email", "")
    password = creds.get("linkedin", {}).get("password", "")

    if not (email and password):
        log.warning("LinkedIn credentials not set in config/credentials.yaml — skipping login")
        await page.close()
        return

    await page.fill("#username", email)
    await asyncio.sleep(0.5)
    await page.fill("#password", password)
    await asyncio.sleep(0.3)
    await page.click("button[type='submit']")
    await asyncio.sleep(3)
    await page.close()
