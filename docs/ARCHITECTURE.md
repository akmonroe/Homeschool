# Homeschool architecture

How the FastAPI monorepo is wired, where each UI lives, and how data flows between Postgres, SQLite, and external services.

---

## 1. Process model

A **single** FastAPI application (`app/main.py`) owns:

- **Root routes:** portal (`/`), health, generic `/ai/generate` and `/tts`, platform admin (`/admin/…`)
- **Mounted sub-app:** dictation at **`/apps/dictation`** (same Python process; paths are prefixed automatically)

**Lifespan:** `setup_dictation()` runs at startup (SQLite init, Coqui VITS load). Postgres engine is disposed on shutdown when configured.

---

## 2. URLs (local default: port 4500)

| URL | Purpose |
|-----|---------|
| `/` | Landing page (`app/static/index.html`) |
| `/docs` | OpenAPI for the **root** app only |
| `/admin/`, `/admin` | Platform admin (`app/static/admin/index.html`). Hash tabs: `#students`, `#assignments`, `#spelling`, `#dictation-progress`, `#dictation-audio`, `#dictionary` |
| `/apps/dictation/ui/` | Student dictation (static + game) |
| `/apps/dictation/ui/review.html` | Read-only dictionary browse |
| `/apps/dictation/ui/admin.html` | Redirects to `/admin/` |
| `/apps/dictation/docs` | Dictation sub-app OpenAPI |

**API prefixes**

- **`/core/*`** — shared Postgres domain (students, suite assignments with **`available_from`** / **`due_at`**, grades with **`completed_at`** / **`graded_at`**, dictation session draft/commit)
- **`/apps/dictation/*`** — dictation REST (users, words, study, generate, audio, TTS settings)

### AI spelling draft (`POST /core/students/{id}/dictation-session/draft`)

- **`target_daily_words`** in the request body is the **count of new words to ask for** (1–50), not “top up the queue to a total.”
- Suggestions are **only from `core.lexemes`** the student is **not** already assigned (unassigned pool). Ollama may pick from a prompt list if the pool is large; otherwise the server picks by weighted **difficulty** near the student’s skill. Response includes **`pool_size`** (unassigned count).
- Response **`due_count`** is how many words are **already in the practice backlog** (`next_review_date <= today`); it is **informational** and does not reduce the batch size (older code incorrectly used `target - due_count` and could request zero new words when backlog was large).

### AI spelling commit (`POST /core/students/{id}/dictation-session/commit`)

- Every word must **already exist** in `core.lexemes` (import / Dictionary). The server no longer creates new dictionary rows on commit; invalid words return **400** with a list of missing surface forms.

### Dictation queue vs suite assignment (two related tables)

- The **dictation app**’s “words due” count and practice flow use **`core.dictation_assignments`** (the per-student **practice queue** joined to `core.lexemes`).  
- The **admin Assignments** tab lists **`core.assignments`** and **`core.assignment_items`**, which is the **suite** assignment record (used for due dates, listing words in the UI, and grades).  
- **Normal path:** A successful `dictation-session/commit` writes **both** the queue rows and one suite `Assignment` (plus `items`).  
- **If you see students with words in dictation but nothing under Assignments:** the queue and suite layer can **drift** (e.g. data from before suite assignments, partial failures, or only queue writes). **Repair:** `POST /core/students/{id}/dictation-session/sync-assignment` — creates or **replaces** one `dictation` **suite** assignment `items` from the **entire** current practice queue, default **due** 7 days ahead (or pass **`due_at`** in JSON). The platform admin’s Assignments tab has a **“Sync dictation → assignment”** button that calls this.

### Dictation practice audio (`POST /apps/dictation/generate`)

| Field / behavior | Notes |
|------------------|--------|
| Request body | `word` (string, surface form for TTS), `regenerate` (bool, default **false**) |
| Ollama | Runs only when there is no cache for this word or `regenerate` is **true**; request uses a **system** message (single-sentence dictation) + lower **temperature**; one retry with `temperature: 0.25` if the first output cannot be cleaned. The response is **cleaned** (first line, strip “Sure!…”, one sentence) and **rejected** if the target word does not appear. |
| Response | `sentence`, `audio_url`, `word_audio_url`, `revision` (int), `from_cache` (bool) |
| On-disk WAVs | Fixed paths under `DICTATION_DATA_DIR` (default `/app/data`): sentence + word-only clips; volume **`dictation-data`** |
| TTS | **Env** (`DICTATION_TTS_SPEAKER`, `DICTATION_TTS_PLAYBACK_TEMPO`, `DICTATION_TTS_WORD_PLAYBACK_TEMPO`) or **in-memory overrides** from admin: `GET/PUT /apps/dictation/tts-settings`, list speakers `GET /apps/dictation/tts-voices` (VCTK ids). **Preview** without touching practice audio: `POST /apps/dictation/tts-preview` then `GET /apps/dictation/audio/tts-preview`. Overrides last until container restart. |

Implementation: `app/apps/dictation/dictation_app.py` (cache + routes + Ollama), tempo in `app/apps/dictation/dictation_tts.py`, runtime overrides in `app/apps/dictation/dictation_tts_settings.py`, Ollama URL/model in `ollama_settings.py`.

**Concurrency note:** the generate cache is **in-process and keyed by normalized word**; the two WAV files are global for the app. That is fine for a single family on one container; a future hardening step is per-session or per-student file names (or no shared mutating files).

---

## 3. Data stores

| Store | Technology | Contents |
|-------|------------|----------|
| **Core** | PostgreSQL, schema `core` | Students, lexemes, dictation queue/attempts, suite assignments/grades/skills |
| **Dictation profiles** | SQLite file on volume `dictation-data` | `users` only: display name, skill text, `core_student_id` |

Details: [DATABASE.md](./DATABASE.md).

---

## 4. Admin surfaces (one place to operate)

**Platform admin** (`/admin/`) is the primary operator UI:

1. **Students** — `POST/PATCH /core/students`; syncs dictation SQLite profile.
2. **Spelling words (AI)** — `POST /core/students/{id}/dictation-session/draft|commit`.
2b. **Assignments (suite)** — `GET /core/students/{id}/assignments`; if dictation shows words but Assignments is empty, **`POST /core/students/{id}/dictation-session/sync-assignment`** (or **“Sync dictation → assignment”** in the admin UI) mirrors the practice queue to `core.assignments` + items.
3. **Dictation progress** — `GET /apps/dictation/users`, `GET .../users/{id}/progress` (Chart.js).
4. **Dictation audio** — TTS voice and playback speed: `GET/PUT /apps/dictation/tts-settings` (in-memory overrides; reset to env in UI).
5. **Dictionary** — `GET/PUT /apps/dictation/words` (UI shows full lexeme summaries; optional script/API: `POST .../words/bulk-upload`).

Bulk enrichment (etymology, phonetics, tricks) is **not** in the browser; use `scripts/import_school_spelling_words.py` (see README and DATABASE.md).

---

## 5. External services

| Service | Used by | Configuration |
|---------|---------|----------------|
| **Ollama** | Root `/ai/generate`, dictation sentence generation, grading feedback, AI word draft in `session_words` | `OLLAMA_BASE_URL` (default host Docker gateway `:11434`), `DEFAULT_OLLAMA_MODEL`, `DICTATION_OLLAMA_MODEL` |
| **Coqui TTS (VITS)** | Dictation `/generate`, word/sentence WAV | VCTK multi-speaker; `split_sentences=false`; ffmpeg `atempo` slows playback (`DICTATION_TTS_PLAYBACK_TEMPO`). Same target word reuses one sentence + WAV until the next word. |
| **Dictionary API / Wiktionary** | Import script only | No runtime dependency |

---

## 6. Docker

- **`docker-compose.yml`:** `postgres` + `app`; optional `ollama` profile.
- **`docker/entrypoint.sh`:** Alembic `upgrade head`, then uvicorn.
- **Volumes:** `postgres-data`, `dictation-data` (SQLite + TTS temp WAV paths under `/app/data`).

Rebuild after changing Python or copied static files:

```bash
docker compose build app && docker compose up -d
```

### Environment variables (dictation-related)

| Variable | Purpose | Default |
|----------|---------|---------|
| `OLLAMA_BASE_URL` | Host for Ollama (`/api/generate`) | `http://host.docker.internal:11434` |
| `OLLAMA_GENERATE_URL` | Full generate URL override | `{OLLAMA_BASE_URL}/api/generate` |
| `DICTATION_OLLAMA_MODEL` | Model name for dictation prompts | `gemma4:e4b` |
| `DICTATION_DATA_DIR` | WAV output directory | `/app/data` |
| `DICTATION_TTS_SPEAKER` | VCTK speaker id for VITS | `p225` |
| `DICTATION_TTS_PLAYBACK_TEMPO` | ffmpeg slowdown factor (lower = slower) | `0.58` |
| `DICTATION_TTS_WORD_PLAYBACK_TEMPO` | Optional; word-only clip | derived from sentence tempo |

Compose passes the `DICTATION_TTS_*` vars in `docker-compose.yml`; override locally as needed.

---

## 7. Refactoring backlog (recommended order)

These are **code health** improvements; none block shipping unless you need multi-tenant isolation.

1. ~~**Centralize Ollama settings for dictation**~~ — Done: `app/apps/dictation/ollama_settings.py`.

2. ~~**Unify Postgres session dependencies**~~ — Done: `app/core/router.py` uses `get_core_pg_session` from `app/core/deps.py`.

3. ~~**Remove dead code**~~ — Removed `app/apps/dictation/routers/routes_OLD.py`.

4. **Replace sync `requests` with `httpx` in async routes**  
   `study.py` uses blocking `requests.post` inside `async def`. Prefer `httpx.AsyncClient` or `asyncio.to_thread` so the event loop stays responsive under load. Optional: same for `session_words.py` / `dictation_app.py` if those paths grow.

5. **Extract dictation “generate” orchestration**  
   Move sentence cache, lock, Ollama call, VITS + ffmpeg pipeline from `dictation_app.py` into e.g. `dictation_generate.py` or `dictation_service.py` so the FastAPI route stays thin and is easier to test.

6. **Safer audio file naming for concurrent users**  
   Today two fixed WAV paths serve the last generated clip. For multiple simultaneous students, use unique filenames (UUID / session id) or stream bytes from memory; optionally key the in-memory cache by `(word, student_id)` if sentence-per-student matters.

7. **Optional: split admin front-end**  
   Move JS from `app/static/admin/index.html` to `app/static/admin/admin.js` (Chart.js + four tabs).

8. **Optional: consolidate duplicate env documentation**  
   Keep `docker-compose.yml` as source of truth for optional env vars; README/ARCHITECTURE link to it to reduce drift.

---

**Last reviewed:** dictation TTS (`dictation_tts.py`, ffmpeg tempo, generate cache + `regenerate` / `revision`), platform admin dictionary summaries.
