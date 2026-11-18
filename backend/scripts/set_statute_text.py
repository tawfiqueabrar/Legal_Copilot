"""Load official statute text (copied from leginfo etc.) into backend/data/statutes.json.

Usage (from repo root):
    python backend/scripts/set_statute_text.py "16600" "bpc16600.txt"
    python backend/scripts/set_statute_text.py "1798.100" "civ1798100.txt"

The needle must match the END of the key (so "16600" will not hit "16600.5").
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "statutes.json"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    needle, text_path = sys.argv[1], Path(sys.argv[2])
    text = text_path.read_text(encoding="utf-8").strip()
    if len(text) < 80:
        print(f"Refusing: {text_path} has only {len(text)} chars. Paste the full official text.")
        return 1
    data = json.loads(DATA.read_text(encoding="utf-8"))
    matches = [k for k in data if k.lower().endswith(needle.lower())]
    if len(matches) != 1:
        print(f"Needle {needle!r} matched {len(matches)} keys: {matches}")
        return 1
    key = matches[0]
    data[key]["text"] = text
    data[key]["retrieved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Loaded {len(text)} chars into {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
