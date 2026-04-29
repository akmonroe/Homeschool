# Homeschool
Repository for AI-enabled homeschooling apps. This monorepo-style layout will
grow with multiple apps; the first integrated app will be **Dictation**.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/DATABASE.md](docs/DATABASE.md) | Postgres `core` vs SQLite dictation, tables, bulk import, code map |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | URLs, dictation generate/TTS, env vars, Docker, refactoring backlog |

## Web portal

After you start the stack, open **http://localhost:4500/** for a landing page
that links to each app and to the shared API documentation (`/docs`).

- **Platform admin** (students, **Assignments** by student and subject, AI word planner, dictation
  progress chart, master dictionary summaries + level/definition edit) — **`http://localhost:4500/admin/`**
  (or **`http://localhost:4500/admin`** — redirects to the trailing slash). Deep links: `#students`,
  `#assignments`, `#spelling`, `#dictation-progress`, `#dictation-audio`, `#dictionary`. Served from `app/static/admin/index.html`. Requires Postgres: if the page loads
  but API calls fail, check **`DATABASE_URL`** and `docker compose ps` (Postgres must be healthy).
- **Legacy URL** `/apps/dictation/ui/admin.html` redirects to **`/admin/`**.
- **Dictation** — student UI at **http://localhost:4500/apps/dictation/ui/**. REST API under **`/apps/dictation`**;
  OpenAPI: **`/apps/dictation/docs`**. SQLite and generated audio persist in the
  **`dictation-data`** Docker volume (`/app/data` in the container).

  Dictation uses **`DICTATION_OLLAMA_MODEL`** (default `gemma4:e4b`) for
  **`POST /apps/dictation/generate`** (sentence text via Ollama). On first start, **uvicorn waits**
  while Coqui downloads the VITS weights into the container; HTTP may reset
  until you see `Application startup complete` in the logs.

  **TTS (VITS + ffmpeg):** `DICTATION_TTS_SPEAKER` (VCTK id, default `p225`), `DICTATION_TTS_PLAYBACK_TEMPO`
  (default `0.58` — lower is slower/clearer), optional `DICTATION_TTS_WORD_PLAYBACK_TEMPO`. Speech is synthesized as one clip (`split_sentences=false`), then slowed with ffmpeg `atempo` (falls back to raw VITS if ffmpeg fails).

  **`POST /apps/dictation/generate`** accepts JSON `{ "word": "<surface form>", "regenerate": false }`. With **`regenerate: false`** (student UI default), the server **reuses** the last sentence and WAV files for that spelling word until practice moves on — so “Listen to Sentence” does not call Ollama again. Response includes **`revision`** (increment when a new sentence is synthesized), **`from_cache`**, plus **`sentence`**, **`audio_url`**, **`word_audio_url`**.

## Core platform (PostgreSQL)

Compose starts **Postgres 16** and sets **`DATABASE_URL`** for the app. On boot,
**Alembic** runs `upgrade head` (see `docker/entrypoint.sh`) so the **`core`**
schema is always present.

- **Schema `core`**: shared across apps — students, projects, assignments
  (with **assignment_items** for tall/step payloads), **grades**, and
  **skill_observations** (time-series skill signals for humans or AI).
- **HTTP API**: under **`/core`** (see **`/docs`**). Examples:
  - `GET /core/students`, `POST /core/students`
  - `GET /core/students/{id}/assignments` — each assignment may include **`items`** (tall `assignment_items`, e.g. `spelling_word` + `payload_json.word` for dictation)
  - `POST .../assignments/{id}/items` — agent-friendly steps (`item_type` +
    `payload_json`)
  - `GET/POST .../grades`, `PATCH .../grades/{grade_id}`, `GET/POST .../skills`
  - **`POST .../dictation-session/commit`** assigns spelling words from admin; optional JSON **`due_at`** (omit for **7 days from commit**). Response echoes the effective **`due_at`**.
  - **`POST .../dictation-session/sync-assignment`** (optional **`due_at`**, optional **`title`**) creates or updates a single **`dictation`** suite assignment and **`items`**, listing **all** words currently in that student’s **`core.dictation_assignments`** practice queue. Use this when the dictation app shows words but **Assignments** is empty (or out of date).
  - Assignments support **`available_from`**, **`due_at`**, and `GET .../assignments?active=true`; **`PATCH .../assignments/{id}`** updates schedule fields; **`DELETE .../assignments/{id}`** removes the row (items cascade; grades’ `assignment_id` is set null).

Use **`metadata`** JSON on rows for extensibility; use **`rubric_json`** /
**`rubric_scores_json`** for structured AI or human scoring later.

**Migrations** (from repo root, with sync driver for Alembic):

```bash
export DATABASE_URL=postgresql+psycopg://homeschool:homeschool@localhost:5432/homeschool
alembic upgrade head
```

(App runtime uses **`postgresql+asyncpg://`** in `DATABASE_URL` inside Docker.)

### Words and dictionary

- **Operator UI:** `/admin/` → **Dictionary** tab — per-word summary and **editable** display form, definition, level, and **full `extensions` JSON** (merged on save into Postgres `core.lexemes`). Bulk CSV remains available via **`POST /apps/dictation/words/bulk-upload`** for scripts if needed.
- **Browse / verify:** `/apps/dictation/ui/review.html` — paginated list including `extensions` (pronunciation, etymology, spelling tips) when populated.
- **Oxford 3000/5000–style import (CLI):** `scripts/import_oxford_5000.py` reads the open [nalgeon/words `oxford-5k.csv`](https://github.com/nalgeon/words/blob/main/data/oxford-5k.csv) (CEFR, part of speech, Oxford Learner's links) and enriches each headword with **api.dictionaryapi.dev** + **Wiktionary** (same pipeline as the school list). **Rebuild the app image** after pulling new scripts, then run (full import is slow and network-heavy; use `--limit` to test):

```bash
docker compose build app && docker compose up -d
docker compose exec app sh -c \
  'export DATABASE_URL_SYNC=postgresql://homeschool:homeschool@postgres:5432/homeschool && \
   python scripts/import_oxford_5000.py --limit 50'
```

- **Other rich import (CLI):** `scripts/import_school_spelling_words.py` — merges API + Wiktionary data into `extensions`. Example with Compose:

```bash
docker compose exec app sh -c \
  'export DATABASE_URL_SYNC=postgresql://homeschool:homeschool@postgres:5432/homeschool && \
   python scripts/import_school_spelling_words.py --csv app/apps/dictation/resources/words/spellingListtwobee.csv'
```

See [docs/DATABASE.md](docs/DATABASE.md) for schema detail and licensing notes on external word lists.

## Base development stack

This repository provides a Docker Compose foundation for Python FastAPI
homeschooling apps with Ollama-backed AI and local text-to-speech support.

### Services

- `postgres`: PostgreSQL for the shared **`core`** schema (port **5432**)
- `app`: FastAPI app exposed at `http://localhost:4500`
- `ollama` (optional): not started by default so Docker does not pull the large
  Ollama image unless you ask for it. When enabled, set
  `OLLAMA_BASE_URL=http://ollama:11434` (or rely on the in-network hostname
  `ollama` if you only use the profile and remove the host override).

### Run locally (app + host Ollama on port 11434)

By default the app container uses **`http://host.docker.internal:11434`**, with
`extra_hosts: host.docker.internal:host-gateway`, so **Ollama on the host**
(listening on `11434`, as with dictation_app’s `network_mode: host` setup) is
used without starting Ollama in Compose:

```bash
docker compose up --build
```

After **code or static file** changes, rebuild the `app` image so the container picks them up (the app source is copied at build time, not bind-mounted):

```bash
docker compose build app && docker compose up -d
```

To **instead** run Ollama in Docker (pulls `ollama/ollama` the first time), use
the profile and point at the compose service:

```bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile ollama up --build
```

The API is available at:

- `GET /` — app portal (landing page)
- `GET /health` - service and Ollama connectivity status
- `POST /ai/generate` - forwards a prompt to Ollama
- `POST /tts` - returns a WAV file generated from text

Override the default Ollama model with:

```bash
DEFAULT_OLLAMA_MODEL=llama3.2 docker compose up --build
```
