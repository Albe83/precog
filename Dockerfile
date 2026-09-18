# syntax=docker/dockerfile:1

# Precog API image (CPU-only) with TimesFM-3 weights baked in.
#
# The image is meant to be built and run locally. It is NOT published: the
# baked weights are under the TimesFM Non-Commercial License v1.0.
#
# Normal build:
#   podman build -t precog-api:local .
#
# Behind a TLS-inspecting proxy, inject the corporate CA:
#   podman build --build-arg CA_CERT="$(cat /path/to/corp-root.crt)" -t precog-api:local .

ARG PYTHON_VERSION=3.12
ARG PRECOG_MODEL_ID=google/timesfm-3.0-pytorch
ARG PRECOG_MODEL_REVISION=43046b85ec22d584a13f8098c2ed39c889e129c2

# ---------------------------------------------------------------------------
# Builder: install dependencies and download the model weights.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG PRECOG_MODEL_ID
ARG PRECOG_MODEL_REVISION
ARG CA_CERT=""

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN if [ -n "$CA_CERT" ]; then \
        printf '%s\n' "$CA_CERT" > /usr/local/share/ca-certificates/corp-root.crt \
        && update-ca-certificates; \
    fi

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY packages/schemas ./packages/schemas
COPY apps/api ./apps/api

# torch CPU wheels come from the PyTorch index; timesfm pulls the rest.
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install "timesfm>=3.0.2" \
    && pip install ./packages/schemas ./apps/api

# httpx (used by huggingface_hub) trusts certifi, not the OS store. When a
# corporate CA was injected, mirror the OS bundle into certifi.
RUN if [ -n "$CA_CERT" ]; then \
        cat /etc/ssl/certs/ca-certificates.crt >> "$(python -c 'import certifi; print(certifi.where())')"; \
    fi

# Bake the weights into the image (Hugging Face hub cache layout).
RUN python -c "from huggingface_hub import snapshot_download as d; d('${PRECOG_MODEL_ID}', revision='${PRECOG_MODEL_REVISION}', cache_dir='/opt/precog/hf')"

# ---------------------------------------------------------------------------
# Runtime: minimal image, non-root, offline.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG PRECOG_MODEL_ID
ARG PRECOG_MODEL_REVISION

LABEL org.opencontainers.image.title="precog-api" \
      org.opencontainers.image.description="TimesFM-3 zero-shot forecasting REST API (CPU)." \
      org.opencontainers.image.source="https://github.com/Albe83/precog" \
      org.opencontainers.image.licenses="MIT AND LicenseRef-TimesFM-NonCommercial-1.0"

RUN useradd --create-home --uid 10001 precog

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/precog /opt/precog
COPY THIRD_PARTY_NOTICES.md LICENSE /opt/precog/

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PRECOG_ENGINE=timesfm3 \
    PRECOG_DEVICE=cpu \
    PRECOG_MODEL_ID=${PRECOG_MODEL_ID} \
    PRECOG_MODEL_REVISION=${PRECOG_MODEL_REVISION} \
    PRECOG_MODEL_PATH=/opt/precog/models \
    PRECOG_CACHE_DIR=/opt/precog/hf \
    PRECOG_LOCAL_FILES_ONLY=true \
    HF_HUB_OFFLINE=1

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz').status==200 else 1)"

CMD ["uvicorn", "precog_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
