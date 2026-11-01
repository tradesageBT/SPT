"""
Screenshot every route at phone and desktop width, and fail on overflow.

The assertion is the point: scrollWidth > innerWidth at 390px is exactly the
bug that shipped, and it is invisible in a thumbnail. Screenshots are for
judging design; this check is for catching regressions.

    python3 shoot.py [label]     -> shots/<label>/*.png  + a pass/fail table
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://localhost:5173"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
OUT = Path(__file__).parent / "shots"

PHONE = {"width": 390, "height": 844}
DESK = {"width": 1280, "height": 800}

ROUTES = [
    ("home", "/"),
    ("my-leagues", "/my-leagues"),
    ("league", "/league/1"),
    ("league-team", "/league/1/team/1"),
    ("league-trades", "/league/1/trades"),
    ("league-evaluate", "/league/1/evaluate"),
    ("league-lineup", "/league/1/lineup?roster_id=1"),
    ("league-waivers", "/league/1/waivers?roster_id=1"),
    ("redraft", "/redraft/1"),
    ("redraft-team", "/redraft/1/team/1"),
    ("redraft-trades", "/redraft/1/trades"),
    ("redraft-lineup", "/redraft/1/lineup?roster_id=1"),
    ("evaluator", "/redraft-trades"),
    ("draft-assistant", "/draft-assistant"),
    ("sleeper-draft", "/sleeper-draft"),
]


async def shoot(page, name, path, size, label, tag):
    await page.set_viewport_size(size)
    await page.goto(f"{BASE}{path}", wait_until="networkidle")
    # Give React a beat to paint after data lands.
    await page.wait_for_timeout(500)

    metrics = await page.evaluate("""() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
        // The widest element overflowing the viewport, for a usable error.
        widest: (() => {
            let worst = null, w = window.innerWidth;
            for (const el of document.querySelectorAll('*')) {
                const r = el.getBoundingClientRect();
                if (r.right > w + 1 && (!worst || r.right > worst.right)) {
                    worst = { right: Math.round(r.right),
                              sel: el.tagName.toLowerCase() +
                                   (el.className && typeof el.className === 'string'
                                    ? '.' + el.className.trim().split(/\\s+/).join('.')
                                    : '') };
                }
            }
            return worst;
        })(),
    })""")

    d = OUT / label / tag
    d.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(d / f"{name}.png"), full_page=True)
    return metrics


async def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "current"
    failures = []
    async with async_playwright() as pw:
        # The container ships Chromium build 1194; pip's playwright expects a
        # newer one. Point at what's actually here rather than downloading.
        browser = await pw.chromium.launch(executable_path=CHROME)
        page = await browser.new_page(device_scale_factor=2)
        page.on("pageerror", lambda e: failures.append(("js", str(e)[:90])))

        print(f"{'route':<20} {'390px':>12}   {'1280px':>8}")
        print("-" * 48)
        for name, path in ROUTES:
            m = await shoot(page, name, path, PHONE, label, "390")
            over = m["scrollWidth"] - m["innerWidth"]
            if over > 1:
                failures.append((name, f"+{over}px  {m['widest']['sel'][:60]}"
                                 if m["widest"] else f"+{over}px"))
                verdict = f"OVERFLOW +{over}"
            else:
                verdict = "ok"
            await shoot(page, name, path, DESK, label, "1280")
            print(f"{name:<20} {verdict:>12}   {'ok':>8}")

        await browser.close()

    print()
    if failures:
        print(f"{len(failures)} problem(s):")
        for n, why in failures:
            print(f"  {n}: {why}")
        sys.exit(1)
    print(f"all {len(ROUTES)} routes fit 390px — shots in {OUT / label}")


asyncio.run(main())
