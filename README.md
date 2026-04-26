# Homeschool
Repository for homeschooling apps

## Base development stack

This repository provides a Docker Compose foundation for Python FastAPI
homeschooling apps with Ollama-backed AI and local text-to-speech support.

### Services

- `app`: FastAPI app exposed at `http://localhost:4500`
- `ollama`: Ollama server exposed inside the Docker network as
  `http://ollama:11434`

### Run locally

```bash
docker compose up --build
```

The API is available at:

- `GET /health` - service and Ollama connectivity status
- `POST /ai/generate` - forwards a prompt to Ollama
- `POST /tts` - returns a WAV file generated from text

Override the default Ollama model with:

```bash
DEFAULT_OLLAMA_MODEL=llama3.2 docker compose up --build
```
