"""Start at login, and stop. Linux (systemd user service): verified by design, test with `doctor`.
macOS (launchd) and Windows (Startup folder): UNTESTED until a teammate confirms."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from . import config

UNIT = "pu-outreach.service"
LABEL = "in.bits.pu-outreach"


def _cmd() -> list[str]:
    py = sys.executable
    if sys.platform == "win32":
        w = Path(py).with_name("pythonw.exe")
        if w.exists():
            py = str(w)
    return [py, "-m", "pu_outreach", "run"]


def pid_file() -> Path:
    return config.data_dir() / "run.pid"


def enable() -> str:
    cmd = _cmd()
    if sys.platform.startswith("linux"):
        unit = Path.home() / ".config" / "systemd" / "user" / UNIT
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(
            "[Unit]\nDescription=PU Outreach screenshot watcher\n"
            "PartOf=graphical-session.target\nAfter=graphical-session.target\n\n"
            f"[Service]\nExecStart={' '.join(cmd)}\nRestart=on-failure\nRestartSec=5\n\n"
            "[Install]\nWantedBy=graphical-session.target\n")
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        subprocess.run(["systemctl", "--user", "enable", "--now", UNIT])
        return f"systemd user service installed: {unit}"
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"<string>{a}</string>" for a in cmd)
        log = config.data_dir() / "run.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict><key>Label</key><string>{LABEL}</string>'
            f"<key>ProgramArguments</key><array>{args}</array>"
            "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
            f"<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>"
            "</dict></plist>\n")
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)])
        return f"launchd agent installed: {plist}"
    if sys.platform == "win32":
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        vbs = startup / "pu-outreach.vbs"
        quoted = " ".join(f'""{a}""' for a in cmd)
        vbs.write_text(f'CreateObject("WScript.Shell").Run "{quoted}", 0, False\n')
        subprocess.Popen(["wscript", str(vbs)])
        return f"Startup script installed: {vbs}"
    return "autostart not supported on this OS"


def disable() -> str:
    stop()
    if sys.platform.startswith("linux"):
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT], capture_output=True)
        (Path.home() / ".config" / "systemd" / "user" / UNIT).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"])
    elif sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
    elif sys.platform == "win32":
        (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "pu-outreach.vbs").unlink(missing_ok=True)
    return "autostart removed"


def stop() -> str:
    msgs = []
    if sys.platform.startswith("linux"):
        r = subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True)
        if r.returncode == 0:
            msgs.append("service stopped")
    elif sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            msgs.append("launchd agent unloaded (runs again at next login; use `autostart disable` to remove)")
    p = pid_file()
    if p.exists():
        try:
            pid = int(p.read_text().strip())
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            msgs.append(f"process {pid} stopped")
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            pass
        p.unlink(missing_ok=True)
    return "; ".join(msgs) or "nothing was running"
