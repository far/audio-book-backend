FROM python:3.13-slim

# ffmpeg is required for Opus transcoding (app/infrastructure/tts/encoding.py).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app/ ./app/

# The Piper voice model is not baked into the image (gitignored, ~60MB) --
# mount it or download it at container start. See README.md.
VOLUME ["/app/voices", "/app/tmp"]

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
