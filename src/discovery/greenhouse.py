"""
Greenhouse global job board search.
Uses Greenhouse's public job board listing (no company ID needed).
Fetches the Greenhouse job board index and searches by keyword.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from .base import BaseDiscoverer, JobListing, detect_work_mode
from src.utils import log

# Greenhouse has a public job search at grnhse.io
GREENHOUSE_SEARCH = "https://job-boards.greenhouse.io/embed/job_board?for={board}"

# Top tech companies on Greenhouse — comprehensive list
GREENHOUSE_BOARDS = [
    "anthropic","stripe","airbnb","notion","figma","airtable","linear",
    "vercel","planetscale","supabase","railway","render","fly","loom",
    "retool","brex","ramp","mercury","plaid","checkr","gusto","rippling",
    "lattice","carta","deel","remote","hubspot","asana","atlassian",
    "coinbase","robinhood","databricks","snowflake","hashicorp","datadog",
    "mongodb","elastic","confluent","dbt","airbyte","fivetran","stytch",
    "clerk","neon","turso","resend","loops","posthog","metabase",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html",
}


class GreenhouseDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company=None) -> list[JobListing]:
        keywords = [k.lower() for k in self.filters.get("keywords", ["software engineer"])]
        listings: list[JobListing] = []

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            # Use Greenhouse API for each board
            tasks = [self._fetch_board(session, board, keywords) for board in GREENHOUSE_BOARDS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    listings.extend(r)

        seen = set()
        unique = [l for l in listings if not (l.job_url in seen or seen.add(l.job_url))]
        unique = self.sort_by_preference(unique)
        log.info(f"[Greenhouse] {len(unique)} unique jobs found across {len(GREENHOUSE_BOARDS)} boards")
        return unique

    async def _fetch_board(self, session, board: str, keywords: list[str]) -> list[JobListing]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

        listings = []
        company_name = board.replace("-", " ").title()

        for job in data.get("jobs", []):
            title    = job.get("title", "")
            location = job.get("location", {}).get("name", "")
            job_url  = job.get("absolute_url", "")
            ext_id   = str(job.get("id", ""))

            if not self.matches_filters(title, location):
                continue

            listings.append(JobListing(
                title=title, company_name=company_name,
                job_url=job_url, portal="greenhouse", location=location,
                external_job_id=ext_id,
                work_mode=detect_work_mode(title, location),
            ))

        return listings
