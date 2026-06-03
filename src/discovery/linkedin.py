"""
LinkedIn job discovery via public guest API — no login required.

Uses the undocumented but stable guest endpoint that LinkedIn uses
for its own public job search pages. Returns HTML fragments parseable
with BeautifulSoup. Fetches multiple pages per keyword+location.
"""
from __future__ import annotations

import asyncio
import random
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

# Public guest API — no auth needed
GUEST_API = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords={kw}&location={loc}&start={start}&count=25&f_TPR=r604800"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs/search/",
}


class LinkedInDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company=None) -> list[JobListing]:
        keywords  = self.filters.get("keywords", ["software engineer"])
        locations = self.filters.get("locations", ["India"])
        listings: list[JobListing] = []

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for kw in keywords:
                for loc in locations[:2]:
                    for start in [0, 25]:  # 2 pages max
                        results = await self._fetch(session, kw, loc, start)
                        listings.extend(results)
                        if len(results) < 10:
                            break   # no more pages
                        await asyncio.sleep(random.uniform(3.0, 5.0))

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = [l for l in unique if l.is_active]
        unique = self.sort_by_preference(unique)
        log.info(f"[LinkedIn] {len(unique)} unique jobs found")
        return unique

    async def _fetch(self, session: aiohttp.ClientSession, kw: str, loc: str, start: int) -> list[JobListing]:
        url = GUEST_API.format(kw=quote_plus(kw), loc=quote_plus(loc), start=start)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 429:
                    log.warning(f"[LinkedIn] Rate limited — backing off 10s")
                    await asyncio.sleep(random.uniform(8.0, 12.0))
                    return []
                if resp.status != 200:
                    log.debug(f"[LinkedIn] HTTP {resp.status} for '{kw}' @ {loc} start={start}")
                    return []
                html = await resp.text()
        except Exception as e:
            log.warning(f"[LinkedIn] Request failed '{kw}' @ {loc}: {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.base-card, li.jobs-search__results-list > li, div.job-search-card")
        log.debug(f"[LinkedIn] '{kw}' @ {loc} start={start}: {len(cards)} cards")

        listings = []
        for card in cards:
            try:
                title_el   = card.select_one("h3.base-search-card__title, h3, a.base-card__full-link")
                company_el = card.select_one("h4.base-search-card__subtitle, a.hidden-nested-link")
                loc_el     = card.select_one("span.job-search-card__location")
                link_el    = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
                closed_el  = card.select_one("[class*='closed'], [class*='no-longer']")

                if not title_el or not link_el:
                    continue

                title   = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                loc_txt = loc_el.get_text(strip=True) if loc_el else loc
                href    = link_el.get("href", "").split("?")[0]

                if not title or not href:
                    continue

                if not self.matches_filters(title, loc_txt):
                    continue

                ext_id = ""
                for part in reversed(href.rstrip("/").split("/")):
                    if part.isdigit():
                        ext_id = part; break

                # Extract posting date from LinkedIn card
                posted_at = None
                try:
                    from datetime import datetime as dt, timedelta
                    # Try datetime attribute first
                    time_el = (card.select_one("time.job-search-card__listdate") or
                               card.select_one("time.job-search-card__listdate--new") or
                               card.select_one("time[datetime]"))
                    if time_el and time_el.get("datetime"):
                        raw = time_el.get("datetime","").replace("Z","").split("+")[0].split(".")[0]
                        posted_at = dt.fromisoformat(raw)
                    else:
                        # Fallback: parse text like "2 days ago", "1 week ago"
                        txt = (time_el.get_text(strip=True) if time_el else "").lower()
                        if not txt:
                            # Try finding any time-related text in card
                            for el in card.select("time,span[class*='time'],span[class*='date']"):
                                t = el.get_text(strip=True).lower()
                                if any(w in t for w in ['ago','hour','day','week','month']):
                                    txt = t; break
                        now = dt.utcnow()
                        if 'second' in txt or 'just' in txt: posted_at = now
                        elif 'minute' in txt:
                            m = int(''.join(filter(str.isdigit,txt)) or '1')
                            posted_at = now - timedelta(minutes=m)
                        elif 'hour' in txt:
                            h = int(''.join(filter(str.isdigit,txt)) or '1')
                            posted_at = now - timedelta(hours=h)
                        elif 'day' in txt:
                            d = int(''.join(filter(str.isdigit,txt)) or '1')
                            posted_at = now - timedelta(days=d)
                        elif 'week' in txt:
                            w = int(''.join(filter(str.isdigit,txt)) or '1')
                            posted_at = now - timedelta(weeks=w)
                        elif 'month' in txt:
                            mo = int(''.join(filter(str.isdigit,txt)) or '1')
                            posted_at = now - timedelta(days=mo*30)
                except Exception:
                    pass

                listings.append(JobListing(
                    title=title, company_name=company,
                    job_url=href, portal="linkedin", location=loc_txt,
                    external_job_id=ext_id,
                    work_mode=detect_work_mode(title, loc_txt),
                    is_active=(closed_el is None),
                    posted_at=posted_at,
                ))
            except Exception as e:
                log.debug(f"[LinkedIn] Card parse error: {e}")

        return listings
