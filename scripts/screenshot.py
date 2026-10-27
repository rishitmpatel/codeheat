"""Screenshot a codeheat HTML report (light + dark) with Playwright.

usage: python scripts/screenshot.py report.html out_prefix [--full]
Writes <out_prefix>-light.png and <out_prefix>-dark.png (1440x900).
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    src, prefix = Path(sys.argv[1]).resolve(), sys.argv[2]
    full = "--full" in sys.argv
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme, device_scale_factor=1)
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(src.as_uri())
            page.wait_for_timeout(500)
            page.screenshot(path=f"{prefix}-{scheme}.png", full_page=full)
            ctx.close()
        b.close()
    if errors:
        print("JS ERRORS:", errors)
        sys.exit(1)


if __name__ == "__main__":
    main()
