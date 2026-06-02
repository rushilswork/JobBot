"""Monster India job discovery."""
from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

MONSTER_URL = "https://www.monsterindia.com/srp/results?query={kw}&locations={loc}&jobAge=7"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


class MonsterDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company=None) -> list[JobListing]:
        keywords  = self.filters.get("keywords", ["software engineer"])
        locations = self.filters.get("locations", ["India"])
        listings: list[JobListing] = []

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for kw in keywords[:3]:
                for loc in locations[:2]:
                    results = await self._fetch(session, kw, loc)
                    listings.extend(results)
                    await asyncio.sleep(1.5)

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Monster] {len(unique)} unique jobs found")
        return unique

    async def _fetch(self, session, kw, loc) -> list[JobListing]:
        url = MONSTER_URL.format(kw=quote_plus(kw), loc=quote_plus(loc))
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
        except Exception as e:
            log.warning(f"[Monster] {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.card-apply-content, div.job-card, div[class*='jobCard']")
        log.debug(f"[Monster] '{kw}' @ {loc}: {len(cards)} cards")

        listings = []
        for card in cards:
            try:
                title_el   = card.select_one("h3.title a, a.job-title, h3 a")
                company_el = card.select_one("span.company-name, div.company, [class*='company']")
                loc_el     = card.select_one("span.location, div.location, [class*='location']")
                link_el    = card.select_one("a[href*='monsterindia'], a[href*='/job-']")

                if not title_el:
                    continue

                title   = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                loc_txt = loc_el.get_text(strip=True) if loc_el else loc
                href    = (link_el or title_el).get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.monsterindia.com" + href

                if not title or not href:
                    continue
                if not self.matches_filters(title, loc_txt):
                    continue

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href, portal="monster", location=loc_txt,
                    work_mode=detect_work_mode(title, loc_txt),
                ))
            except Exception as e:
                log.debug(f"[Monster] Card error: {e}")

        return listings
