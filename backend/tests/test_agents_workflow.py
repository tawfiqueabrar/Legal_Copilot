from app.agents.risk_models import DraftMemo, RiskFinding, RiskScan, VisionExtraction
from app.agents.workflow import LegalWorkflow, _source_grounded_claims
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


def test_source_grounded_claim_uses_only_relevant_verbatim_authority_sentence():
    authority = Authority(
        id="A1", key="synthetic privacy source", kind="usc", title="Synthetic source",
        source="test", url="https://example.test/source", text=SUPPORT_TEXT,
        retrieved_at="2026-01-01T00:00:00Z", status="resolved",
    )
    from app.verification.bank import AuthorityBank
    bank = AuthorityBank([authority])
    clause_quote = "Supplier shall protect customer data."
    claims, gaps = _source_grounded_claims([{
        "risk_id":"R1", "title":"Customer data safeguards", "why_non_obvious":"Supplier safeguards may be incomplete.",
        "exact_quotes":[clause_quote], "authority_ids":["A1"], "search_queries":[],
    }], bank, clause_quote)

    assert len(claims) == 1
    assert claims[0].text.startswith("[A1] states:")
    assert SUPPORT_TEXT in claims[0].text
    assert claims[0].clause_quote == clause_quote
    assert claims[0].authority_ids == ["A1"]
    assert gaps == []


async def fake_model(prompt, schema, model):
    if schema is RiskScan:
        if "Analyze interactions across the supplied candidate clause pairs" in prompt:
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
    # Any legal statement is assembled from loaded source text and remains
    # independently verified; risk applicability is stated conditionally.
    assert memo["claims"]
    assert all(claim["result"]["status"] in {"verified", "existence_only", "unverified", "rejected"} for claim in memo["claims"])
    assert all(claim["result"]["authority_quotes"] == [SUPPORT_TEXT] for claim in memo["claims"] if claim["result"]["status"] == "verified")
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


def test_image_triage_keeps_structured_notice_parties_and_deadlines():
    async def vision_model(_prompt, schema, _model_name):
        assert schema is VisionExtraction
        return VisionExtraction(
            document_text="Court notice text extracted from the supplied image.",
            page_texts=["Court notice text extracted from the supplied image."],
            document_kind="court_notice", parties=["Party extracted from image"],
            deadlines=["Date extracted from image; confirm against original."],
        )

    workflow = LegalWorkflow(model_call=vision_model, resolver=FakeResolver())
    parsed = ParsedDocument(filename="notice.png", content_type="image/png", text="", page_texts=[])
    state = {
        "filename": "notice.png", "mime_type": "image/png", "document_bytes": b"in-memory image payload",
        "parsed_document": parsed.model_dump(), "warnings": [],
    }

    result = run_inline(workflow.ingest(state))

    assert result["vision_facts"]["document_kind"] == "court_notice"
    assert result["vision_facts"]["parties"] == ["Party extracted from image"]
    assert result["vision_facts"]["deadlines"] == ["Date extracted from image; confirm against original."]
    assert "Court notice text" in result["parsed_document"]["text"]


def test_support_checker_call_metadata_is_recorded_without_corpus_text():
    workflow = LegalWorkflow(
        model_call=fake_model, resolver=FakeResolver(),
        support_checker=lambda *_: SupportVerdict(label="supports", authority_quote=SUPPORT_TEXT, rationale="Grounded test response."),
    )
    token = workflow._support_check_records.set([])
    try:
        result = run_inline(workflow._checker("[A1] may support a narrow claim.", "Synthetic authority", SUPPORT_TEXT))
        calls = workflow._support_check_records.get()
    finally:
        workflow._support_check_records.reset(token)

    assert result.label == "supports"
    assert calls == [{
        "claim": "[A1] may support a narrow claim.", "authority_title": "Synthetic authority",
        "label": "supports", "support_quote": SUPPORT_TEXT, "quote_verbatim": True,
        "model": "injected-test-checker",
    }]


def test_cross_clause_finding_requires_two_ids():
    prompts = []
    async def bad(*_):
        return RiskScan(risks=[RiskFinding(risk_id="bad-cross", title="Single clause", severity="high", clause_ids=["C1"], exact_quotes=["Actual clause text."], why_non_obvious="No interaction.", jurisdiction_assumption="unclear", suggested_mitigation_clause="Clarify it.")])
    async def model(prompt, schema, model_name):
        prompts.append(prompt)
        return await bad(prompt, schema, model_name)
    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver())
    state = {"document_text":"Actual clause text and related language.", "clauses":[
        {"id":"C1","section":"A","text":"Actual clause text describes a recurring operational obligation."},
        {"id":"C2","section":"B","text":"Related language describes a recurring operational obligation."},
    ], "jurisdiction":{}, "definitions":{}, "warnings":[]}
    result = run_inline(workflow.cross_clause_scan(state))
    assert result["risks"] == []
    assert "every materially involved clause ID" in prompts[0]
    assert "separate verbatim quote from that clause" in prompts[0]


def test_cross_clause_candidates_rank_rare_shared_terms_without_document_specific_rules():
    from app.agents.workflow import _cross_clause_candidates

    clauses = [
        {"id":"C1","text":"The processor maintains confidential safeguards for regulated records."},
        {"id":"C2","text":"Confidential safeguards must include annual independent examinations."},
        {"id":"C3","text":"Invoices are payable within thirty days after receipt."},
    ]

    pairs = _cross_clause_candidates(clauses)

    assert pairs
    assert pairs[0] == (clauses[0], clauses[1])
    assert all(left is not clauses[2] and right is not clauses[2] for left, right in pairs)


def test_cross_clause_candidates_prioritize_general_legal_interaction_topics():
    from app.agents.workflow import _cross_clause_candidates

    clauses = [
        {"id":"C1","text":"Aggregate liability is limited to an agreed cap."},
        {"id":"C2","text":"Indemnification obligations are outside the stated cap."},
        {"id":"C3","text":"Invoices are payable after receipt."},
    ]

    pairs = _cross_clause_candidates(clauses)

    assert pairs[0] == (clauses[0], clauses[1])


def test_research_query_includes_contract_evidence_and_jurisdiction_context(monkeypatch):
    import app.services.retrieval as retrieval

    observed = {}

    class RecordingIndex:
        def __init__(self, entries):
            pass
        def search(self, query, **kwargs):
            observed["query"] = query
            observed["context"] = kwargs["context_text"]
            return []

    monkeypatch.setattr(retrieval, "BM25EntryIndex", RecordingIndex)
    workflow = LegalWorkflow(model_call=fake_model, resolver=FakeResolver())
    state = {
        "risks": [{"risk_id":"r1", "title":"Potential records risk", "why_non_obvious":"A retention rule may have operational effects.", "exact_quotes":["Records are retained for a limited period."], "search_queries":[]}],
        "jurisdiction":{"governing_law":"Example law", "venue":"Example venue", "party_locations":[], "data_subject_regions":[], "subject_hints":["privacy"]},
    }

    run_inline(workflow.research(state))

    assert "Records are retained for a limited period." in observed["query"]
    assert "Example law" in observed["context"]
    assert "privacy" in observed["context"]


def test_checklist_scan_batches_long_documents_and_keeps_grounded_results():
    prompts = []
    clauses = [{"id":f"C{i}","text":f"Clause language {i} requires documented operational review."} for i in range(1, 51)]

    async def model(prompt, schema, _model_name):
        prompts.append(prompt)
        clause_id = f"C{len(prompts)}"
        source = next(item["text"] for item in clauses if item["id"] == clause_id)
        return RiskScan(risks=[RiskFinding(
            risk_id="R1", title="Potential review item", severity="medium",
            clause_ids=[clause_id], exact_quotes=[source], why_non_obvious="The obligation may need review.",
            jurisdiction_assumption="Applicability depends on context.", suggested_mitigation_clause="Clarify the scope.",
        )])

    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver())
    state = {"clauses":clauses,"jurisdiction":{},"warnings":[]}

    result = run_inline(workflow.checklist_scan(state))

    assert len(prompts) == 4
    assert len(result["risks"]) == 4
    assert len({risk["risk_id"] for risk in result["risks"]}) == 4
    assert all("Clause batch" in prompt for prompt in prompts)


def test_research_deduplicates_search_queries_across_risks():
    class CountingResolver(FakeResolver):
        def __init__(self):
            self.queries = []
        async def search_query(self, query):
            self.queries.append(query)
            return []

    resolver = CountingResolver()
    workflow = LegalWorkflow(model_call=fake_model, resolver=resolver)
    state = {"risks":[
        {"risk_id":"r1", "search_queries":["neutral lookup question"]},
        {"risk_id":"r2", "search_queries":["neutral lookup question"]},
    ]}

    run_inline(workflow.research(state))

    assert resolver.queries == ["neutral lookup question"]


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
    async def model(prompt, schema, _model_name):
        prompts.append(prompt)
        if schema is DraftMemo:
                return DraftMemo(executive_summary="Review pending source coverage.")
        raise AssertionError(f"Unexpected schema: {schema}")

    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver())
    state = {"filename": "fixture.txt", "document_text": "Supplier may revise the Services.", "authority_bank": [], "risks": [{"risk_id":"R1", "title":"Unilateral change", "exact_quotes":["Supplier may revise the Services."], "authority_ids":[]}]}
    state = run_inline(workflow.draft_memo(state))
    state = run_inline(workflow.verify(state))

    assert "Return an empty claims list" in prompts[0]
    assert state["verified_results"] == []
    assert any(gap.startswith("No loaded source sentence") for gap in state["draft"]["coverage_gaps"])


def test_memo_writer_receives_risk_scoped_sources_and_abstention_rules():
    prompts = []
    authority = Authority(
        id="A1", key="synthetic section", kind="usc", title="Synthetic section",
        source="test", url="https://example.test/source", text=SUPPORT_TEXT,
        retrieved_at="2026-01-01T00:00:00Z", status="resolved",
    )

    async def model(prompt, schema, _model_name):
        prompts.append(prompt)
        return DraftMemo(executive_summary="Review pending.")

    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver())
    state = {
        "risks":[{"risk_id":"risk-x","authority_ids":["A1"]}],
        "authority_bank":[authority.model_dump()],
    }

    run_inline(workflow.draft_memo(state))

    assert "Return an empty claims list" in prompts[0]
    assert "Do not cite or paraphrase legal authorities" in prompts[0]
    assert "The server will build any legal claim only by quoting" in prompts[0]


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
        "draft": DraftMemo(executive_summary="Review pending.", claims=[claim_data]).model_dump(),
    }
    state = run_inline(workflow.verify(state))

    assert state["verified_results"][0]["status"] == "verified"
    assert state["verified_results"][0]["authority_quotes"] == [SUPPORT_TEXT]


def test_verifier_feedback_triggers_one_source_scoped_claim_repair():
    authority = Authority(
        id="A1", key="synthetic section", kind="usc", title="Synthetic section",
        source="test", url="https://example.test/source", text=SUPPORT_TEXT,
        retrieved_at="2026-01-01T00:00:00Z", status="resolved",
    )
    original = {
        "claim_id":"M-repair", "text":"A broad weak claim could apply.",
        "authority_ids":["A1"], "clause_quote":"Supplier shall protect the data.",
    }
    revised_claim = {
        **original, "text":"The source states that the covered party must protect customer data using safeguards.",
    }
    model_prompts = []
    checker_count = 0

    async def model(prompt, schema, _model_name):
        model_prompts.append(prompt)
        assert schema is DraftMemo
        return DraftMemo(
            executive_summary="Revised source-specific assessment.",
            claims=[revised_claim],
        )

    def checker(*_args):
        nonlocal checker_count
        checker_count += 1
        if checker_count == 1:
            return SupportVerdict(label="not_supported", authority_quote="", rationale="The original claim was too broad.")
        return SupportVerdict(label="supports", authority_quote=SUPPORT_TEXT, rationale="The revised proposition is directly supported.")

    workflow = LegalWorkflow(model_call=model, resolver=FakeResolver(), support_checker=checker)
    state = {
        "draft":DraftMemo(executive_summary="Initial assessment.", claims=[original]).model_dump(),
        "authority_bank":[authority.model_dump()],
        "document_text":"Supplier shall protect the data.",
        "risks":[{"risk_id":"risk-1","authority_ids":["A1"],"exact_quotes":["Supplier shall protect the data."]}],
    }

    result = run_inline(workflow.verify(state))

    assert result["claim_repair_attempted"] is True
    assert len(model_prompts) == 1
    assert "one bounded self-correction attempt" in model_prompts[0]
    assert result["draft"]["claims"][0]["clause_quote"] == original["clause_quote"]
    assert result["verified_results"][0]["status"] == "verified"
    assert checker_count == 2


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
        "draft": DraftMemo(executive_summary="Review pending.", claims=[claim_data]).model_dump(),
    }
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
        "draft": DraftMemo(executive_summary="Review pending.", claims=[claim_data]).model_dump(),
    }
    state = run_inline(workflow.verify(state))

    result = state["verified_results"][0]
    assert result["status"] == "unverified"
    assert result["reasons"][0].startswith("Source not loaded:")
