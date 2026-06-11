"""
Lever job board discovery.

Lever exposes a public JSON API at:
  https://api.lever.co/v0/postings/{company_id}?mode=json

Also clean — no browser, no auth needed.
"""

from __future__ import annotations

import aiohttp

from .base import BaseDiscoverer, JobListing
from src.utils import log


LEVER_API = "https://api.lever.co/v0/postings/{company_id}?mode=json"


class LeverDiscoverer(BaseDiscoverer):

    async def discover(self, context=None, company: dict = None) -> list[JobListing]:
        if not company:
            return []
        lever_id = company.get("lever_id")
        if not lever_id:
            return []

        url = LEVER_API.format(company_id=lever_id)
        listings: list[JobListing] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        log.warning(f"[Lever] {company['name']}: HTTP {resp.status}")
                        return []
                    data = await resp.json()
        except Exception as e:
            log.warning(f"[Lever] {company['name']}: request failed — {e}")
            return []

        for job in data:
            title = job.get("text", "")
            location = job.get("categories", {}).get("location", "")
            team = job.get("categories", {}).get("team", "")
            job_url = job.get("hostedUrl", "")
            external_id = job.get("id", "")

            if not self.matches_filters(title, location):
                continue

            # Build plain-text description from lists
            lists = job.get("lists", [])
            description_parts = []
            for l in lists:
                description_parts.append(f"{l.get('text', '')}: {l.get('content', '')}")
            description = "\n\n".join(description_parts)

            listings.append(
                JobListing(
                    title=title,
                    company_name=company["name"],
                    job_url=job_url,
                    portal="lever",
                    location=location,
                    description=description,
                    external_job_id=external_id,
                    extra={"team": team},
                    posted_at=__import__('datetime').datetime.utcfromtimestamp(job.get('createdAt',0)/1000) if job.get('createdAt') else None,
                )
            )

        log.info(f"[Lever] {company['name']}: {len(listings)} matching jobs")
        return listings
