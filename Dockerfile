# syntax=docker/dockerfile:1

# Precog API image (CPU-only).
#
# By default the TimesFM-3 weights are NOT baked in: the entrypoint downloads
# them at startup into PRECOG_CACHE_DIR (/opt/precog/hf), which can be an
# ephemeral directory, a named volume, a bind mount or a Kubernetes PVC. Set
# PRECOG_BAKE_WEIGHTS=true to bake them for air-gapped deployments.
#
# The resulting image does not contain the weights, so it does not redistribute
# them. The weights themselves remain under the TimesFM Non-Commercial License
# v1.0 once downloaded.
#
#   podman build -t precog-api:local .
#   # behind TLS inspection:
#   podman build --build-arg CA_CERT="$(cat corp-root.crt)" -t precog-api:local .

ARG PYTHON_VERSION=3.12
ARG PRECOG_MODEL_ID=google/timesfm-3.0-pytorch
ARG PRECOG_MODEL_REVISION=43046b85ec22d584a13f8098c2ed39c889e129c2

# ---------------------------------------------------------------------------
# Builder: Python dependencies; optionally bake the weights.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG CA_CERT=""
ARG PRECOG_BAKE_WEIGHTS=false
ARG PRECOG_MODEL_ID
ARG PRECOG_MODEL_REVISION

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
    && pip install ./packages/schemas "./apps/api[otel]"

# httpx (used by huggingface_hub) trusts certifi, not the OS store.
RUN if [ -n "$CA_CERT" ]; then \
        cat /etc/ssl/certs/ca-certificates.crt >> "$(python -c 'import certifi; print(certifi.where())')"; \
    fi

RUN if [ "$PRECOG_BAKE_WEIGHTS" = "true" ]; then \
        python -c "from huggingface_hub import snapshot_download as d; d('${PRECOG_MODEL_ID}', revision='${PRECOG_MODEL_REVISION}', cache_dir='/opt/precog/hf-baked')"; \
    fi

# ---------------------------------------------------------------------------
# Runtime: minimal image, non-root. Downloads weights at startup by default.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG CA_CERT=""
ARG PRECOG_BAKE_WEIGHTS=false
ARG PRECOG_MODEL_ID
ARG PRECOG_MODEL_REVISION

LABEL org.opencontainers.image.title="precog-api" \
      org.opencontainers.image.description="TimesFM-3 zero-shot forecasting REST API (CPU)." \
      org.opencontainers.image.source="https://github.com/Albe83/precog" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 precog

COPY --from=builder /opt/venv /opt/venv

# Optional corporate CA, needed for the runtime download behind TLS inspection.
RUN if [ -n "$CA_CERT" ]; then \
        printf '%s\n' "$CA_CERT" > /usr/local/share/ca-certificates/corp-root.crt \
        && update-ca-certificates \
        && cat /etc/ssl/certs/ca-certificates.crt >> "$(/opt/venv/bin/python -c 'import certifi; print(certifi.where())')"; \
    fi

# Cache directory owned by the runtime user, so a fresh named volume inherits it.
RUN mkdir -p /opt/precog/hf && chown -R 10001:10001 /opt/precog

COPY deploy/docker/entrypoint.sh /usr/local/bin/precog-entrypoint.sh
COPY THIRD_PARTY_NOTICES.md LICENSE /opt/precog/
RUN chmod +x /usr/local/bin/precog-entrypoint.sh

# Optionally seed the cache from baked weights (air-gapped mode).
RUN if [ "$PRECOG_BAKE_WEIGHTS" = "true" ]; then \
        cp -a /opt/precog/hf-baked/. /opt/precog/hf/ \
        && chown -R 10001:10001 /opt/precog/hf; \
    fi

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRECOG_ENGINE=timesfm3 \
    PRECOG_DEVICE=cpu \
    PRECOG_MODEL_ID=${PRECOG_MODEL_ID} \
    PRECOG_MODEL_REVISION=${PRECOG_MODEL_REVISION} \
    PRECOG_MODEL_PATH=/opt/precog/models \
    PRECOG_CACHE_DIR=/opt/precog/hf \
    PRECOG_LOCAL_FILES_ONLY=true \
    PRECOG_PRELOAD=auto

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz').status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/precog-entrypoint.sh"]
CMD ["uvicorn", "precog_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
