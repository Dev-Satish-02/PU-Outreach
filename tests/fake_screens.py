"""Generates FAKE LinkedIn-like screenshots for tests. No real person's data."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "C:/Windows/Fonts"]


def font(size: int, bold: bool = False):
    for d in FONT_DIRS:
        for name in (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]) + ["Arial.ttf", "arial.ttf"]:
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def make(path: Path, *, theme="dark", url="linkedin.com/in/riya-fakename-4b2a1c/",
         name="Riya Fakename", title="Talent Acquisition Lead",
         company=("Examplelogix (Example Logistics", "Solutions Pvt. Ltd.)"),
         school=("Fake Institute of", "Technology"),
         panel_lines=("riya.fakename@examplelogix.test", "+919876543210"),
         panel=True) -> Path:
    W, H = 1920, 1080
    dark = theme == "dark"
    bg, fg, card = ("#000000", "#e8e8e8", "#1b1f23") if dark else ("#f4f2ee", "#191919", "#ffffff")
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    # browser bar
    d.rectangle((0, 0, W, 85), fill="#202124" if dark else "#dfe1e5")
    d.text((158, 52), url, fill="#e8eaed" if dark else "#202124", font=font(15))
    # profile card
    d.rectangle((331, 170, 1203, 727), fill=card)
    d.text((359, 500), name, fill=fg, font=font(26, True))
    d.text((360, 535), title, fill=fg, font=font(17))
    d.text((360, 560), "Pune, Maharashtra, India · Contact info", fill="#999999", font=font(14))
    if company:
        for i, line in enumerate(company):
            d.text((954, 494 + i * 19), line, fill=fg, font=font(15, True))
        d.rectangle((910, 495, 945, 530), fill="#ff6600")          # fake logo
    if school:
        for i, line in enumerate(school):
            d.text((954, 548 + i * 19), line, fill=fg, font=font(15, True))
    # right sidebar
    d.rectangle((1229, 455, 1573, 1080), fill=card)
    d.text((1257, 486), "More profiles for you", fill=fg, font=font(21))
    d.text((1319, 537), "Arjun Sampleperson · 3rd", fill=fg, font=font(17))
    d.text((1319, 560), "HR Business Partner", fill=fg, font=font(13))
    # ContactOut panel (always white)
    if panel:
        d.rectangle((1552, 148, 1903, 850), fill="#ffffff", outline="#dddddd")
        d.text((1574, 166), "ContactOut", fill="#111111", font=font(18, True))
        d.text((1575, 215), name, fill="#111111", font=font(18))
        d.text((1575, 241), title, fill="#444444", font=font(13))
        for i, line in enumerate(panel_lines):
            d.text((1606, 274 + i * 35), line, fill="#111111", font=font(16))
        d.text((1613, 382), "Save to List / ATS / CRM", fill="#111111", font=font(16))
    im.save(path)
    return path
