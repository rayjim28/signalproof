"""Read-only connection-quality summaries from existing SignalProof measurements.

These timings are TCP connection setup times to SignalProof's configured primary
endpoint, not Internet speed, game-server latency, or definitive ISP outages.
"""

from math import ceil
from statistics import median


def summarize_quality(db, since, settings):
    """Summarize every primary endpoint check in the selected time window.

    An unusual spike is a successful TCP check whose connection time reaches
    both the user-selected slow-check threshold and at least 2x the median.
    Five successful samples are required to establish that baseline.
    """
    rows = list(db.execute(
        "SELECT checked_at, online, latency_ms FROM measurements "
        "WHERE target = ? AND checked_at >= ? ORDER BY id ASC",
        ("Internet", since),
    ))
    good = [(row["checked_at"], float(row["latency_ms"])) for row in rows
            if row["online"] and row["latency_ms"] is not None
            and 0 <= float(row["latency_ms"]) < float("inf")]
    values = sorted(latency for _, latency in good)
    slow_threshold = int(settings["slow_connect_ms"])
    baseline = median(values) if len(values) >= 5 else None
    spike_threshold = max(float(slow_threshold), baseline * 2) if baseline is not None else None
    spikes = ([{"checked_at": stamp, "latency_ms": round(latency, 1)}
               for stamp, latency in good if latency >= spike_threshold]
              if spike_threshold is not None else [])
    p95 = values[ceil(len(values) * .95) - 1] if values else None
    return {
        "total_checks": len(rows),
        "failed_checks": sum(1 for row in rows if not row["online"]),
        "successful_timed_checks": len(values),
        "slow_checks": sum(1 for value in values if value >= slow_threshold),
        "slow_threshold_ms": slow_threshold,
        "baseline_median_ms": round(baseline, 1) if baseline is not None else None,
        "p95_ms": round(p95, 1) if p95 is not None else None,
        "spike_threshold_ms": round(spike_threshold, 1) if spike_threshold is not None else None,
        "spike_count": len(spikes),
        "recent_spikes": list(reversed(spikes[-5:])),
    }
