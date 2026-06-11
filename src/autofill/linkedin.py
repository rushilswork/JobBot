"""
LinkedIn Easy Apply — multi-step modal handler.
"""
from __future__ import annotations
import asyncio
from playwright.async_api import Page
from .base import fill_text_field, fill_select, upload_resume, take_screenshot, dismiss_popups
from .generic import fill_generic_form
from src.utils import log

EASY_APPLY_SELECTORS = [
    "button.jobs-apply-button",
    "button[data-control-name='jobdetails_topcard_inapply']",
    "button:has-text('Easy Apply')",
    ".jobs-apply-button",
    "[aria-label*='Easy Apply']",
]
NEXT_SELECTORS = [
    "button[aria-label='Continue to next step']",
    "button:has-text('Next')",
    "button:has-text('Continue')",
    "button:has-text('Review')",
]
SUBMIT_SELECTORS = [
    "button[aria-label='Submit application']",
    "button:has-text('Submit application')",
    "button:has-text('Submit')",
]


async def apply_linkedin(
    page: Page,
    profile: dict,
    job_id: int,
    ai=None,
    job_context: dict = None,
) -> dict:
    result = {"filled": [], "skipped": [], "needs_manual": [], "screenshot_path": "", "steps": 0}

    await dismiss_popups(page)

    # Click Easy Apply button
    clicked = False
    for sel in EASY_APPLY_SELECTORS:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.5)
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        log.warning("[LinkedIn] Easy Apply button not found — falling back to generic")
        return await fill_generic_form(page, profile, job_id, ai=ai, job_context=job_context)

    # Upload resume early if modal has file input
    resume_path = profile.get("resume_path", "")
    if resume_path:
        await upload_resume(page, resume_path)

    max_steps = 10
    for step in range(max_steps):
        result["steps"] = step + 1
        await asyncio.sleep(0.8)

        # Fill current step's fields
        step_r = await fill_generic_form(page, profile, job_id, ai=ai, job_context=job_context)
        result["filled"].extend(step_r["filled"])
        result["needs_manual"].extend(step_r["needs_manual"])
        result["screenshot_path"] = await take_screenshot(page, job_id, f"li_step{step+1}")

        # Check for submit
        for sel in SUBMIT_SELECTORS:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                log.info(f"[LinkedIn] Ready to submit after {step+1} steps — pausing")
                result["screenshot_path"] = await take_screenshot(page, job_id, "li_ready")
                result["submit_selector"] = ", ".join(SUBMIT_SELECTORS)
                return result

        # Check for next step
        advanced = False
        for sel in NEXT_SELECTORS:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.2)
                advanced = True
                break
        if not advanced:
            break

    return result
