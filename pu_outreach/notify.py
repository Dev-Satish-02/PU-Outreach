"""Desktop notifications per OS. Linux: verified (notify-send). macOS/Windows: untested."""
from __future__ import annotations

import shutil
import subprocess
import sys


def tool_available() -> str | None:
    if sys.platform.startswith("linux"):
        return "notify-send" if shutil.which("notify-send") else None
    if sys.platform == "darwin":
        return "osascript" if shutil.which("osascript") else None
    if sys.platform == "win32":
        return "powershell" if shutil.which("powershell") else None
    return None


def send(title: str, body: str = "") -> None:
    print(f"[{title}] {body}", flush=True)
    try:
        if sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "PU Outreach", title, body], timeout=10)
        elif sys.platform == "darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}"'], timeout=10)
        elif sys.platform == "win32":
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$x=$t.GetElementsByTagName('text');"
                f"$x.Item(0).AppendChild($t.CreateTextNode('{title.replace(chr(39), chr(39)*2)}')) > $null;"
                f"$x.Item(1).AppendChild($t.CreateTextNode('{body.replace(chr(39), chr(39)*2)}')) > $null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PU Outreach').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
