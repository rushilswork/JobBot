"""
Greenhouse application auto-filler.

Greenhouse forms are standardized — they all use the same field names and layout.
We fill the form and screenshot the review page but do NOT submit.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeout

from src.utils import load_profile, log

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def _human_delay(min_ms: int = 400, max_ms: int = 1200) -> None:
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


class GreenhouseAutoFiller:

    def __init__(self, cover_letter: str = "", screening_answers: dict | None = None):
        self.profile = load_profile()
        self.cover_letter = cover_letter
        self.screening_answers = screening_answers or {}

    async def fill(self, context: BrowserContext, job_url: str, job_id: int) -> dict:
        page = await context.new_page()
        result = {"success": False, "screenshot_path": "", "error": ""}

        # Greenhouse apply URL is typically job_url + /applications/new
        apply_url = job_url.rstrip("/") + "/applications/new"

        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30_000)
            await _human_delay(1000, 2000)

            personal = self.profile.get("personal", {})

            # Basic fields
            await self._fill_if_empty(page, "#first_name", personal.get("first_name", ""))
            await self._fill_if_empty(page, "#last_name", personal.get("last_name", ""))
            await self._fill_if_empty(page, "#email", personal.get("email", ""))
            await self._fill_if_empty(page, "#phone", personal.get("phone", ""))
            await self._fill_if_empty(page, "#job_application_location", personal.get("location", ""))

            # Resume upload
            resume_path = PROJECT_ROOT / personal.get("resume_path", "data/resume.pdf")
            if resume_path.exists():
                upload = await page.query_selector("input#resume[type='file']")
                if upload:
                    await upload.set_input_files(str(resume_path))
                    await _human_delay(800, 1500)

            # Cover letter
            if self.cover_letter:
                cl_area = await page.query_selector("textarea#cover_letter")
                if cl_area:
                    await cl_area.fill(self.cover_letter)

            # LinkedIn URL
            if personal.get("linkedin_url"):
                await self._fill_if_empty(page, "input[name*='linkedin']", personal["linkedin_url"])

            # Custom screening questions
            await self._fill_custom_questions(page)

            await _human_delay(500, 1000)

            # Screenshot the filled form — don't submit
            screenshot_path = str(SCREENSHOTS_DIR / f"job_{job_id}_greenhouse_review.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            result["success"] = True
            result["screenshot_path"] = screenshot_path
            log.info(f"[Greenhouse AutoFill] Staged job {job_id} — screenshot saved")

        except PWTimeout:
            result["error"] = "Timed out filling Greenhouse form"
        except Exception as e:
            result["error"] = str(e)
            log.error(f"[Greenhouse AutoFill] Error on job {job_id}: {e}")
        finally:
            await page.close()

        return result

    async def _fill_if_empty(self, page: Page, selector: str, value: str) -> None:
        if not value:
            return
        try:
            el = await page.query_selector(selector)
            if el:
                current = await el.input_value()
                if not current:
                    await el.fill(value)
        except Exception:
            pass

    async def _fill_custom_questions(self, page: Page) -> None:
        """Fill custom application questions using screening_answers."""
        question_blocks = await page.query_selector_all(".field")
        for block in question_blocks:
            label_el = await block.query_selector("label")
            if not label_el:
                continue
            label_text = (await label_el.inner_text()).strip()

            # Try text input
            text_input = await block.query_selector("input[type='text'], input[type='number']")
            if text_input:
                answer = self._find_answer(label_text)
                if answer:
                    await text_input.fill(answer)
                continue

            # Try textarea
            textarea = await block.query_selector("textarea")
            if textarea:
                answer = self._find_answer(label_text)
                if answer:
                    await textarea.fill(answer)
                continue

            # Try select
            select = await block.query_selector("select")
            if select:
                answer = self._find_answer(label_text)
                if answer:
                    try:
                        await select.select_option(label=answer)
                    except Exception:
                        pass

    def _find_answer(self, label_text: str) -> str:
        label_lower = label_text.lower()
        for question, answer in self.screening_answers.items():
            if question.lower() in label_lower or label_lower in question.lower():
                return str(answer)

        profile = self.profile
        auth = profile.get("work_authorization", {})
        salary = profile.get("salary", {})
        sa = profile.get("screening_answers", {})

        if "years" in label_lower and "experience" in label_lower:
            return str(sa.get("years_of_experience", ""))
        if "salary" in label_lower:
            return str(salary.get("desired_min", ""))
        if "sponsorship" in label_lower:
            return "No" if not auth.get("requires_sponsorship") else "Yes"
        if "authorized" in label_lower:
            return "Yes" if auth.get("authorized_to_work_in_us") else "No"

        return ""
