#!/usr/bin/env python3
"""Small, repeatable SignalProof README change for the first desktop beta.
Run from the repository root: python3 tools/update_beta_readme.py
"""
from pathlib import Path

readme = Path('README.md')
if not readme.is_file():
    raise SystemExit('README.md not found. Run this from the SignalProof project root.')

text = readme.read_text(encoding='utf-8')
start_marker = '<!-- SIGNALPROOF_MACOS_BETA_START -->'
end_marker = '<!-- SIGNALPROOF_MACOS_BETA_END -->'

new_support = ('  * macOS: **v0.1.0 Beta available for Apple Silicon**. '
               'Unsigned and not notarized by Apple.')
old_support = ('  * macOS: The local Python app is working. '
               'A standalone installer is still being developed.')
# Also handle hyphen lists as used in the checked public README.
for bullet in ('  * ', '* ', '- '):
    old = bullet + 'macOS: The local Python app is working. A standalone installer is still being developed.'
    new = bullet + 'macOS: **v0.1.0 Beta available for Apple Silicon**. Unsigned and not notarized by Apple.'
    text = text.replace(old, new)

section = '''<!-- SIGNALPROOF_MACOS_BETA_START -->
## Download the macOS beta

**SignalProof v0.1.0 Beta** is available for Apple Silicon Macs (M-series chips). This is the actual local desktop monitoring app, not the sample-data browser demo.

**[Get the macOS beta on GitHub Releases](https://github.com/rayjim28/signalproof/releases/tag/v0.1.0-beta.1)**

1. On the release page, expand **Assets** and download the macOS ZIP whose name ends in `UNNOTARIZED.zip` (not the `.sha256` checksum or GitHub's source-code ZIP).
2. Extract the ZIP and move `SignalProof.app` into **Applications**.
3. Open SignalProof. If macOS blocks it, after attempting to open it visit **System Settings → Privacy & Security**, find the SignalProof notice, and select **Open Anyway** *only if you trust the download*.
4. Use the local dashboard to run diagnostics and manual performance tests. Use **Quit app** when you want to stop the local monitoring agent.

**Important:** This beta is not Developer ID signed or notarized by Apple. No paid Apple developer membership or Python installation is required to run the packaged application, but some Macs may require a manual security exception. Do not disable macOS security globally. The standalone download currently targets Apple Silicon only; Windows and Linux are coming soon.

The hosted [browser demo](https://rayjim28.github.io/signalproof/) displays example measurements. It **does not** measure the visitor's internet connection. The installed desktop app monitors the local connection.

Found a problem? [Report a bug on GitHub Issues](https://github.com/rayjim28/signalproof/issues/new/choose). Please remove private information (including public IP addresses) from screenshots and logs.
<!-- SIGNALPROOF_MACOS_BETA_END -->'''

if start_marker in text and end_marker in text:
    before, rest = text.split(start_marker, 1)
    _, after = rest.split(end_marker, 1)
    text = before + section + after
elif start_marker in text or end_marker in text:
    raise SystemExit('README has only one beta marker; please inspect it before modifying.')
else:
    anchor = '## What it does'
    if anchor not in text:
        raise SystemExit(f'Could not find the expected README section: {anchor}. No file changed.')
    text = text.replace(anchor, section + '\n\n' + anchor, 1)

# Remove accidental duplicates when run multiple times.
readme.write_text(text, encoding='utf-8')
print('README.md: macOS beta section updated successfully.')
