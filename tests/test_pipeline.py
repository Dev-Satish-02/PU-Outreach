"""Pipeline against a FAKE local web app that mimics Apps Script (POST → 302 → GET JSON)."""
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pu_outreach import config, metrics, pipeline

from .fake_screens import make

pytestmark = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
STATE = {"rows": [], "last": None}


class FakeAppsScript(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["token"] == "fake-token"
        c = body["contact"]
        dup = next((i + 2 for i, r in enumerate(STATE["rows"]) if r["email"] == c["email"]), None)
        STATE["last"] = ({"ok": True, "outcome": "duplicate", "duplicate": {"row": dup, "by": "email", "status": "Drafted"}}
                         if dup else {"ok": True, "outcome": "drafted", "row": len(STATE["rows"]) + 2})
        if not dup:
            STATE["rows"].append(c)
        self.send_response(302)                      # what Apps Script really does
        self.send_header("Location", "/echo")
        self.end_headers()

    def do_GET(self):
        out = json.dumps(STATE["last"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path / "cfg")
    STATE.update(rows=[], last=None)
    srv = HTTPServer(("127.0.0.1", 0), FakeAppsScript)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/exec"
    srv.shutdown()


def test_draft_then_duplicate(server, tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(pipeline.notify, "send", lambda t, b="": notes.append((t, b)))
    cfg = {"webapp_url": server, "token": "fake-token", "tesseract_cmd": "tesseract"}
    shot = make(tmp_path / "s1.png")
    assert pipeline.process(shot, cfg) == "drafted"
    sent = STATE["rows"][0]
    assert sent["email"] == "riya.fakename@examplelogix.test"
    assert sent["company_short"] == "Examplelogix" and sent["mobile"] == "+91 98765 43210"
    assert sent["greeting"].startswith("Dear ")
    assert pipeline.process(make(tmp_path / "s2.png"), cfg) == "duplicate"
    assert "duplicate" in notes[-1][0]
    s = metrics.summary()
    assert s["drafted"] == 1 and s["duplicates_blocked"] == 1
    # the log must not contain personal data
    log = metrics.path().read_text()
    assert "riya" not in log.lower() and "9876" not in log


def test_non_profile_screenshot_is_silent(server, tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(pipeline.notify, "send", lambda t, b="": notes.append(t))
    cfg = {"webapp_url": server, "token": "fake-token"}
    assert pipeline.process(make(tmp_path / "x.png", url="docs.example.test", panel=False), cfg) == "ignored"
    assert notes == [] and STATE["rows"] == []


def test_watch_loop_picks_up_new_screenshot_only(server, tmp_path, monkeypatch):
    import time
    notes = []
    monkeypatch.setattr(pipeline.notify, "send", lambda t, b="": notes.append(t))
    folder = tmp_path / "shots"
    folder.mkdir()
    make(folder / "old.png")                                   # existed before start: ignored
    cfg = {"webapp_url": server, "token": "fake-token", "screenshot_dir": str(folder), "poll_seconds": 0.2}
    threading.Thread(target=pipeline.watch, args=(cfg,), daemon=True).start()
    time.sleep(0.5)
    make(folder / "new.png")
    for _ in range(100):
        if STATE["rows"]:
            break
        time.sleep(0.2)
    assert len(STATE["rows"]) == 1
    assert any("draft ready" in n for n in notes)
