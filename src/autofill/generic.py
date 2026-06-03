"""
Generic form filler — works on any ATS or job application form.
Detects fields by label text, fills using profile data.
"""
from __future__ import annotations
import asyncio, random
from playwright.async_api import Page
from .base import resolve_field, fill_text_field, select_option, take_screenshot, human_type
from src.utils import log


async def fill_generic_form(page: Page, profile: dict, job_id: int) -> dict:
    """
    Detect and fill all form fields on current page.
    Returns dict with results: {filled, skipped, needs_manual, screenshot_path}
    """
    filled = []
    skipped = []
    needs_manual = []

    # Dismiss cookie/GDPR banners first
    try:
        for sel in [
            "button:has-text('Accept all')", "button:has-text('Accept All')",
            "button:has-text('Accept cookies')", "button:has-text('I Accept')",
            "button:has-text('Agree')", "button:has-text('Got it')",
            "[id*='cookie'] button", "[class*='cookie'] button[class*='accept']",
            "[class*='consent'] button[class*='accept']",
        ]:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                break
    except Exception: pass

    # Upload resume if there's a file input
    try:
        resume_input = await page.query_selector("input[type='file']")
        if resume_input:
            resume_path = profile.get("resume", {}).get("path", "")
            if resume_path:
                import os
                from pathlib import Path
                full_path = Path(__file__).resolve().parent.parent.parent / resume_path
                if full_path.exists():
                    await resume_input.set_input_files(str(full_path))
                    filled.append("Resume")
                    await asyncio.sleep(1)
    except Exception as e:
        log.debug(f"[Autofill] Resume upload: {e}")

    # Find all form fields
    fields = await page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select")

    for field in fields:
        try:
            # Get the label for this field
            field_id = await field.get_attribute("id") or ""
            field_name = await field.get_attribute("name") or ""
            field_placeholder = await field.get_attribute("placeholder") or ""
            aria_label = await field.get_attribute("aria-label") or ""

            # Try to find associated label element
            label_text = ""
            if field_id:
                lbl = await page.query_selector(f"label[for='{field_id}']")
                if lbl:
                    label_text = (await lbl.inner_text()).strip()

            # Use best available label
            label = label_text or aria_label or field_placeholder or field_name

            if not label:
                skipped.append(f"unlabeled field")
                continue

            # Skip cookie consent, GDPR, tracking fields - not part of job application
            NOISE_PATTERNS = [
                'cookie', 'gdpr', 'consent', 'tracking', 'analytics', 'marketing',
                'functional', 'performance', 'targeting', 'tothr', 'checkbox label',
                'privacy policy', 'terms', 'subscribe', 'newsletter', 'captcha',
            ]
            if any(n in label.lower() for n in NOISE_PATTERNS):
                skipped.append(label)
                continue

            # Resolve value from profile
            value = resolve_field(label, profile)

            if value:
                tag = await field.evaluate("e => e.tagName.toLowerCase()")
                if tag == "select":
                    ok = await select_option(page, field, value)
                else:
                    ok = await fill_text_field(page, field, value)
                if ok:
                    filled.append(label)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                else:
                    skipped.append(label)
            else:
                needs_manual.append(label)

        except Exception as e:
            log.debug(f"[Autofill] Field error: {e}")

    screenshot_path = await take_screenshot(page, job_id, "filled")

    return {
        "filled": filled,
        "skipped": skipped,
        "needs_manual": needs_manual,
        "screenshot_path": screenshot_path,
    }
