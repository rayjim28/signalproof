# Building SignalProof for macOS

I originally ran SignalProof with `python3 app.py`, which worked but wasn't how I wanted other people to use it. This build gives me a Mac application I can launch from Finder. The dashboard still opens in a browser, but the Python server is bundled inside the app.

## Build on a Mac

Python 3.12 is needed **to build** the app, not to use the finished `.app`. In the SignalProof folder:

```bash
bash build_macos.sh
```

The script installs PyInstaller into a separate `.build-venv`, bundles the dashboard files, and creates `dist/SignalProof.app`. It does not install PyInstaller into my monitoring environment. The computer building the app needs internet access for the initial PyInstaller install.

## Try it

1. Stop the old `python3 app.py` process with `Control+C`. The desktop app uses the same localhost port.
2. Open `dist/SignalProof.app` from Finder.
3. The dashboard opens at `http://127.0.0.1:8765`.
4. A small macOS control dialog stays open. Use **Open Dashboard** to reopen the page or **Quit SignalProof** to stop the monitor.
5. Run one manual performance test and make sure the results and incident history appear.

The first launch copies the existing `~/personal_projects/signalproof/measurements.db`, if present, into `~/Library/Application Support/SignalProof/measurements.db`. The original stays where it is. Later launches use the Application Support copy. This also means that results collected by the desktop app don't automatically appear in the old Terminal version.

The app only listens on `127.0.0.1`, not the public internet. The ordinary connectivity checks still run while the app is open. Download/upload testing remains manual.

## Release notes

This is a **local macOS build**, not yet a signed/notarized public release. PyInstaller creates a macOS `.app` on the same architecture used for the build. Test on another Mac before distributing it. Apple's Gatekeeper may block an unnotarized build on another computer. I won't ask users to disable their Mac's security protections to install it; signing and notarization are the next release step.

Windows and Linux: **Coming soon**. The GitHub Pages demo is interactive sample data, not real network monitoring.

If the app doesn't open, the startup log is at `~/Library/Logs/SignalProof/launcher.log`. A process already using port 8765 will also prevent the desktop version from starting.

## Publishing

Don't publish `measurements.db`, a generated `.build-venv`, or private logs to GitHub. After testing the `.app` locally, package a clean release ZIP from your Mac and add it to a GitHub Release once signing and distribution checks are complete.
