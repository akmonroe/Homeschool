# Homeschool
Repository for AI-enabled homeschooling apps. This monorepo-style layout will
grow with multiple apps; the first integrated app will be **Dictation**.

## Web portal

After you start the stack, open **http://localhost:4500/** for a landing page
that links to each app and to the shared API documentation (`/docs`).

- **Dictation** — `/apps/dictation` (placeholder until the dictation app is merged)

## Base development stack

This repository provides a Docker Compose foundation for Python FastAPI
homeschooling apps with Ollama-backed AI and local text-to-speech support.

### Services

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
