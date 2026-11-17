import asyncio, re
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from urllib.parse import quote_plus
import httpx
from app.config import settings
from app.agents.schemas import Citation


class LegalSearch:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15, follow_redirects=True)

    async def close(self):
        await self.client.aclose()

    async def _request(self, url: str, *, params=None, headers=None, auth=None):
        for attempt in range(4):
            try:
                response = await self.client.get(url, params=params, headers=headers, auth=auth)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 3:
                        await asyncio.sleep(min(0.5 * (2 ** attempt), 4))
                        continue
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt == 3:
                    raise
                await asyncio.sleep(min(0.5 * (2 ** attempt), 4))

    async def verify(self, citation: Citation) -> Citation:
        if not citation.citation_text.strip():
            citation.status = "proprietary_clause"
            citation.verification_note = "No external authority cited; this is a document-based observation."
            return citation
        try:
            if citation.source == "eurlex":
                return await self._verify_eurlex(citation)
            if citation.source == "courtlistener":
                return await self._verify_courtlistener(citation)
            citation.status = "unverified"
            citation.verification_note = "No compatible legal source was selected; citation withheld."
        except Exception as exc:
            citation.status = "unverified"
            citation.verification_note = f"Source unavailable; no verification claimed ({type(exc).__name__})."
        return citation

    async def _verify_courtlistener(self, citation: Citation) -> Citation:
        headers = {"Authorization": f"Token {settings.courtlistener_api_token}"} if settings.courtlistener_api_token else {}
        q = citation.citation_text
        search_type = "d" if "docket" in q.casefold() or re.search(r"\b\d{1,2}[:-]\d{3,6}\b", q) else "o"
        payload = await self._request("https://www.courtlistener.com/api/rest/v4/search/", params={"q": q, "type": search_type, "page_size": 5}, headers=headers)
        results = payload.get("results", [])
        target = re.sub(r"\W+", "", q).casefold()
        for result in results:
            title = result.get("caseName") or result.get("case_name") or ""
            cite = " ".join(result.get("citation", []) if isinstance(result.get("citation"), list) else [str(result.get("citation", ""))])
            docket = result.get("docketNumber") or result.get("docket_number") or ""
            norm = lambda value: re.sub(r"\W+", "", str(value)).casefold()
            title_norm, cite_norm, docket_norm = norm(title), norm(cite), norm(docket)
            matched = target and (target == title_norm or target == cite_norm or target == docket_norm or (title_norm and cite_norm and title_norm in target and cite_norm in target))
            if matched:
                citation.status = "verified_record"
                citation.matched_title = title or None
                citation.url = "https://www.courtlistener.com" + result.get("absolute_url", "") if result.get("absolute_url", "").startswith("/") else result.get("absolute_url")
                citation.verification_note = "Exact normalized citation text found in CourtListener record metadata. The record match does not verify the legal proposition."
                return citation
        citation.status = "unverified"
        citation.verification_note = "No exact normalized citation match in returned CourtListener metadata."
        return citation

    async def _verify_eurlex(self, citation: Citation) -> Citation:
        if not settings.eurlex_ws_username or not settings.eurlex_ws_password:
            citation.status = "unverified"
            citation.verification_note = "EUR-Lex SOAP access requires a registered account; no verification claimed."
            return citation
        query = escape('"' + citation.citation_text + '"')
        username = escape(settings.eurlex_ws_username)
        password = escape(settings.eurlex_ws_password)
        envelope = f'''<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:sear="http://eur-lex.europa.eu/search" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"><soap:Header><wsse:Security soap:mustUnderstand="true"><wsse:UsernameToken><wsse:Username>{username}</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">{password}</wsse:Password></wsse:UsernameToken></wsse:Security></soap:Header><soap:Body><sear:searchRequest><sear:expertQuery>{query}</sear:expertQuery><sear:page>1</sear:page><sear:pageSize>10</sear:pageSize><sear:searchLanguage>en</sear:searchLanguage><sear:excludeAllConsleg>false</sear:excludeAllConsleg><sear:limitToLatestConsleg>false</sear:limitToLatestConsleg></sear:searchRequest></soap:Body></soap:Envelope>'''
        response = None
        for attempt in range(4):
            try:
                response = await self.client.post("https://eur-lex.europa.eu/EURLexWebService", content=envelope.encode(), headers={"Content-Type": "application/soap+xml; charset=utf-8"})
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 3:
                        await asyncio.sleep(min(0.5 * (2 ** attempt), 4))
                        continue
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt == 3:
                    raise
                await asyncio.sleep(min(0.5 * (2 ** attempt), 4))
        text = response.text if response else ""
        try:
            root = ElementTree.fromstring(text)
            text = " ".join(root.itertext())
        except ElementTree.ParseError:
            pass
        if citation.citation_text.casefold() in text.casefold():
            citation.status = "verified_record"
            citation.url = "https://eur-lex.europa.eu/search.html?text=" + quote_plus(citation.citation_text)
            citation.verification_note = "Exact citation text found in EUR-Lex SOAP results. The record match does not verify the legal proposition."
        else:
            citation.status = "unverified"
            citation.verification_note = "No exact citation text in EUR-Lex SOAP results."
        return citation
