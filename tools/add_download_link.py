"""Add the platform page link to the existing GitHub Pages demo without changing its layout."""

from pathlib import Path
import re

page = Path(__file__).resolve().parent.parent / 'docs' / 'index.html'
if not page.exists():
    raise SystemExit('Missing docs/index.html. Run this from your SignalProof repository.')
html = page.read_text(encoding='utf-8')
if 'href="./download.html"' in html:
    print('Download link already present.')
    raise SystemExit(0)

link = '<a href="./download.html">Get the Mac app ↗</a>'
match = re.search(r'(<div\s+class="sample-banner"[^>]*>)(.*?)(</div>)', html, flags=re.S)
if not match:
    raise SystemExit('Sample banner not found; docs/index.html left unchanged.')
updated = html[:match.start()] + match.group(1) + match.group(2) + link + match.group(3) + html[match.end():]
page.write_text(updated, encoding='utf-8')
print('Added Mac app link to the public demo banner.')
