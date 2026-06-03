"""hiring.cafe keyword-based discovery via Playwright (React SPA)."""
from __future__ import annotations
import asyncio, random
from urllib.parse import quote_plus
from playwright.async_api import BrowserContext, TimeoutError as PWTimeout
from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

HIRING_CAFE_SEARCH = "https://hiring.cafe/?searchQuery={query}"

async def _delay(mn=1500, mx=3000):
    await asyncio.sleep(random.uniform(mn/1000, mx/1000))

class HiringCafeDiscoverer(BaseDiscoverer):

    async def discover(self, context: BrowserContext = None, company=None) -> list[JobListing]:
        keywords = self.filters.get("keywords", ["software engineer"])
        listings: list[JobListing] = []

        # HiringCafe is a React SPA - needs browser
        if context is None:
            log.warning("[HiringCafe] No browser context provided - skipping")
            return []

        page = await context.new_page()
        try:
            for kw in keywords[:2]:
                results = await self._search(page, kw)
                listings.extend(results)
                await _delay()
        finally:
            await page.close()

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[HiringCafe] {len(unique)} unique jobs found")
        return unique

    async def _search(self, page, keyword: str) -> list[JobListing]:
        url = HIRING_CAFE_SEARCH.format(query=quote_plus(keyword))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await _delay(3000, 5000)  # Wait for React to render
        except PWTimeout:
            log.warning(f"[HiringCafe] Timeout: {keyword}")
            return []

        # Try multiple selectors
        cards = []
        for sel in ["[class*='JobCard']","[class*='job-card']","[class*='listing']","article","[data-job]"]:
            cards = await page.query_selector_all(sel)
            if len(cards) > 2:
                log.debug(f"[HiringCafe] '{keyword}': {len(cards)} cards with {sel!r}")
                break

        listings = []
        for card in cards[:20]:
            try:
                title_el = await card.query_selector("h2,h3,[class*='title'],[class*='Title']")
                link_el  = await card.query_selector("a[href]")
                co_el    = await card.query_selector("[class*='company'],[class*='Company']")
                loc_el   = await card.query_selector("[class*='location'],[class*='Location']")

                if not title_el or not link_el: continue

                title   = (await title_el.inner_text()).strip()
                href    = await link_el.get_attribute("href") or ""
                company = (await co_el.inner_text()).strip() if co_el else "Unknown"
                loc_txt = (await loc_el.inner_text()).strip() if loc_el else "India"

                if not href.startswith("http"):
                    href = "https://hiring.cafe" + href

                if not self.matches_filters(title, loc_txt): continue

                listings.append(JobListing(
                    title=title, company_name=company or "Unknown",
                    job_url=href, portal="hiring_cafe",
                    location=loc_txt, work_mode=detect_work_mode(title, loc_txt),
                ))
            except Exception as e:
                log.debug(f"[HiringCafe] Card error: {e}")

        return listings
