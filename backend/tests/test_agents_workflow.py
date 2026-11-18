from app.agents.risk_models import DraftMemo, RiskFinding, RiskScan
from app.agents.workflow import LegalWorkflow
from app.config import settings
from app.ingestion.models import ParsedDocument
from app.verification.models import Authority, SupportVerdict
from app.verification.resolvers import CompositeResolver, StaticCorpusResolver
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

SUPPORT_TEXT = (
    "The covered supplier shall protect customer data using reasonable administrative, technical, "
    "and physical safeguards, and must notify the customer promptly after confirming a material incident."
)


class FakeResolver:
    async def resolve(self, citation):
        return Authority(id="A1", key=citation.normalized_key, kind=citation.kind, title="Resolved authority", source="test", url="https://example.test/authority", text=SUPPORT_TEXT, retrieved_at="2026-01-01T00:00:00Z", status="resolved")
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
        return SupportVerdict(label="supports", authority_quote=SUPPORT_TEXT, rationale="The quoted passage supports the limited claim.")
    raise AssertionError(f"Unexpected schema {schema} using model {model}")


def test_fake_model_and_resolver_produce_quote_grounded_cross_clause_memo():
    workflow = LegalWorkflow(model_call=fake_model, resolver=FakeResolver())
    parsed = ParsedDocument(filename="sample.txt", content_type="text/plain", text=CONTRACT, page_texts=[CONTRACT])
    state = {"session_id":"s1", "filename":"sample.txt", "mime_type":"text/plain", "parsed_document":parsed.model_dump(), "document_text":CONTRACT, "warnings":[]}
    model_token = workflow._model_call_records.set([])
    try:
        for node in (workflow.segment, workflow.detect_jurisdiction, workflow.checklist_scan, workflow.cross_clause_scan, workflow.research, workflow.build_bank, workflow.draft_memo, workflow.verify, workflow.finalize):
            state = run_inline(node(state))
    finally:
        workflow._model_call_records.reset(model_token)
    memo = state["memo"]
    assert len(memo["risks"]) >= 3
    cross = next(risk for risk in memo["risks"] if risk["risk_id"] == "cap-indemnity")
    assert len(cross["clause_ids"]) >= 2
    assert all(quote in CONTRACT for quote in cross["exact_quotes"])
    assert memo["claims"][0]["result"]["status"] == "verified"
    assert "Not legal advice" in memo["notice"]
    assert memo["analysis_metadata"]["model_calls"]
    assert all(
        call["model"] == (settings.support_check_model if call["result_schema"] == "SupportVerdict" else settings.gemini_model)
        for call in memo["analysis_metadata"]["model_calls"]
    )


def test_unverbatim_risk_quote_is_dropped():
    async def bad(*_):
        return RiskScan(risks=[RiskFinding(risk_id="bad", title="Invented", severity="high", clause_ids=["C2"], exact_quotes=["This clause is not in the contract."], why_non_obvious="No source.", jurisdiction_assumption="unclear", suggested_mitigation_clause="Delete it.")])
    workflow = LegalWorkflow(model_call=bad, resolver=FakeResolver())
    state = {"document_text":CONTRACT, "clauses":[{"id":"C2","text":"Actual clause."}], "jurisdiction":{}, "warnings":[]}
    result = run_inline(workflow.checklist_scan(state))
    assert result["risks"] == []


def test_cross_clause_finding_requires_two_ids():
    prompts = []
    async def bad(*_):
        return RiskScan(risks=[RiskFinding(risk_id="bad-cross", title="Single clause", severity="high", clause_ids=["C1"], exact_quotes=["Actual clause text."], why_non_obvious="No interaction.", jurisdiction_assumption="unclear", suggested_mitigation_clause="Clarify it.")])
    async def model(prompt, schema, model_name):
        prompts.append(prompt)
        return await bad(prompt, schema, model_name)
    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver())
    state = {"document_text":"Actual clause text.", "clauses":[{"id":"C1","text":"Actual clause text."}], "jurisdiction":{}, "definitions":{}, "warnings":[]}
    result = run_inline(workflow.cross_clause_scan(state))
    assert result["risks"] == []
    assert "every materially involved clause ID" in prompts[0]
    assert "separate verbatim quote from that clause" in prompts[0]


def test_research_omits_authorities_without_source_text():
    class EmptyTextResolver:
        async def resolve(self, citation):
            return Authority(id="A1", key=citation.normalized_key, kind=citation.kind, title="Metadata only", source="test", url="https://example.test", text=None, status="existence-only")
        async def search_query(self, _query):
            return []

    workflow = LegalWorkflow(model_call=fake_model, resolver=EmptyTextResolver())
    state = {"risks": [{"risk_id": "r1", "search_queries": ["42 U.S.C. § 1983"]}]}
    result = run_inline(workflow.research(state))
    assert result["authority_candidates"] == []
    assert result["risk_authority_keys"] == {"r1": []}


def test_research_uses_generic_bm25_article_section_hits_with_text(tmp_path):
    import json

    corpus = {
        "EU REGULATION 2016/679": {"title": "Combined instrument", "url": "https://example.test/all", "text": "combined whole text", "source": "test", "kind": "eu_regulation"},
        "EU REGULATION 2016/679 ART. 28": {"title": "Processor obligations", "url": "https://example.test/a28", "text": "A processor shall protect personal data with suitable safeguards.", "source": "test", "kind": "eu_regulation", "retrieved_at": "2026-01-01T00:00:00Z"},
        "CAL CIV. CODE § 1798.100": {"title": "Business data practices", "url": "https://example.test/cal", "text": "A business shall provide information about collection and use.", "source": "test", "kind": "cal_civ_code", "retrieved_at": "2026-01-01T00:00:00Z"},
        "29 U.S.C. § 206": {"title": "Wage payment", "url": "https://example.test/wage", "text": "An employer shall pay wages for covered work.", "source": "test", "kind": "usc", "retrieved_at": "2026-01-01T00:00:00Z"},
        "15 U.S.C. § 45": {"title": "Trade practices", "url": "https://example.test/trade", "text": "Unfair practices are prohibited.", "source": "test", "kind": "usc", "retrieved_at": "2026-01-01T00:00:00Z"},
    }
    corpus_path = tmp_path / "statutes.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    workflow = LegalWorkflow(resolver=CompositeResolver([StaticCorpusResolver(corpus_path)]))
    state = {
        "risks": [{"risk_id": "r1", "title": "Data processor obligations", "why_non_obvious": "The processor may handle personal data.", "jurisdiction_assumption": "EU applicability is conditional.", "search_queries": []}],
        "jurisdiction": {"governing_law": "Unclear", "venue": "Unclear", "party_locations": ["Example jurisdiction"], "data_subject_regions": ["EU data subjects may be implicated"], "subject_hints": ["data and privacy"]},
    }

    result = run_inline(workflow.research(state))

    assert result["risk_authority_keys"]["r1"][0] == "EU REGULATION 2016/679 ART. 28"
    assert all(item["text"] for item in result["authority_candidates"])
    assert "EU REGULATION 2016/679" not in result["risk_authority_keys"]["r1"]
    selected = result["authority_candidates"][0]
    assert selected["chunk_locator"]
    assert selected["text"] in corpus["EU REGULATION 2016/679 ART. 28"]["text"]
    diagnostic = result["research_diagnostics"][0]
    assert "data and privacy" in diagnostic["query"]
    assert diagnostic["authorities"][0]["score"] > 0


def test_no_loaded_authority_is_unverified_and_says_source_not_loaded():
    prompts = []
    claim_data = {"claim_id": "M-no-source", "text": "A legal proposition may apply.", "authority_ids": [], "clause_quote": "Supplier may revise the Services."}

    async def model(prompt, schema, _model_name):
        prompts.append(prompt)
        if schema is DraftMemo:
            return DraftMemo(executive_summary="Review pending source coverage.", claims=[claim_data])
        raise AssertionError(f"Unexpected schema: {schema}")

    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver())
    state = {"filename": "fixture.txt", "document_text": "Supplier may revise the Services.", "authority_bank": [], "risks": []}
    state = run_inline(workflow.draft_memo(state))
    state = run_inline(workflow.verify(state))

    assert "Source not loaded:" in prompts[0]
    result = state["verified_results"][0]
    assert result["status"] == "unverified"
    assert result["reasons"][0].startswith("Source not loaded:")


def test_fake_model_claim_with_grounded_operative_text_verifies():
    claim_data = {
        "claim_id": "M-grounded", "text": "[A1] may require safeguards.",
        "authority_ids": ["A1"], "clause_quote": "Supplier shall protect the data.",
    }
    authority = Authority(
        id="A1", key="CAL CIV. CODE § 1798.100", kind="cal_civ_code",
        title="Synthetic resolver record", source="test", url="https://example.test/source",
        text=SUPPORT_TEXT, retrieved_at="2026-01-01T00:00:00Z", status="resolved",
    )

    async def model(prompt, schema, _model_name):
        if schema is DraftMemo:
            return DraftMemo(executive_summary="Review pending.", claims=[claim_data])
        raise AssertionError(f"Unexpected model schema: {schema}")

    workflow = LegalWorkflow(
        model_call=model,
        support_checker=lambda *_: SupportVerdict(label="supports", authority_quote=SUPPORT_TEXT, rationale="Grounded operative support."),
    )
    state = {
        "filename": "synthetic.txt", "document_text": "Supplier shall protect the data.",
        "authority_bank": [authority.model_dump()], "risks": [],
    }
    state = run_inline(workflow.draft_memo(state))
    state = run_inline(workflow.verify(state))

    assert state["verified_results"][0]["status"] == "verified"
    assert state["verified_results"][0]["authority_quotes"] == [SUPPORT_TEXT]


def test_fake_model_claim_without_loaded_authority_is_unverified():
    checker_calls = []
    claim_data = {
        "claim_id": "M-no-text", "text": "[A1] may apply.",
        "authority_ids": ["A1"], "clause_quote": "Supplier shall protect the data.",
    }
    authority = Authority(
        id="A1", key="CAL CIV. CODE § 1798.100", kind="cal_civ_code",
        title="Existence-only resolver record", source="test", url="https://example.test/source",
        text=None, retrieved_at=None, status="existence-only",
    )

    async def model(prompt, schema, _model_name):
        if schema is DraftMemo:
            return DraftMemo(executive_summary="Review pending.", claims=[claim_data])
        raise AssertionError(f"Unexpected model schema: {schema}")

    workflow = LegalWorkflow(model_call=model, support_checker=lambda *args: checker_calls.append(args))
    state = {
        "filename": "synthetic.txt", "document_text": "Supplier shall protect the data.",
        "authority_bank": [authority.model_dump()], "risks": [],
    }
    state = run_inline(workflow.draft_memo(state))
    state = run_inline(workflow.verify(state))

    result = state["verified_results"][0]
    assert result["status"] == "unverified"
    assert result["reasons"][0].startswith("Source not loaded:")
    assert checker_calls == []


def test_fake_model_claim_with_no_authority_ids_is_never_verified():
    claim_data = {
        "claim_id": "M-no-ids", "text": "A proposition may apply.",
        "authority_ids": [], "clause_quote": "Supplier shall protect the data.",
    }

    async def model(prompt, schema, _model_name):
        if schema is DraftMemo:
            return DraftMemo(executive_summary="Review pending.", claims=[claim_data])
        raise AssertionError(f"Unexpected model schema: {schema}")

    workflow = LegalWorkflow(
        model_call=model,
        support_checker=lambda *_: SupportVerdict(label="supports", authority_quote=SUPPORT_TEXT, rationale="Should not run."),
    )
    state = {
        "filename": "synthetic.txt", "document_text": "Supplier shall protect the data.",
        "authority_bank": [], "risks": [],
    }
    state = run_inline(workflow.draft_memo(state))
    state = run_inline(workflow.verify(state))

    result = state["verified_results"][0]
    assert result["status"] == "unverified"
    assert result["reasons"][0].startswith("Source not loaded:")
