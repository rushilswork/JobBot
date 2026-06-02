"""Uplers remote jobs discovery — India's top remote hiring platform."""
from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

UPLERS_URL   = "https://uplers.com/remote-jobs/?s={kw}"
UPLERS_API   = "https://uplers.com/wp-json/wp/v2/jobs?search={kw}&per_page=50"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html",
}


class UplersDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company=None) -> list[JobListing]:
        keywords = self.filters.get("keywords", ["software engineer"])
        listings: list[JobListing] = []

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for kw in keywords[:3]:
                results = await self._fetch(session, kw)
                listings.extend(results)
                await asyncio.sleep(1.0)

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Uplers] {len(unique)} unique jobs found")
        return unique

    async def _fetch(self, session, kw: str) -> list[JobListing]:
        # Try REST API first
        url = UPLERS_API.format(kw=quote_plus(kw))
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    listings = []
                    for job in data:
                        title   = job.get("title", {}).get("rendered", "")
                        href    = job.get("link", "")
                        loc_txt = "Remote"
                        if not title or not href:
                            continue
                        if not self.matches_filters(title, loc_txt):
                            continue
                        listings.append(JobListing(
                            title=title, company_name="Via Uplers",
                            job_url=href, portal="uplers", location=loc_txt,
                            work_mode="remote",
                        ))
                    return listings
        except Exception:
            pass

        # Fallback: scrape HTML
        url = UPLERS_URL.format(kw=quote_plus(kw))
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
        except Exception as e:
            log.warning(f"[Uplers] {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        listings = []
        for card in soup.select("div.job-card, article.job, [class*='job-listing']")[:30]:
            try:
                title_el   = card.select_one("h2, h3, [class*='title']")
                company_el = card.select_one("[class*='company'], [class*='client']")
                link_el    = card.select_one("a[href]")
                if not title_el or not link_el:
                    continue

                title   = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else "Via Uplers"
                href    = link_el["href"]
                if not href.startswith("http"):
                    href = "https://uplers.com" + href
                if not self.matches_filters(title, "remote"):
                    continue

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href, portal="uplers", location="Remote",
                    work_mode="remote",
                ))
            except Exception as e:
                log.debug(f"[Uplers] {e}")

        return listings
