"""Greeting from first name, using aggregate electoral-roll name composition (naampy, CC0 source).

Rule (set by the user): "Dear <First> ma'am," / "Dear <First> sir," only when the name is
clearly one way; otherwise "Dear Team,". Never a bare first name.
"""
from __future__ import annotations

import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import config
from .extract import display_first_name, prefix_honorific

THRESHOLD = 0.95          # share needed to choose ma'am / sir
MIN_RECORDS = 1000        # naampy lookup already only publishes names with >= 1000 records
PACKAGED = Path(__file__).parent / "data" / "names.json.gz"


def normalise(name: str) -> str | None:
    """naampy normalisation: NFC, strip, casefold, ASCII a-z only."""
    s = unicodedata.normalize("NFC", name or "").strip().casefold()
    return s if s and re.fullmatch(r"[a-z]+", s) else None


@lru_cache(maxsize=1)
def table() -> dict[str, list[int]]:
    for p in (config.data_dir() / "names.json.gz", PACKAGED):
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
    return {}


def overrides() -> dict[str, str]:
    p = config.config_dir() / "names_override.json"
    if p.exists():
        try:
            return {normalise(k) or k: v for k, v in json.loads(p.read_text("utf-8")).items()}
        except Exception:
            return {}
    return {}


def honorific_for(first: str, tbl: dict | None = None, ovr: dict | None = None) -> tuple[str | None, str]:
    """Returns ('maam'|'sir'|None, reason)."""
    key = normalise(first)
    if not key:
        return None, "name not in a-z (non-English characters?)"
    ovr = overrides() if ovr is None else ovr
    if key in ovr and ovr[key] in {"maam", "sir", "team"}:
        v = ovr[key]
        return (None if v == "team" else v), "your override"
    tbl = table() if tbl is None else tbl
    if not tbl:
        return None, "names data not installed (run `pu-outreach build-names`)"
    rec = tbl.get(key)
    if not rec:
        return None, "name not in data"
    f, m = rec
    total = f + m
    if total < MIN_RECORDS:
        return None, "too few records"
    share = f / total
    if share >= THRESHOLD:
        return "maam", f"{share:.0%} female in data"
    if share <= 1 - THRESHOLD:
        return "sir", f"{1 - share:.0%} male in data"
    return None, f"ambiguous ({share:.0%} female)"


def greeting(full_name: str | None, tbl: dict | None = None, ovr: dict | None = None) -> tuple[str, str]:
    """Returns (greeting line, remark)."""
    if not full_name:
        return "Dear Team,", "greeting: no name found → Team"
    first = display_first_name(full_name)
    if not first:
        return "Dear Team,", "greeting: no usable first name → Team"
    pre = prefix_honorific(full_name)
    if pre:
        h, why = pre, "title in name"
    else:
        h, why = honorific_for(first, tbl, ovr)
    if h == "maam":
        return f"Dear {first} ma'am,", f"greeting: ma'am ({why}) — check"
    if h == "sir":
        return f"Dear {first} sir,", f"greeting: sir ({why}) — check"
    return "Dear Team,", f"greeting: Team ({why})"
