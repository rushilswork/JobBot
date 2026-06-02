"""Naukri keyword-based job discovery. No company list required."""
from __future__ import annotations

import asyncio
import random
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, TimeoutError as PWTimeout

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

NAUKRI_BASE = "https://www.naukri.com"

async def _delay(mn=1000, mx=2500):
    await asyncio.sleep(random.uniform(mn/1000, mx/1000))


class NaukriDiscoverer(BaseDiscoverer):

    async def discover(self, context: BrowserContext, company=None) -> list[JobListing]:
        keywords  = self.filters.get("keywords", ["software engineer"])
        locations = self.filters.get("locations", ["India"])
        listings: list[JobListing] = []

        page = await context.new_page()
        try:
            for kw in keywords[:3]:
                for loc in locations[:2]:
                    results = await self._search(page, kw, loc)
                    listings.extend(results)
                    await _delay()
        finally:
            await page.close()

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Naukri] {len(unique)} unique jobs found")
        return unique

    async def _search(self, page, keyword: str, location: str) -> list[JobListing]:
        kw_slug  = keyword.lower().replace(" ", "-")
        loc_slug = location.lower().replace(" ", "-")
        url = f"{NAUKRI_BASE}/{kw_slug}-jobs-in-{loc_slug}?jobAge=1&experience=0,3"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await _delay(1500, 3000)
        except PWTimeout:
            log.warning(f"[Naukri] Timeout: {keyword} @ {location}")
            return []

        cards = await page.query_selector_all(
            "article.jobTuple, div.jobTupleHeader, [class*='job-tuple'], [class*='jobTuple']"
        )
        log.debug(f"[Naukri] '{keyword}' @ {location}: {len(cards)} cards")

        listings = []
        for card in cards[:25]:
            try:
                title_el    = await card.query_selector("a.title, a[class*='jobTitle'], [class*='title'] a")
                location_el = await card.query_selector("li.location, span[class*='location'], [class*='location']")
                company_el  = await card.query_selector("a.subTitle, a[class*='companyName'], [class*='compName']")

                if not title_el:
                    continue

                title      = (await title_el.inner_text()).strip()
                loc_text   = (await location_el.inner_text()).strip() if location_el else location
                company    = (await company_el.inner_text()).strip() if company_el else "Unknown"
                href       = await title_el.get_attribute("href") or ""
                if not href.startswith("http"):
                    href = NAUKRI_BASE + href

                if not href or not title:
                    continue

                # Reject blank company (recruiter omitting name)
                if not company or company.lower() in ("", "unknown"):
                    continue

                if not self.matches_filters(title, loc_text):
                    continue

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href.split("?")[0], portal="naukri",
                    location=loc_text, work_mode=detect_work_mode(title, loc_text),
                ))
            except Exception as e:
                log.debug(f"[Naukri] Card error: {e}")

        return listings
