# syntax=docker/dockerfile:1

###############################################################################
# Backend – dependency builder (WhisperX alignment engine)
###############################################################################
# WhisperX requires Python ≤3.13 (PyTorch wheel matrix). The 'align' extra
# pulls in torch + faster-whisper + the wav2vec2 alignment models on first use.
FROM python:3.13-slim AS backend-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libffi-dev libssl-dev ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

# Install alignment extra (WhisperX + torch). Skip if you'll never run alignment.
RUN uv pip install -e ".[align]"

COPY src/earmark ./src/earmark
RUN uv pip install --no-deps .

###############################################################################
# Backend – runtime image
###############################################################################
FROM python:3.13-slim AS backend

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=backend-builder /app/.venv ./.venv
COPY --from=backend-builder /app/src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/data

EXPOSE 7700
CMD ["uvicorn", "earmark.main:app", "--host", "0.0.0.0", "--port", "7700"]

###############################################################################
# Frontend – build
###############################################################################
FROM node:22-alpine AS frontend-builder

WORKDIR /app

COPY src/frontend/package*.json ./
RUN npm ci

COPY src/frontend ./

RUN npm run build

###############################################################################
# Frontend – runtime image
###############################################################################
FROM node:22-alpine AS frontend

WORKDIR /app

COPY --from=frontend-builder /app/build ./build
COPY --from=frontend-builder /app/package*.json ./
RUN npm ci --omit=dev

ENV NODE_ENV=production

EXPOSE 3000
CMD ["node", "build/index.js"]
