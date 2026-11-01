"""Add the same pick three times, then remove one, and check the totals."""
import asyncio
from playwright.async_api import async_playwright
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME)
        pg = await b.new_page(device_scale_factor=2)
        await pg.set_viewport_size({"width": 390, "height": 844})
        await pg.goto("http://localhost:5173/redraft-trades", wait_until="networkidle")
        await pg.get_by_role("button", name="Dynasty").click()
        await pg.wait_for_timeout(400)

        async def rows():
            return await pg.locator(".rt-side").first.locator(".rt-player-row").count()
        async def total():
            return (await pg.locator(".rt-slot-total").first.inner_text()).strip()

        for n in (1, 2, 3):
            await pg.locator(".rt-add-pick").first.click()
            await pg.get_by_role("button", name="2028 2nd").first.click()
            await pg.wait_for_timeout(250)
            print(f"  after add #{n}: rows={await rows()}  total={await total()}")

        assert await rows() == 3, "three copies of the same pick must coexist"

        # Remove the middle one — only that instance may go.
        await pg.locator(".rt-side").first.locator(".rt-remove").nth(1).click()
        await pg.wait_for_timeout(250)
        print(f"  after removing one: rows={await rows()}  total={await total()}")
        assert await rows() == 2, "removing one copy must not remove the rest"

        # A player, by contrast, must still refuse to be added twice.
        await pg.fill(".rt-side >> nth=0 >> input", "Josh")
        await pg.wait_for_timeout(600)
        opt = pg.locator(".rt-suggestion, .rt-dropdown button").first
        if await opt.count():
            await opt.click(); await pg.wait_for_timeout(250)
            before = await rows()
            await pg.fill(".rt-side >> nth=0 >> input", "Josh")
            await pg.wait_for_timeout(600)
            o2 = pg.locator(".rt-suggestion, .rt-dropdown button").first
            if await o2.count():
                await o2.click(); await pg.wait_for_timeout(250)
            print(f"  player re-add: rows {before} -> {await rows()} (must not grow)")

        await pg.screenshot(path="shots/dup-picks.png", full_page=True)
        print("\nDUPLICATE PICKS OK")
        await b.close()

asyncio.run(main())
