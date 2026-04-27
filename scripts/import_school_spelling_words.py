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
import os
import re
import sys
import time
import uuid
from html import unescape
from typing import Any

import requests
from bs4 import BeautifulSoup
from psycopg.types.json import Json

REQUEST_TIMEOUT = 25
SLEEP_SEC = 0.35


def sync_url_from_env() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "").strip()
    if u:
        return u.replace("postgresql+asyncpg://", "postgresql://", 1)
    u = os.getenv("DATABASE_URL", "").strip()
    if not u:
        print("Set DATABASE_URL_SYNC or DATABASE_URL", file=sys.stderr)
        sys.exit(1)
    u = u.replace("postgresql+asyncpg://", "postgresql://", 1)
    return u


def fetch_dictionary(word: str) -> dict[str, Any]:
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{requests.utils.quote(word, safe='')}"
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        return {}
    entry = data[0]
    phonetic = entry.get("phonetic") or ""
    phonetics = []
    for p in entry.get("phonetics") or []:
        if isinstance(p, dict):
            phonetics.append(
                {k: v for k, v in p.items() if k in ("text", "audio") and v}
            )
    gloss_parts: list[str] = []
    for m in entry.get("meanings") or []:
        pos = m.get("partOfSpeech") or ""
        for d in (m.get("definitions") or [])[:2]:
            t = (d.get("definition") or "").strip()
            if t:
                gloss_parts.append(f"({pos}) {t}" if pos else t)
    return {
        "phonetic": phonetic,
        "phonetics": phonetics,
        "gloss_from_api": " ".join(gloss_parts[:3])[:1200],
        "source_urls": entry.get("sourceUrls") or [],
    }


def fetch_wiktionary_etymology(word: str) -> str:
    url = f"https://en.wiktionary.org/wiki/{requests.utils.quote(word.replace(' ', '_'), safe='')}"
    r = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "HomeschoolImport/1.0 (educational; contact: local)"},
    )
    if r.status_code != 200:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    # Find first Etymology headline (English entries)
    for h in soup.find_all(["h2", "h3", "h4"]):
        span = h.find("span", class_="mw-headline")
        if not span or not span.get("id"):
            continue
        hid = span["id"].lower()
        if "etymology" in hid:
            parts: list[str] = []
            for sib in h.find_next_siblings():
                if sib.name in ("h2", "h3", "h4"):
                    break
                text = sib.get_text(" ", strip=True)
                if text:
                    parts.append(text)
                if len(" ".join(parts)) > 1800:
                    break
            return " ".join(parts)[:2000]
    return ""


def spelling_tricks(word: str) -> list[str]:
    w = word.lower()
    tips: list[str] = []
    if re.search(r"[aeiou]{3,}", w):
        tips.append("Watch the vowel sequence — say it slowly and match each vowel sound to a letter.")
    if re.search(r"(.)\1", w):
        tips.append("This word has a double letter; remember which letter is doubled.")
    if w.startswith("kn"):
        tips.append("'Kn' at the start: the k is silent in many English words.")
    if "ph" in w:
        tips.append("'ph' often sounds like /f/ — one sound, two letters.")
    if "tion" in w or "sion" in w:
        tips.append("The '-tion/-sion' ending is common; stress the syllable before it.")
    if w.endswith("e") and len(w) > 3:
        tips.append("Final silent 'e' may signal a long vowel in the stem — split into syllables.")
    if not tips:
        tips.append("Chunk the word into syllables; check each chunk against how you say it aloud.")
    return tips[:6]


def pronunciation_rules(phonetic: str, phonetics: list[dict]) -> list[str]:
    rules: list[str] = []
    if phonetic:
        rules.append(f"IPA-style guide from learner dictionary: {phonetic}")
    for p in phonetics:
        t = p.get("text")
        if t and t not in (phonetic,):
            rules.append(f"Alternate notation: {t}")
        if p.get("audio"):
            rules.append("Listen to the linked audio clip and match syllable stress.")
    if not rules:
        rules.append("Stress the strongest syllable you hear when saying the word naturally.")
    return rules[:8]


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


def upsert_lexeme(
    conn,
    word: str,
    difficulty: int,
    definition: str,
    extensions: dict[str, Any],
) -> None:
    cw = word.lower().strip()
    ext = Json(extensions)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM core.lexemes
            WHERE locale_code = 'en' AND lower(canonical_word) = lower(%s)
            """,
            (cw,),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE core.lexemes
                SET difficulty_level = %s,
                    definition = COALESCE(NULLIF(%s, ''), definition),
                    extensions = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (difficulty, definition, ext, existing[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO core.lexemes (
                    id, locale_code, canonical_word, display_word,
                    difficulty_level, definition, extensions, created_at, updated_at
                ) VALUES (%s, 'en', %s, %s, %s, %s, %s, now(), now())
                """,
                (str(uuid.uuid4()), cw, word.strip(), difficulty, definition or None, ext),
            )


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

    import psycopg

    dsn = sync_url_from_env()
    if args.dry_run:
        print(f"Dry run: would process {len(rows)} rows from {args.csv}")
        return

    conn = psycopg.connect(dsn)

    ok = 0
    for i, row in enumerate(rows):
        word = row["word"]
        diff = row["difficulty_level"]
        csv_def = row["definition"]
        try:
            dinfo = fetch_dictionary(word)
            time.sleep(SLEEP_SEC)
            etym = fetch_wiktionary_etymology(word)
            time.sleep(SLEEP_SEC)
        except Exception as exc:
            print(f"WARN {word}: {exc}", file=sys.stderr)
            dinfo, etym = {}, ""

        gloss = dinfo.get("gloss_from_api") or ""
        definition = csv_def or gloss or None

        ext: dict[str, Any] = {
            "pronunciation": {
                "ipa_or_dictionary_phonetic": dinfo.get("phonetic") or "",
                "phonetics": dinfo.get("phonetics") or [],
                "pronunciation_rules": pronunciation_rules(
                    dinfo.get("phonetic") or "", dinfo.get("phonetics") or []
                ),
            },
            "etymology": etym or "Etymology not extracted from Wiktionary for this headword (check Wiktionary manually).",
            "spelling_tricks": spelling_tricks(word),
            "word_origin_notes": "School spelling list vocabulary; verify against Merriam-Webster for competition use.",
            "import_source": "scripts/import_school_spelling_words.py",
            "dictionary_api_license": "CC BY-SA 3.0 (api.dictionaryapi.dev / Wiktionary)",
        }
        if gloss and gloss != (csv_def or ""):
            ext["dictionary_api_gloss"] = gloss[:800]

        upsert_lexeme(conn, word, diff, definition or "", ext)
        conn.commit()
        ok += 1
        if (i + 1) % 25 == 0:
            print(f"  … {i + 1}/{len(rows)}", flush=True)

    conn.close()
    print(f"Done. Upserted {ok} lexemes from {args.csv}")


if __name__ == "__main__":
    main()
