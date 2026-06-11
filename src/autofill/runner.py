"""
Autofill runner — persistent browser window, new tab per job.
Loads profile from DB, routes to portal-specific handler, waits for user confirmation.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Optional, Callable

from playwright.async_api import async_playwright, BrowserContext
from src.utils import log

PROJECT_ROOT    = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR     = PROJECT_ROOT / "data" / "browser_profile" / "autofill"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

_sessions: dict                       = {}
_browser_ctx: Optional[BrowserContext] = None
_browser_lock                          = threading.Lock()
_playwright_instance                   = None


# ── Portal routing ────────────────────────────────────────────────────────────

def _route_portal(portal: str, url: str):
    """Return the autofill coroutine for a given portal / URL."""
    from .linkedin   import apply_linkedin
    from .greenhouse import apply_greenhouse
    from .lever      import apply_lever
    from .naukri     import apply_naukri
    from .glassdoor  import apply_glassdoor
    from .generic    import fill_generic_form

    url_lo    = url.lower()
    portal_lo = portal.lower()

    if "linkedin.com"  in url_lo or "linkedin"   in portal_lo: return apply_linkedin
    if "greenhouse.io" in url_lo or "greenhouse" in portal_lo: return apply_greenhouse
    if "lever.co"      in url_lo or "lever"      in portal_lo: return apply_lever
    if "naukri.com"    in url_lo or "naukri"     in portal_lo: return apply_naukri
    if "glassdoor.com" in url_lo or "glassdoor"  in portal_lo: return apply_glassdoor

    return lambda page, profile, job_id, **kw: fill_generic_form(page, profile, job_id, **kw)


# ── Browser management ────────────────────────────────────────────────────────

async def _get_or_create_context() -> BrowserContext:
    global _browser_ctx, _playwright_instance
    if _browser_ctx:
        try:
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
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    log.info("[Autofill] Browser window opened")
    return _browser_ctx


# ── Session helpers ───────────────────────────────────────────────────────────

def get_session(job_id: int) -> Optional[dict]:
    return _sessions.get(job_id)


def clear_session(job_id: int):
    _sessions.pop(job_id, None)


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_autofill(
    job_id:      int,
    job_url:     str,
    portal:      str,
    username:    str = "",
    on_progress: Callable = None,
    ai           = None,
    job_context: dict = None,
) -> dict:
    def _prog(msg: str):
        log.info(f"[Autofill] {msg}")
        if on_progress:
            on_progress(msg)

    from .profile_adapter import load_autofill_profile
    profile = load_autofill_profile(username)
    if not profile.get("email"):
        _prog("WARNING: Profile is empty — fill in your Profile page first")

    handler = _route_portal(portal, job_url)
    result  = {
        "job_id": job_id, "portal": portal,
        "filled": [], "needs_manual": [], "status": "running",
    }

    _prog(f"Opening browser tab for job {job_id} ({portal})")
    ctx  = await _get_or_create_context()
    page = await ctx.new_page()

    try:
        _prog("Navigating to job page...")
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

        _prog(f"Running {handler.__module__.split('.')[-1]} handler...")
        fill_result = await handler(
            page, profile, job_id,
            ai=ai,
            job_context=job_context,
        )
        result.update(fill_result)
        result["status"] = "waiting_confirm"

        from .base import take_screenshot
        ss = await take_screenshot(page, job_id, "review")
        result["screenshot_path"] = ss

        _prog(f"Done — {len(result.get('filled',[]))} fields filled, "
              f"{len(result.get('needs_manual',[]))} need manual input")

        # Register session and wait for confirm / cancel (10 min timeout)
        loop          = asyncio.get_event_loop()
        confirmed_evt = asyncio.Event()
        cancelled_evt = asyncio.Event()
        _sessions[job_id] = {
            "result":    result,
            "page":      page,
            "ctx":       ctx,
            "confirmed": confirmed_evt,
            "cancelled": cancelled_evt,
            "loop":      loop,
        }

        _prog("Waiting for your confirmation in the dashboard...")
        done, _ = await asyncio.wait(
            [asyncio.ensure_future(confirmed_evt.wait()),
             asyncio.ensure_future(cancelled_evt.wait())],
            timeout=600,
        )

        if confirmed_evt.is_set():
            _prog("Confirmed — submitting application...")
            try:
                submit_sel = result.get(
                    "submit_selector",
                    "button[type='submit'], input[type='submit'], "
                    "button:has-text('Submit'), button:has-text('Apply')"
                )
                btn = await page.query_selector(submit_sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(2)
                    ss_done = await take_screenshot(page, job_id, "submitted")
                    result["confirmation_screenshot"] = ss_done
                    result["status"] = "submitted"
                    _prog("Application submitted!")
                else:
                    result["status"] = "submit_button_not_found"
                    _prog("Submit button not found — please submit manually in the browser")
            except Exception as e:
                result["status"] = "submit_error"
                result["error"]  = str(e)
        else:
            result["status"] = "cancelled"
            _prog("Cancelled")

    except Exception as e:
        log.error(f"[Autofill] Fatal error for job {job_id}: {e}")
        result["status"] = "error"
        result["error"]  = str(e)
        try:
            from .base import take_screenshot as ts
            result["screenshot_path"] = await ts(page, job_id, "error")
        except Exception:
            pass
        # Update pre-registered session if it exists
        if job_id in _sessions:
            _sessions[job_id]["result"].update(result)
    finally:
        try:
            await page.close()
        except Exception:
            pass
        clear_session(job_id)

    return result


# ── Confirm / cancel (called from API thread) ─────────────────────────────────

def confirm_apply(job_id: int):
    s = _sessions.get(job_id)
    if s:
        loop = s.get("loop")
        evt  = s.get("confirmed")
        if loop and loop.is_running() and evt:
            loop.call_soon_threadsafe(evt.set)
        elif evt:
            evt.set()


def cancel_apply(job_id: int):
    s = _sessions.get(job_id)
    if s:
        loop = s.get("loop")
        evt  = s.get("cancelled")
        if loop and loop.is_running() and evt:
            loop.call_soon_threadsafe(evt.set)
        elif evt:
            evt.set()
