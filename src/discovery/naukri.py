"""Naukri keyword-based job discovery — updated selectors for 2024 redesign."""
from __future__ import annotations
import asyncio, random
from urllib.parse import quote_plus
from playwright.async_api import BrowserContext, TimeoutError as PWTimeout
from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

NAUKRI_BASE = "https://www.naukri.com"

async def _delay(mn=1000, mx=2500):
    await asyncio.sleep(random.uniform(mn/1000, mx/1000))

class NaukriDiscoverer(BaseDiscoverer):

    async def discover(self, context: BrowserContext, company=None) -> list[JobListing]:
        keywords = self.filters.get("keywords", ["software engineer"])
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
        # Use Naukri search URL directly
        url = f"{NAUKRI_BASE}/jobs?k={quote_plus(keyword)}&l={quote_plus(location)}&jobAge=1"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await _delay(2000, 3500)
        except PWTimeout:
            log.warning(f"[Naukri] Timeout: {keyword} @ {location}")
            return []

        # Try multiple selector generations for Naukri's frequently changing HTML
        CARD_SELECTORS = [
            "article.jobTuple",
            "div.srp-jobtuple-wrapper",
            "[class*='srp-jobtuple']",
            "[data-job-id]",
            "article[class*='job']",
            "div[class*='job-tuple']",
            "li[class*='result']",
        ]
        cards = []
        for sel in CARD_SELECTORS:
            cards = await page.query_selector_all(sel)
            if cards:
                log.debug(f"[Naukri] '{keyword}' @ {location}: {len(cards)} cards with {sel!r}")
                break

        if not cards:
            # Fallback: dump page snippet for debugging
            try:
                body = await page.inner_text("body")
                log.debug(f"[Naukri] No cards found. Page snippet: {body[:300]}")
            except Exception:
                pass
            return []

        listings = []
        for card in cards[:25]:
            try:
                # Try multiple title selectors
                title_el = None
                for t_sel in ["a.title", "a[class*='title']", "[class*='jobTitle'] a", "a[href*='naukri.com/']", "h2 a", "h3 a"]:
                    title_el = await card.query_selector(t_sel)
                    if title_el: break

                if not title_el:
                    continue

                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href") or ""
                if not href.startswith("http"):
                    href = NAUKRI_BASE + href

                # Company
                company = "Unknown"
                for c_sel in ["a.subTitle", "a[class*='comp']", "[class*='compName'] a", "[class*='company']"]:
                    c_el = await card.query_selector(c_sel)
                    if c_el:
                        company = (await c_el.inner_text()).strip()
                        break

                # Location
                loc_text = location
                for l_sel in ["li.location", "span[class*='location']", "[class*='loc']"]:
                    l_el = await card.query_selector(l_sel)
                    if l_el:
                        loc_text = (await l_el.inner_text()).strip()
                        break

                if not href or not title or not company or company.lower() == "unknown":
                    continue

                if not self.matches_filters(title, loc_text):
                    continue

                # Posted date
                posted_at = None
                try:
                    t = await card.query_selector("[class*='date'],[class*='fresh'],time,[class*='ago']")
                    if t:
                        txt = (await t.inner_text()).strip().lower()
                        from datetime import datetime as dt2, timedelta
                        now = dt2.utcnow()
                        if 'today' in txt or 'just' in txt: posted_at = now
                        elif 'hour' in txt:
                            h = int(''.join(filter(str.isdigit, txt)) or '1')
                            posted_at = now - timedelta(hours=h)
                        elif 'day' in txt:
                            d = int(''.join(filter(str.isdigit, txt)) or '1')
                            posted_at = now - timedelta(days=d)
                        elif 'week' in txt:
                            posted_at = now - timedelta(weeks=int(''.join(filter(str.isdigit,txt)) or '1'))
                except Exception: pass

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href.split("?")[0], portal="naukri",
                    location=loc_text, work_mode=detect_work_mode(title, loc_text),
                    posted_at=posted_at,
                ))
            except Exception as e:
                log.debug(f"[Naukri] Card error: {e}")

        return listings
