from .extract import normalize_citation
from .models import Authority, Citation


class AuthorityBank:
    """Closed set of resolved authorities; IDs are assigned deterministically by key."""

    def __init__(self, authorities: list[Authority] | None = None):
        self._by_id: dict[str, Authority] = {}
        self._by_key: dict[str, Authority] = {}
        self.add_many(authorities or [])

    def add_many(self, authorities: list[Authority]) -> list[Authority]:
        for auth in sorted(authorities, key=lambda item: (item.key, item.source, item.url)):
            if auth.key in self._by_key:
                continue
            next_id = f"A{len(self._by_id) + 1}"
            assigned = auth.model_copy(update={"id": next_id})
            self._by_id[next_id] = assigned
            self._by_key[assigned.key] = assigned
        return self.all()

    def add(self, authority: Authority) -> Authority:
        existing = self._by_key.get(authority.key)
        if existing:
            return existing
        next_id = f"A{len(self._by_id) + 1}"
        assigned = authority.model_copy(update={"id": next_id})
        self._by_id[next_id] = assigned
        self._by_key[assigned.key] = assigned
        return assigned

    def get(self, authority_id: str) -> Authority | None:
        return self._by_id.get(authority_id)

    def get_by_key(self, key: str) -> Authority | None:
        return self._by_key.get(key)

    def get_for_citation(self, citation: Citation) -> Authority | None:
        return self.get_by_key(normalize_citation(citation.raw, citation.kind))

    def all(self) -> list[Authority]:
        return list(self._by_id.values())

    def prompt_block(self) -> str:
        lines = ["AUTHORITY BANK (closed set; cite only these IDs):"]
        for authority in self._by_id.values():
            basis = "source text available" if authority.text else "existence only; no source text available"
            lines.append(f"[{authority.id}] {authority.title} | {authority.key} | {authority.url} | {basis}")
            if authority.text:
                lines.append(authority.text)
        return "\n".join(lines)
