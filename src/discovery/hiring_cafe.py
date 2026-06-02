"""hiring.cafe keyword-based discovery via HTTP (server-rendered)."""
from __future__ import annotations

import asyncio
import random
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

HIRING_CAFE_SEARCH = "https://hiring.cafe/search?q={query}&location={location}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class HiringCafeDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company=None) -> list[JobListing]:
        keywords  = self.filters.get("keywords", ["software engineer"])
        locations = self.filters.get("locations", ["India"])
        listings: list[JobListing] = []

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for kw in keywords[:3]:
                for loc in locations[:2]:
                    url = HIRING_CAFE_SEARCH.format(
                        query=quote_plus(kw), location=quote_plus(loc)
                    )
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                continue
                            html = await resp.text()
                    except Exception as e:
                        log.warning(f"[HiringCafe] Request failed: {e}")
                        continue

                    soup = BeautifulSoup(html, "lxml")
                    for card in soup.select("div.job-card, article.job, div[class*='JobCard']")[:20]:
                        try:
                            title_el   = card.select_one("h2, h3, a[class*='title']")
                            loc_el     = card.select_one("[class*='location'], [class*='place']")
                            company_el = card.select_one("[class*='company']")
                            link_el    = card.select_one("a[href]")
                            if not title_el or not link_el:
                                continue

                            title   = title_el.get_text(strip=True)
                            loc_txt = loc_el.get_text(strip=True) if loc_el else loc
                            company = company_el.get_text(strip=True) if company_el else "Unknown"
                            href    = link_el["href"]
                            if not href.startswith("http"):
                                href = "https://hiring.cafe" + href

                            if not self.matches_filters(title, loc_txt):
                                continue

                            listings.append(JobListing(
                                title=title, company_name=company or "Unknown",
                                job_url=href, portal="hiring_cafe",
                                location=loc_txt, work_mode=detect_work_mode(title, loc_txt),
                            ))
                        except Exception as e:
                            log.debug(f"[HiringCafe] Parse error: {e}")

                    await asyncio.sleep(random.uniform(1.0, 2.0))

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[HiringCafe] {len(unique)} unique jobs found")
        return unique
