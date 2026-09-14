#!/usr/bin/env python3
"""
Assembles frontend-src/ into static/index.html.

Why this exists: static/index.html is one big single-page app (shared CSS,
sidebar/topbar/notifications-drawer shell, one <div class="page"> per page,
and all the JS) with no separate build tooling. That's fine to *ship* as one
file, but painful to *edit* — touching the Upload page meant scrolling
through Analytics, CSS, and JS to find it. This script lets you edit each
part as its own file under frontend-src/ and reassembles them into the
exact same static/index.html the server actually serves.

Note: static/login.html and static/signup.html are standalone pages (not
part of this single-page app) and are small enough on their own — they're
not part of this build, edit them directly.

Run it after editing anything under frontend-src/:

    python3 build.py

CI also runs this automatically on every push that touches frontend-src/
(see .github/workflows/deploy.yml), so the two can't drift apart — but run
it locally too so you can preview your change before pushing.

Source layout:
    frontend-src/layout.html   the shared shell — <head>, sidebar,
                                notifications drawer, topbar, with
                                {{CSS}}, {{PAGES}}, {{JS}} placeholders
    frontend-src/style.css     all CSS
    frontend-src/app.js        all JavaScript
    frontend-src/pages/*.html  one file per page (dashboard, accounts,
                                platforms, scheduled, published, analytics,
                                settings, help, upload)
"""

from pathlib import Path

SRC_DIR = Path(__file__).parent / "frontend-src"
OUTPUT_PATH = Path(__file__).parent / "static" / "index.html"

# Order matters (matches original page order in the app), and the comment
# after each page name is the exact section-divider comment that appears
# between that page and the next one in the assembled file. An empty
# string means no divider — those pages just sit back-to-back (this is how
# analytics/settings/help were originally laid out).
PAGE_ORDER = [
    ("dashboard", "\n  <!-- ACCOUNTS (manage the accounts themselves — rename/delete/add) -->\n"),
    ("accounts", "\n  <!-- PLATFORMS -->\n"),
    ("platforms", "\n  <!-- SCHEDULED -->\n"),
    ("scheduled", "\n  <!-- PUBLISHED -->\n"),
    ("published", "\n  <!-- ANALYTICS / SETTINGS / HELP — placeholders for now -->\n"),
    ("analytics", ""),
    ("settings", ""),
    ("help", "\n  <!-- NEW UPLOAD (existing, fully wired) -->\n"),
    ("upload", ""),
]


def build() -> str:
    layout = (SRC_DIR / "layout.html").read_text()
    css = (SRC_DIR / "style.css").read_text()
    js = (SRC_DIR / "app.js").read_text()

    pages_blob = ""
    for page_name, following_gap in PAGE_ORDER:
        pages_blob += (SRC_DIR / "pages" / f"{page_name}.html").read_text()
        pages_blob += following_gap

    html = layout.replace("{{CSS}}", css, 1)
    html = html.replace("{{PAGES}}", pages_blob, 1)
    html = html.replace("{{JS}}", js, 1)
    # Placed after <!DOCTYPE html> (not before it) so it can't affect
    # browsers' standards-mode detection.
    marker = "<!-- GENERATED FILE — do not edit directly. Edit frontend-src/ and run `python3 build.py`. -->\n"
    html = html.replace("</title>\n", "</title>\n" + marker, 1)
    return html


if __name__ == "__main__":
    output = build()
    OUTPUT_PATH.write_text(output)
    print(f"Wrote {OUTPUT_PATH} ({len(output.splitlines())} lines)")
