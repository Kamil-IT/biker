"""Screenshot proof for the merged Offers view (TODO-001).

Drives the running frontend at http://localhost:5173:
  search -> open first result -> wait for the merged Offers card -> screenshot.
Saves PNGs to backend/scripts/ss_*.png (committed on the feature branch).
"""
import asyncio
from patchright.async_api import async_playwright

FRONTEND = "http://localhost:5173"
QUERY = "trek marlin affordable trail and city bike"


async def shoot():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1400})
        page.on("console", lambda m: print(f"[console:{m.type}] {m.text}"))
        page.on("requestfailed", lambda r: print(f"[reqfail] {r.url} {r.failure}"))
        page.on("request", lambda r: print(f"[req] {r.method} {r.url}") if "/v1/" in r.url else None)
        await page.goto(FRONTEND, wait_until="domcontentloaded")

        # Search — this UI is two-step: 1st submit parses free text + fills filters
        # (returns early), 2nd submit runs the actual search.
        await page.wait_for_selector("#bike-search", timeout=15000)
        await page.click("#bike-search")
        await page.type("#bike-search", QUERY, delay=10)
        print("input value =", repr(await page.input_value("#bike-search")))

        async with page.expect_response(lambda r: "/v1/bike/parse" in r.url, timeout=60000) as ri:
            await page.click("button[type='submit']")
        print("parse status", (await ri.value).status)
        await page.wait_for_timeout(2000)  # let filters populate from parse

        # If results didn't already appear, submit again to run the search.
        if await page.locator("button.rounded-2xl").count() == 0:
            try:
                async with page.expect_response(lambda r: "/v1/bike/search" in r.url, timeout=120000):
                    await page.click("button[type='submit']")
                print("search response received")
            except Exception as e:
                print(f"search response wait failed: {e}")

        # Wait for result cards, open the first one
        try:
            await page.wait_for_selector("button.rounded-2xl", timeout=30000)
        except Exception:
            await page.screenshot(path="scripts/ss_debug_after_search.png", full_page=True)
            body = (await page.inner_text("body"))[:600]
            print(f"no result cards. page text:\n{body}")
            await browser.close()
            return
        await page.locator("button.rounded-2xl").first.click()
        print("opened first result")

        # Wait for the merged Offers card header
        await page.wait_for_selector("text=Offers", timeout=30000)

        # Locate the Offers card and wait until its skeletons clear. Both category
        # cards stay in skeleton until all four (web-search backed, slow) sources
        # settle — poll up to 200s for the shimmer to disappear.
        offers_label = page.get_by_text("Offers", exact=True).first
        card = page.locator("div.bg-card", has=offers_label).first
        for _ in range(100):  # 100 * 2s = 200s
            if await card.locator(".shimmer").count() == 0:
                break
            await page.wait_for_timeout(2000)
        else:
            print("Offers still loading after 200s — capturing current state.")
        await page.wait_for_timeout(800)
        await offers_label.scroll_into_view_if_needed()
        try:
            await card.screenshot(path="scripts/ss_1_offers_merged.png")
            print("saved scripts/ss_1_offers_merged.png")
        except Exception as e:
            print(f"card screenshot failed ({e}); full-page fallback")
            await page.screenshot(path="scripts/ss_1_offers_merged.png")

        # Full details page for context
        await page.screenshot(path="scripts/ss_2_details_full.png", full_page=True)
        print("saved scripts/ss_2_details_full.png")

        await browser.close()


asyncio.run(shoot())
