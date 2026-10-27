#!/usr/bin/env python3
"""Update the public demo banner with a link to SignalProof macOS beta.

Changes only docs/index.html; never touches the real app/dashboard source.
"""
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
page = repo / "docs" / "index.html"
if not page.exists():
    raise SystemExit("Missing docs/index.html. Run this inside the SignalProof repository.")
html = page.read_text(encoding="utf-8")
link = '<a href="./download.html">Get macOS Beta ↗</a>'
if link not in html:
    # Replace the old optional link if present; otherwise add after the source link.
    old = '<a href="./download.html">Get the Mac app ↗</a>'
    if old in html:
        html = html.replace(old, link, 1)
    else:
        source = '<a href="https://github.com/rayjim28/signalproof" target="_blank" rel="noopener noreferrer">Source code ↗</a>'
        if source not in html:
            raise SystemExit("Could not identify the demo banner. No changes made.")
        html = html.replace(source, source + link, 1)

old_status = '<span>macOS · Python app available</span>'
new_status = '<span>macOS · Beta available</span>'
if old_status in html:
    html = html.replace(old_status, new_status, 1)
elif new_status not in html:
    print("No legacy platform badge found; leaving the platform-support section unchanged.")

page.write_text(html, encoding="utf-8")
print("Updated docs/index.html: Get macOS Beta link and platform status.")
