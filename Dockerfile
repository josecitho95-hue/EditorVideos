# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AutoEdit AI — Dockerfile                                                   ║
# ║                                                                              ║
# ║  Base : CUDA 12.8 + cuDNN 9 (matches PyTorch cu128 wheels)                 ║
# ║  GPU  : NVENC for render, CUDA for Whisper / CLIP / F5-TTS inference        ║
# ║  Models are NOT bundled — mount ./data as a volume and run                  ║
# ║    docker compose run --rm download-models  (once, on first setup)          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ─── Stage 1 · base ───────────────────────────────────────────────────────────
# System packages + uv + Python 3.12 managed by uv.
# This layer changes only when system-level packages change.
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04 AS base

ARG DEBIAN_FRONTEND=noninteractive

# FFmpeg from the Ubuntu repo includes NVENC/NVDEC support (pre-built with
# --enable-nvenc; the encoder calls into the driver at runtime via NVAPI,
# no additional headers needed).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      curl \
      ca-certificates \
      libsndfile1 \
      libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Pin uv version for reproducible builds.
# The binary is copied straight from the official minimal image.
COPY --from=ghcr.io/astral-sh/uv:0.7.8 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # uv stores its own Python under UV_PYTHON_INSTALL_DIR.
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    # uv installs packages into a plain venv (not the project venv).
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    # Copy mode avoids hard-link issues across overlay FS layers.
    UV_LINK_MODE=copy \
    # Never fall back to the system Python.
    UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

# Install Python 3.12 — stored in UV_PYTHON_INSTALL_DIR, reused by all stages.
RUN uv python install 3.12


# ─── Stage 2 · builder ────────────────────────────────────────────────────────
# Install ALL Python dependencies (includes PyTorch ~4 GB from cu128 index).
# This layer is cached as long as pyproject.toml + uv.lock don't change,
# so iterating on source code doesn't re-download multi-GB wheels.
FROM base AS builder

# Copy only the dependency manifest — not the source.
COPY pyproject.toml uv.lock ./

# --no-install-project : skip installing the autoedit package itself (src/ not
#                        copied yet); only third-party deps go in here.
# --frozen             : honour uv.lock exactly — no network resolution.
# BuildKit cache mount : wheel cache is kept between builds on the same host.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


# ─── Stage 3 · runtime ────────────────────────────────────────────────────────
# Thin final image: reuse the base (no build tools) and layer the venv on top.
FROM base AS runtime

# Pull the fully-populated venv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Application source — copied after deps so this (frequently-changing) layer
# doesn't invalidate the expensive deps layer above.
COPY pyproject.toml uv.lock ./
# README.md is required by hatchling (pyproject.toml: readme = "README.md").
# Without it, `uv sync` fails with OSError at build time.
COPY README.md ./
COPY src/ ./src/
COPY infra/ ./infra/

# Install only the autoedit package itself (deps already present in /opt/venv).
# This is fast: just copies src/ into the venv as an editable install.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY infra/entrypoint.sh /entrypoint.sh
# Strip Windows CRLF line endings (file may be created on Windows) and make executable.
RUN sed -i 's/\r//' /entrypoint.sh && chmod +x /entrypoint.sh

# Make venv binaries (autoedit, ffmpeg wrappers, etc.) available without prefix.
ENV PATH="/opt/venv/bin:$PATH"

# Runtime environment defaults — all overridable via .env / compose env_file.
ENV DATA_DIR=/app/data \
    REDIS_URL=redis://redis:6379/0 \
    QDRANT_URL=http://qdrant:6333 \
    FFMPEG_BIN=ffmpeg \
    GPU_VRAM_BUDGET_MB=7000

# Declare the data volume mount point (SQLite DB, model weights, VODs, outputs).
VOLUME ["/app/data"]

EXPOSE 7880

ENTRYPOINT ["/entrypoint.sh"]
# Default: show help — overridden by compose services.
CMD ["autoedit", "--help"]
