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
| `/admin/`, `/admin` | Platform admin (`app/static/admin/index.html`). Hash tabs: `#students`, `#spelling`, `#dictation-progress`, `#dictionary` |
| `/apps/dictation/ui/` | Student dictation (static + game) |
| `/apps/dictation/ui/review.html` | Read-only dictionary browse |
| `/apps/dictation/ui/admin.html` | Redirects to `/admin/` |
| `/apps/dictation/docs` | Dictation sub-app OpenAPI |

**API prefixes**

- **`/core/*`** — shared Postgres domain (students, suite assignments, dictation session draft/commit)
- **`/apps/dictation/*`** — dictation REST (users, words, study, generate, audio)

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
3. **Dictation progress** — `GET /apps/dictation/users`, `GET .../users/{id}/progress` (Chart.js).
4. **Dictionary** — `GET/PUT /apps/dictation/words` (UI shows full lexeme summaries; optional script/API: `POST .../words/bulk-upload`).

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

---

## 7. Simplification opportunities (recommended order)

These are **code health** suggestions; none block shipping.

1. ~~**Centralize Ollama settings for dictation**~~ — Done: `app/apps/dictation/ollama_settings.py`.

2. ~~**Unify Postgres session dependencies**~~ — Done: `app/core/router.py` uses `get_core_pg_session` from `app/core/deps.py`.

3. ~~**Remove dead code**~~ — Removed `app/apps/dictation/routers/routes_OLD.py`.

4. **Replace sync `requests` with `httpx` in async routes**  
   `study.py` (and any similar) uses blocking `requests.post` inside `async def`. Use `httpx.AsyncClient` or `run_in_executor` so event loop latency stays predictable under load.

5. **Optional: split admin front-end**  
   `app/static/admin/index.html` is large (tabs + Chart.js + three API surfaces). For maintainability you could move JS to `app/static/admin/admin.js` and keep HTML as shell only—no behavior change.

6. **Optional: service layer for dictation**  
   `dictation_lexemes.py` is already the data access layer; consider a thin `dictation_service.py` that owns “generate sentence + TTS files” so `dictation_app.py` routes stay small.

---

**Last reviewed:** dictation `ollama_settings.py`, unified `get_core_pg_session`, removal of `routes_OLD.py`.
