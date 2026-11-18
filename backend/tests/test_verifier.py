from conftest import run_inline
from app.verification.bank import AuthorityBank
from app.verification.models import Authority, Claim, SupportVerdict, ClaimResult
from app.verification.verifier import verify_claim, verify_memo, publishable
from app.config import MIN_SUPPORT_QUOTE_CHARS


OPERATIVE_TEXT = (
    "The covered supplier shall protect customer data using reasonable administrative, technical, "
    "and physical safeguards, and must notify the customer promptly after confirming a material incident."
)


def make_bank(text=OPERATIVE_TEXT, status="resolved"):
    return AuthorityBank([Authority(id="A1", key="42 U.S.C. § 1983", kind="usc", title="Civil action", source="official", url="https://example.test/1983", text=text if status == "resolved" else None, retrieved_at="2026-01-01T00:00:00Z" if status == "resolved" else None, status=status)])


def claim(**overrides):
    values = {"claim_id":"C1","text":"[A1] supports a civil action in this context.","authority_ids":["A1"],"clause_quote":"Provider shall protect all customer data."}
    values.update(overrides)
    return Claim(**values)


def test_rejects_authority_id_outside_closed_bank():
    result = run_inline(verify_claim(claim(authority_ids=["A9"]), make_bank(), "Provider shall protect all customer data.", lambda *_: {}))
    assert result.status == "rejected"


def test_rejects_fabricated_raw_citation():
    result = run_inline(verify_claim(claim(text="42 U.S.C. § 1983 and 410 U.S. 113 support this."), make_bank(), "Provider shall protect all customer data.", lambda *_: {}))
    assert result.status == "rejected"


def test_mapped_raw_citation_is_still_rejected_in_memo_copy():
    result = run_inline(verify_claim(claim(text="42 U.S.C. § 1983 applies."), make_bank(), "Provider shall protect all customer data.", lambda *_: None))
    assert result.status == "rejected"


def test_rejects_clause_quote_mismatch():
    result = run_inline(verify_claim(claim(clause_quote="Provider protects customer data."), make_bank(), "Provider shall protect all customer data.", lambda *_: {}))
    assert result.status == "rejected"


def test_checker_quote_not_in_authority_is_discarded():
    result = run_inline(verify_claim(claim(), make_bank(), "Provider shall protect all customer data.", lambda *_: SupportVerdict(label="supports", authority_quote="fabricated passage", rationale="supports")))
    assert result.status == "unverified"
    assert result.authority_quotes == []


def test_verified_existence_only_and_unverified_paths():
    good = run_inline(verify_claim(claim(), make_bank(), "Provider shall protect all customer data.", lambda *_: SupportVerdict(label="supports", authority_quote=OPERATIVE_TEXT, rationale="The source states this rule.")))
    existence = run_inline(verify_claim(claim(), make_bank(status="existence-only"), "Provider shall protect all customer data.", lambda *_: None))
    unsupported = run_inline(verify_claim(claim(), make_bank(), "Provider shall protect all customer data.", lambda *_: SupportVerdict(label="not_supported", authority_quote="", rationale="No support.")))
    assert [good.status, existence.status, unsupported.status] == ["verified", "existence_only", "unverified"]


def test_section_number_only_quote_cannot_verify():
    result = run_inline(verify_claim(
        claim(), make_bank("Section 16600."), "Provider shall protect all customer data.",
        lambda *_: SupportVerdict(label="supports", authority_quote="Section 16600.", rationale="The heading names a section."),
    ))
    assert result.status == "unverified"
    assert result.authority_quotes == []


def test_bare_16600_heading_cannot_verify():
    result = run_inline(verify_claim(
        claim(), make_bank("16600."), "Provider shall protect all customer data.",
        lambda *_: SupportVerdict(label="supports", authority_quote="16600.", rationale="Heading only."),
    ))
    assert result.status == "unverified"
    assert result.authority_quotes == []


def test_support_checker_receives_only_the_cited_authority_chunk():
    chunk = "(b) The covered organization shall retain incident records and provide written notice within a reasonable period after discovery."
    other_chunk = "(c) The provider may transfer data subject to separate safeguards and applicable authorization requirements."
    bank = AuthorityBank([Authority(
        id="A1", key="CAL CIV. CODE § 1798.100", kind="cal_civ_code", title="Source section",
        source="test", url="https://example.test/source", text=chunk, chunk_locator="(b)",
        retrieved_at="2026-01-01T00:00:00Z", status="resolved",
    )])
    checker_texts = []

    def checker(_claim, _title, authority_text):
        checker_texts.append(authority_text)
        return SupportVerdict(label="supports", authority_quote=chunk, rationale="The cited chunk supports the claim.")

    result = run_inline(verify_claim(claim(), bank, "Provider shall protect all customer data.", checker))

    assert result.status == "verified"
    assert checker_texts == [chunk]
    assert other_chunk not in checker_texts[0]


def test_real_corpus_subsection_quotes_pass_grounding_and_quote_gate():
    import json
    import re
    from pathlib import Path
    from app.verification.verifier import _is_operative_support_quote

    corpus_path = Path(__file__).resolve().parents[1] / "data" / "statutes.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    def subsection(key, marker, next_marker):
        text = corpus[key]["text"]
        start_match = re.search(r"(?m)^[ \t]*" + re.escape(marker) + r"(?=\s|$)", text)
        assert start_match, f"Missing requested subsection marker in {key}"
        start = start_match.start()
        after = text[start_match.end():]
        end_match = re.search(r"(?m)^[ \t]*" + re.escape(next_marker) + r"(?=\s|$)", after)
        end = start_match.end() + end_match.start() if end_match else len(text)
        return text[start:end].strip()

    targets = [
        ("CAL BUS. & PROF. CODE § 16600", "(a)", "(b)"),
        ("EU REGULATION 2016/679 ART. 33", "1.", "2."),
        ("CAL CIV. CODE § 1798.100", "(d)", "(e)"),
        ("CAL CIV. CODE § 1798.100", "(e)", "(f)"),
        ("EU REGULATION 2016/679 ART. 28", "2.", "3."),
    ]
    for index, (key, marker, following) in enumerate(targets, 1):
        quote = subsection(key, marker, following)
        entry = corpus[key]
        assert quote in entry["text"]
        assert _is_operative_support_quote(quote), (key, marker, len(quote))
        authority = Authority(
            id="A1", key=key, kind=entry["kind"], title=entry["title"], source=entry["source"],
            url=entry["url"], text=entry["text"], retrieved_at=entry["retrieved_at"], status="resolved",
        )
        source_bank = AuthorityBank([authority])
        result = run_inline(verify_claim(
            claim(claim_id=f"real-{index}", text="The rule may be relevant [A1].", authority_ids=["A1"], clause_quote="Provider shall protect all customer data."),
            source_bank, "Provider shall protect all customer data.",
            lambda *_args, quote=quote: SupportVerdict(label="supports", authority_quote=quote, rationale="Test checker supports the claim."),
        ))
        assert result.status == "verified", (key, marker, result.reasons)


def test_heading_only_quote_cannot_verify_even_when_long():
    heading = "Definitions of scope, delivery, timing, approval, authorization, and supporting documentation"
    assert len(heading) >= MIN_SUPPORT_QUOTE_CHARS
    result = run_inline(verify_claim(
        claim(), make_bank(heading), "Provider shall protect all customer data.",
        lambda *_: SupportVerdict(label="supports", authority_quote=heading, rationale="The heading appears."),
    ))
    assert result.status == "unverified"
    assert result.authority_quotes == []


def test_operative_quote_below_minimum_length_cannot_verify():
    short = "The supplier shall " + ("x" * (MIN_SUPPORT_QUOTE_CHARS - len("The supplier shall ") - 1))
    assert len(short) == MIN_SUPPORT_QUOTE_CHARS - 1
    result = run_inline(verify_claim(
        claim(), make_bank(short), "Provider shall protect all customer data.",
        lambda *_: SupportVerdict(label="supports", authority_quote=short, rationale="The text is short."),
    ))
    assert result.status == "unverified"


def test_verify_memo_and_publishability():
    results = run_inline(verify_memo([claim()], make_bank(status="existence-only"), "Provider shall protect all customer data.", lambda *_: None))
    assert publishable(results)
    assert not publishable([ClaimResult(claim_id="C2", status="rejected")])
