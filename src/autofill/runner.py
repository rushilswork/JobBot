"""
Autofill runner — persistent browser, new tab per job.
First use opens one browser window. All subsequent auto-applies
open as new tabs in that same window (login session preserved).
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Optional, Callable

import yaml
from playwright.async_api import async_playwright, BrowserContext

from src.utils import log

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profile" / "autofill"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

_sessions: dict = {}

# Persistent browser state — shared across all auto-apply calls
_browser_ctx: Optional[BrowserContext] = None
_browser_lock = threading.Lock()
_playwright_instance = None


def load_profile() -> dict:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError("Fill in config/profile.yaml before using auto-apply")
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f) or {}


def get_session(job_id: int) -> Optional[dict]:
    return _sessions.get(job_id)


def clear_session(job_id: int):
    _sessions.pop(job_id, None)


async def _get_or_create_context() -> BrowserContext:
    """Get existing browser context or create a new one. Reuses window."""
    global _browser_ctx, _playwright_instance
    if _browser_ctx:
        try:
            # Test if still alive
            _ = _browser_ctx.pages
            return _browser_ctx
        except Exception:
            _browser_ctx = None

    if _playwright_instance is None:
        _playwright_instance = await async_playwright().start()

    _browser_ctx = await _playwright_instance.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
    )
    log.info("[Autofill] Browser window opened")
    return _browser_ctx


async def run_autofill(job_id: int, job_url: str, portal: str, on_progress: Callable = None) -> dict:
    def _prog(msg):
        log.info(f"[Autofill] {msg}")
        if on_progress: on_progress(msg)

    profile = load_profile()
    result = {"job_id": job_id, "portal": portal, "filled": [], "needs_manual": [], "status": "running"}

    _prog(f"Opening new tab for job {job_id}")

    ctx = await _get_or_create_context()
    page = await ctx.new_page()  # New TAB in existing window

    try:
        _prog("Navigating to job URL")
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

        if "linkedin.com" in job_url:
            from .linkedin import apply_linkedin
            result.update(await apply_linkedin(page, profile, job_id))
        else:
            from .generic import fill_generic_form
            result.update(await fill_generic_form(page, profile, job_id))

        result["status"] = "waiting_confirm"

        # Screenshot for review modal
        ss_path = SCREENSHOTS_DIR / f"job_{job_id}_review.png"
        await page.screenshot(path=str(ss_path), full_page=False)
        result["screenshot_path"] = str(ss_path)

        _prog("Form filled — waiting for confirmation")

        loop = asyncio.get_event_loop()
        confirmed_evt = asyncio.Event()
        cancelled_evt = asyncio.Event()
        _sessions[job_id] = {
            "result": result, "page": page, "ctx": ctx,
            "confirmed": confirmed_evt, "cancelled": cancelled_evt, "loop": loop,
        }

        done, _ = await asyncio.wait(
            [asyncio.ensure_future(confirmed_evt.wait()),
             asyncio.ensure_future(cancelled_evt.wait())],
            timeout=600
        )

        if confirmed_evt.is_set():
            _prog("Confirmed — submitting")
            try:
                submit_sel = result.get("submit_selector",
                    "button[type='submit'], button:has-text('Submit'), button:has-text('Apply')")
                btn = await page.query_selector(submit_sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(2)
                    ss_done = SCREENSHOTS_DIR / f"job_{job_id}_submitted.png"
                    await page.screenshot(path=str(ss_done), full_page=False)
                    result["confirmation_screenshot"] = str(ss_done)
                    result["status"] = "submitted"
                    _prog("Submitted ✓")
                else:
                    result["status"] = "submit_button_not_found"
            except Exception as e:
                result["status"] = "submit_error"
                result["error"] = str(e)
        else:
            result["status"] = "cancelled"

    except Exception as e:
        log.error(f"[Autofill] {e}")
        result["status"] = "error"
        result["error"] = str(e)
        try:
            ss_err = SCREENSHOTS_DIR / f"job_{job_id}_error.png"
            await page.screenshot(path=str(ss_err))
            result["screenshot_path"] = str(ss_err)
        except Exception: pass
    finally:
        # Close the tab, not the whole browser
        try:
            await page.close()
        except Exception: pass
        clear_session(job_id)

    return result


def confirm_apply(job_id: int):
    s = _sessions.get(job_id)
    if s:
        loop = s.get("loop")
        if loop and loop.is_running():
            loop.call_soon_threadsafe(s["confirmed"].set)
        else:
            s["confirmed"].set()


def cancel_apply(job_id: int):
    s = _sessions.get(job_id)
    if s:
        loop = s.get("loop")
        if loop and loop.is_running():
            loop.call_soon_threadsafe(s["cancelled"].set)
        else:
            s["cancelled"].set()
