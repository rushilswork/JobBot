"""Base class and shared utilities for all job discovery scrapers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import BrowserContext, Page

WORK_MODE_PRIORITY = ["remote", "hybrid", "onsite", "unknown"]

_RECRUITER_PATTERNS = re.compile(
    r"\b("
    r"hiring for|product based company|client hiring|mnc hiring|"
    r"requirement (at|for)|vacancy (at|for)|opening (at|for)|"
    r"walk[\s\-]?in|walkin|urgent(ly)? (hiring|required|requirement)|"
    r"immediate (hiring|opening|requirement)|"
    r"leading (mnc|product|company)|top (mnc|product|company)|"
    r"global mnc|fortune 500|staffing|recruitment agency|"
    r"confidential company|company name"
    r")\b",
    re.IGNORECASE,
)

_EXCLUDE_PATTERNS = re.compile(
    r"\b("
    r"intern|internship|senior staff|principal|staff engineer|"
    r"VP|vice president|director|head of|lead engineer|"
    r"SDET|QA engineer|quality assurance|test engineer|automation test|"
    r"devops|site reliability|SRE|data scientist|data analyst|"
    r"machine learning|ML engineer|data engineer|product manager|"
    r"designer|UX|"
    r"experience must|banking experience|insurance experience|"
    r"fintech experience|domain experience|notice period|"
    r"immediate joiner|serve notice|years exp"
    r")\b",
    re.IGNORECASE,
)


def detect_work_mode(title: str, location: str, description: str = "") -> str:
    combined = f"{title} {location} {description}".lower()
    if "remote" in combined:
        return "remote"
    if "hybrid" in combined:
        return "hybrid"
    if any(w in combined for w in ["onsite", "on-site", "in-office", "in office"]):
        return "onsite"
    return "unknown"


def work_mode_rank(mode: str) -> int:
    try:
        return WORK_MODE_PRIORITY.index(mode)
    except ValueError:
        return len(WORK_MODE_PRIORITY)


def verify_company(actual: str, expected: str) -> bool:
    """Return True if actual company name reasonably matches expected."""
    if not actual:
        return False
    a = actual.strip().lower()
    e = expected.strip().lower()

    if e in a or a in e:
        return True

    first_word = e.split()[0] if e.split() else e
    if len(first_word) > 3 and first_word in a:
        return True

    acronym = "".join(w[0] for w in e.split())
    if len(acronym) >= 2 and acronym == "".join(w[0] for w in a.split()):
        return True

    return False


def is_recruiter_title(title: str) -> bool:
    return bool(_RECRUITER_PATTERNS.search(title))


@dataclass
class JobListing:
    title: str
    company_name: str
    job_url: str
    portal: str
    location: str = ""
    description: str = ""
    external_job_id: str = ""
    work_mode: str = "unknown"
    is_active: bool = True
    extra: dict = field(default_factory=dict)


class BaseDiscoverer(ABC):
    def __init__(self, config: dict, filters: dict):
        self.config = config
        self.filters = filters
        self._keywords = [k.lower() for k in filters.get("keywords", [])]
        self._locations = [l.lower() for l in filters.get("locations", [])]
        self._exclude = [x.lower() for x in filters.get("exclude_keywords", [])]

    @abstractmethod
    async def discover(self, context=None, company=None) -> list[JobListing]:
        ...

    def matches_filters(self, title: str, location: str = "") -> bool:
        """
        Return True if the job should be kept.
        1. Must match at least one keyword
        2. Must NOT match any exclude keyword
        3. Must NOT be a recruiter posting
        """
        t = title.lower()

        if is_recruiter_title(title):
            return False

        for ex in self._exclude:
            if ex in t:
                return False

        if _EXCLUDE_PATTERNS.search(title):
            return False

        if self._keywords:
            if not any(kw in t for kw in self._keywords):
                return False

        return True

    def sort_by_preference(self, listings: list[JobListing]) -> list[JobListing]:
        return sorted(listings, key=lambda j: work_mode_rank(j.work_mode))
