"""Watch the screenshot folder; for each LinkedIn profile screenshot: read → dedupe → draft → row."""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import client, metrics, names, notify
from .ocr import OCR, Capture, read_screenshot

IMAGE_EXT = {".png", ".jpg", ".jpeg"}


def build_payload(cap: Capture) -> tuple[dict, str]:
    greet, greet_note = names.greeting(cap.name)
    remarks = [greet_note] + cap.flags
    return {
        "company_full": cap.company_full or "",
        "company_short": cap.company_short or "",
        "poc": cap.name or "",
        "email": cap.email or "",
        "mobile": cap.phone or "",
        "linkedin": cap.linkedin or "",
        "greeting": greet,
        "remarks": remarks,
    }, greet


def process(path: Path, cfg: dict, dry_run: bool = False) -> str:
    started = path.stat().st_mtime
    cap = read_screenshot(str(path), OCR(cfg.get("tesseract_cmd") or "tesseract"))
    if not cap.is_profile:
        return "ignored"                                    # not a LinkedIn profile: stay silent
    company = cap.company_short or ""
    if cap.blocking:
        notify.send("PU Outreach: not drafted", cap.blocking)
        metrics.record("unclear", started, company, flags=[cap.blocking])
        return "unclear"

    payload, greet = build_payload(cap)
    try:
        res = client.call(cfg["webapp_url"], cfg["token"], "draft", contact=payload, dry_run=dry_run)
    except client.DrafterError as e:
        notify.send("PU Outreach: error", str(e))
        metrics.record("error", started, company, flags=[str(e)])
        return "error"

    if not res.get("ok"):
        msg = res.get("detail") or res.get("error") or "unknown error"
        notify.send("PU Outreach: error", msg)
        metrics.record("error", started, company, row=res.get("row", ""), flags=[msg])
        return "error"

    out = res.get("outcome")
    if out == "duplicate":
        d = res["duplicate"]
        notify.send("PU Outreach: duplicate — no draft",
                    f"{company or cap.email} already in row {d['row']} (same {d['by']}, status: {d.get('status') or '—'})")
        metrics.record("duplicate", started, company, row=d["row"], duplicate=True)
    elif out == "drafted":
        notify.send("PU Outreach: draft ready", f"{company} → {greet} {cap.email}  (row {res['row']})")
        metrics.record("drafted", started, company, row=res["row"], flags=cap.flags)
    elif out == "row_only":
        notify.send("PU Outreach: row saved, no draft", f"row {res['row']}: needs company name")
        metrics.record("row_only", started, company, row=res["row"], flags=cap.flags)
    elif out == "dry_run":
        notify.send("PU Outreach: dry run OK", f"would write row {res.get('would_write_row')}: {res.get('subject')}")
    return out or "error"


def watch(cfg: dict) -> None:
    folder = Path(cfg["screenshot_dir"]).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    seen = {p.name for p in folder.iterdir()}
    pending: dict[str, int] = {}
    notify.send("PU Outreach running", f"watching {folder}")
    while True:
        try:
            for p in folder.iterdir():
                if p.name in seen or p.suffix.lower() not in IMAGE_EXT:
                    continue
                size = p.stat().st_size
                if pending.get(p.name) != size or size == 0:    # wait until the file stops growing
                    pending[p.name] = size
                    continue
                seen.add(p.name)
                pending.pop(p.name, None)
                try:
                    outcome = process(p, cfg)
                except Exception as e:                           # never crash the watcher
                    notify.send("PU Outreach: error", f"{type(e).__name__}: {e}")
                    outcome = "error"
                if outcome == "drafted" and cfg.get("delete_after_success"):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        except FileNotFoundError:
            folder.mkdir(parents=True, exist_ok=True)
        time.sleep(float(cfg.get("poll_seconds") or 1.0))
