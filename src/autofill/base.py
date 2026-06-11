"""
Base autofill utilities — shared across all portal handlers.
Field detection (6 strategies), human typing, nav filtering, popup dismissal, resume upload.
"""
from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, ElementHandle
from src.utils import log

PROJECT_ROOT    = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Field → profile key map (ordered, first match wins) ──────────────────────
FIELD_MAP: list[tuple[str, str]] = [
    (r"first[\s\-_]*name",                    "first_name"),
    (r"last[\s\-_]*name|surname|family",      "last_name"),
    (r"full[\s\-_]*name|your[\s\-_]*name|complete[\s\-_]*name", "full_name"),
    (r"e[\s\-_]*mail",                        "email"),
    (r"phone|mobile|contact[\s\-_]*no",       "phone"),
    (r"linkedin",                             "linkedin_url"),
    (r"github",                               "github_url"),
    (r"portfolio|personal[\s\-_]*website|website[\s\-_]*url", "portfolio_url"),
    (r"\bcity\b",                             "city"),
    (r"\bstate\b|\bprovince\b",               "state"),
    (r"\bcountry\b",                          "country"),
    (r"zip|postal[\s\-_]*code|pin[\s\-_]*code", "zip"),
    (r"current[\s\-_]*(title|position|role|designation)", "current_title"),
    (r"current[\s\-_]*(company|employer|organization)",   "current_company"),
    (r"years[\s\-_]*of[\s\-_]*(experience|exp)|total[\s\-_]*exp", "years_experience"),
    (r"notice[\s\-_]*period",                 "notice_period"),
    (r"expected[\s\-_]*(salary|ctc|compensation|package)", "salary_expectation"),
    (r"current[\s\-_]*(salary|ctc)",          "salary_expectation"),
    (r"desired[\s\-_]*(salary|pay)",          "salary_expectation"),
    (r"willing[\s\-_]*to[\s\-_]*relocate|open[\s\-_]*to[\s\-_]*relocation", "willing_to_relocate"),
    (r"work[\s\-_]*mode|remote|hybrid|onsite","work_mode"),
    (r"degree|qualification",                 "degree"),
    (r"field[\s\-_]*of[\s\-_]*study|major|specialization", "field"),
    (r"university|college|institution|school","institution"),
    (r"graduation[\s\-_]*year|passing[\s\-_]*year|year[\s\-_]*of[\s\-_]*grad", "grad_year"),
    (r"authorized|eligible|right[\s\-_]*to[\s\-_]*work|work[\s\-_]*authorization", "work_authorization"),
    (r"salary[\s\-_]*expect|expect.*salary|desired[\s\-_]*compen", "salary_expectation"),
]

CHROME_LABELS: set[str] = {
    "search", "search jobs", "find your perfect job", "job title", "keywords",
    "location", "city, county, region or remote", "city or zip code",
    "where", "what", "find jobs", "search for jobs", "job search",
}

NOISE_PATTERNS: list[str] = [
    "cookie", "gdpr", "consent", "tracking", "analytics", "marketing",
    "newsletter", "subscribe", "captcha", "privacy policy", "terms",
    "functional", "performance", "targeting", "verify", "human",
]

POPUP_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept cookies')",
    "button:has-text('I Accept')",
    "button:has-text('I agree')",
    "button:has-text('Agree')",
    "button:has-text('Got it')",
    "[id*='cookie'] button[class*='accept']",
    "[class*='cookie'] button[class*='accept']",
    "[class*='consent'] button[class*='accept']",
    "[id*='gdpr'] button",
]


async def get_field_label(page: Page, el: ElementHandle) -> str:
    """6-strategy label extraction: label[for], aria-label, aria-labelledby, placeholder, name, DOM walk."""
    try:
        field_id = await el.get_attribute("id") or ""
        if field_id:
            lbl = await page.query_selector(f"label[for='{field_id}']")
            if lbl:
                txt = (await lbl.inner_text()).strip()
                if txt:
                    return txt
        aria = await el.get_attribute("aria-label") or ""
        if aria.strip():
            return aria.strip()
        labelledby = await el.get_attribute("aria-labelledby") or ""
        if labelledby:
            for ref_id in labelledby.split():
                ref = await page.query_selector(f"#{ref_id}")
                if ref:
                    txt = (await ref.inner_text()).strip()
                    if txt:
                        return txt
        ph = await el.get_attribute("placeholder") or ""
        if ph.strip():
            return ph.strip()
        name = await el.get_attribute("name") or ""
        if name.strip():
            return re.sub(r"[_\-]", " ", name).strip()
        label_txt: str = await el.evaluate("""el => {
            let node = el.parentElement;
            for (let i = 0; i < 5; i++) {
                if (!node) break;
                const label = node.querySelector('label, legend, [class*="label"], [class*="title"]');
                if (label && label.innerText && label.innerText.trim()) return label.innerText.trim();
                for (const child of node.childNodes) {
                    if (child.nodeType === 3 && child.textContent.trim().length > 1)
                        return child.textContent.trim();
                }
                node = node.parentElement;
            }
            return '';
        }""")
        return label_txt.strip()
    except Exception:
        return ""


def resolve_field(label: str, profile: dict) -> Optional[str]:
    label_lo = re.sub(r"[\*\:\?]+$", "", label.lower().strip()).strip()
    for pattern, key in FIELD_MAP:
        if re.search(pattern, label_lo):
            val = profile.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return None


async def is_in_nav(el: ElementHandle) -> bool:
    try:
        return await el.evaluate("""el => {
            let node = el;
            for (let i = 0; i < 10; i++) {
                if (!node) break;
                const tag = (node.tagName || '').toLowerCase();
                if (['header','nav','footer'].includes(tag)) return true;
                const cls = (node.className || '').toString().toLowerCase();
                const id  = (node.id || '').toLowerCase();
                if (/nav|navbar|header|topbar|search-bar|site-search/.test(cls + ' ' + id)) return true;
                node = node.parentElement;
            }
            return false;
        }""")
    except Exception:
        return False


def is_noise_label(label: str) -> bool:
    lo = label.lower()
    return any(n in lo for n in NOISE_PATTERNS)


def is_chrome_label(label: str) -> bool:
    return label.lower().strip() in CHROME_LABELS


async def human_type(el: ElementHandle, text: str) -> None:
    try:
        await el.triple_click()
        await asyncio.sleep(0.05)
        await el.press("Backspace")
        for char in str(text):
            await el.type(char, delay=random.randint(25, 90))
        await asyncio.sleep(random.uniform(0.05, 0.15))
    except Exception as e:
        log.debug(f"[human_type] {e}")


async def fill_text_field(el: ElementHandle, value: str) -> bool:
    try:
        tag        = await el.evaluate("e => e.tagName.toLowerCase()")
        input_type = (await el.get_attribute("type") or "text").lower()
        if tag in ("input", "textarea") and input_type not in ("checkbox", "radio", "file", "submit", "button", "hidden"):
            await el.scroll_into_view_if_needed()
            await el.click()
            await asyncio.sleep(random.uniform(0.05, 0.12))
            await el.fill(value)
            await asyncio.sleep(0.08)
            return True
    except Exception as e:
        log.debug(f"[fill_text] {e}")
    return False


async def fill_select(el: ElementHandle, value: str) -> bool:
    try:
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        if tag != "select":
            return False
        options = await el.query_selector_all("option")
        value_lo = value.lower()
        for opt in options:
            txt = (await opt.inner_text()).strip()
            val = await opt.get_attribute("value") or ""
            if txt.lower() == value_lo or val.lower() == value_lo:
                await el.select_option(value=val or txt)
                return True
        for opt in options:
            txt = (await opt.inner_text()).strip()
            val = await opt.get_attribute("value") or ""
            if value_lo in txt.lower() or txt.lower() in value_lo:
                await el.select_option(value=val or txt)
                return True
        return False
    except Exception as e:
        log.debug(f"[fill_select] {e}")
        return False


async def fill_checkbox(el: ElementHandle, value: str) -> bool:
    try:
        should_check = value.lower() in ("yes", "true", "1", "on")
        is_checked   = await el.is_checked()
        if should_check != is_checked:
            await el.click()
        return True
    except Exception as e:
        log.debug(f"[fill_checkbox] {e}")
        return False


async def fill_radio_group(page: Page, name: str, value: str) -> bool:
    try:
        radios = await page.query_selector_all(f"input[type='radio'][name='{name}']")
        value_lo = value.lower()
        for radio in radios:
            rv = (await radio.get_attribute("value") or "").lower()
            label = await get_field_label(page, radio)
            if rv == value_lo or value_lo in rv or (label and value_lo in label.lower()):
                await radio.click()
                return True
        return False
    except Exception as e:
        log.debug(f"[fill_radio] {e}")
        return False


async def dismiss_popups(page: Page) -> None:
    for sel in POPUP_SELECTORS:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.4)
                break
        except Exception:
            pass


async def upload_resume(page: Page, resume_path: str) -> bool:
    if not resume_path or not Path(resume_path).exists():
        log.warning(f"[Autofill] Resume not found: {resume_path}")
        return False
    try:
        for sel in [
            "input[type='file'][accept*='pdf']",
            "input[type='file'][accept*='.pdf']",
            "input[type='file'][accept*='doc']",
            "input[type='file']",
        ]:
            inp = await page.query_selector(sel)
            if inp:
                await inp.set_input_files(resume_path)
                await asyncio.sleep(1.5)
                log.info(f"[Autofill] Resume uploaded: {Path(resume_path).name}")
                return True
    except Exception as e:
        log.warning(f"[Autofill] Resume upload failed: {e}")
    return False


async def take_screenshot(page: Page, job_id: int, step: str = "filled") -> str:
    filename = f"job_{job_id}_{step}_{datetime.utcnow().strftime('%H%M%S')}.png"
    path = SCREENSHOTS_DIR / filename
    try:
        await page.screenshot(path=str(path), full_page=False)
    except Exception as e:
        log.debug(f"[Screenshot] {e}")
    return str(path)
