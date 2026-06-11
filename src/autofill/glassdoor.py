"""
Glassdoor — Easy Apply button + form fill + resume upload.
"""
from __future__ import annotations
import asyncio
from playwright.async_api import Page
from .base import upload_resume, take_screenshot, dismiss_popups
from .generic import fill_generic_form
from src.utils import log

APPLY_SELECTORS = [
    "button:has-text('Easy Apply')",
    "button:has-text('Apply Now')",
    "button:has-text('Apply')",
    "[data-test='applyButton']",
    ".apply-btn",
    "[class*='applyButton']",
    "[class*='easy-apply']",
]
NEXT_SELECTORS = [
    "button:has-text('Continue')",
    "button:has-text('Next')",
    "button[type='submit']:has-text('Next')",
]
SUBMIT_SELECTORS = [
    "button:has-text('Submit')",
    "button:has-text('Submit application')",
    "button[type='submit']",
]


async def apply_glassdoor(
    page: Page,
    profile: dict,
    job_id: int,
    ai=None,
    job_context: dict = None,
) -> dict:
    result = {"filled": [], "skipped": [], "needs_manual": [], "screenshot_path": ""}

    await dismiss_popups(page)
    await asyncio.sleep(0.5)

    # Click Easy Apply / Apply
    for sel in APPLY_SELECTORS:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.5)
                break
        except Exception:
            pass

    await dismiss_popups(page)  # new popups after click

    # Resume upload
    if profile.get("resume_path"):
        ok = await upload_resume(page, profile["resume_path"])
        if ok:
            result["filled"].append("Resume")

    # Multi-step form — up to 8 steps
    for step in range(8):
        step_r = await fill_generic_form(page, profile, job_id, ai=ai, job_context=job_context)
        for f in step_r["filled"]:
            if f not in result["filled"]:
                result["filled"].append(f)
        result["needs_manual"].extend(step_r["needs_manual"])
        result["screenshot_path"] = await take_screenshot(page, job_id, f"gd_step{step+1}")

        # Check for submit
        for sel in SUBMIT_SELECTORS:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                result["submit_selector"] = ", ".join(SUBMIT_SELECTORS)
                return result

        # Advance to next step
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

    result["screenshot_path"] = await take_screenshot(page, job_id, "glassdoor_filled")
    return result
