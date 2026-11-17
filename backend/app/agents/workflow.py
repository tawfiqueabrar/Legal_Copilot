import json, re
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from google import genai
from google.genai import types
from app.config import settings
from app.agents.schemas import AnalysisState, DocumentFact, Risk, Citation, Memo, SynthesisDraft
from app.services.legal_search import LegalSearch
from app.services.retrieval import embed_and_rerank


class GraphState(TypedDict, total=False):
    session_id: str; document_text: str; page_texts: list[str]; mime_type: str; filename: str; document_bytes: bytes
    event_queue: Any
    document: dict; risks: list[dict]; citations: list[dict]; memo: dict
    iteration: int; errors: list[str]; progress: list[dict]


def _json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    return json.loads(text)


class LegalWorkflow:
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
        self.search = LegalSearch()
        graph = StateGraph(GraphState)
        graph.add_node("triage", self.triage)
        graph.add_node("risk_hunter", self.risk_hunter)
        graph.add_node("citation_verifier", self.citation_verifier)
        graph.add_node("synthesizer", self.synthesizer)
        graph.set_entry_point("triage")
        graph.add_edge("triage", "risk_hunter")
        graph.add_edge("risk_hunter", "citation_verifier")
        graph.add_conditional_edges("citation_verifier", self._route_after_verify, {"risk_hunter": "risk_hunter", "synthesizer": "synthesizer"})
        graph.add_edge("synthesizer", END)
        self.graph = graph.compile()

    @staticmethod
    async def _event(state, node, message):
        state.setdefault("progress", []).append({"stage": node, "message": message})
        if state.get("event_queue"):
            await state["event_queue"].put({"event": "progress", "data": {"stage": node, "message": message}})

    async def _generate(self, prompt: str, mime_type: str = "application/json", media: bytes | None = None, media_type: str | None = None, cache_prefix: str = "") -> str:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        contents: Any = ([cache_prefix, prompt] if cache_prefix else prompt)
        if media and media_type:
            contents = ([cache_prefix, prompt, types.Part.from_bytes(data=media, mime_type=media_type)]
                        if cache_prefix else [prompt, types.Part.from_bytes(data=media, mime_type=media_type)])
        response = await self.client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(temperature=0.0, response_mime_type=mime_type),
        )
        return response.text or "{}"

    async def triage(self, s: GraphState) -> GraphState:
        await self._event(s, "triage", "Extracting document structure and deadlines")
        source = s.get("document_text", "")
        prompt = '''Return strict JSON with keys kind,title,jurisdiction,parties,deadlines,clauses. Identify contract vs court notice. In each clause include exact text, section, page, and bbox when visually available; bbox is [left,top,right,bottom] normalized to 0-1000 relative to the page. Preserve clause/page references and extract deadlines literally. Do not infer jurisdiction. For image/PDF media, use the visual document as evidence; note unreadable parts rather than guessing.'''
        try:
            media = s.get("document_bytes") if s.get("mime_type") == "application/pdf" or s.get("mime_type", "").startswith("image/") else None
            s["document"] = DocumentFact.model_validate(_json(await self._generate(prompt, media=media, media_type=s.get("mime_type"), cache_prefix=source[:180000]))).model_dump()
        except Exception as exc:
            s.setdefault("errors", []).append(f"triage: {type(exc).__name__}")
            s["document"] = DocumentFact().model_dump()
        return s

    async def risk_hunter(self, s: GraphState) -> GraphState:
        await self._event(s, "risk_hunter", "Reviewing clauses for non-obvious compliance risks")
        doc = s.get("document_text", "")[:180000]
        # Hybrid retrieval is scoped to this invocation and destroyed after return.
        chunks = [doc[i:i + 3500] for i in range(0, len(doc), 3000)]
        relevant = await embed_and_rerank("liability indemnity renewal termination governing law privacy audit deadlines", chunks)
        facts = json.dumps(s.get("document", {}), ensure_ascii=False)
        corpus = "\n\n".join(relevant) or doc or f"Triage extracted clauses and facts (use only exact quoted text where available):\n{facts}"
        prompt = f'''You are a cautious legal issue-spotting auditor. Return strict JSON {{"risks":[...]}}. Identify at least three distinct non-obvious risks supported by evidence. Never invent terms: if fewer than three substantive risks can be grounded, include explicit evidence-gap risks and explain what is unreadable or missing. For each provide id,title,severity(issue severity high/medium/low/critical),issue,rule,analysis,conclusion,quote,page,bbox,section,why_non_obvious,citation_text,query,source,mitigation. Quote exact words. Use bbox only when visual coordinates are available: four normalized values [left,top,right,bottom] on a 0-1000 scale for the exact evidence region. Cite external law only when clearly relevant and known; otherwise citation_text="", source="none". Treat proprietary clause findings as document-only. If unreadable, say so and include an evidence-gap risk. Consider uncapped indemnity carveouts beneath caps, one-sided renewal/notice mechanics, inconsistent law/forum, data-processing/incident gaps, audit/security obligations, survival, assignment, deadlines/service defects.\nDocument facts: {json.dumps(s.get('document',{}))}\nEvidence:\n{corpus}'''
        if s.get("verification_feedback"):
            prompt += f"\nCitation verifier feedback from the prior pass: {s['verification_feedback']} Do not repeat rejected authorities; either use a supported document-only finding or omit the authority."
        try:
            raw = _json(await self._generate(prompt, cache_prefix=doc)).get("risks", [])
            risks = []
            for i, item in enumerate(raw[:12]):
                item["id"] = str(item.get("id") or f"risk-{i+1}")
                citation_text = item.pop("citation_text", "")
                query = item.pop("query", citation_text)
                source = item.pop("source", "none")
                item["citation"] = Citation(citation_text=citation_text, query=query, source=source if source in ("courtlistener","eurlex") else "none", status="unverified", verification_note="Awaiting live source verification." if citation_text else "Document-only finding.").model_dump()
                risks.append(Risk.model_validate(item).model_dump())
            s["risks"] = risks
        except Exception as exc:
            s.setdefault("errors", []).append(f"risk_hunter: {type(exc).__name__}")
            s["risks"] = []
        s["iteration"] = s.get("iteration", 0) + 1
        return s

    async def citation_verifier(self, s: GraphState) -> GraphState:
        await self._event(s, "citation_verifier", "Checking each authority against its source")
        citations = []
        for risk in s.get("risks", []):
            citation = Citation.model_validate(risk.get("citation", {}))
            verified = await self.search.verify(citation)
            if verified.status == "unverified" and verified.citation_text:
                verified.citation_text = ""
                verified.url = None
                verified.matched_title = None
                verified.verification_note += " Unsupported authority removed from the memo."
            risk["citation"] = verified.model_dump()
            citations.append(verified.model_dump())
        s["risks"] = [Risk.model_validate(r).model_dump() for r in s.get("risks", [])]
        s["citations"] = citations
        rejected = [c.get("query") or c.get("citation_text") for c in citations if c.get("status") == "unverified" and c.get("source") != "none"]
        s["verification_feedback"] = "Rejected unverified citations: " + "; ".join(rejected) if rejected else ""
        return s

    def _route_after_verify(self, s: GraphState) -> str:
        # One correction pass: ask the auditor to replace/remove unsupported law.
        has_bad = any(c.get("status") == "unverified" and c.get("source") != "none" for c in s.get("citations", []))
        return "risk_hunter" if has_bad and s.get("iteration", 0) < 2 else "synthesizer"

    async def synthesizer(self, s: GraphState) -> GraphState:
        await self._event(s, "synthesizer", "Drafting the structured memorandum")
        risks = [Risk.model_validate(r) for r in s.get("risks", [])]
        jurisdiction = s.get("document", {}).get("jurisdiction") or "Unspecified"
        synthesis = None
        if self.client:
            prompt = f'''Return strict JSON with executive_summary, conclusion, and mitigations (object keyed by risk id). Draft concise formal legal memo language and commercially workable redline clauses for each risk. Preserve the findings, severity, exact evidence, and jurisdiction. Do not introduce any new cases, statutes, legal propositions, or facts; only use the verified risk data. If a citation is unverified or absent, do not imply external law.\nJurisdiction: {jurisdiction}\nVerified findings: {json.dumps([risk.model_dump() for risk in risks])}'''
            try:
                synthesis = SynthesisDraft.model_validate(_json(await self._generate(prompt)))
                risks = [risk.model_copy(update={"mitigation": synthesis.mitigations.get(risk.id, risk.mitigation)}) for risk in risks]
            except Exception as exc:
                s.setdefault("errors", []).append(f"synthesizer: {type(exc).__name__}")
        memo = Memo(jurisdiction=jurisdiction,
                    executive_summary=synthesis.executive_summary if synthesis else f"Review identified {len(risks)} issue(s). Confirm jurisdiction, source text, and deadlines with qualified counsel.",
                    risks=risks,
                    conclusion=synthesis.conclusion if synthesis else "Prioritize any court filing deadlines, negotiate high-severity terms before signature, and obtain jurisdiction-specific counsel review.")
        s["memo"] = memo.model_dump()
        return s

    async def run(self, initial: GraphState):
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        return await self.graph.ainvoke(initial)

