"""
Greenhouse ATS — standardised field selectors (#first_name, #last_name, etc.)
"""
from __future__ import annotations
import asyncio
from playwright.async_api import Page
from .base import fill_text_field, fill_select, upload_resume, take_screenshot, dismiss_popups
from .generic import fill_generic_form
from src.utils import log


async def apply_greenhouse(
    page: Page,
    profile: dict,
    job_id: int,
    ai=None,
    job_context: dict = None,
) -> dict:
    result = {"filled": [], "skipped": [], "needs_manual": [], "screenshot_path": ""}

    await dismiss_popups(page)
    await asyncio.sleep(1)

    async def _fill(selector: str, value: str, label: str):
        if not value:
            return
        el = await page.query_selector(selector)
        if el:
            ok = await fill_text_field(el, value)
            if ok:
                result["filled"].append(label)
            else:
                result["needs_manual"].append(label)

    await _fill("#first_name",              profile.get("first_name", ""),   "First name")
    await _fill("#last_name",               profile.get("last_name", ""),    "Last name")
    await _fill("#email",                   profile.get("email", ""),        "Email")
    await _fill("#phone",                   profile.get("phone", ""),        "Phone")
    await _fill("#job_application_location",profile.get("city", ""),         "Location")

    # LinkedIn / social links
    for sel, key, lbl in [
        ("input[name*='linkedin']", "linkedin_url", "LinkedIn"),
        ("input[name*='github']",   "github_url",   "GitHub"),
        ("input[name*='website']",  "portfolio_url","Website"),
    ]:
        el = await page.query_selector(sel)
        if el and profile.get(key):
            ok = await fill_text_field(el, profile[key])
            if ok:
                result["filled"].append(lbl)

    # Resume upload
    resume_path = profile.get("resume_path", "")
    if resume_path:
        ok = await upload_resume(page, resume_path)
        if ok:
            result["filled"].append("Resume")

    # Cover letter
    cover = (job_context or {}).get("cover_letter", "")
    if cover:
        cl = await page.query_selector("textarea#cover_letter, textarea[name*='cover']")
        if cl:
            ok = await fill_text_field(cl, cover)
            if ok:
                result["filled"].append("Cover letter")

    # Generic pass for remaining / custom questions
    extra = await fill_generic_form(page, profile, job_id, ai=ai, job_context=job_context)
    for f in extra["filled"]:
        if f not in result["filled"]:
            result["filled"].append(f)
    result["needs_manual"].extend(extra["needs_manual"])

    result["screenshot_path"] = await take_screenshot(page, job_id, "greenhouse_filled")
    return result

