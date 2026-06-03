"""Glassdoor job discovery via Playwright (handles JS rendering)."""
from __future__ import annotations

import asyncio
import random
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, TimeoutError as PWTimeout

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

GLASSDOOR_URL = "https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={kw}&locT=N&locId=115&fromAge=7&sort.sortType=date&sort.descending=true"

async def _delay(mn=1000, mx=2500):
    await asyncio.sleep(random.uniform(mn/1000, mx/1000))


class GlassdoorDiscoverer(BaseDiscoverer):

    async def discover(self, context: BrowserContext, company=None) -> list[JobListing]:
        keywords = self.filters.get("keywords", ["software engineer"])
        listings: list[JobListing] = []

        page = await context.new_page()
        try:
            for kw in keywords[:3]:
                results = await self._search(page, kw)
                listings.extend(results)
                await _delay(1500, 3000)
        finally:
            await page.close()

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Glassdoor] {len(unique)} unique jobs found")
        return unique

    async def _search(self, page, kw: str) -> list[JobListing]:
        url = GLASSDOOR_URL.format(kw=quote_plus(kw))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await _delay(2000, 3500)
        except PWTimeout:
            log.warning(f"[Glassdoor] Timeout for '{kw}'")
            return []

        # Dismiss modal if present
        try:
            close = await page.query_selector("[alt='Close'], button[class*='modal'] svg, [data-test='modal-close']")
            if close:
                await close.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        cards = await page.query_selector_all(
            "li.react-job-listing, div.jobCard, [data-test='jobListing'], li[class*='JobsList']"
        )
        log.debug(f"[Glassdoor] '{kw}': {len(cards)} cards on {page.url[:60]}")

        listings = []
        for card in cards[:25]:
            try:
                title_el   = await card.query_selector("[data-test='job-title'], a.jobLink, [class*='JobCard_jobTitle']")
                company_el = await card.query_selector("[class*='EmployerProfile'], [data-test='employer-name'], [class*='jobEmpolyerName']")
                loc_el     = await card.query_selector("[data-test='emp-location'], [class*='JobCard_location']")
                link_el    = await card.query_selector("a[href*='/job-listing/'], a[href*='glassdoor']")

                if not title_el:
                    continue

                title   = (await title_el.inner_text()).strip()
                company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                loc_txt = (await loc_el.inner_text()).strip() if loc_el else "India"
                href    = await (link_el or title_el).get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.glassdoor.co.in" + href

                if not title or not href:
                    continue
                if not self.matches_filters(title, loc_txt):
                    continue

                posted_at = None
                try:
                    t = await card.query_selector("time[datetime],[data-test*='job-age'],[class*='age'],[class*='date']")
                    if t:
                        dt_val = await t.get_attribute("datetime") or await t.inner_text()
                        if dt_val and 'T' in str(dt_val):
                            from datetime import datetime as dt2
                            posted_at = dt2.fromisoformat(str(dt_val).replace("Z","").split("+")[0])
                except Exception: pass

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href, portal="glassdoor", location=loc_txt,
                    work_mode=detect_work_mode(title, loc_txt),
                    posted_at=posted_at,
                ))
            except Exception as e:
                log.debug(f"[Glassdoor] Card error: {e}")

        return listings
