from conftest import run_inline
from app.verification.bank import AuthorityBank
from app.verification.models import Authority, Claim, SupportVerdict, ClaimResult
from app.verification.verifier import verify_claim, verify_memo, publishable


def make_bank(text="The statute provides an action for damages.", status="resolved"):
    return AuthorityBank([Authority(id="A1", key="42 U.S.C. § 1983", kind="usc", title="Civil action", source="official", url="https://example.test/1983", text=text if status == "resolved" else None, retrieved_at="2026-01-01T00:00:00Z" if status == "resolved" else None, status=status)])


def claim(**overrides):
    values = {"claim_id":"C1","text":"42 U.S.C. § 1983 provides a civil action.","authority_ids":["A1"],"clause_quote":"Provider shall protect all customer data."}
    values.update(overrides)
    return Claim(**values)


def test_rejects_authority_id_outside_closed_bank():
    result = run_inline(verify_claim(claim(authority_ids=["A9"]), make_bank(), "Provider shall protect all customer data.", lambda *_: {}))
    assert result.status == "rejected"


def test_rejects_fabricated_raw_citation():
    result = run_inline(verify_claim(claim(text="42 U.S.C. § 1983 and 410 U.S. 113 support this."), make_bank(), "Provider shall protect all customer data.", lambda *_: {}))
    assert result.status == "rejected"


def test_rejects_clause_quote_mismatch():
    result = run_inline(verify_claim(claim(clause_quote="Provider protects customer data."), make_bank(), "Provider shall protect all customer data.", lambda *_: {}))
    assert result.status == "rejected"


def test_checker_quote_not_in_authority_is_discarded():
    result = run_inline(verify_claim(claim(), make_bank(), "Provider shall protect all customer data.", lambda *_: SupportVerdict(label="supports", authority_quote="fabricated passage", rationale="supports")))
    assert result.status == "unverified"
    assert result.authority_quotes == []


def test_verified_existence_only_and_unverified_paths():
    good = run_inline(verify_claim(claim(), make_bank(), "Provider shall protect all customer data.", lambda *_: SupportVerdict(label="supports", authority_quote="The statute provides an action for damages.", rationale="The source states this rule.")))
    existence = run_inline(verify_claim(claim(), make_bank(status="existence-only"), "Provider shall protect all customer data.", lambda *_: None))
    unsupported = run_inline(verify_claim(claim(), make_bank(), "Provider shall protect all customer data.", lambda *_: SupportVerdict(label="not_supported", authority_quote="", rationale="No support.")))
    assert [good.status, existence.status, unsupported.status] == ["verified", "existence_only", "unverified"]


def test_verify_memo_and_publishability():
    results = run_inline(verify_memo([claim()], make_bank(status="existence-only"), "Provider shall protect all customer data.", lambda *_: None))
    assert publishable(results)
    assert not publishable([ClaimResult(claim_id="C2", status="rejected")])
