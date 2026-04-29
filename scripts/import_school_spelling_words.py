#!/usr/bin/env python3
"""
Import spelling-bee-style word rows into core.lexemes with rich JSON extensions.

Sources:
  - CSV: word, difficulty_level, definition (repo-bundled study list style)
  - https://api.dictionaryapi.dev — phonetics / gloss (no API key; be polite with rate limits)
  - https://en.wiktionary.org — HTML scrape for Etymology section (Wiktionary CC BY-SA)

Usage (sync URL for psycopg; inside Docker use postgres hostname):
  export DATABASE_URL_SYNC=postgresql://homeschool:homeschool@localhost:5432/homeschool
  python scripts/import_school_spelling_words.py --csv app/apps/dictation/resources/words/spellingListtwobee.csv

This does NOT replace official Scripps materials; use for local enrichment only.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Any

import psycopg

_scripts = Path(__file__).resolve().parent
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

import lexeme_enrich as le

SLEEP_SEC = 0.35


def read_csv(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            w = (row.get("word") or "").strip()
            if not w:
                continue
            try:
                lvl = int(row.get("difficulty_level", 3))
            except (TypeError, ValueError):
                lvl = 3
            defn = (row.get("definition") or "").strip()
            rows.append({"word": w, "difficulty_level": lvl, "definition": defn})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        default="app/apps/dictation/resources/words/spellingListtwobee.csv",
        help="CSV with word,difficulty_level,definition (School Spelling Bee style list)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Process only first N words (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = read_csv(args.csv)
    if args.limit:
        rows = rows[: args.limit]

    if args.dry_run:
        print(f"Dry run: would process {len(rows)} rows from {args.csv}")
        return

    dsn = le.sync_url_from_env()
    conn = psycopg.connect(dsn)

    ok = 0
    for i, row in enumerate(rows):
        word = row["word"]
        diff = row["difficulty_level"]
        csv_def = row["definition"]
        try:
            dinfo = le.fetch_dictionary(word)
            time.sleep(SLEEP_SEC)
            etym = le.fetch_wiktionary_etymology(word)
            time.sleep(SLEEP_SEC)
        except Exception as exc:
            print(f"WARN {word}: {exc}", file=sys.stderr)
            dinfo, etym = {}, {}

        gloss = dinfo.get("gloss_from_api") or ""
        definition = csv_def or gloss or None

        ext: dict[str, Any] = {
            "pronunciation": {
                "ipa_or_dictionary_phonetic": dinfo.get("phonetic") or "",
                "phonetics": dinfo.get("phonetics") or [],
                "pronunciation_rules": le.pronunciation_rules(
                    dinfo.get("phonetic") or "", dinfo.get("phonetics") or []
                ),
            },
            "etymology": etym
            or "Etymology not extracted from Wiktionary for this headword (check Wiktionary manually).",
            "spelling_tricks": le.spelling_tricks(word),
            "word_origin_notes": "School spelling list vocabulary; verify against Merriam-Webster for competition use.",
            "import_source": "scripts/import_school_spelling_words.py",
            "dictionary_api_license": "CC BY-SA 3.0 (api.dictionaryapi.dev / Wiktionary)",
        }
        if gloss and gloss != (csv_def or ""):
            ext["dictionary_api_gloss"] = gloss[:800]

        le.upsert_lexeme(conn, word, diff, definition or "", ext)
        conn.commit()
        ok += 1
        if (i + 1) % 25 == 0:
            print(f"  … {i + 1}/{len(rows)}", flush=True)

    conn.close()
    print(f"Done. Upserted {ok} lexemes from {args.csv}")


if __name__ == "__main__":
    main()
