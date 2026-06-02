"""
LinkedIn Easy Apply auto-filler.

Flow:
  1. Navigate to the job posting URL
  2. Click "Easy Apply" button
  3. Step through the multi-page form:
     - Contact info (pre-filled from profile)
     - Resume upload
     - Screening questions (AI-answered)
     - Review → stage for user approval (DO NOT auto-submit)
  4. Screenshot the review page and save path to Application record
  5. Return without submitting — user reviews in the dashboard
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeout

from src.utils import load_profile, log

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def _human_delay(min_ms: int = 400, max_ms: int = 1200) -> None:
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def _type_slowly(page: Page, selector: str, text: str) -> None:
    """Type text character by character to mimic human input."""
    await page.click(selector)
    await page.fill(selector, "")  # clear first
    for char in text:
        await page.type(selector, char, delay=random.randint(40, 120))


class LinkedInAutoFiller:

    def __init__(self, cover_letter: str = "", screening_answers: dict | None = None):
        self.profile = load_profile()
        self.cover_letter = cover_letter
        self.screening_answers = screening_answers or {}

    async def fill(self, context: BrowserContext, job_url: str, job_id: int) -> dict:
        """
        Navigate to job URL and fill out the Easy Apply form.
        Returns {"success": bool, "screenshot_path": str, "error": str}.
        """
        page = await context.new_page()
        result = {"success": False, "screenshot_path": "", "error": ""}

        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
            await _human_delay(1500, 2500)

            # Click Easy Apply button
            easy_apply = await page.query_selector("button.jobs-apply-button, button[aria-label*='Easy Apply']")
            if not easy_apply:
                result["error"] = "Easy Apply button not found — may not be an Easy Apply job"
                return result

            await easy_apply.click()
            await _human_delay(1000, 2000)

            # Step through form pages
            max_steps = 10
            for step in range(max_steps):
                await self._fill_current_step(page)
                await _human_delay(800, 1500)

                # Check if we've reached the Review step
                review_header = await page.query_selector("h3:has-text('Review'), h3:has-text('Submit application')")
                if review_header:
                    # Take screenshot of review page — DO NOT click submit
                    screenshot_path = str(SCREENSHOTS_DIR / f"job_{job_id}_review.png")
                    await page.screenshot(path=screenshot_path, full_page=False)
                    result["success"] = True
                    result["screenshot_path"] = screenshot_path
                    log.info(f"[LinkedIn AutoFill] Staged job {job_id} for review — screenshot saved")
                    break

                # Try to click Next
                next_btn = await page.query_selector("button[aria-label='Continue to next step'], button:has-text('Next')")
                if next_btn:
                    await next_btn.click()
                    await _human_delay(700, 1400)
                else:
                    result["error"] = f"Could not find Next button on step {step + 1}"
                    break

        except PWTimeout:
            result["error"] = "Timed out during form fill"
        except Exception as e:
            result["error"] = str(e)
            log.error(f"[LinkedIn AutoFill] Error on job {job_id}: {e}")
        finally:
            await page.close()

        return result

    async def _fill_current_step(self, page: Page) -> None:
        """Fill all visible form fields on the current step."""
        profile = self.profile
        personal = profile.get("personal", {})

        # Phone number field
        phone_input = await page.query_selector("input[name*='phoneNumber'], input[id*='phoneNumber']")
        if phone_input and personal.get("phone"):
            current = await phone_input.input_value()
            if not current:
                await _type_slowly(page, "input[name*='phoneNumber']", personal["phone"])

        # Resume upload
        resume_path = PROJECT_ROOT / profile.get("personal", {}).get("resume_path", "data/resume.pdf")
        if resume_path.exists():
            upload_btn = await page.query_selector("input[type='file']")
            if upload_btn:
                await upload_btn.set_input_files(str(resume_path))
                await _human_delay(500, 1000)

        # Cover letter textarea
        cover_letter_area = await page.query_selector(
            "textarea[id*='coverLetter'], textarea[placeholder*='cover letter']"
        )
        if cover_letter_area and self.cover_letter:
            await cover_letter_area.fill(self.cover_letter)

        # Screening questions — text inputs
        text_inputs = await page.query_selector_all("input[type='text']:not([name*='phone'])")
        for inp in text_inputs:
            label_text = await self._get_label_text(page, inp)
            if not label_text:
                continue
            answer = self._find_answer(label_text)
            if answer:
                current = await inp.input_value()
                if not current:
                    await inp.fill(answer)

        # Screening questions — dropdowns
        selects = await page.query_selector_all("select")
        for sel in selects:
            label_text = await self._get_label_text(page, sel)
            if not label_text:
                continue
            answer = self._find_answer(label_text)
            if answer:
                try:
                    await sel.select_option(label=answer)
                except Exception:
                    pass  # option may not match exactly

        # Yes/No radio groups
        radio_groups = await page.query_selector_all("fieldset")
        for fieldset in radio_groups:
            legend = await fieldset.query_selector("legend")
            if not legend:
                continue
            legend_text = await legend.inner_text()
            answer = self._find_answer(legend_text)
            if answer:
                answer_lower = answer.lower()
                if "yes" in answer_lower or answer_lower == "true":
                    radio = await fieldset.query_selector("input[type='radio'][value='Yes'], input[type='radio'][value='true']")
                elif "no" in answer_lower or answer_lower == "false":
                    radio = await fieldset.query_selector("input[type='radio'][value='No'], input[type='radio'][value='false']")
                else:
                    radio = None
                if radio:
                    await radio.check()

    async def _get_label_text(self, page: Page, element) -> str:
        """Try to find the label text associated with a form element."""
        try:
            el_id = await element.get_attribute("id")
            if el_id:
                label = await page.query_selector(f"label[for='{el_id}']")
                if label:
                    return (await label.inner_text()).strip().lower()
        except Exception:
            pass
        return ""

    def _find_answer(self, label_text: str) -> str:
        """Look up screening_answers dict for a matching question."""
        label_lower = label_text.lower()
        for question, answer in self.screening_answers.items():
            if question.lower() in label_lower or label_lower in question.lower():
                return str(answer)

        # Fallback: profile data for common fields
        profile = self.profile
        personal = profile.get("personal", {})
        auth = profile.get("work_authorization", {})
        salary = profile.get("salary", {})
        sa = profile.get("screening_answers", {})

        if "years" in label_lower and "experience" in label_lower:
            return str(sa.get("years_of_experience", ""))
        if "salary" in label_lower or "compensation" in label_lower:
            return str(salary.get("desired_min", ""))
        if "sponsorship" in label_lower:
            return "No" if not auth.get("requires_sponsorship") else "Yes"
        if "authorized" in label_lower or "eligible" in label_lower:
            return "Yes" if auth.get("authorized_to_work_in_us") else "No"
        if "relocat" in label_lower:
            return "Yes" if sa.get("willing_to_relocate") else "No"
        if "start date" in label_lower or "available" in label_lower:
            return sa.get("available_start_date", "2 weeks")

        return ""
