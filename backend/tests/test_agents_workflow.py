from app.agents.risk_models import DraftMemo, RiskFinding, RiskScan
from app.agents.workflow import LegalWorkflow
from app.ingestion.models import ParsedDocument
from app.verification.models import Authority, SupportVerdict
from conftest import run_inline


CONTRACT = """1. LIABILITY CAP
Each party's aggregate liability is capped at fees paid in the prior twelve months.

2. INDEMNITY
Supplier's indemnity obligations are unlimited and not subject to the cap in Section 1.

3. RENEWAL
This Agreement renews automatically for successive one-year terms unless Customer gives 90 days notice.

4. TERMINATION
Supplier may terminate immediately for any breach, whether material or not.
"""


class FakeResolver:
    async def resolve(self, citation):
        return Authority(id="A1", key=citation.normalized_key, kind=citation.kind, title="Resolved authority", source="test", url="https://example.test/authority", text="The source contains an exact support passage.", retrieved_at="2026-01-01T00:00:00Z", status="resolved")
    async def search_query(self, query):
        return []


async def fake_model(prompt, schema, model):
    if schema is RiskScan:
        if "cross-clause interactions only" in prompt:
            return RiskScan(risks=[RiskFinding(risk_id="cap-indemnity", title="Cap defeated by carve-out", severity="high", clause_ids=["C1", "C2"], exact_quotes=["Each party's aggregate liability is capped at fees paid in the prior twelve months.", "Supplier's indemnity obligations are unlimited and not subject to the cap in Section 1."], why_non_obvious="The two sections appear separate but the carve-out swallows the negotiated cap.", jurisdiction_assumption="Contract language only; governing law unclear.", suggested_mitigation_clause="Indemnity obligations count toward the aggregate cap except for fraud.", search_queries=["42 U.S.C. § 1983"])])
        return RiskScan(risks=[
            RiskFinding(risk_id="renewal", title="Long renewal notice window", severity="medium", clause_ids=["C3"], exact_quotes=["This Agreement renews automatically for successive one-year terms unless Customer gives 90 days notice."], why_non_obvious="Notice is due well before the term ends.", jurisdiction_assumption="Contract language only.", suggested_mitigation_clause="Renew only by mutual written agreement.", search_queries=["42 U.S.C. § 1983"]),
            RiskFinding(risk_id="termination", title="Asymmetric termination trigger", severity="high", clause_ids=["C4"], exact_quotes=["Supplier may terminate immediately for any breach, whether material or not."], why_non_obvious="A minor breach can trigger immediate termination.", jurisdiction_assumption="Contract language only.", suggested_mitigation_clause="Limit termination to uncured material breach after notice.", search_queries=["42 U.S.C. § 1983"]),
        ])
    if schema is DraftMemo:
        return DraftMemo(title="Memo", executive_summary="The agreement has uncapped indemnity and renewal risks.", claims=[{"claim_id":"M1","text":"The agreement allocates uncapped indemnity exposure [A1].","authority_ids":["A1"],"clause_quote":"Supplier's indemnity obligations are unlimited and not subject to the cap in Section 1."}])
    if schema is SupportVerdict:
        return SupportVerdict(label="supports", authority_quote="The source contains an exact support passage.", rationale="The quoted passage supports the limited claim.")
    raise AssertionError(f"Unexpected schema {schema} using model {model}")


def test_fake_model_and_resolver_produce_quote_grounded_cross_clause_memo():
    workflow = LegalWorkflow(model_call=fake_model, resolver=FakeResolver())
    parsed = ParsedDocument(filename="sample.txt", content_type="text/plain", text=CONTRACT, page_texts=[CONTRACT])
    state = {"session_id":"s1", "filename":"sample.txt", "mime_type":"text/plain", "parsed_document":parsed.model_dump(), "document_text":CONTRACT, "warnings":[]}
    for node in (workflow.segment, workflow.detect_jurisdiction, workflow.checklist_scan, workflow.cross_clause_scan, workflow.research, workflow.build_bank, workflow.draft_memo, workflow.verify, workflow.finalize):
        state = run_inline(node(state))
    memo = state["memo"]
    assert len(memo["risks"]) >= 3
    cross = next(risk for risk in memo["risks"] if risk["risk_id"] == "cap-indemnity")
    assert len(cross["clause_ids"]) >= 2
    assert all(quote in CONTRACT for quote in cross["exact_quotes"])
    assert memo["claims"][0]["result"]["status"] == "verified"
    assert "Not legal advice" in memo["notice"]


def test_unverbatim_risk_quote_is_dropped():
    async def bad(*_):
        return RiskScan(risks=[RiskFinding(risk_id="bad", title="Invented", severity="high", clause_ids=["C2"], exact_quotes=["This clause is not in the contract."], why_non_obvious="No source.", jurisdiction_assumption="unclear", suggested_mitigation_clause="Delete it.")])
    workflow = LegalWorkflow(model_call=bad, resolver=FakeResolver())
    state = {"document_text":CONTRACT, "clauses":[{"id":"C2","text":"Actual clause."}], "jurisdiction":{}, "warnings":[]}
    result = run_inline(workflow.checklist_scan(state))
    assert result["risks"] == []


def test_cross_clause_finding_requires_two_ids():
    async def bad(*_):
        return RiskScan(risks=[RiskFinding(risk_id="bad-cross", title="Single clause", severity="high", clause_ids=["C1"], exact_quotes=["Actual clause text."], why_non_obvious="No interaction.", jurisdiction_assumption="unclear", suggested_mitigation_clause="Clarify it.")])
    workflow = LegalWorkflow(model_call=bad, resolver=FakeResolver())
    state = {"document_text":"Actual clause text.", "clauses":[{"id":"C1","text":"Actual clause text."}], "jurisdiction":{}, "definitions":{}, "warnings":[]}
    result = run_inline(workflow.cross_clause_scan(state))
    assert result["risks"] == []
