from app.verification.extract import extract_citations, normalize_citation, span_in_text


def test_extracts_each_requested_citation_family():
    source = "410 U.S. 113; 22 F.3d 55; 42 U.S.C. § 1983(a); 29 C.F.R. § 541.100(a)(1); Regulation (EU) 2016/679; Directive 2019/1152; Cal. Bus. & Prof. Code § 16600."
    candidates = extract_citations(source)
    assert [candidate.kind for candidate in candidates] == [
        "us_case", "us_case", "usc", "cfr", "eu_regulation", "eu_directive", "cal_code"
    ]


def test_subsections_do_not_change_statute_key():
    assert normalize_citation("42 U.S.C. § 1983(a)(1)", "usc") == "42 U.S.C. § 1983"
    assert normalize_citation("29 C.F.R. § 541.100(a)(1)", "cfr") == "29 C.F.R. § 541.100"
    assert normalize_citation("Cal. Bus. & Prof. Code § 16600.5(b)", "cal_code") == "CAL BUS. & PROF. CODE § 16600.5"


def test_random_numbers_are_not_citations():
    assert extract_citations("The internal ticket is 410 113 and the price is 1983 dollars.") == []


def test_span_matching_normalizes_case_whitespace_and_smart_quotes():
    assert span_in_text("  THE “PARTY” SHALL  PAY ", "The ‘Party’ shall\n   pay within 30 days.")
    assert not span_in_text("the party pays", "the party shall pay")
