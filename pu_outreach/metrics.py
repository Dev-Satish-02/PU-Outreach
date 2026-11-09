"""Local measurement log for the before/after comparison. Stores no personal data
(no names, emails or phones) — only timings, outcome and company."""
from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

from . import config

FIELDS = ["timestamp", "outcome", "seconds_to_draft", "duplicate", "company", "row", "flags"]


def path() -> Path:
    return config.data_dir() / "metrics.csv"


def record(outcome: str, started: float, company: str = "", row="", flags=(), duplicate=False) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "outcome": outcome,
            "seconds_to_draft": f"{time.time() - started:.1f}" if outcome == "drafted" else "",
            "duplicate": "yes" if duplicate else "no",
            "company": company or "",
            "row": row or "",
            "flags": "; ".join(flags),
        })


def summary(gap_minutes: int = 30) -> dict:
    p = path()
    if not p.exists():
        return {}
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    if not rows:
        return {}
    times = [datetime.fromisoformat(r["timestamp"]) for r in rows]
    # active time = sum of sessions (gaps > gap_minutes split sessions); each session gets +2 min
    active = 0.0
    start = prev = times[0]
    for t in times[1:]:
        if (t - prev).total_seconds() > gap_minutes * 60:
            active += (prev - start).total_seconds() + 120
            start = t
        prev = t
    active += (prev - start).total_seconds() + 120
    drafted = [r for r in rows if r["outcome"] == "drafted"]
    secs = sorted(float(r["seconds_to_draft"]) for r in drafted if r["seconds_to_draft"])
    return {
        "captures": len(rows),
        "drafted": len(drafted),
        "duplicates_blocked": sum(r["outcome"] == "duplicate" for r in rows),
        "errors": sum(r["outcome"] in ("error", "unclear") for r in rows),
        "median_seconds_screenshot_to_draft": secs[len(secs) // 2] if secs else None,
        "active_hours": round(active / 3600, 2),
        "drafts_per_active_hour": round(len(drafted) / (active / 3600), 1) if active else None,
    }
