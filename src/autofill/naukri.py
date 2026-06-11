"""
Naukri.com — apply button click + modal form fill.
"""
from __future__ import annotations
import asyncio
from playwright.async_api import Page
from .base import fill_text_field, upload_resume, take_screenshot, dismiss_popups
from .generic import fill_generic_form
from src.utils import log

APPLY_SELECTORS = [
    "button:has-text('Apply')",
    "a:has-text('Apply')",
    ".apply-button",
    "#apply-button",
    "[class*='applyButton']",
    "button:has-text('Apply now')",
    "a:has-text('Apply now')",
]


async def apply_naukri(
    page: Page,
    profile: dict,
    job_id: int,
    ai=None,
    job_context: dict = None,
) -> dict:
    result = {"filled": [], "skipped": [], "needs_manual": [], "screenshot_path": ""}

    await dismiss_popups(page)
    await asyncio.sleep(0.5)

    # Click apply button
    for sel in APPLY_SELECTORS:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.5)
                break
        except Exception:
            pass

    await dismiss_popups(page)  # dismiss post-click popups

    # Naukri modal fields
    async def _fill(selector: str, value: str, label: str):
        if not value:
            return
        el = await page.query_selector(selector)
        if el:
            ok = await fill_text_field(el, value)
            (result["filled"] if ok else result["needs_manual"]).append(label)

    full = profile.get("full_name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    await _fill("input[placeholder*='name' i], input[name*='name' i]",     full,                            "Full name")
    await _fill("input[placeholder*='email' i], input[name*='email' i]",   profile.get("email", ""),        "Email")
    await _fill("input[placeholder*='mobile' i], input[name*='phone' i]",  profile.get("phone", ""),        "Mobile")
    await _fill("input[placeholder*='experience' i]",                      profile.get("years_experience",""), "Experience")
    await _fill("input[placeholder*='ctc' i], input[placeholder*='salary' i]", profile.get("salary_expectation",""), "Expected CTC")
    await _fill("input[placeholder*='notice' i]",                          profile.get("notice_period", ""), "Notice period")

    # Resume
    if profile.get("resume_path"):
        ok = await upload_resume(page, profile["resume_path"])
        if ok:
            result["filled"].append("Resume")

    # Generic pass for remaining fields
    extra = await fill_generic_form(page, profile, job_id, ai=ai, job_context=job_context)
    for f2 in extra["filled"]:
        if f2 not in result["filled"]:
            result["filled"].append(f2)
    result["needs_manual"].extend(extra["needs_manual"])

    result["screenshot_path"] = await take_screenshot(page, job_id, "naukri_filled")
    return result

