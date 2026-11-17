from app.ingestion.segment import segment_document
from app.ingestion.models import ParsedDocument


def test_numbered_all_caps_and_definition_sections_keep_exact_offsets():
    text = "DEFINITIONS\n\n1. Customer Data means all personal information.\n\n1.1 Use\nProvider may use Customer Data only to provide the Services.\n\n(a) Security\nProvider shall encrypt it."
    clauses, definitions = segment_document(text)
    assert [c.id for c in clauses] == ["C1", "C2", "C3", "C4"]
    assert clauses[0].heading == "DEFINITIONS"
    assert clauses[2].heading == "1.1 Use"
    assert all(text[c.start:c.end] == c.text for c in clauses)
    assert definitions["Customer Data"] == "all personal information"


def test_page_marker_assigns_clause_page():
    text = "[Page 1]\n\n1. Scope\nService terms.\n\n[Page 2]\n\n2. Term\nRenews automatically."
    clauses, _ = segment_document(text, ["1. Scope\nService terms.", "2. Term\nRenews automatically."])
    assert any(c.page == 1 for c in clauses)
    assert any(c.page == 2 for c in clauses)


def test_parsed_document_schema_is_structured():
    parsed = ParsedDocument(filename="msa.txt", content_type="text/plain", text="Terms")
    assert parsed.clauses == []
    assert parsed.definitions == {}
