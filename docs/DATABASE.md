# Homeschool database structure

Reference for **where data lives**, **relationships**, and **how to extend** language / spelling metadata.

---

## 1. Executive summary

| Store | Engine | Role |
|-------|--------|------|
| **Core platform** | PostgreSQL, schema **`core`** | Students, projects, suite-level assignments, grades, skills, **dictionary (lexemes)**, **dictation word queue**, **dictation attempt history**. |
| **Dictation profiles** | SQLite (`dictation.db`) | **Only** the lightweight **`users`** table: integer `id` for the student picker, display `name`, `difficulty_level`, link `core_student_id` → Postgres `core.students.id`. |

**Rule of thumb:** Anything about **which words exist** and **which words are assigned to whom** is in **Postgres**. SQLite answers **“which dictation profile id is playing?”** only.

---

## 2. PostgreSQL — schema `core`

### 2.1 Migrations

- **Alembic** in `alembic/versions/`.
- **`0001_core`:** students, projects, assignments, assignment_items, grades, skill_observations.
- **`0002_dictation_lexemes`:** `lexemes`, `dictation_assignments`, `dictation_attempts`.

### 2.2 `core.lexemes` — canonical dictionary + dynamic language fields

One row per **(locale, canonical word)**. This replaces the old SQLite `words` table.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID` | PK. |
| `locale_code` | `VARCHAR(16)` | Default `en`. Enables future multi-locale dictionaries without duplicate global rows. |
| `canonical_word` | `VARCHAR(255)` | Normalized for matching (app uses lowercase). |
| `display_word` | `VARCHAR(255)` nullable | Optional casing / presentation. |
| `difficulty_level` | `INTEGER` nullable | 1–10 style scale for AI and UI. |
| `definition` | `TEXT` nullable | Short gloss for hints. |
| **`extensions`** | **`JSONB`** | **Primary extension point.** Default `{}`. Typical keys (add freely): |
| | | • **`pronunciation`** — `{ "ipa_or_dictionary_phonetic", "phonetics"[], "pronunciation_rules"[] }` |
| | | • **`etymology`** — text (often from Wiktionary scrape in import script) |
| | | • **`spelling_tricks`** — string array (heuristics + patterns) |
| | | • **`dictionary_api_gloss`**, **`import_source`**, **`word_origin_notes`** — provenance / extra gloss |
| | | Prefer **new keys inside `extensions`** over new columns when the shape may evolve. |

**Uniqueness:** unique index on `(locale_code, lower(canonical_word))`.

---

### 2.3 `core.dictation_assignments` — per-user word queue

Replaces SQLite `user_words`. **`dictation_user_id`** is the **integer** from SQLite `users.id` (not a UUID).

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID` | PK (also exposed as `assignment_id` in API responses for the student UI). |
| `dictation_user_id` | `INTEGER` | Matches `dictation.db` `users.id`. |
| `lexeme_id` | `UUID` | FK → `lexemes.id`, CASCADE delete. |
| `interval`, `correct_streak` | `INTEGER` | Spaced repetition fields. |
| `next_review_date` | `DATE` | Due logic. |

**Constraint:** `UNIQUE(dictation_user_id, lexeme_id)`.

---

### 2.4 `core.dictation_attempts` — practice history

Replaces SQLite `history`.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID` | PK. |
| `dictation_user_id` | `INTEGER` | SQLite profile id. |
| `lexeme_id` | `UUID` | FK → `lexemes.id`. |
| `is_correct` | `BOOLEAN` | |
| `attempt_date` | `DATE` | |
| `metadata` | `JSONB` | Default `{}` for future per-attempt notes. |

**Index:** `(dictation_user_id, attempt_date)` for progress charts.

---

### 2.5 Other `core` tables (unchanged conceptually)

See `app/core/models.py` and migration `0001_core` for:

- `students`, `projects`, `assignments`, `assignment_items`, `grades`, `skill_observations`

Suite-level **assignments** (e.g. from platform admin when committing an AI word list) remain separate from **`dictation_assignments`** (per-word queue for the game).

---

## 3. SQLite — `dictation.db`

### 3.1 Table: `users`

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK | **dictation_user_id** everywhere in Postgres dictation tables. |
| `name` | TEXT UNIQUE | Display name in student UI. |
| `difficulty_level` | TEXT | Used for Ollama prompts (numeric as string). |
| `core_student_id` | TEXT nullable | String form of `core.students.id` (UUID). |
| `created_at` | timestamp | |

**No** `words`, `user_words`, or `history` tables in current code paths.

---

## 4. Cross-store flows

1. **Create core student** → sync SQLite `users` row with `core_student_id`.
2. **Platform admin → Dictionary tab** (view/edit) or **import script / `POST /apps/dictation/words/bulk-upload`** → upserts **`core.lexemes`**.
3. **Assign words** (API or AI commit) → **`core.dictation_assignments`** + optional **`core.assignments`** (suite record).
4. **Student plays** → reads due rows from **`dictation_assignments`** + **`lexemes`**; grades write **`dictation_attempts`** and update the assignment row.

---

## 5. Code map

| Area | Module |
|------|--------|
| Lexeme + dictation queue queries | `app/apps/dictation/dictation_lexemes.py` |
| SQLite profile + async Ollama draft/commit | `app/apps/dictation/session_words.py` |
| Dictation HTTP: dictionary | `app/apps/dictation/routers/dictionary.py` (uses `get_core_pg_session`) |
| Dictation HTTP: study | `app/apps/dictation/routers/study.py` |
| Progress API | `app/apps/dictation/routers/users.py` (`/users/{id}/progress` → Postgres) |
| Dictation Ollama env | `app/apps/dictation/ollama_settings.py` |
| ORM models | `app/core/models.py` |
| FastAPI Postgres session dep | `app/core/deps.py` |
| Platform admin UI (students, AI words, progress chart, dictionary) | `app/static/admin/index.html` |
| Root app: admin routes, portal, lifespan | `app/main.py` |

---

## 6. Bulk import (school spelling lists → `lexemes`)

`scripts/import_school_spelling_words.py` reads a CSV (`word`, `difficulty_level`, `definition`), then for each word:

- Fetches phonetics from **api.dictionaryapi.dev** (CC BY-SA 3.0)
- Scrapes an **Etymology** blurb from **English Wiktionary** when the section exists
- Writes **`extensions`** with `pronunciation`, `etymology`, `spelling_tricks`, and notes

Run inside Docker (sync URL uses the `postgres` service name):

```bash
docker compose exec app sh -c \
  'export DATABASE_URL_SYNC=postgresql://homeschool:homeschool@postgres:5432/homeschool && \
   python scripts/import_school_spelling_words.py --csv app/apps/dictation/resources/words/spellingListtwobee.csv'
```

Bundled CSVs are **study-style** vocabulary lists, not a substitute for official Scripps materials.

---

## 7. Maintenance

- **Schema changes:** new Alembic revision; update this doc and `models.py`.
- **Backups:** Postgres volume + `dictation-data` (SQLite) for profile ids.
- **Migrating old SQLite `words`:** one-off script: read old DB → `INSERT`/`upsert` into `core.lexemes` and rebuild `dictation_assignments` from old `user_words` if you still have a legacy file.

**Last reviewed:** platform admin dictionary tab (full lexeme summaries, no CSV in UI); see [ARCHITECTURE.md](./ARCHITECTURE.md) for URL map and simplification notes.
