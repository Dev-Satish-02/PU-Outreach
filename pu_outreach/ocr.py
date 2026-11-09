"""Screenshot -> contact fields, using the Tesseract command-line tool.

Verified on one real screenshot (dark LinkedIn theme, 1920x1080, ContactOut open):
whole-page OCR misses the ContactOut panel, but cropping it first reads email and
phone exactly. So we OCR crops, twice, and require the two reads to agree.
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

from PIL import Image, ImageOps

from . import extract as X


@dataclass
class Capture:
    is_profile: bool = False
    name: str | None = None
    company_full: str | None = None
    company_short: str | None = None
    email: str | None = None
    other_emails: list[str] = field(default_factory=list)
    phone: str | None = None
    linkedin: str | None = None
    flags: list[str] = field(default_factory=list)       # go into Remarks
    blocking: str | None = None                           # reason NOT to draft
    debug: dict = field(default_factory=dict)


class OCR:
    def __init__(self, cmd: str = "tesseract"):
        self.cmd = cmd

    def _run(self, img: Image.Image, psm: int, tsv: bool = False) -> str:
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            img.save(path)
            args = [self.cmd, path, "stdout", "--psm", str(psm)]
            if tsv:
                args.append("tsv")
            r = subprocess.run(args, capture_output=True, timeout=60)
            return r.stdout.decode("utf-8", "replace")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def text(self, img: Image.Image, psm: int = 6) -> str:
        return self._run(img, psm)

    def words(self, img: Image.Image, psm: int = 3) -> list[dict]:
        raw = self._run(img, psm, tsv=True)
        out = []
        for row in csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
            t = (row.get("text") or "").strip()
            if not t or row.get("level") != "5":
                continue
            try:
                conf = float(row.get("conf") or -1)
            except ValueError:
                conf = -1
            out.append({
                "text": t, "conf": conf,
                "left": int(row["left"]), "top": int(row["top"]),
                "width": int(row["width"]), "height": int(row["height"]),
                "line": (row["block_num"], row["par_num"], row["line_num"]),
            })
        return out


# ------------------------------------------------------------------ image regions

def _upscale_gray(img: Image.Image, k: int = 2) -> Image.Image:
    return ImageOps.grayscale(img.resize((img.width * k, img.height * k), Image.LANCZOS))


def find_bright_panel(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Largest bright rectangle in the right half (ContactOut's white panel on a dark page)."""
    W, H = img.size
    g = ImageOps.grayscale(img)
    x0 = W // 2
    region = g.crop((x0, 0, W, H))
    px = region.load()
    w, h = region.size
    step = 2
    col_frac = []
    for x in range(0, w, step):
        bright = sum(1 for y in range(0, h, step) if px[x, y] > 235)
        col_frac.append(bright / (h / step))
    cols = [i * step for i, f in enumerate(col_frac) if f > 0.35]
    if not cols:
        return None
    # longest contiguous run of bright columns
    runs, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > step * 2:
            runs.append((start, prev)); start = c
        prev = c
    runs.append((start, prev))
    cx0, cx1 = max(runs, key=lambda r: r[1] - r[0])
    if cx1 - cx0 < w * 0.15:
        return None
    rows = [y for y in range(0, h, step)
            if sum(1 for x in range(cx0, cx1, step) if px[x, y] > 235) / max(1, (cx1 - cx0) / step) > 0.6]
    if not rows:
        return None
    return (x0 + cx0, rows[0], x0 + cx1, rows[-1])


# ------------------------------------------------------------------ main entry

def read_screenshot(path: str, ocr: OCR | None = None) -> Capture:
    ocr = ocr or OCR()
    img = Image.open(path).convert("RGB")
    W, H = img.size
    cap = Capture()

    # 1. Address bar (top strip)
    # Several reads, majority vote: URL endings like "4b2a1c" are easy to misread (1 vs l).
    strip = img.crop((0, 0, W, max(60, int(H * 0.12))))
    band = _address_band(strip, ocr)
    if band is not None:
        up = _upscale_gray(band)
        reads = [ocr.text(band, psm=7), ocr.text(up, psm=7), ocr.text(ImageOps.invert(up), psm=7)]
    else:
        reads = [ocr.text(strip, psm=11)]
    cap.debug["bar"] = " || ".join(r.strip() for r in reads)
    if any(X.is_non_profile_page(r) for r in reads):
        return cap                                         # company/school page: ignore
    urls = [u for u in (X.find_profile_url(r) for r in reads) if u]
    url_unsure = False
    if urls:
        best = max(set(urls), key=urls.count)
        cap.linkedin = best
        url_unsure = urls.count(best) < 2

    # 2. ContactOut panel, read two different ways
    right = img.crop((int(W * 0.75), 0, W, H))
    read_a = ocr.text(right, psm=11)
    box = find_bright_panel(img)
    if box:
        read_b = ocr.text(img.crop(box), psm=6)
    else:
        read_b = ocr.text(_upscale_gray(right), psm=11)
    cap.debug.update(panel_a=read_a, panel_b=read_b, panel_box=box)

    emails_a, emails_b = X.find_emails(read_a), X.find_emails(read_b)
    agreed = [e for e in emails_a if e in emails_b]
    cap.is_profile = bool(cap.linkedin or "contactout" in (read_a + read_b).lower().replace(" ", ""))
    if not cap.is_profile:
        return cap

    if agreed:
        cap.email, cap.other_emails = X.pick_email(agreed)
    elif emails_a or emails_b:
        cap.blocking = "email unclear (two reads disagree: %s / %s)" % (
            ", ".join(emails_a) or "-", ", ".join(emails_b) or "-")
    else:
        cap.blocking = "no email found — is the ContactOut panel open and showing the email?"

    phones_a, phones_b = X.find_phones(read_a), X.find_phones(read_b)
    phones = [p for p in phones_a if p in phones_b]
    if phones:
        cap.phone = phones[0]
    elif phones_a or phones_b:
        cap.flags.append("phone unclear — left blank")

    # 3. Name: ContactOut panel first, profile header as fallback/cross-check
    page_words = ocr.words(img, psm=3)
    page_text = _lines_text(page_words)
    cap.name = X.name_from_panel(read_b) or X.name_from_panel(read_a) or X.name_from_page(page_text)
    if not cap.name:
        cap.flags.append("needs POC name")

    # 4. Company: right-hand column of the profile card, re-read tightly without the logo
    comp = _company_from_card(img, page_words, cap.name, ocr)
    if comp:
        cap.company_full = comp
        if X.looks_like_school(comp):
            cap.flags.append("company may be a school/university — check")
    elif cap.email and X.company_from_domain(cap.email):
        cap.company_full = X.company_from_domain(cap.email)
        cap.flags.append("company taken from email domain — check")
    else:
        cap.flags.append("needs company")
    cap.company_short = X.short_company(cap.company_full) if cap.company_full else None

    # 5. Cross-checks → Remarks
    if cap.email and cap.company_full:
        dm = X.domain_matches_company(cap.email, cap.company_full)
        if dm == "personal":
            cap.flags.append("personal email")
        elif dm in ("partial", "none"):
            cap.flags.append("email domain differs from company — check")
    if cap.other_emails:
        cap.flags.append("other email(s): " + ", ".join(cap.other_emails))
    if cap.linkedin and (url_unsure or (cap.name and not X.slug_matches_name(cap.linkedin, cap.name))):
        cap.flags.append("check LinkedIn URL")
    if not cap.linkedin:
        cap.flags.append("LinkedIn URL not visible")
    return cap


def _address_band(strip: Image.Image, ocr: OCR) -> Image.Image | None:
    """The single text row of the top strip that holds 'linkedin.com/...' (the address bar)."""
    W, h = strip.size
    for w in ocr.words(strip, psm=11):
        if "linkedin" in w["text"].lower():
            return strip.crop((0, max(0, w["top"] - 8), W, min(h, w["top"] + w["height"] + 8)))
    for y in range(0, max(1, h - 30), 20):                 # slow path: scan rows
        band = strip.crop((0, y, W, min(h, y + 44)))
        if "linkedin" in ocr.text(_upscale_gray(band), psm=7).lower():
            return band
    return None


def _group_lines(words: list[dict]) -> list[dict]:
    lines: dict = {}
    for w in words:
        lines.setdefault(w["line"], []).append(w)
    out = []
    for ws in lines.values():
        ws.sort(key=lambda w: w["left"])
        out.append({
            "words": ws,
            "text": " ".join(w["text"] for w in ws),
            "left": min(w["left"] for w in ws),
            "right": max(w["left"] + w["width"] for w in ws),
            "top": min(w["top"] for w in ws),
            "bottom": max(w["top"] + w["height"] for w in ws),
        })
    out.sort(key=lambda l: (l["top"], l["left"]))
    return out


def _lines_text(words: list[dict]) -> str:
    return "\n".join(l["text"] for l in _group_lines(words))


def _company_from_card(img: Image.Image, words: list[dict], name: str | None, ocr: OCR) -> str | None:
    if not name:
        return None
    W, H = img.size
    first = X.ascii_fold(name.split()[0]).lower()
    # Anchor on the WORD of the first name in the main column (Tesseract may merge
    # the name and the company into one "line", so lines are unreliable here).
    anchors = [w for w in words if X.ascii_fold(w["text"]).lower().strip("©@.,") == first
               and w["left"] < W * 0.5 and w["top"] < H * 0.8]
    if not anchors:
        return None
    anchor = min(anchors, key=lambda w: w["top"])
    lh = max(10, anchor["height"])
    # Company sits in the right part of the profile card (x ≈ 0.50–0.62 W on 1920 px);
    # the "More profiles for you" sidebar starts around 0.655 W and must be excluded.
    sidebar_x = W * 0.65
    sidebar_rows = {w["top"] // 4 for w in words if w["text"].lower() in {"profiles", "viewed"}}
    cands = [w for w in words
             if w["left"] > anchor["left"] + W * 0.2 and w["left"] + w["width"] < sidebar_x
             and w["top"] // 4 not in sidebar_rows
             and anchor["top"] - 3 * lh <= w["top"] <= anchor["top"] + 4 * lh
             and w["conf"] >= 40 and sum(c.isalpha() for c in w["text"]) >= 2]
    if not cands:
        return None
    # cluster words into visual rows, then take the first block of adjacent rows
    cands.sort(key=lambda w: (w["top"], w["left"]))
    raw_rows: list[list[dict]] = []
    for w in cands:
        if raw_rows and abs(w["top"] - raw_rows[-1][0]["top"]) < 0.6 * lh:
            raw_rows[-1].append(w)
        else:
            raw_rows.append([w])

    def first_segment(row: list[dict]) -> list[dict]:
        """Leftmost run of words; a big horizontal gap means another column (sidebar)."""
        row = sorted(row, key=lambda w: w["left"])
        seg = [row[0]]
        for w in row[1:]:
            if w["left"] - (seg[-1]["left"] + seg[-1]["width"]) > 2.5 * max(w["height"], seg[-1]["height"]):
                break
            seg.append(w)
        return seg

    rows = [first_segment(r) for r in raw_rows]
    col_left = min(w["left"] for w in rows[0])
    row_h = sorted(w["height"] for w in rows[0])[len(rows[0]) // 2]
    block = [rows[0]]
    for r in rows[1:]:
        prev_bottom = max(w["top"] + w["height"] for w in block[-1])
        if r[0]["top"] - prev_bottom < 0.6 * row_h and abs(min(w["left"] for w in r) - col_left) < W * 0.03:
            block.append(r)
        else:
            break
    real = [w for r in block for w in r]
    x0 = min(w["left"] for w in real) - 3
    x1 = max(w["left"] + w["width"] for w in real) + 6
    y0 = min(w["top"] for w in real) - 4
    y1 = max(w["top"] + w["height"] for w in real) + 4
    tight = ocr.text(img.crop((max(0, x0), max(0, y0), min(W, x1), min(H, y1))), psm=6)
    text = X.clean_company_line(" ".join(tight.split()))
    if sum(c.isalpha() for c in text) < 2:
        text = X.clean_company_line(" ".join(w["text"] for w in real))
    return text or None
