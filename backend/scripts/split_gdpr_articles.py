"""Plan or create article-specific entries from the combined GDPR text.

Default mode is a read-only dry run. Pass --write only after reviewing the plan.
Article text is always sliced from the existing combined entry; this script does
not fetch, author, or normalize statute text.
"""
import argparse
import json
import re
from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / "data" / "statutes.json"
COMBINED_KEY = "EU REGULATION 2016/679"
ARTICLE_HEADING = re.compile(r"(?m)^Article[ \t]+(\d{1,3})[ \t]*$")


def split_article_text(text: str) -> tuple[dict[int, str], list[tuple[str, str]]]:
    """Return exact article slices and unattached prefix material, if any."""
    headings = list(ARTICLE_HEADING.finditer(text))
    if not headings:
        return {}, [("entire-text", text)] if text else []

    articles: dict[int, str] = {}
    leftovers: list[tuple[str, str]] = []
    if text[:headings[0].start()].strip():
        leftovers.append(("prefix-before-first-article", text[:headings[0].start()]))

    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        article_number = int(heading.group(1))
        article_slice = text[heading.start():end]
        if article_number in articles:
            raise ValueError(f"Repeated article heading: {article_number}")
        if not article_slice.strip():
            raise ValueError(f"Empty article slice: {article_number}")
        articles[article_number] = article_slice

    return articles, leftovers


def plan_entries(data: dict) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    combined = data.get(COMBINED_KEY)
    if not isinstance(combined, dict) or not isinstance(combined.get("text"), str) or not combined["text"].strip():
        raise ValueError(f"Combined corpus entry {COMBINED_KEY!r} has no text.")

    articles, leftovers = split_article_text(combined["text"])
    generated: dict[str, dict] = {}
    for number, article_text in articles.items():
        key = f"{COMBINED_KEY} ART. {number}"
        entry = {
            "title": f"Regulation (EU) 2016/679, Article {number}",
            "url": combined.get("url", ""),
            "source": combined.get("source", ""),
            "kind": combined.get("kind", "eu_regulation"),
            "text": article_text,
            "retrieved_at": combined.get("retrieved_at"),
        }
        generated[key] = entry
    return generated, leftovers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="write planned article entries")
    action.add_argument("--dry-run", action="store_true", help="print keys and character counts without writing (default)")
    args = parser.parse_args(argv)

    data = json.loads(args.data.read_text(encoding="utf-8"))
    generated, leftovers = plan_entries(data)
    collisions = sorted(set(generated).intersection(data))
    if collisions:
        print(f"Refusing: generated keys already exist: {collisions}")
        return 1

    for key, entry in generated.items():
        print(f"{'Added' if args.write else 'Would add'} {key}: {len(entry['text'])} characters")
    for label, text in leftovers:
        print(f"Unattached leftover {label}: {len(text)} characters (not assigned to an article)")
    if not args.write:
        print("Dry run only; no corpus changes written.")
        return 0

    data.update(generated)
    args.data.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(generated)} article entries to {args.data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
