#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  echo "Usage: bash release_macos.sh v0.1.0 --candidate|--notarize"
  echo "  --candidate: creates an unsigned local-test ZIP; do not publish as a general release"
  echo "  --notarize: verifies Developer ID signing, notarizes, staples, and creates a public-release ZIP"
}

if [[ $# -ne 2 || ! "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || ( "$2" != "--candidate" && "$2" != "--notarize" ) ]]; then
  usage
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this on the Mac that built SignalProof.app."
  exit 1
fi

version="$1"
mode="$2"
arch="$(uname -m)"
if [[ "$arch" != "arm64" && "$arch" != "x86_64" ]]; then
  echo "Unsupported architecture: $arch"
  exit 1
fi

app="dist/SignalProof.app"
if [[ ! -d "$app" || ! -f "$app/Contents/Info.plist" ]]; then
  echo "Missing $app. Run bash build_macos.sh first."
  exit 1
fi

# The app archive must not contain anyone's connection history.
if find "$app" -type f \( -name 'measurements.db' -o -name '*.sqlite3' -o -name '*.db-wal' -o -name '*.db-shm' \) | grep -q .; then
  echo "Private SQLite data found inside the app bundle. Refusing to package."
  exit 1
fi

if [[ "$mode" == "--notarize" ]]; then
  if ! codesign -dv --verbose=4 "$app" 2>&1 | grep -q '^Authority=Developer ID Application:'; then
    echo "This app is not signed with a Developer ID Application certificate."
    echo "Rebuild it with SIGNALPROOF_CODESIGN_IDENTITY set."
    exit 1
  fi
  codesign --verify --deep --strict --verbose=2 "$app"
  if ! xcrun --find notarytool >/dev/null 2>&1; then
    echo "notarytool is not available. Install a supported version of Xcode."
    exit 1
  fi
  # Apple only accepts archived apps for notarization.
  submission="dist/SignalProof-${version}-notary-submission.zip"
  ditto -c -k --sequesterRsrc --keepParent "$app" "$submission"
  profile="${SIGNALPROOF_NOTARY_PROFILE:-SignalProofNotary}"
  xcrun notarytool submit "$submission" --keychain-profile "$profile" --wait
  xcrun stapler staple "$app"
  xcrun stapler validate "$app"
  codesign --verify --deep --strict --verbose=2 "$app"
  spctl --assess --type execute --verbose=4 "$app"
  rm -f "$submission"
  out="dist/SignalProof-${version}-macOS-${arch}.zip"
else
  echo "Creating a LOCAL TEST archive. This is not a signed/notarized public download."
  out="dist/SignalProof-${version}-macOS-${arch}-LOCAL-TEST.zip"
fi

rm -f "$out" "$out.sha256"
ditto -c -k --sequesterRsrc --keepParent "$app" "$out"
(cd "$(dirname "$out")" && shasum -a 256 "$(basename "$out")" > "$(basename "$out").sha256")

echo
printf 'Created: %s\n' "$out"
printf 'Checksum: %s.sha256\n' "$out"
if [[ "$mode" == "--candidate" ]]; then
  echo "Try this archive on another Mac. Don't label it a public, notarized release."
else
  echo "Developer ID signature and notarization verified. Test on another Mac before making the GitHub Release public."
fi
