"""
LinkedIn Easy Apply autofiller.
Handles multi-step Easy Apply modal.
"""
from __future__ import annotations
import asyncio, random
from playwright.async_api import Page, TimeoutError as PWTimeout
from .base import resolve_field, fill_text_field, select_option, take_screenshot
from .generic import fill_generic_form
from src.utils import log

PROFILE_DIR = __import__('pathlib').Path(__file__).resolve().parent.parent.parent / "data" / "browser_profile" / "linkedin"


async def apply_linkedin(page: Page, profile: dict, job_id: int) -> dict:
    """Fill LinkedIn Easy Apply modal step by step."""
    results = {"filled": [], "skipped": [], "needs_manual": [], "screenshot_path": "", "steps": 0}

    try:
        # Click Easy Apply button
        easy_apply = await page.query_selector("button.jobs-apply-button, [data-control-name='jobdetails_topcard_inapply'], button:has-text('Easy Apply')")
        if not easy_apply:
            log.warning("[LinkedIn Autofill] No Easy Apply button found")
            return results
        await easy_apply.click()
        await asyncio.sleep(1.5)

        # Handle multi-step modal
        max_steps = 8
        for step in range(max_steps):
            results["steps"] = step + 1

            # Fill current step
            step_result = await fill_generic_form(page, profile, job_id)
            results["filled"].extend(step_result["filled"])
            results["needs_manual"].extend(step_result["needs_manual"])

            # Take screenshot of this step
            results["screenshot_path"] = await take_screenshot(page, job_id, f"step_{step+1}")

            # Check for Next/Review/Submit buttons
            next_btn = await page.query_selector("button[aria-label='Continue to next step'], button:has-text('Next'), button:has-text('Review')")
            submit_btn = await page.query_selector("button[aria-label='Submit application'], button:has-text('Submit application')")

            if submit_btn:
                # PAUSE HERE — don't click submit, wait for user confirmation
                log.info(f"[LinkedIn Autofill] Ready to submit — pausing for user confirmation")
                results["screenshot_path"] = await take_screenshot(page, job_id, "ready_to_submit")
                results["submit_selector"] = "button[aria-label='Submit application'], button:has-text('Submit application')"
                break
            elif next_btn:
                await next_btn.click()
                await asyncio.sleep(1.2)
            else:
                break

    except Exception as e:
        log.error(f"[LinkedIn Autofill] Error: {e}")
        results["error"] = str(e)

    return results
