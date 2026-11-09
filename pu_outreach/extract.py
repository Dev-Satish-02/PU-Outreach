"""Pure text parsing: emails, phones, LinkedIn URLs, names, company names.

No OCR here, so everything is unit-testable with fake strings.
Rule everywhere: if uncertain, return None / add a flag. Never guess.
"""
from __future__ import annotations

import re
import unicodedata

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
# +91 98765 43210 / +91-9876543210 / +919876543210 / 098765 43210 / 9876543210
PHONE_RE = re.compile(r"(?<![\d])(?:\+?91[\s\-]?|0)?([6-9]\d{4})[\s\-]?(\d{5})(?![\d])")
PROFILE_URL_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", re.I)
COMPANY_URL_RE = re.compile(r"linkedin\.com/(company|school|showcase)/", re.I)

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "outlook.com",
    "hotmail.com", "live.com", "icloud.com", "me.com", "rediffmail.com", "protonmail.com",
    "proton.me", "aol.com", "zoho.com", "zohomail.in", "msn.com", "ymail.com",
}

LEGAL_SUFFIX_RE = re.compile(
    r"\b(private\s+limited|pvt\.?\s*ltd\.?|pvt\.?|ltd\.?|limited|inc\.?|incorporated|llp|llc|"
    r"corp\.?|corporation|co\.)(?=\s|$|,)",
    re.I,
)
SCHOOL_WORDS = re.compile(r"\b(university|institute|college|school|iit|nit|iim|vidyapeeth|academy)\b", re.I)
HONORIFIC_PREFIX = {"mr": "sir", "mr.": "sir", "shri": "sir", "ms": "maam", "ms.": "maam",
                    "mrs": "maam", "mrs.": "maam", "smt": "maam", "smt.": "maam",
                    "dr": None, "dr.": None, "prof": None, "prof.": None, "er": None, "er.": None,
                    "ca": None}


# ------------------------------------------------------------------ email

def find_emails(text: str) -> list[str]:
    seen: list[str] = []
    for m in EMAIL_RE.finditer(text or ""):
        e = m.group(0).strip(".").lower()
        if e not in seen:
            seen.append(e)
    return seen


def is_free_mail(email: str) -> bool:
    return email.split("@")[-1].lower() in FREE_MAIL


def pick_email(candidates: list[str]) -> tuple[str | None, list[str]]:
    """Prefer a work address; returns (chosen, others)."""
    if not candidates:
        return None, []
    work = [e for e in candidates if not is_free_mail(e)]
    chosen = work[0] if work else candidates[0]
    return chosen, [e for e in candidates if e != chosen]


def domain_label(email: str) -> str:
    """'riya@examplelogix.com' -> 'examplelogix'; 'a@mail.tcs.co.in' -> 'tcs'."""
    host = email.split("@")[-1].lower()
    parts = [p for p in host.split(".") if p]
    # drop public suffix-ish tails
    while len(parts) > 1 and parts[-1] in {"com", "in", "co", "org", "net", "io", "ai", "tech", "biz", "info", "us", "uk", "edu", "ac", "gov", "app", "dev", "test"}:
        parts.pop()
    return parts[-1] if parts else host


def domain_matches_company(email: str, company: str) -> str:
    """Returns 'match', 'partial', 'personal' or 'none'."""
    if is_free_mail(email):
        return "personal"
    label = re.sub(r"[^a-z0-9]", "", domain_label(email))
    comp = normalise_company(company)
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in short_company(company).split()]
    words = [w for w in words if w]
    if not label or not comp:
        return "none"
    if label == comp or comp in label or (comp.startswith(label) and len(label) >= 0.8 * len(comp)):
        return "match"
    if label in comp and len(label) >= 3:
        return "partial"
    if words and (words[0].startswith(label) or label.startswith(words[0])) and len(label) >= 3:
        return "partial"
    initials = "".join(w[0] for w in words) if len(words) > 1 else ""
    if initials and label == initials:
        return "partial"
    return "none"


# ------------------------------------------------------------------ phone

def find_phones(text: str) -> list[str]:
    out: list[str] = []
    for m in PHONE_RE.finditer(text or ""):
        p = f"+91 {m.group(1)} {m.group(2)}"
        if p not in out:
            out.append(p)
    return out


# ------------------------------------------------------------------ LinkedIn URL

def find_profile_url(text: str) -> str | None:
    m = PROFILE_URL_RE.search(text or "")
    if not m:
        return None
    slug = m.group(1).strip("-_")
    if not slug:
        return None
    return f"https://www.linkedin.com/in/{fix_id_suffix(slug)}/"


def fix_id_suffix(slug: str) -> str:
    """LinkedIn's auto-generated URL endings are hex ('-4b2a1c'). OCR reads 1 as l and 0 as o
    there, so repair those characters ONLY in a final hex-looking part that contains a digit."""
    head, sep, tail = slug.rpartition("-")
    if not sep or not 5 <= len(tail) <= 12:
        return slug
    fixed = tail.translate(str.maketrans({"l": "1", "I": "1", "i": "1", "o": "0", "O": "0"}))
    if re.fullmatch(r"[0-9a-f]+", fixed) and any(c.isdigit() for c in tail) and fixed != tail:
        return f"{head}-{fixed}"
    return slug


def is_non_profile_page(text: str) -> bool:
    return bool(COMPANY_URL_RE.search(text or ""))


def slug_matches_name(url: str | None, name: str | None) -> bool:
    if not url or not name:
        return False
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    tokens = [ascii_fold(t).lower() for t in name.split() if len(t) > 1]
    tokens = [t for t in tokens if t and t.rstrip(".") not in HONORIFIC_PREFIX]
    return any(t in slug for t in tokens)


# ------------------------------------------------------------------ names

NAME_TOKEN = re.compile(r"^[^\W\d_][^\W\d_'’.\-]*(?:['’.\-][^\W\d_]+)*\.?$", re.UNICODE)


def looks_like_name(line: str) -> bool:
    words = clean_name(line).split()
    if not 1 <= len(words) <= 5:
        return False
    if any(ch.isdigit() for ch in line) or "@" in line or "|" in line:
        return False
    return all(NAME_TOKEN.match(w) for w in words)


def clean_name(line: str) -> str:
    """Strip OCR junk like '©', '· 2nd', verified badges, '(3)'."""
    s = line or ""
    s = re.sub(r"^\(\d+\)\s*", "", s)                                  # "(3) Name"
    s = re.sub(r"[\s©®@°•·:\-–—]*\b(1st|2nd|3rd|3rd\+)\b.*$", "", s)   # "Name © · 2nd"
    s = re.sub(r"[©®@°•·|\[\]{}<>]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -–—.,:;")
    return s


def name_from_panel(panel_text: str) -> str | None:
    """Line after the 'ContactOut' header that looks like a person's name."""
    lines = [l.strip() for l in (panel_text or "").splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if "contactout" in l.lower().replace(" ", ""):
            for cand in lines[i + 1:i + 4]:
                if looks_like_name(cand):
                    return clean_name(cand)
            break
    return None


def name_from_page(page_text: str) -> str | None:
    """Profile header line like 'Riya Fakename © -2nd'."""
    for l in (page_text or "").splitlines():
        if re.search(r"\b(1st|2nd|3rd)\b", l):
            n = clean_name(l)
            if looks_like_name(n) and len(n.split()) >= 2:
                return n
    return None


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def display_first_name(name: str) -> str | None:
    words = [w for w in name.split() if w.lower().rstrip(".") not in {k.rstrip(".") for k in HONORIFIC_PREFIX}]
    if not words:
        return None
    first = words[0].strip(".")
    if len(first) < 2:
        return None
    return first[:1].upper() + first[1:].lower() if first.isupper() or first.islower() else first


def prefix_honorific(name: str) -> str | None:
    """'Ms. Riya Sen' -> 'maam'; 'Dr. ...' -> None (unknown)."""
    w = (name.split() or [""])[0].lower()
    return HONORIFIC_PREFIX.get(w) if w in HONORIFIC_PREFIX else None


# ------------------------------------------------------------------ company

def short_company(name: str) -> str:
    s = re.sub(r"\([^)]*\)?", " ", name or "")
    s = LEGAL_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,.-–—")


def normalise_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", short_company(name).lower())


def clean_company_line(text: str) -> str:
    s = re.sub(r"\s+", " ", text or "").strip()
    # drop leading OCR junk from logos: lone symbols / single letters
    toks = s.split(" ")
    while toks and (len(toks[0]) == 1 and not toks[0].isalnum() or toks[0] in {"x", "X", "|", "*", "©", "e"} or re.fullmatch(r"[\W_]+", toks[0])):
        toks.pop(0)
    return " ".join(toks).strip(" ,;:")


def looks_like_school(name: str) -> bool:
    return bool(SCHOOL_WORDS.search(name or ""))


def company_from_domain(email: str) -> str | None:
    if not email or is_free_mail(email):
        return None
    label = domain_label(email)
    return label[:1].upper() + label[1:] if label else None
