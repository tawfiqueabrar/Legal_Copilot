from scripts.split_gdpr_articles import ARTICLE_HEADING, plan_entries


def test_article_slices_are_exact_substrings_and_exclude_other_article_headings():
    combined = (
        "Article 28\nDummy text for article twenty eight.\n"
        "Article 44\nDummy text for article forty four.\n"
        "Article 46\nDummy text for article forty six."
    )
    data = {
        "EU REGULATION 2016/679": {
            "title": "Dummy combined title", "url": "https://example.test/source",
            "source": "test", "kind": "eu_regulation", "text": combined,
            "retrieved_at": "2026-01-01T00:00:00Z",
        }
    }
    generated, leftovers = plan_entries(data)

    assert list(generated) == [
        "EU REGULATION 2016/679 ART. 28",
        "EU REGULATION 2016/679 ART. 44",
        "EU REGULATION 2016/679 ART. 46",
    ]
    for key, entry in generated.items():
        article_number = int(key.rsplit(" ", 1)[1])
        assert entry["text"] in combined
        other_headings = [
            int(match.group(1)) for match in ARTICLE_HEADING.finditer(entry["text"])
            if int(match.group(1)) != article_number
        ]
        assert other_headings == []
        assert entry["url"] == data["EU REGULATION 2016/679"]["url"]
        assert entry["source"] == data["EU REGULATION 2016/679"]["source"]
        assert entry["kind"] == data["EU REGULATION 2016/679"]["kind"]
        assert entry["retrieved_at"] == data["EU REGULATION 2016/679"]["retrieved_at"]
    assert leftovers == []


def test_prefix_leftover_is_not_attached_to_an_article():
    combined = "Unattached dummy prefix.\nArticle 28\nDummy article body."
    data = {"EU REGULATION 2016/679": {"text": combined}}
    generated, leftovers = plan_entries(data)
    article_text = generated["EU REGULATION 2016/679 ART. 28"]["text"]
    assert "Unattached dummy prefix." not in article_text
    assert len(leftovers) == 1
    assert leftovers[0][0] == "prefix-before-first-article"
    assert leftovers[0][1] == "Unattached dummy prefix.\n"
