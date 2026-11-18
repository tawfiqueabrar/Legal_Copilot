"""Add an entry to the statute corpus from a UTF-8 text file.

Usage (from repo root):
    python backend/scripts/add_statute.py --key "EU REGULATION 2016/679 ART. 33" \
        --title "GDPR Article 33" --url "<url>" --source "EUR-Lex" \
        --kind eu_regulation --text-file gdpr_art33.txt

Pass --replace to replace an existing key.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / "data" / "statutes.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--text-file", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    text = args.text_file.read_text(encoding="utf-8").strip()
    if len(text) < 80:
        print(f"Refusing: {args.text_file} has only {len(text)} characters; expected at least 80.")
        return 1

    data = json.loads(DATA.read_text(encoding="utf-8"))
    if args.key in data and not args.replace:
        print(f"Refusing: key already exists: {args.key!r}. Pass --replace to overwrite it.")
        return 1

    data[args.key] = {
        "title": args.title,
        "url": args.url,
        "source": args.source,
        "kind": args.kind,
        "text": text,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added statute entry {args.key!r} with {len(text)} characters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
