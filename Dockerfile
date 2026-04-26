# Coqui TTS is not published for Python 3.12; match dictation_app baseline.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COQUI_TOS_AGREED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libsndfile1 \
        espeak-ng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install CPU PyTorch first (avoids multi‑GB CUDA wheels), then Coqui TTS stack.
RUN pip install --no-cache-dir --default-timeout=1000 \
        torch==2.2.2+cpu torchaudio==2.2.2+cpu \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

COPY alembic.ini alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 4500

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4500"]
