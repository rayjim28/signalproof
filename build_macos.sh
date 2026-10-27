#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Build SignalProof.app on a Mac, not Windows or Linux."
  exit 1
fi

PYTHON="$(command -v python3.12 || true)"
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.12 is required to build. Install it with: brew install python@3.12"
  exit 1
fi

"$PYTHON" -m venv .build-venv
source .build-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'pyinstaller>=6.17,<7'

# Accumulate optional PyInstaller arguments using positional parameters.
# This also works with the older Bash version supplied with macOS and `set -u`.
set --
if command -v sips >/dev/null && command -v iconutil >/dev/null; then
  mkdir -p .icon-build/icon.iconset
  for s in 16 32 128 256 512; do
    sips -s format png -z "$s" "$s" assets/signalproof-icon-1024.png \
      --out ".icon-build/icon.iconset/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2))
    sips -s format png -z "$d" "$d" assets/signalproof-icon-1024.png \
      --out ".icon-build/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns .icon-build/icon.iconset -o .icon-build/SignalProof.icns
  set -- "$@" --icon .icon-build/SignalProof.icns
fi

# Supply a Developer ID identity only when preparing a notarized public build.

if [[ -n "${SIGNALPROOF_CODESIGN_IDENTITY:-}" ]]; then
  if [[ "$SIGNALPROOF_CODESIGN_IDENTITY" != "Developer ID Application:"* ]]; then
    echo "Expected a Developer ID Application signing identity."
    exit 1
  fi
  set -- "$@" --codesign-identity "$SIGNALPROOF_CODESIGN_IDENTITY"
fi

python -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name SignalProof \
  --osx-bundle-identifier com.rayjim28.signalproof \
  --add-data "index.html:." \
  --add-data "styles.css:." \
  --add-data "app.js:." \
  --add-data "favicon.svg:." \
  "$@" \
  desktop_launcher.py

echo
echo "Build complete: $(pwd)/dist/SignalProof.app"
echo "Stop python3 app.py if it is running, then open the app from Finder."
