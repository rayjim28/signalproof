# SignalProof

My internet would sometimes lag or drop for a few seconds, and by the time I checked it, everything looked normal again. I built SignalProof to record those interruptions and give me something concrete to look at instead of guessing.

SignalProof is a local Python application with a browser dashboard. It runs lightweight connection checks in the background and stores the results in SQLite. I can also run a separate speed and latency test when I need one. The speed test **never starts automatically**.

## Platform support

- **macOS:** The local Python app is working. A standalone installer is still being developed.
- **Windows:** Coming soon.
- **Linux:** Coming soon.

The browser demo is available to everyone, but uses sample measurements instead of testing the visitor's connection.

## What it does

- Checks two external TCP endpoints and, when possible, my default gateway.
- Records repeated connection failures, recoveries, and approximate incident durations.
- Shows a timeline of measurements, incidents, and troubleshooting suggestions.
- Lets me change monitoring intervals and incident thresholds.
- Runs a **manual** performance test for download speed, upload speed, ping, jitter, and packet loss.
- Keeps past performance tests in SQLite and exports measurements, incidents, and speed-test results to CSV.
- Builds a printable report with connection history and the latest manual test.

## Run it

I use Python 3.10 or newer. The project doesn't need pip or npm packages.

```bash
cd ~/personal_projects/signalproof
python3 app.py
```

I open `http://127.0.0.1:8765` in my browser. The terminal needs to stay open for the monitoring agent to run. `Control+C` stops it.

## Manual speed and gaming checks

The **Performance lab** is below the main connection status. I select a ping target, click **Run performance test**, and wait for it to finish. Results are saved locally. Tests never repeat on a schedule.

Here's exactly what the test measures:

- **Download:** on macOS, it uses Apple's built-in `networkQuality` command when I click **Run performance test**. It tests download only, then saves the reported Mbps reading. If that command is missing or fails, it tries the capped HTTP download test.
- **Upload:** a 3 MiB upload to Cloudflare's speed-test endpoint.
- **Ping:** 10 ICMP echo requests to the selected public endpoint, using the Mac's `ping` command.
- **Jitter:** the average absolute change between consecutive successful ping round-trip times.
- **Packet loss:** the percentage of ICMP requests that didn't receive a reply.

The upload transfer is capped at 3 MiB. On macOS, the native download measurement is a throughput test and **is not capped at 12 MiB**. It can use substantially more bandwidth, depending on my connection. I only run it manually. Results can differ from a speed test that runs longer or uses multiple simultaneous connections. The upload goes to Cloudflare; the Mac download test uses Apple's network quality service. Both services see the public IP used for those requests.

**Gaming latency is an estimate, not actual in-game ping.** SignalProof does not connect to NBA 2K, Call of Duty, PSN, or Xbox servers. The selected target is a public network endpoint; the route to an actual game server can be different. Some networks also block ICMP, which can make packet loss look high even when other traffic is working. Results are left blank if a measurement fails rather than inventing a number.

If an endpoint rejects a test, the other measurements are kept and the error is displayed. Cloudflare and Hetzner are different network destinations, so results may vary based on their location and load. Only one performance test can run at a time.

## If a performance test comes back partial

A blank reading means that check did not finish. It does not necessarily mean the internet is down. I fixed the macOS ping command lookup so the app finds `/sbin/ping` even when the process has a limited command path. The download measurement uses macOS `networkQuality` first, rather than repeatedly retrying servers that reject automated downloads. When it cannot run, the app tries the original capped HTTP test. If every source fails, the reading remains blank and shows the reason.

To confirm the ping tool works outside SignalProof on my Mac, I can run:

```bash
/sbin/ping -c 3 9.9.9.9
```

This only tests ICMP reachability. Some networks reject ping requests even when websites are working.

## Existing data

I can update the source files without replacing `measurements.db`. SignalProof adds a `performance_tests` table to the existing SQLite database. It leaves my earlier measurements, settings, and incidents in place.

Before updating, I stop the server and make a backup:

```bash
cd ~/personal_projects
cp -R signalproof "signalproof-backup-$(date +%Y%m%d-%H%M%S)"
unzip -o ~/Downloads/signalproof-download-fix.zip -d signalproof
cd signalproof
python3 app.py
```

The ZIP doesn't include a database or new sample measurements. It updates the existing app, not the saved data.

## Project files

- `app.py` — local HTTP server, monitoring loop, database, and evidence reports.
- `performance.py` — manual speed checks, ping parsing, and performance history.
- `index.html` — the dashboard layout.
- `styles.css` — dark, responsive interface.
- `app.js` — rendering, buttons, and live status updates.
- `tests/` — tests for incident detection, settings, and manual performance checks.

To run the tests:

```bash
python3 -m unittest discover -s tests -v
```

All saved results are local. The application binds to `127.0.0.1` instead of opening a public network port. If port 8765 is already occupied, I use `SIGNALPROOF_PORT=8766 python3 app.py`.

## What I want to improve next

I'd like to compare local gateway reliability against remote endpoint failures more carefully and add optional alerts. A public portfolio demo will need sample data because a hosted app cannot directly monitor someone else's home connection.

## Browser demo

I put together a public demo so people can explore SignalProof without installing Python. It has sample connection history, incidents, and performance results. The controls let visitors browse example data, but the demo does not run tests against their networks.

[Try the demo](https://rayjim28.github.io/signalproof/)

The local Python application is the part that measures a real connection and saves its history.
