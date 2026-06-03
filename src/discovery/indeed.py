"""Indeed India job discovery via HTTP scraping."""
from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

INDEED_URL = "https://in.indeed.com/jobs?q={kw}&l={loc}&fromage=7&sort=date&start={start}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


class IndeedDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company=None) -> list[JobListing]:
        keywords  = self.filters.get("keywords", ["software engineer"])
        locations = self.filters.get("locations", ["India"])
        listings: list[JobListing] = []

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for kw in keywords[:3]:
                for loc in locations[:2]:
                    for start in [0, 10, 20]:
                        results = await self._fetch(session, kw, loc, start)
                        listings.extend(results)
                        if len(results) < 5:
                            break
                        await asyncio.sleep(1.5)

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Indeed] {len(unique)} unique jobs found")
        return unique

    async def _fetch(self, session, kw, loc, start) -> list[JobListing]:
        url = INDEED_URL.format(kw=quote_plus(kw), loc=quote_plus(loc), start=start)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
        except Exception as e:
            log.warning(f"[Indeed] {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.job_seen_beacon, div.tapItem, td.resultContent")
        log.debug(f"[Indeed] '{kw}' @ {loc} start={start}: {len(cards)} cards")

        listings = []
        for card in cards:
            try:
                title_el   = card.select_one("h2.jobTitle a, a.jcs-JobTitle, h2 a")
                company_el = card.select_one("span.companyName, [data-testid='company-name']")
                loc_el     = card.select_one("div.companyLocation, [data-testid='text-location']")

                if not title_el:
                    continue

                title   = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                loc_txt = loc_el.get_text(strip=True) if loc_el else loc
                href    = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://in.indeed.com" + href
                href = href.split("?")[0]

                if not title or not href:
                    continue
                if not self.matches_filters(title, loc_txt):
                    continue

                posted_at = None
                try:
                    t = card.select_one("span.date,time[datetime],[class*='date']")
                    if t and t.get("datetime"):
                        from datetime import datetime as dt
                        posted_at = dt.fromisoformat(t["datetime"].replace("Z","").split("+")[0].split(".")[0])
                except Exception: pass

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href, portal="indeed", location=loc_txt,
                    work_mode=detect_work_mode(title, loc_txt),
                    posted_at=posted_at,
                ))
            except Exception as e:
                log.debug(f"[Indeed] Card error: {e}")

        return listings
