#!/usr/bin/env python3
"""Safely activate SignalProof macOS Beta 2 across the existing GitHub Pages site.

Updates only docs/download.html, docs/index.html and README.md.
Handles either the pre-beta download page or the existing Beta 1 page.
No changes to the local agent, desktop app, or measurement data.
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parent.parent
OLD = 'https://github.com/rayjim28/signalproof/releases/tag/v0.1.0-beta.1'
NEW = 'https://github.com/rayjim28/signalproof/releases/tag/v0.1.0-beta.2'
files = {
    'docs/download.html': REPO / 'docs' / 'download.html',
    'docs/index.html': REPO / 'docs' / 'index.html',
    'README.md': REPO / 'README.md',
}
for name, path in files.items():
    if not path.is_file():
        raise SystemExit(f'Missing {name}. Run this from the existing SignalProof repository.')

def fix_version(s):
    # Avoid changing other versions or repeating "Beta 2" if this runs twice.
    return re.sub(r'v0\.1\.0 Beta(?!\s*2\b)', 'v0.1.0 Beta 2', s)

original = {name: path.read_text(encoding='utf-8') for name, path in files.items()}
updated = {}

# On main, the legacy page may still say "Release preparation". When it does,
# restore the known working beta page design with the corrected back-link.
page = original['docs/download.html']
if 'Release preparation' in page and 'being prepared for public distribution' in page:
    page = (REPO / 'tools' / 'beta2_download_template.html').read_text(encoding='utf-8')
else:
    page = fix_version(page.replace(OLD, NEW))
    # Repair the older local-folder navigation issue without changing other links.
    page = re.sub(r'(<a class="(?:brand|back)" href=")\./("[^>]*>)',
                  r'\1./index.html\2', page)
if NEW not in page:
    raise SystemExit('Cannot locate the Beta 2 release link in docs/download.html; no files changed.')
updated['docs/download.html'] = page

# Make the demo's banner link to the download page, not to its own folder.
index = original['docs/index.html'].replace(OLD, NEW)
index = index.replace('macOS · Python app available', 'macOS · Beta 2 available')
index = index.replace('macOS · Beta available', 'macOS · Beta 2 available')
if 'href="./download.html"' not in index and 'href="download.html"' not in index:
    link = '<a href="./download.html">Get macOS Beta ↗</a>'
    source = '<a href="https://github.com/rayjim28/signalproof" target="_blank" rel="noopener noreferrer">Source code ↗</a>'
    if source not in index:
        raise SystemExit('Could not identify public-demo banner in docs/index.html; no files changed.')
    index = index.replace(source, link + source, 1)
updated['docs/index.html'] = index

readme = original['README.md'].replace(OLD, NEW)
readme = fix_version(readme)
readme = readme.replace(
    '- **macOS:** The local Python app is working. A standalone installer is still being developed.',
    '- **macOS:** Beta 2 available for Apple Silicon (unsigned and unnotarized).'
)
if NEW not in readme:
    raise SystemExit('README.md has no beta release link. Review it manually; no files changed.')
updated['README.md'] = readme

# Write only after all files have passed validation.
for name, path in files.items():
    if updated[name] != original[name]:
        path.write_text(updated[name], encoding='utf-8')
        print(f'Updated {name}')
    else:
        print(f'Already current: {name}')
print('Beta 2 download page, demo link and README are ready for review.')
