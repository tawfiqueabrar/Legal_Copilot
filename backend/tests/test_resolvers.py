import json
from conftest import run_inline
from app.verification.models import Citation
from app.verification.resolvers import CourtListenerResolver, StaticCorpusResolver, CompositeResolver, build_bank


class Response:
    def __init__(self, payload, status=200): self.payload, self.status_code = payload, status
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("HTTP error")
    def json(self): return self.payload


class FakeHttp:
    def __init__(self): self.calls = []
    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return Response([{"citation":"410 U.S. 113","normalized_citations":["410 U.S. 113"],"status":200,"clusters":[{"case_name":"Roe v. Wade","absolute_url":"/opinion/1/","sub_opinions":[{"resource_uri":"/api/rest/v4/opinions/1/"}]}]}])
    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return Response({"plain_text":"Opinion source text."})


def test_courtlistener_resolves_and_fetches_opinion_text():
    http = FakeHttp()
    resolver = CourtListenerResolver(token="test-token", http=http)
    authority = run_inline(resolver.resolve(Citation(kind="us_case", raw="410 U.S. 113", normalized_key="410 U.S. 113")))
    assert authority.title == "Roe v. Wade"
    assert authority.text == "Opinion source text."
    assert authority.status == "resolved"
    assert http.calls[0][1].endswith("/citation-lookup/")


def test_network_error_is_never_resolved():
    class Broken:
        async def post(self, *args, **kwargs): raise OSError("offline")
    resolver = CourtListenerResolver(token="", http=Broken())
    authority = run_inline(resolver.resolve(Citation(kind="us_case", raw="410 U.S. 113", normalized_key="410 U.S. 113")))
    assert authority is None


def test_static_corpus_and_composite_fallback(tmp_path):
    path = tmp_path / "statutes.json"
    path.write_text(json.dumps({"42 U.S.C. § 1983":{"title":"Civil action","url":"https://example.test/1983","text":"official text","retrieved_at":"2026-01-01T00:00:00Z","source":"official"}}), encoding="utf-8")
    citation = Citation(kind="usc", raw="42 U.S.C. § 1983(a)", normalized_key="42 U.S.C. § 1983")
    resolver = StaticCorpusResolver(path)
    authority = run_inline(resolver.resolve(citation))
    assert authority.status == "resolved"
    bank = run_inline(build_bank([citation], CompositeResolver([resolver])))
    assert bank.get("A1").text == "official text"
