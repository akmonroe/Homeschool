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
- **`0003_assignment_schedule`:** `available_from`, due indexes, grade timestamps.
- **`0004_science_experiments`:** `science_experiment_templates`, `science_experiment_runs`, `science_media` (and seed template rows).

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

### 2.5 `core.assignments` — suite-level work (scheduling + due dates)

| Column | Type | Notes |
|--------|------|--------|
| `available_from` | `TIMESTAMPTZ` nullable | First instant the assignment “opens”. Null = no start restriction. |
| `due_at` | `TIMESTAMPTZ` nullable | Deadline. Null = no fixed due date. Indexed for queries. |

Use **`GET /core/students/{id}/assignments?active=true`** for rows whose window contains “now” (`available_from` passed or null, and `due_at` not passed or null).

Dictation AI commits create an **`assignments`** row with **`available_from`** set to “now” and **`due_at`** seven days later by default (adjust via **`PATCH`**).

**Delete:** `DELETE /core/students/{id}/assignments/{assignment_id}` removes the assignment; **`assignment_items`** cascade; **`grades.assignment_id`** and **`skill_observations.context_assignment_id`** are set to **NULL** (grade rows remain).

### 2.6 `core.grades` — scores linked to assignments

**FK:** `assignment_id` → `core.assignments.id` (nullable). One assignment may have multiple grades over time (regrades); use **`graded_at`** / metadata if you need uniqueness rules in application logic.

| Column | Type | Notes |
|--------|------|--------|
| `completed_at` | `TIMESTAMPTZ` nullable | When the learner finished/submitted the work. |
| `graded_at` | `TIMESTAMPTZ` nullable | When the grade was recorded; **`POST /grades`** defaults this to “now” if omitted. |
| `score_numeric`, `score_max`, `letter`, … | | Existing score fields. |

### 2.7 Other `core` tables

See `app/core/models.py` and migrations for **`assignment_items`**, **`skill_observations`**, etc.

### 2.8 Science app — `science_experiment_templates`, `science_experiment_runs`, `science_media`

- **`science_experiment_templates`:** optional library of published experiments (title, summary, `subject_tags` JSON array, `procedure_outline`). Seeded with two examples in migration `0004`.
- **`science_experiment_runs`:** one student’s lab write-up. **`source`** is `assigned` (linked to **`core.assignments`** with **`app_slug` = `science`**) or `self_chosen` (from a template) or `ad_hoc`. **`observations`** is a JSONB array of `{ "at", "text" }` (and can hold richer objects later). Optional **`assignment_id`**, **`template_id`**.
- **`science_media`:** metadata for a file on disk: **`rel_path`** relative to **`SCIENCE_DATA_DIR`**, **`kind`** `image` or `video`. Bytes are **not** stored in Postgres.

The Science UI lists assignments where **`app_slug` = `science`**. Create those via the core assignments API or admin.

Suite-level **assignments** (above) remain separate from **`dictation_assignments`** (per-word queue for the dictation game).

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

Dictation **practice sentence audio** is **not** stored in Postgres or SQLite; it is generated on demand (Ollama + Coqui VITS + optional ffmpeg tempo) and written to WAV files on the `dictation-data` volume. Lexeme text and hints for study still come from **`core.lexemes`**.

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
| Dictation TTS post-process (tempo, speaker env) | `app/apps/dictation/dictation_tts.py` |
| Dictation sub-app: generate, audio, static, VITS startup | `app/apps/dictation/dictation_app.py` |
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

### 6.1 Oxford 3000/5000–style list (open CSV + enrichment)

`scripts/import_oxford_5000.py` loads words from the community dataset [nalgeon/words `data/oxford-5k.csv`](https://github.com/nalgeon/words/blob/main/data/oxford-5k.csv) (CEFR band, part of speech, links to **Oxford Learner's Dictionaries** definition and audio URLs). **This is not an official OUP machine export;** align list membership with your own Oxford materials if required. The script merges duplicate headwords, stores CEFR and OALD links under `extensions`, and runs the same **dictionaryapi.dev** + **Wiktionary** enrichment as the school import. Full run can take **many hours** (rate-limited sleeps); use `--limit` for testing.

```bash
docker compose exec app sh -c \
  'export DATABASE_URL_SYNC=postgresql://homeschool:homeschool@postgres:5432/homeschool && \
   python scripts/import_oxford_5000.py --limit 100'
```

---

## 7. Maintenance

- **Schema changes:** new Alembic revision; update this doc and `models.py`.
- **Backups:** Postgres volume + `dictation-data` (SQLite) for profile ids.
- **Migrating old SQLite `words`:** one-off script: read old DB → `INSERT`/`upsert` into `core.lexemes` and rebuild `dictation_assignments` from old `user_words` if you still have a legacy file.

**Last reviewed:** migration **`0003_assignment_schedule`** (`available_from`, grade **`completed_at`** / **`graded_at`**); see [ARCHITECTURE.md](./ARCHITECTURE.md).
