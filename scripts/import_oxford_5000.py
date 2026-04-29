#!/usr/bin/env python3
"""
Import Oxford 3000/5000-style vocabulary into core.lexemes.

The open dataset at https://github.com/nalgeon/words (data/oxford-5k.csv) lists
words with CEFR band, part of speech, and links to Oxford Learner's Dictionaries
(definition and pronunciation audio). OUP does not publish a public API; this
script enriches each headword the same way as import_school_spelling_words.py:
- https://api.dictionaryapi.dev (gloss, phonetics; no API key)
- https://en.wiktionary.org (etymology scrape; CC BY-SA)

Usage (inside Docker; use host postgres:5432 from host):
  export DATABASE_URL_SYNC=postgresql://homeschool:homeschool@postgres:5432/homeschool
  python scripts/import_oxford_5000.py
  python scripts/import_oxford_5000.py --limit 200
  python scripts/import_oxford_5000.py --csv /path/to/oxford-5k.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import psycopg

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import lexeme_enrich as le

SLEEP_SEC = 0.35


def cefr_to_level_and_difficulty(cefr: str) -> tuple[str, int]:
    """Map OALD-style level (a1, b1, c1) to a label and 1-10 dictation difficulty."""
    c = (cefr or "").strip().lower()
    order = ["a1", "a2", "b1", "b2", "b3", "c1", "c2"]
    if c in order:
        idx = order.index(c) + 1
        return c.upper(), max(1, min(10, int(round((idx / len(order)) * 10)) or 1))
    if not c:
        return "", 5
    return c.upper() if c else "", 5


def load_oxford_rows_from_url(url: str) -> list[dict[str, str]]:
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    raw = list(csv.DictReader(io.StringIO(text)))
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in raw]


def load_oxford_rows_from_path(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in raw]


def best_cefr(a: str, b: str) -> str:
    order = ["a1", "a2", "b1", "b2", "b3", "c1", "c2"]
    aa = (a or "").strip().lower()
    bb = (b or "").strip().lower()
    if aa in order and bb in order:
        return aa if order.index(aa) <= order.index(bb) else bb
    return aa or bb


def build_word_index(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """One entry per surface word: merge CEFR, collect pos and OALD links."""
    by_word: dict[str, dict[str, Any]] = {}
    for row in rows:
        w = (row.get("word") or "").strip()
        if not w or w.startswith("#"):
            continue
        level = (row.get("level") or "").strip().lower()
        pos = (row.get("pos") or "").strip()
        def_url = (row.get("definition_url") or "").strip()
        voice = (row.get("voice_url") or "").strip()
        key = w.lower()
        if key not in by_word:
            by_word[key] = {
                "surface": w,
                "cefr": level,
                "parts_of_speech": [],
                "oxford_definition_urls": [],
                "oxford_voice_urls": [],
            }
        b = by_word[key]
        if level:
            b["cefr"] = best_cefr(b.get("cefr", ""), level)
        if pos and pos not in b["parts_of_speech"]:
            b["parts_of_speech"].append(pos)
        if def_url and def_url not in b["oxford_definition_urls"]:
            b["oxford_definition_urls"].append(def_url)
        if voice and voice not in b["oxford_voice_urls"]:
            b["oxford_voice_urls"].append(voice)
    return by_word


def run_import(
    rows: list[dict[str, str]],
    *,
    limit: int,
    dry_run: bool,
) -> int:
    index = build_word_index(rows)
    items = list(index.values())
    items.sort(key=lambda x: x["surface"].lower())
    if limit:
        items = items[:limit]

    if dry_run:
        print(f"Dry run: {len(items)} headwords (from {len(index)} unique after merge)")
        return 0

    dsn = le.sync_url_from_env()
    conn = psycopg.connect(dsn)
    ok = 0
    for i, meta in enumerate(items):
        word = meta["surface"]
        cefr_label, diff = cefr_to_level_and_difficulty(meta.get("cefr") or "")
        try:
            dinfo = le.fetch_dictionary(word)
            time.sleep(SLEEP_SEC)
            etym = le.fetch_wiktionary_etymology(word)
            time.sleep(SLEEP_SEC)
        except Exception as exc:
            print(f"WARN {word}: {exc}", file=sys.stderr)
            dinfo, etym = {}, ""

        gloss = dinfo.get("gloss_from_api") or ""
        definition = gloss or f"Oxford {cefr_label or 'learner'} list word — add a gloss in admin if needed."

        ext: dict[str, Any] = {
            "vocabulary_list": "Oxford 5000 (open dataset: nalgeon/words oxford-5k.csv; align with OUP materials for class use).",
            "cefr_oxford": cefr_label,
            "parts_of_speech": meta.get("parts_of_speech") or [],
            "oxford_learners_links": {
                "definition_urls": (meta.get("oxford_definition_urls") or [])[:5],
                "audio_urls": (meta.get("oxford_voice_urls") or [])[:5],
            },
            "pronunciation": {
                "ipa_or_dictionary_phonetic": dinfo.get("phonetic") or "",
                "phonetics": dinfo.get("phonetics") or [],
                "pronunciation_rules": le.pronunciation_rules(
                    dinfo.get("phonetic") or "", dinfo.get("phonetics") or []
                ),
            },
            "etymology": etym
            or "Etymology not found on Wiktionary for this headword (edit in admin or check Wiktionary).",
            "spelling_tricks": le.spelling_tricks(word),
            "import_source": "scripts/import_oxford_5000.py",
            "enrichment": {
                "dictionary_api": "https://api.dictionaryapi.dev (CC BY-SA 3.0; verify at source)",
                "wiktionary": "https://en.wiktionary.org (CC BY-SA)",
            },
        }
        if gloss:
            ext["dictionary_api_gloss"] = gloss[:800]

        le.upsert_lexeme(conn, word, diff, definition, ext)
        conn.commit()
        ok += 1
        if (i + 1) % 50 == 0:
            print(f"  … {i + 1}/{len(items)}", flush=True)

    conn.close()
    return ok


def main() -> None:
    default_csv = "https://raw.githubusercontent.com/nalgeon/words/main/data/oxford-5k.csv"
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        default=default_csv,
        help="Path to oxford-5k.csv or URL (default: nalgeon/words raw on GitHub)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Max headwords to import (0 = all unique words)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.csv.startswith("http://") or args.csv.startswith("https://"):
        print(f"Fetching {args.csv} …", flush=True)
        rows = load_oxford_rows_from_url(args.csv)
    else:
        rows = load_oxford_rows_from_path(args.csv)

    n = run_import(rows, limit=args.limit or 0, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"Done. Upserted {n} lexeme headwords.")


if __name__ == "__main__":
    main()
