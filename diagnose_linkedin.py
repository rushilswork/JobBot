"""
Run this to diagnose why LinkedIn returns 0 jobs.
Usage:  python diagnose_linkedin.py

Opens a headed browser, navigates to Google's LinkedIn jobs page,
and prints the actual HTML structure so we can fix the selectors.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE = Path(__file__).parent / "data" / "browser_profile" / "linkedin"
PROFILE.mkdir(parents=True, exist_ok=True)

CARD_SELECTORS = [
    "div.job-search-card",
    "li.jobs-search-results__list-item",
    "div[data-entity-urn]",
    "li[class*='ember-view'][class*='occludable']",
    "div.base-card",
    "div[class*='job-card-container']",
    "ul[class*='jobs-list'] > li",
    "ul[class*='job-list'] > li",
    "[class*='job-card']",
    "div[data-job-id]",
    "li[data-occludable-job-id]",
]

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        url = "https://www.linkedin.com/company/google/jobs/"
        print(f"\nNavigating to: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(4)

        final_url = page.url
        print(f"Landed on:     {final_url}")

        if "login" in final_url or "authwall" in final_url:
            print("\n*** AUTH WALL — you need to log in first ***")
            print("Log in now in the browser window, then press Enter...")
            input()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(4)

        print("\n--- Trying card selectors ---")
        found = False
        for sel in CARD_SELECTORS:
            els = await page.query_selector_all(sel)
            if els:
                print(f"  FOUND {len(els)} cards with: {sel!r}")
                found = True
                # Print HTML of first card
                html = await els[0].inner_html()
                print(f"  First card HTML (first 600 chars):\n{html[:600]}\n")
                break
            else:
                print(f"  0    cards with: {sel!r}")

        if not found:
            print("\n--- No cards found. Dumping page body classes ---")
            # Print all class names present on the page
            classes = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('[class]');
                    const cls = new Set();
                    all.forEach(el => el.className.toString().split(' ').forEach(c => c && cls.add(c)));
                    return [...cls].filter(c => c.toLowerCase().includes('job')).slice(0, 60);
                }
            """)
            print("Job-related class names on page:")
            for c in classes:
                print(f"  {c}")

        input("\nPress Enter to close browser...")
        await ctx.close()

asyncio.run(main())
