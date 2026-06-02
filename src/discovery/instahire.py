"""InstaHire keyword-based discovery via Playwright."""
from __future__ import annotations

import asyncio
import random
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, TimeoutError as PWTimeout

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

INSTAHIRE_SEARCH = "https://instahire.app/jobs?q={query}&location={location}"

async def _delay(mn=1000, mx=2500):
    await asyncio.sleep(random.uniform(mn/1000, mx/1000))


class InstahireDiscoverer(BaseDiscoverer):

    async def discover(self, context: BrowserContext, company=None) -> list[JobListing]:
        keywords  = self.filters.get("keywords", ["software engineer"])
        locations = self.filters.get("locations", ["India"])
        listings: list[JobListing] = []

        page = await context.new_page()
        try:
            for kw in keywords[:2]:
                for loc in locations[:2]:
                    results = await self._search(page, kw, loc)
                    listings.extend(results)
                    await _delay()
        finally:
            await page.close()

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Instahire] {len(unique)} unique jobs found")
        return unique

    async def _search(self, page, keyword: str, location: str) -> list[JobListing]:
        url = INSTAHIRE_SEARCH.format(query=quote_plus(keyword), location=quote_plus(location))
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await _delay(1500, 2500)
        except PWTimeout:
            log.warning(f"[Instahire] Timeout: {keyword} @ {location}")
            return []

        cards = await page.query_selector_all(
            "div[class*='JobCard'], article[class*='job'], div[class*='job-item'], div[class*='job-card']"
        )
        log.debug(f"[Instahire] '{keyword}' @ {location}: {len(cards)} cards")

        listings = []
        for card in cards[:20]:
            try:
                title_el   = await card.query_selector("h2, h3, [class*='title']")
                loc_el     = await card.query_selector("[class*='location'], [class*='place']")
                company_el = await card.query_selector("[class*='company']")
                link_el    = await card.query_selector("a")
                if not title_el:
                    continue

                title   = (await title_el.inner_text()).strip()
                loc_txt = (await loc_el.inner_text()).strip() if loc_el else location
                company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                href    = await link_el.get_attribute("href") if link_el else ""
                if href and not href.startswith("http"):
                    href = "https://instahire.app" + href
                if not href or not title:
                    continue

                if not self.matches_filters(title, loc_txt):
                    continue

                listings.append(JobListing(
                    title=title, company_name=company or "Unknown",
                    job_url=href, portal="instahire",
                    location=loc_txt, work_mode=detect_work_mode(title, loc_txt),
                ))
            except Exception as e:
                log.debug(f"[Instahire] Card error: {e}")

        return listings
