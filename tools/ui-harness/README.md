# UI harness

Renders the real frontend against canned data and screenshots every route at
phone and desktop width — and **fails if any page scrolls sideways**.

The redesign work needs this because the app is used on a phone and the CSS was
written desktop-first: the header overflowed every route by 195px for months
because nothing checked, and a thumbnail doesn't show it.

```bash
pip install playwright                     # Chromium is already on the image
python3 tools/ui-harness/mock_api.py &     # :8000, canned JSON
cd frontend && node node_modules/vite/bin/vite.js &   # :5173, proxies /api
python3 tools/ui-harness/shoot.py before   # -> shots/before/{390,1280}/*.png
```

`shoot.py` exits non-zero when `scrollWidth > innerWidth` at 390px and names
the widest offending element, so overflow fails loudly instead of being noticed
weeks later.

`mock_api.py` returns 404 with an explanatory body for any route it doesn't
know, so a blank page traces to a missing mock rather than a CSS bug.

`CHROME` in `shoot.py` is pinned to the image's Chromium build because the pip
package expects a newer one; `playwright install` is not needed.
