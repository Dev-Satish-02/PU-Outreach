"""Unit tests on FAKE strings: parsing, greeting, company handling. No OCR needed."""
from pu_outreach import extract as X
from pu_outreach import names

TABLE = {"riya": [99000, 500], "arjun": [300, 98000], "kiran": [50000, 48000]}


def g(name):
    return names.greeting(name, tbl=TABLE, ovr={})[0]


# --- greeting ----------------------------------------------------------------
def test_greeting_female_male():
    assert g("Riya Fakename") == "Dear Riya ma'am,"
    assert g("ARJUN SAMPLEPERSON") == "Dear Arjun sir,"


def test_greeting_ambiguous_and_unknown_fall_back_to_team():
    assert g("Kiran Testname") == "Dear Team,"           # unisex
    assert g("Zxqv Unknownname") == "Dear Team,"         # not in data
    assert g(None) == "Dear Team,"


def test_greeting_non_english_characters():
    assert g("प्रिया शर्मा") == "Dear Team,"
    assert g("Zoë Müller") == "Dear Team,"


def test_greeting_titles_and_overrides():
    assert g("Ms. Kiran Testname") == "Dear Kiran ma'am,"
    assert g("Dr. Riya Fakename") == "Dear Riya ma'am,"   # Dr. skipped, name decides
    assert names.greeting("Kiran X", tbl=TABLE, ovr={"kiran": "sir"})[0] == "Dear Kiran sir,"


def test_greeting_never_bare_name():
    for n in ["Riya", "Kiran", "Q", "Arjun Sampleperson", "", "प्रिया"]:
        out = g(n)
        assert out == "Dear Team," or out.endswith(("ma'am,", "sir,"))


# --- names from OCR text ------------------------------------------------------
def test_clean_name_strips_badges_degree_and_counts():
    assert X.clean_name("Riya Fakename © -2nd") == "Riya Fakename"
    assert X.clean_name("(3) Riya Fakename") == "Riya Fakename"
    assert X.name_from_page("junk\n(3) Messaging\nRiya Fakename @ · 3rd\n") == "Riya Fakename"


def test_name_from_panel():
    panel = "P\nContactOut @P O=-\nRiya Fakename\nTalent Lead\n© riya@x.test e"
    assert X.name_from_panel(panel) == "Riya Fakename"
    assert X.name_from_panel("no header here\nRiya Fakename") is None


# --- email --------------------------------------------------------------------
def test_pick_work_email_over_personal():
    chosen, others = X.pick_email(["riya.f@gmail.com", "riya@examplelogix.test"])
    assert chosen == "riya@examplelogix.test" and others == ["riya.f@gmail.com"]


def test_domain_match_levels():
    assert X.domain_matches_company("a@examplelogix.com", "Examplelogix (Example Logistics Pvt. Ltd.)") == "match"
    assert X.domain_matches_company("riya@examplel.in", "Examplelogix") == "partial"
    assert X.domain_matches_company("a@gmail.com", "Examplelogix") == "personal"
    assert X.domain_matches_company("a@totallyother.com", "Examplelogix") == "none"


def test_email_regex_ignores_badges():
    assert X.find_emails("Omprakash Sutar @ - 3rd\ng@\n© riya.f@examplelogix.test @") == ["riya.f@examplelogix.test"]


# --- phone --------------------------------------------------------------------
def test_phone_formats():
    for s in ["+919876543210", "+91 98765 43210", "+91-98765-43210", "09876543210", "9876543210"]:
        assert X.find_phones(s) == ["+91 98765 43210"], s
    assert X.find_phones("CTC 12 LPA, 2026-27, 500+ connections, 1234567890") == []


# --- URL ----------------------------------------------------------------------
def test_profile_url_from_ocr_junk():
    assert X.find_profile_url("€ > © &% linkedin.com/in/riya-fakename-4b2a1c/") == \
        "https://www.linkedin.com/in/riya-fakename-4b2a1c/"
    assert X.find_profile_url("linkedin.com/in/riya-fakename-4b2alc/").endswith("-4b2a1c/")   # l→1 in hex id
    assert X.find_profile_url("linkedin.com/in/riya-fakename/").endswith("/riya-fakename/")   # names untouched
    assert X.find_profile_url("linkedin.com/in/neil-shah-lolo/").endswith("/neil-shah-lolo/")  # no digit: untouched
    assert X.is_non_profile_page("linkedin.com/company/examplelogix/")
    assert X.slug_matches_name("https://www.linkedin.com/in/riya-fakename/", "Riya Fakename")
    assert not X.slug_matches_name("https://www.linkedin.com/in/rlya-faknme/", "Riya Fakename")


# --- company ------------------------------------------------------------------
def test_short_company():
    assert X.short_company("Examplelogix (Example Logistics Solutions Pvt. Ltd.)") == "Examplelogix"
    assert X.short_company("Examplesoft Private Limited") == "Examplesoft"
    assert X.short_company("Acme Inc.") == "Acme"
    assert X.short_company("Fake Analytics LLP") == "Fake Analytics"


def test_same_company_different_spelling_normalises_equal():
    a = X.normalise_company("ExampleLogix Pvt. Ltd.")
    assert a == X.normalise_company("Examplelogix (Example Logistics Solutions Pvt. Ltd.)") == X.normalise_company("examplelogix")


def test_clean_company_line_drops_logo_junk():
    assert X.clean_company_line("x ExampleLogix (Example") == "ExampleLogix (Example"
    assert X.clean_company_line("* | Examplelogix") == "Examplelogix"


def test_school_detection_and_domain_fallback():
    assert X.looks_like_school("Fake Institute of Technology")
    assert X.company_from_domain("a@examplelogix.co.in") == "Examplelogix"
    assert X.company_from_domain("a@gmail.com") is None
