"""pu-outreach command line: setup, doctor, run, try, stats, autostart, stop, greet, build-names."""
from __future__ import annotations

import argparse
import getpass
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import __version__, autostart, client, config, metrics, names, notify, pipeline
from .ocr import OCR, read_screenshot

OK, BAD, INFO = "✔", "✖", "•"


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    shown = f" [{'(saved)' if secret and default else default}]" if default else ""
    val = (getpass.getpass if secret else input)(f"{prompt}{shown}: ").strip()
    return val or default


# ------------------------------------------------------------------ setup

def cmd_setup(_a) -> int:
    cfg = config.load()
    print("PU Outreach setup. Press Enter to keep the value in [brackets].\n")
    cfg["member"] = _ask("Your name (kept on this computer only)", cfg["member"])
    print("\nFrom your Apps Script deployment (Deploy > Manage deployments): the Web app URL ending in /exec")
    cfg["webapp_url"] = _ask("Web app URL", cfg["webapp_url"])
    print("\nThe token printed when you ran setupToken in the Apps Script editor")
    cfg["token"] = _ask("Token", cfg["token"], secret=True)
    cfg["screenshot_dir"] = _ask("\nScreenshot folder to watch", cfg["screenshot_dir"])
    d = _ask("Delete a profile screenshot after its draft is created? (y/n)",
             "y" if cfg["delete_after_success"] else "n")
    cfg["delete_after_success"] = d.lower().startswith("y")
    p = config.save(cfg)
    print(f"\nSaved to {p}\n")
    return cmd_doctor(argparse.Namespace(notify=False))


# ------------------------------------------------------------------ doctor

def cmd_doctor(a) -> int:
    cfg = config.load()
    fails = 0

    def line(ok, name, detail="", fix=""):
        nonlocal fails
        mark = OK if ok is True else (BAD if ok is False else INFO)
        if ok is False:
            fails += 1
        print(f" {mark} {name}" + (f": {detail}" if detail else ""))
        if ok is False and fix:
            print(f"     → fix: {fix}")

    print("This computer")
    line(sys.version_info >= (3, 10), "Python", platform.python_version(), "install Python 3.10 or newer")
    line(INFO, "OS", f"{platform.system()} {platform.release()}"
         + (f", session={os.environ.get('XDG_SESSION_TYPE', '?')}" if sys.platform.startswith("linux") else ""))
    tess = shutil.which(cfg["tesseract_cmd"]) or (cfg["tesseract_cmd"] if Path(cfg["tesseract_cmd"]).exists() else None)
    if tess:
        v = subprocess.run([tess, "--version"], capture_output=True, text=True).stdout.splitlines()
        line(True, "Tesseract OCR", v[0] if v else tess)
    else:
        line(False, "Tesseract OCR", "not found", {
            "linux": "sudo apt install tesseract-ocr", "darwin": "brew install tesseract",
            "win32": "install from github.com/UB-Mannheim/tesseract/wiki, then set tesseract_cmd in config",
        }.get("linux" if sys.platform.startswith("linux") else sys.platform, "install tesseract"))
    sd = Path(cfg["screenshot_dir"]).expanduser()
    line(sd.exists(), "Screenshot folder", str(sd), "take one screenshot, or set the right folder with `pu-outreach setup`")
    nt = notify.tool_available()
    line(bool(nt), "Notifications", nt or "none", "Linux: sudo apt install libnotify-bin")
    if a.notify and nt:
        notify.send("PU Outreach test", "If you see this, notifications work")
    n = len(names.table())
    line(n > 0, "Names data (for ma'am/sir)", f"{n:,} names" if n else "missing — every greeting will be 'Dear Team,'",
         "ask the maintainer for data/names.json.gz, or run `pu-outreach build-names`")
    line(config.config_path().exists(), "Config", str(config.config_path()), "run `pu-outreach setup`")

    print("\nYour web app (Apps Script)")
    if not cfg["webapp_url"] or not cfg["token"]:
        line(False, "Web app", "URL or token missing", "run `pu-outreach setup`")
    else:
        try:
            r = client.call(cfg["webapp_url"], cfg["token"], "ping", timeout=60)
            line(bool(r.get("ok")), "Reachable", f"running as {r.get('user', '?')}", r.get("fix", ""))
            d = client.call(cfg["webapp_url"], cfg["token"], "doctor", timeout=180)
            for c in d.get("checks", []):
                line(c["ok"], c["name"], c.get("detail", ""), c.get("detail", "") if not c["ok"] else "")
        except client.DrafterError as e:
            line(False, "Web app", str(e))
    print(f"\n{'All good.' if not fails else f'{fails} problem(s) found.'}")
    return 1 if fails else 0


# ------------------------------------------------------------------ run / try

def cmd_run(_a) -> int:
    cfg = config.load()
    if not cfg["webapp_url"] or not cfg["token"]:
        print("Not set up yet: run `pu-outreach setup` first.")
        return 1
    pf = autostart.pid_file()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(os.getpid()))
    try:
        pipeline.watch(cfg)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        pf.unlink(missing_ok=True)
    return 0


def cmd_try(a) -> int:
    cfg = config.load()
    cap = read_screenshot(a.image, OCR(cfg.get("tesseract_cmd") or "tesseract"))
    payload, _ = pipeline.build_payload(cap)
    print(json.dumps({
        "is_profile": cap.is_profile, "blocking": cap.blocking,
        **{k: v for k, v in payload.items() if k != "remarks"},
        "remarks": payload["remarks"],
    }, indent=2, ensure_ascii=False))
    if a.debug:
        print("\n--- raw OCR ---")
        for k, v in cap.debug.items():
            print(f"[{k}]\n{v}\n")
    if a.server or a.draft:
        if not cap.is_profile or cap.blocking:
            print("Not sending: " + (cap.blocking or "not a profile"))
            return 1
        res = client.call(cfg["webapp_url"], cfg["token"], "draft", contact=payload, dry_run=not a.draft)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ stats

def cmd_stats(_a) -> int:
    s = metrics.summary()
    if not s:
        print("No captures recorded yet.")
    else:
        for k, v in s.items():
            print(f"{k.replace('_', ' '):38} {v}")
    cfg = config.load()
    if cfg["webapp_url"] and cfg["token"]:
        try:
            r = client.call(cfg["webapp_url"], cfg["token"], "stats", timeout=60)
            st = r.get("stats", {})
            print(f"{'sent (seen in Sent mail)':38} {st.get('sent', 0)}")
            print(f"{'  sent unedited':38} {st.get('unedited', 0)}")
            print(f"{'  edited before sending':38} {st.get('edited', 0)}")
            if not st.get("sent"):
                print("  (needs installSentChecker run once in Apps Script)")
        except client.DrafterError as e:
            print(f"server stats unavailable: {e}")
    print(f"\nRaw log: {metrics.path()}")
    return 0


# ------------------------------------------------------------------ misc

def cmd_autostart(a) -> int:
    print({"enable": autostart.enable, "disable": autostart.disable}[a.what]())
    return 0


def cmd_stop(_a) -> int:
    print(autostart.stop())
    return 0


def cmd_greet(a) -> int:
    g, note = names.greeting(" ".join(a.name))
    print(g, f"   ({note})")
    return 0


HF = "https://huggingface.co/gojiberries/naampy/resolve/72d5ec16d3ede38e3627504a108b69ffd114c813/"


def cmd_build_names(a) -> int:
    """Downloads naampy's published first-name lookup (CC0 electoral-roll source) → names.json.gz."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("Needs pyarrow once:  uv tool run --from . --with pyarrow pu-outreach build-names --out pu_outreach/data/names.json.gz")
        return 1
    tmp = config.data_dir() / "naampy"
    tmp.mkdir(parents=True, exist_ok=True)
    man = tmp / "manifest.json"
    urllib.request.urlretrieve(HF + "first_name_composition_manifest.json", man)
    m = json.loads(man.read_text())
    fn, sha = m["output"]["filename"], m["output"]["sha256"]
    pq_path = tmp / fn
    urllib.request.urlretrieve(HF + fn, pq_path)
    if hashlib.sha256(pq_path.read_bytes()).hexdigest() != sha:
        print("Checksum mismatch — download corrupted, try again.")
        return 1
    t = pq.read_table(pq_path).to_pydict()
    data = {n: [f, mm] for n, f, mm in zip(t["normalized_name"], t["female_label_record_count"], t["male_label_record_count"])}
    out = Path(a.out) if a.out else config.data_dir() / "names.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{len(data):,} names written to {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pu-outreach", description="Screenshot a LinkedIn profile → Sheet row + Gmail draft.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="guided setup").set_defaults(f=cmd_setup)
    d = sub.add_parser("doctor", help="check everything, with fixes")
    d.add_argument("--notify", action="store_true", help="also send a test notification")
    d.set_defaults(f=cmd_doctor)
    sub.add_parser("run", help="watch the screenshot folder (foreground)").set_defaults(f=cmd_run)
    t = sub.add_parser("try", help="read one screenshot and show what would be saved")
    t.add_argument("image")
    t.add_argument("--debug", action="store_true", help="show raw OCR text")
    t.add_argument("--server", action="store_true", help="also ask the web app for a dry run (no draft, no row)")
    t.add_argument("--draft", action="store_true", help="really create the draft and row")
    t.set_defaults(f=cmd_try)
    sub.add_parser("stats", help="measurement summary").set_defaults(f=cmd_stats)
    au = sub.add_parser("autostart", help="start at login")
    au.add_argument("what", choices=["enable", "disable"])
    au.set_defaults(f=cmd_autostart)
    sub.add_parser("stop", help="stop the running watcher").set_defaults(f=cmd_stop)
    g = sub.add_parser("greet", help="show the greeting a name would get")
    g.add_argument("name", nargs="+")
    g.set_defaults(f=cmd_greet)
    b = sub.add_parser("build-names", help="(maintainer) download the names data")
    b.add_argument("--out")
    b.set_defaults(f=cmd_build_names)
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
