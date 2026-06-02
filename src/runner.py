"""
Discovery runner — keyword-based across all portals.

HTTP portals (no browser): LinkedIn, Indeed, Monster, HiringCafe, Greenhouse, Uplers
Browser portals:           Naukri, Glassdoor, Instahire

All HTTP portals run fully concurrently.
All browser portals share one Chromium instance, run concurrently capped by BROWSER_SEM.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from src.database import Company, JobStatus, get_session, init_db, upsert_job
from src.discovery import (
    LinkedInDiscoverer, NaukriDiscoverer, IndeedDiscoverer,
    MonsterDiscoverer, GlassdoorDiscoverer, GreenhouseDiscoverer,
    HiringCafeDiscoverer, InstahireDiscoverer, UplersDiscoverer,
)
from src.utils import load_config, log

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR  = PROJECT_ROOT / "data" / "browser_profile"

BROWSER_SEM   = 3
PORTAL_TIMEOUT = 300


def _enabled(config: dict, key: str) -> bool:
    cfg = config.get("portals", {}).get(key, {})
    return cfg.get("enabled", True) if isinstance(cfg, dict) else True


def _save(session, listings, discovered_by="system") -> int:
    count = 0
    for l in listings:
        co = session.query(Company).filter_by(name=l.company_name).first()
        if not co:
            co = Company(name=l.company_name)
            session.add(co)
            session.flush()
        _, created = upsert_job(session, {
            "company_id":      co.id,
            "title":           l.title,
            "location":        l.location,
            "description":     l.description,
            "job_url":         l.job_url,
            "portal":          l.portal,
            "external_job_id": l.external_job_id,
            "status":          JobStatus.NEW,
            "discovered_at":   datetime.utcnow(),
            "notes":           f"work_mode:{l.work_mode}",
            "discovered_by":   discovered_by,
        })
        if created:
            count += 1
            tag = f"[{l.work_mode.upper()}]" if l.work_mode != "unknown" else ""
            log.info(f"  + [{l.portal.upper()}] {tag} {l.title} @ {l.company_name}")
    return count


async def run_discovery(headed: bool = False, on_progress=None) -> int:
    headed  = headed or os.environ.get("JOBBOT_HEADED", "").lower() in ("1","true","yes")
    config  = load_config()
    filters = config.get("filters", {})

    # Get who triggered this scan
    from src.background import _read_state
    state = _read_state()
    triggered_by = state.get("triggered_by", "system")

    init_db()
    session   = get_session()
    total_new = 0

    def _prog(msg: str):
        log.info(msg)
        if on_progress: on_progress(msg)

    # ── HTTP portals (aiohttp, no browser) ───────────────────────────────
    http_map = [
        ("linkedin",    LinkedInDiscoverer),
        ("indeed",      IndeedDiscoverer),
        ("monster",     MonsterDiscoverer),
        ("hiring_cafe", HiringCafeDiscoverer),
        ("greenhouse",  GreenhouseDiscoverer),
        ("uplers",      UplersDiscoverer),
    ]
    http_portals = [(k, cls(config, filters)) for k, cls in http_map if _enabled(config, k)]

    async def http_task(key, discoverer):
        nonlocal total_new
        try:
            _prog(f"[{key.upper()}] searching...")
            listings = await discoverer.discover()
            n = _save(session, listings, triggered_by)
            total_new += n
            _prog(f"[{key.upper()}] +{n} new jobs ({len(listings)} found)")
        except Exception as e:
            log.error(f"[{key}] {e}")

    # ── Browser portals ───────────────────────────────────────────────────
    browser_map = [
        ("naukri",    NaukriDiscoverer),
        ("glassdoor", GlassdoorDiscoverer),
        ("instahire", InstahireDiscoverer),
    ]
    browser_portals = [(k, cls(config, filters)) for k, cls in browser_map if _enabled(config, k)]
    browser_sem = asyncio.Semaphore(BROWSER_SEM)

    async def run_browser_portals():
        nonlocal total_new
        if not browser_portals:
            return
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox","--disable-dev-shm-usage","--disable-gpu"],
            )

            async def portal_task(key, discoverer):
                nonlocal total_new
                ctx = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="en-IN", timezone_id="Asia/Kolkata",
                )
                async with browser_sem:
                    try:
                        _prog(f"[{key.upper()}] searching...")
                        listings = await asyncio.wait_for(
                            discoverer.discover(ctx), timeout=PORTAL_TIMEOUT
                        )
                        n = _save(session, listings, triggered_by)
                        total_new += n
                        _prog(f"[{key.upper()}] +{n} new jobs ({len(listings)} found)")
                    except asyncio.TimeoutError:
                        _prog(f"[{key.upper()}] timed out — partial results saved")
                    except Exception as e:
                        log.error(f"[{key}] {e}")
                    finally:
                        await ctx.close()

            await asyncio.gather(*[portal_task(k, d) for k, d in browser_portals])
            await browser.close()

    _prog(f"Starting — {len(http_portals)} HTTP portals, {len(browser_portals)} browser portals")
    await asyncio.gather(
        asyncio.gather(*[http_task(k, d) for k, d in http_portals]),
        run_browser_portals(),
    )

    session.commit()
    session.close()
    _prog(f"Complete — {total_new} new job(s) added")
    return total_new
