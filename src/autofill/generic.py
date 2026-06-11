"""
Generic form filler — works on any ATS or job board.
Skips nav/search chrome, handles text/select/radio/checkbox, AI fallback for unknown fields.
"""
from __future__ import annotations
import asyncio, random
from playwright.async_api import Page
from .base import (
    get_field_label, resolve_field, is_in_nav, is_noise_label, is_chrome_label,
    fill_text_field, fill_select, fill_checkbox, fill_radio_group,
    dismiss_popups, upload_resume, take_screenshot,
)
from src.utils import log


async def fill_generic_form(
    page: Page,
    profile: dict,
    job_id: int,
    ai=None,
    job_context: dict = None,
) -> dict:
    filled, skipped, needs_manual = [], [], []

    await dismiss_popups(page)
    await asyncio.sleep(0.5)

    # Upload resume first (before filling text fields)
    resume_path = profile.get("resume_path", "")
    if resume_path:
        ok = await upload_resume(page, resume_path)
        if ok:
            filled.append("Resume")

    # Collect all interactive form fields
    fields = await page.query_selector_all(
        "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']),"
        "textarea, select"
    )

    seen_radio_names: set[str] = set()

    for field in fields:
        try:
            # Skip invisible fields
            if not await field.is_visible():
                continue

            # Skip nav/search chrome inputs
            if await is_in_nav(field):
                continue

            input_type = (await field.get_attribute("type") or "text").lower()
            tag        = await field.evaluate("e => e.tagName.toLowerCase()")

            # Handle radio buttons as a group
            if input_type == "radio":
                name = await field.get_attribute("name") or ""
                if not name or name in seen_radio_names:
                    continue
                seen_radio_names.add(name)
                label = await get_field_label(page, field)
                if not label or is_chrome_label(label) or is_noise_label(label):
                    continue
                value = resolve_field(label, profile)
                if not value and ai:
                    value = await _ask_ai(label, profile, ai, job_context)
                if value:
                    ok = await fill_radio_group(page, name, value)
                    (filled if ok else needs_manual).append(label)
                else:
                    needs_manual.append(label)
                continue

            # Skip file inputs (handled by upload_resume above)
            if input_type == "file":
                continue

            # Get label
            label = await get_field_label(page, field)
            if not label:
                continue

            if is_chrome_label(label) or is_noise_label(label):
                skipped.append(label)
                continue

            # Resolve value
            value = resolve_field(label, profile)

            if not value and ai:
                value = await _ask_ai(label, profile, ai, job_context)

            if not value:
                needs_manual.append(label)
                continue

            # Fill by field type
            if tag == "select":
                ok = await fill_select(field, value)
            elif input_type == "checkbox":
                ok = await fill_checkbox(field, value)
            else:
                ok = await fill_text_field(field, value)

            if ok:
                filled.append(label)
                await asyncio.sleep(random.uniform(0.08, 0.2))
            else:
                needs_manual.append(label)

        except Exception as e:
            log.debug(f"[Generic] Field error: {e}")

    screenshot_path = await take_screenshot(page, job_id, "generic_filled")
    return {
        "filled":          filled,
        "skipped":         skipped,
        "needs_manual":    needs_manual,
        "screenshot_path": screenshot_path,
    }


async def _ask_ai(label: str, profile: dict, ai, job_context: dict = None) -> str:
    """Ask AI to answer an unknown form field given the candidate's profile."""
    if not ai:
        return ""
    try:
        ctx = job_context or {}
        prompt = (
            f"You are filling a job application form for: {ctx.get('title','')} at {ctx.get('company','')}.\n"
            f"Candidate profile:\n"
            f"  Name: {profile.get('full_name','')}\n"
            f"  Skills: {profile.get('skills_str','')}\n"
            f"  Experience: {profile.get('years_experience','')} years\n"
            f"  Current title: {profile.get('current_title','')}\n"
            f"  Notice period: {profile.get('notice_period','')}\n"
            f"  Work auth: {profile.get('work_authorization','')}\n\n"
            f"Form field label: \"{label}\"\n"
            f"Provide a SHORT, direct answer (1-2 sentences max). "
            f"If it's a yes/no question, answer Yes or No. "
            f"If you don't know, reply: SKIP"
        )
        answer = ai.generate_text(prompt)
        if answer and "SKIP" not in answer.upper():
            return answer.strip()[:200]
    except Exception as e:
        log.debug(f"[AI field] {e}")
    return ""
