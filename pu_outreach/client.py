"""Talks to the member's own Apps Script web app."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class DrafterError(Exception):
    pass


def call(url: str, token: str, action: str, timeout: int = 180, **extra) -> dict:
    if not url:
        raise DrafterError("web-app URL not set — run `pu-outreach setup`")
    body = json.dumps({"token": token, "action": action, **extra}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        # Apps Script answers POST with a 302 to googleusercontent.com; urllib follows it as GET,
        # which is exactly what Apps Script expects.
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise DrafterError(f"web app returned HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise DrafterError(f"cannot reach web app: {e.reason}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if "<html" in raw.lower():
            raise DrafterError("web app returned a web page, not data — check the deployment's "
                               "'Who has access' is 'Anyone' and the URL ends in /exec")
        raise DrafterError("web app returned something unexpected")
    if data.get("error") == "bad_token":
        raise DrafterError("token rejected — re-run `pu-outreach setup` with the token from setupToken")
    return data
