"""
Base autofiller — shared utilities for all portal-specific fillers.
Handles field detection, smart mapping, human-like typing, screenshots.
"""
from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import Page
from src.utils import log

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Field label → profile key mapping ─────────────────────────────────────
FIELD_MAP = {
    # Personal
    r"first.?name":          "personal.first_name",
    r"last.?name":           "personal.last_name",
    r"full.?name|your name": "personal.full_name",
    r"email":                "personal.email",
    r"phone|mobile":         "personal.phone",
    r"linkedin":             "personal.linkedin_url",
    r"github":               "personal.github_url",
    r"portfolio|website":    "personal.portfolio_url",
    r"city":                 "personal.location.city",
    r"state|province":       "personal.location.state",
    r"country":              "personal.location.country",
    r"zip|postal":           "personal.location.zip",
    # Professional
    r"years.*(experience|exp)": "professional.years_experience",
    r"current.*(title|position|role)": "professional.current_title",
    r"current.*(company|employer)": "professional.current_company",
    r"notice.?period":       "professional.notice_period_days",
    r"expected.*(salary|ctc|compensation)": "professional.expected_ctc",
    r"current.*(salary|ctc)": "professional.current_ctc",
    # Screening
    r"authorized|eligible|right to work": "answers.work_authorization",
    r"gender":               "answers.gender",
    r"veteran":              "answers.veteran_status",
    r"disability":           "answers.disability",
    r"salary.*expect|expect.*salary|desired.*salary": "answers.salary_expectation",
    r"earliest.*start|when.*start|available": "answers.earliest_start",
    r"relocation|relocate":  "professional.willing_to_relocate",
}


def resolve_field(label: str, profile: dict) -> Optional[str]:
    """Map a form field label to a profile value."""
    label_lo = label.lower().strip()
    for pattern, key_path in FIELD_MAP.items():
        if re.search(pattern, label_lo):
            val = profile
            for k in key_path.split("."):
                if isinstance(val, dict):
                    val = val.get(k)
                else:
                    val = None
                    break
            if val is not None:
                return str(val)
    return None


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type text with human-like delays."""
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.fill(selector, "")
    for char in str(text):
        await page.type(selector, char, delay=random.randint(30, 120))
    await asyncio.sleep(random.uniform(0.1, 0.2))


async def take_screenshot(page: Page, job_id: int, step: str = "filled") -> str:
    """Take a screenshot and return the file path."""
    filename = f"job_{job_id}_{step}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
    path = SCREENSHOTS_DIR / filename
    await page.screenshot(path=str(path), full_page=True)
    return str(path)


async def fill_text_field(page, el, value: str) -> bool:
    """Fill a text input or textarea."""
    try:
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        input_type = await el.get_attribute("type") or "text"
        if tag in ("input", "textarea") and input_type not in ("checkbox", "radio", "file", "submit", "button"):
            await el.click()
            await asyncio.sleep(0.1)
            await el.fill("")
            await el.type(value, delay=random.randint(30, 80))
            return True
    except Exception:
        pass
    return False


async def select_option(page, el, value: str) -> bool:
    """Select from a dropdown."""
    try:
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        if tag == "select":
            options = await el.query_selector_all("option")
            for opt in options:
                txt = (await opt.inner_text()).strip().lower()
                if value.lower() in txt or txt in value.lower():
                    await el.select_option(value=await opt.get_attribute("value"))
                    return True
            # Try by label
            await el.select_option(label=value)
            return True
    except Exception:
        pass
    return False
