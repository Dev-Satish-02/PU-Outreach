"""End-to-end OCR on generated FAKE screenshots. Skipped if Tesseract isn't installed."""
import shutil

import pytest

from pu_outreach.ocr import read_screenshot

from .fake_screens import make

pytestmark = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")


def test_dark_theme_full_capture(tmp_path):
    c = read_screenshot(str(make(tmp_path / "a.png")))
    assert c.is_profile and c.blocking is None
    assert c.email == "riya.fakename@examplelogix.test"
    assert c.phone == "+91 98765 43210"
    assert c.name == "Riya Fakename"
    assert c.linkedin == "https://www.linkedin.com/in/riya-fakename-4b2a1c/"
    assert c.company_short == "Examplelogix"
    assert "Solutions" in c.company_full and "Institute" not in c.company_full


def test_light_theme(tmp_path):
    c = read_screenshot(str(make(tmp_path / "b.png", theme="light")))
    assert c.email == "riya.fakename@examplelogix.test"
    assert c.phone == "+91 98765 43210"


def test_company_page_is_ignored(tmp_path):
    c = read_screenshot(str(make(tmp_path / "c.png", url="linkedin.com/company/examplelogix/", panel=False)))
    assert not c.is_profile


def test_non_linkedin_screenshot_is_ignored(tmp_path):
    c = read_screenshot(str(make(tmp_path / "d.png", url="docs.example.test/notes", panel=False)))
    assert not c.is_profile


def test_panel_without_email_blocks_draft(tmp_path):
    c = read_screenshot(str(make(tmp_path / "e.png", panel_lines=("Find work email",))))
    assert c.is_profile and c.email is None and c.blocking


def test_missing_company_uses_domain_and_flags(tmp_path):
    c = read_screenshot(str(make(tmp_path / "f.png", company=None, school=None)))
    assert c.company_short == "Examplelogix"
    assert any("email domain" in f for f in c.flags)


def test_missing_company_personal_email_needs_company(tmp_path):
    c = read_screenshot(str(make(tmp_path / "g.png", company=None, school=None,
                                 panel_lines=("riya.fakename@gmail.com", "+919876543210"))))
    assert c.company_full is None and "needs company" in c.flags


def test_no_address_bar_still_works_and_flags_url(tmp_path):
    c = read_screenshot(str(make(tmp_path / "h.png", url="")))
    assert c.is_profile and c.email and c.linkedin is None
    assert "LinkedIn URL not visible" in c.flags
