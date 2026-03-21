#!/usr/bin/env python3
"""CLI utility to browse VoiceTyper transcription history."""
import argparse
from src.db import init_db, get_recent, search


def main():
    parser = argparse.ArgumentParser(description="VoiceTyper History")
    parser.add_argument("-n", "--limit", type=int, default=20, help="Number of entries")
    parser.add_argument("-s", "--search", type=str, help="Search query")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    init_db()

    if args.search:
        rows = search(args.search, args.limit)
    else:
        rows = get_recent(args.limit)

    if not rows:
        print("No transcriptions found.")
        return

    if args.json:
        import json
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    for r in rows:
        ts = r["created_at"][:16]
        lang = r["language"] or "?"
        dur = r["duration_secs"] or 0
        app = r["source_app"] or "?"
        print(f"\033[90m[{ts}] {dur:.1f}s | {lang} | {app}\033[0m")
        print(f"  {r['text']}")
        print()


if __name__ == "__main__":
    main()
