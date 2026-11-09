"""Config lives OUTSIDE the repo, per user, per OS."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

APP = "pu-outreach"

DEFAULTS = {
    "webapp_url": "",
    "token": "",
    "member": "",
    "screenshot_dir": "",
    "delete_after_success": False,   # only ever deletes screenshots it recognised as LinkedIn profiles
    "tesseract_cmd": "tesseract",
    "poll_seconds": 1.0,
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        cfg.update(json.loads(p.read_text("utf-8")))
    if not cfg["screenshot_dir"]:
        cfg["screenshot_dir"] = str(default_screenshot_dir())
    return cfg


def save(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), "utf-8")
    try:
        os.chmod(p, 0o600)          # token is a secret
    except OSError:
        pass
    return p


def default_screenshot_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        try:
            loc = subprocess.run(["defaults", "read", "com.apple.screencapture", "location"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if loc:
                return Path(os.path.expanduser(loc))
        except Exception:
            pass
        return home / "Desktop"
    if sys.platform == "win32":
        for p in (home / "OneDrive" / "Pictures" / "Screenshots", home / "Pictures" / "Screenshots"):
            if p.exists():
                return p
        return home / "Pictures" / "Screenshots"
    pictures = home / "Pictures"
    ud = home / ".config" / "user-dirs.dirs"
    if ud.exists():
        for line in ud.read_text("utf-8", "ignore").splitlines():
            if line.startswith("XDG_PICTURES_DIR="):
                val = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home))
                pictures = Path(val)
    return pictures / "Screenshots"
