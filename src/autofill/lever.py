"""
Lever ATS — /apply page with standard input[name=...] selectors.
"""
from __future__ import annotations
import asyncio
from playwright.async_api import Page
from .base import fill_text_field, upload_resume, take_screenshot, dismiss_popups
from .generic import fill_generic_form
from src.utils import log


async def apply_lever(
    page: Page,
    profile: dict,
    job_id: int,
    ai=None,
    job_context: dict = None,
) -> dict:
    result = {"filled": [], "skipped": [], "needs_manual": [], "screenshot_path": ""}

    # Lever apply URL is job URL + /apply
    current_url = page.url
    if "/apply" not in current_url:
        try:
            apply_url = current_url.rstrip("/") + "/apply"
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(1)
        except Exception as e:
            log.warning(f"[Lever] Navigate to /apply failed: {e}")

    await dismiss_popups(page)

    async def _fill(selector: str, value: str, label: str):
        if not value:
            return
        el = await page.query_selector(selector)
        if el:
            ok = await fill_text_field(el, value)
            (result["filled"] if ok else result["needs_manual"]).append(label)

    full = profile.get("full_name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    await _fill("input[name='name']",              full,                               "Full name")
    await _fill("input[name='email']",             profile.get("email", ""),           "Email")
    await _fill("input[name='phone']",             profile.get("phone", ""),           "Phone")
    await _fill("input[name='org']",               profile.get("current_company", ""), "Current company")
    await _fill("input[name='urls[LinkedIn]']",    profile.get("linkedin_url", ""),    "LinkedIn")
    await _fill("input[name='urls[GitHub]']",      profile.get("github_url", ""),      "GitHub")
    await _fill("input[name='urls[Portfolio]']",   profile.get("portfolio_url", ""),   "Portfolio")

    # Cover letter
    cover = (job_context or {}).get("cover_letter", "")
    if cover:
        for sel in ("textarea[name='comments']", "textarea[name='cover_letter']", "textarea"):
            cl = await page.query_selector(sel)
            if cl:
                ok = await fill_text_field(cl, cover)
                if ok:
                    result["filled"].append("Cover letter")
                    break

    # Resume
    if profile.get("resume_path"):
        ok = await upload_resume(page, profile["resume_path"])
        if ok:
            result["filled"].append("Resume")

    # Generic pass for custom / extra questions
    extra = await fill_generic_form(page, profile, job_id, ai=ai, job_context=job_context)
    for f2 in extra["filled"]:
        if f2 not in result["filled"]:
            result["filled"].append(f2)
    result["needs_manual"].extend(extra["needs_manual"])

    result["screenshot_path"] = await take_screenshot(page, job_id, "lever_filled")
    return result
