# syntax=docker/dockerfile:1

###############################################################################
# Backend – dependency + aeneas builder
###############################################################################
FROM python:3.12-alpine AS backend-builder

RUN apk add --no-cache \
    gcc musl-dev libffi-dev openssl-dev \
    ffmpeg espeak espeak-dev curl

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY scripts/ ./scripts/

ENV PATH="/app/.venv/bin:$PATH"

RUN uv pip install setuptools

# Install aeneas 1.7.3.0 with patches for numpy 2.x / Python 3.12+
RUN set -e && \
    curl -sL "https://files.pythonhosted.org/packages/source/a/aeneas/aeneas-1.7.3.0.tar.gz" \
        | tar xz -C /tmp && \
    python scripts/patch_aeneas_setup.py /tmp/aeneas-1.7.3.0/setup.py && \
    AENEAS_WITH_CEW=False uv pip install --no-build-isolation /tmp/aeneas-1.7.3.0 && \
    WAVFILE=$(python -c "import aeneas.wavfile as m, inspect, pathlib; print(pathlib.Path(inspect.getfile(m)))") && \
    python scripts/patch_aeneas_wavfile.py "$WAVFILE"

COPY src/earmark ./src/earmark
RUN uv pip install --no-deps .

###############################################################################
# Backend – runtime image
###############################################################################
FROM python:3.12-alpine AS backend

RUN apk add --no-cache ffmpeg espeak

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
