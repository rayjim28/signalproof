# SignalProof — macOS release

The local Mac app is working. I want to make it available to other people without asking them to install Python or lower their Mac's security settings.

## 1. Build and test it

Use the working SignalProof repository on a Mac:

```bash
cd ~/personal_projects/signalproof
python3 -m unittest discover -s tests -q
bash build_macos.sh
open dist/SignalProof.app
```

Check the real download/upload, ping, jitter, packet loss, CSV report and incident history. Quit and reopen the app; verify the database still contains earlier readings. Test the build on another Mac with the same architecture too. Make sure `python3 app.py` is stopped first so the port is available.

## 2. Create a local release candidate

```bash
bash release_macos.sh v0.1.0 --candidate
```

This makes `dist/SignalProof-v0.1.0-macOS-arm64-LOCAL-TEST.zip` on an Apple Silicon Mac (or an `x86_64` file on an Intel Mac), plus a SHA-256 checksum file. The candidate is for local evaluation, **not** a public signed release. macOS Gatekeeper may block it on other computers.

## 3. Developer ID signing and notarization

Apple's public distribution flow needs an Apple Developer Program account, an installed **Developer ID Application** certificate, and a notarization profile configured on this Mac. The identity can be listed with:

```bash
security find-identity -v -p codesigning
```

Set the identity in your local shell using the *exact* name from your keychain. Don't put signing credentials, certificates, app passwords, or API keys into the repository.

```bash
export SIGNALPROOF_CODESIGN_IDENTITY='Developer ID Application: YOUR CERTIFICATE NAME (TEAMID)'
bash build_macos.sh
```

The build script passes your identity to PyInstaller, which signs the collected binaries and uses the hardened runtime. A release can't be notarized with an ad-hoc signature.

Configure notarization credentials using Apple's `xcrun notarytool store-credentials` and a local keychain profile named `SignalProofNotary` (or set `SIGNALPROOF_NOTARY_PROFILE` to an existing profile). Use an App Store Connect API key or another Apple-supported authentication method. See Apple's docs: https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution

Then:

```bash
bash release_macos.sh v0.1.0 --notarize
```

The script verifies Developer ID signing, submits an archive for notarization, staples Apple's ticket to the `.app`, verifies Gatekeeper acceptance, then creates a fresh ZIP containing the stapled app and a `.sha256` file. It stops rather than making a public ZIP if any check fails.

## 4. Publish on GitHub

1. Push the updated source and build scripts to `rayjim28/signalproof`, excluding personal database files.
2. Open https://github.com/rayjim28/signalproof/releases/new.
3. Set tag `v0.1.0` and title `SignalProof v0.1.0 — macOS`.
4. Upload only the **notarized**, non-LOCAL-TEST ZIP and its checksum.
5. Mention the architecture (`Apple Silicon` or `Intel`), minimum tested macOS version, that speed tests are manual, and that Windows/Linux are coming soon.
6. Test downloading and opening the ZIP on a different Mac with Gatekeeper enabled before announcing general availability.

For now, the public download page deliberately says **Release preparation**, not **Download now**. Update that label and add the exact release asset URL only after the notarized release is published. The demo still uses synthetic data and remains publicly usable.

## 5. Add the platform page to the demo

```bash
python3 tools/add_download_link.py
python3 -m http.server 8085 --directory docs
```

Preview `http://127.0.0.1:8085/download.html` and the homepage link, stop the local server with `Control+C`, then commit and push `docs/download.html` and `docs/index.html` with the build scripts. GitHub Pages publishes the page from the existing `docs` folder.

## A note on privacy

Measurements stay in `~/Library/Application Support/SignalProof` for the bundled Mac app. That local database and your personal logs should never be part of a GitHub Release. Network tests contact the selected external endpoints and upload/download services; users should know this before starting a manual speed test.
