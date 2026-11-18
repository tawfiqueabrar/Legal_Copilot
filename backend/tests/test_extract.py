from app.verification.extract import extract_citations, normalize_citation, span_in_text


def test_extracts_each_requested_citation_family():
    source = "410 U.S. 113; 22 F.3d 55; 42 U.S.C. § 1983(a); 29 C.F.R. § 541.100(a)(1); Regulation (EU) 2016/679; Directive 2019/1152; Cal. Bus. & Prof. Code § 16600.; Cal. Civ. Code § 1798.100."
    candidates = extract_citations(source)
    assert [candidate.kind for candidate in candidates] == [
        "us_case", "us_case", "usc", "cfr", "eu_regulation", "eu_directive", "cal_code", "cal_civ_code"
    ]


def test_subsections_do_not_change_statute_key():
    assert normalize_citation("42 U.S.C. § 1983(a)(1)", "usc") == "42 U.S.C. § 1983"
    assert normalize_citation("29 C.F.R. § 541.100(a)(1)", "cfr") == "29 C.F.R. § 541.100"
    assert normalize_citation("Cal. Bus. & Prof. Code § 16600.5(b)", "cal_code") == "CAL BUS. & PROF. CODE § 16600.5"
    assert normalize_citation("Cal. Civ. Code § 1798.100(a)", "cal_civ_code") == "CAL CIV. CODE § 1798.100"


def test_random_numbers_are_not_citations():
    assert extract_citations("The internal ticket is 410 113 and the price is 1983 dollars.") == []


def test_span_matching_normalizes_case_whitespace_and_smart_quotes():
    assert span_in_text("  THE “PARTY” SHALL  PAY ", "The ‘Party’ shall\n   pay within 30 days.")
    assert not span_in_text("the party pays", "the party shall pay")


def test_gdpr_article_citation_forms_normalize_to_article_keys():
    examples = [
        "GDPR Article 33",
        "GDPR Art. 33",
        "Regulation (EU) 2016/679, Article 33",
        "Article 33 GDPR",
    ]
    for source in examples:
        candidates = extract_citations(source)
        assert len(candidates) == 1
        assert candidates[0].normalized_key == "EU REGULATION 2016/679 ART. 33"


def test_articles_44_and_46_expand_to_two_citations():
    candidates = extract_citations("Articles 44 and 46")
    assert [item.normalized_key for item in candidates] == [
        "EU REGULATION 2016/679 ART. 44",
        "EU REGULATION 2016/679 ART. 46",
    ]


def test_whole_gdpr_regulation_still_uses_combined_key():
    candidates = extract_citations("Regulation (EU) 2016/679")
    assert len(candidates) == 1
    assert candidates[0].normalized_key == "EU REGULATION 2016/679"
