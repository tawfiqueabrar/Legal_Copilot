from app.verification.bank import AuthorityBank
from app.verification.models import Authority, Citation


def auth(key: str, title: str = "Case"):
    return Authority(id="A1", key=key, kind="us_case", title=title, source="test", url="https://example.test", text=None, status="existence-only")


def test_bank_ids_are_deterministic_for_bulk_input():
    bank = AuthorityBank([auth("B key"), auth("A key")])
    assert [(a.id, a.key) for a in bank.all()] == [("A1", "A key"), ("A2", "B key")]
    assert bank.get("A2").key == "B key"


def test_bank_deduplicates_and_resolves_normalized_citation():
    bank = AuthorityBank([auth("410 U.S. 113")])
    bank.add(auth("410 U.S. 113", "Duplicate"))
    citation = Citation(kind="us_case", raw="410 U.S. 113", normalized_key="410 U.S. 113")
    assert len(bank.all()) == 1
    assert bank.get_for_citation(citation).title == "Case"
    assert "[A1]" in bank.prompt_block()
