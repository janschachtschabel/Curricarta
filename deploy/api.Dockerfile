# The API and the worker: one image, two commands (python -m app.serve, python -m app.jobs.worker).
# Build from the repository root: docker build -f deploy/api.Dockerfile .
# The converter's image is the same with Docling beside it (plan M1 3b; Compose service converter):
#   docker build -f deploy/api.Dockerfile --build-arg VENV=convert -t curricarta-convert:local .
#
# Bases are pinned by digest: a build tomorrow gives the same image, and a Debian or CPython
# security fix arrives as a new digest someone chooses to take. python:3.13-slim (Debian trixie).

# The venv the image carries: api (the default, which CI and Compose build) or convert
ARG VENV=api

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS venv-api
# The runtime packages of uv.lock, exported with their hashes (a test keeps the export equal to the
# lock): pip checks every file against its hash, takes wheels only, so nothing compiles here, and
# installs nothing the export does not name. No uv in the image: pip comes with the base.
COPY deploy/requirements-api.txt /tmp/requirements-api.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check \
       --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements-api.txt

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS venv-convert
# The same with the group convert of uv.lock: Docling, EasyOCR and torch without CUDA (~1.6 GB);
# its models are no part of the image (MODELS_DIR, python -m app.conversion.fetch_models). torch's
# CPU builds come from PyTorch's index; the hashes hold every file to the lock whichever index has it
COPY deploy/requirements-convert.txt /tmp/requirements-convert.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check \
       --extra-index-url https://download.pytorch.org/whl/cpu \
       --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements-convert.txt

# BuildKit takes no build argument in COPY --from, and builds only the venv this stage names
FROM venv-${VENV} AS venv

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS runtime
# Code and ontology belong to root: the service reads them, it cannot change them. It writes
# nothing to the image; objects go to the object store, rows to PostgreSQL. With a read-only root
# file system (Compose, Helm) only /tmp stays writable.
# /models, empty, the service's: the converter's volume (MODELS_DIR) takes its owner on its first mount,
# so the fetch of the models (python -m app.conversion.fetch_models) may write it
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin curricarta \
    && install -d -o 10001 -g 10001 /models
COPY --from=venv /opt/venv /opt/venv
# The repository's layout: settings find ontology/ two folders above app/ by default; ONTOLOGY_DIR
# says it as well, for whoever reads the environment. Of ontology/ only what the service reads
# (MODEL_DIRS in app/vocab/loader.py, the stages' output schemas: SCHEMA_DIR in app/llm/schema.py)
# and the folder of the research results, 2.4 MB, whole: the register is seeded from the reports
# of its five assignments (python -m app.sources.research_t1, ASSIGNMENTS); not the research
# assignments, examples and tools beside it.
COPY backend/app /srv/backend/app
COPY ontology/ontologie /srv/ontology/ontologie
COPY ontology/vokabulare /srv/ontology/vokabulare
COPY ontology/profile /srv/ontology/profile
COPY ontology/schemas /srv/ontology/schemas
COPY ontology/recherche-ergebnisse /srv/ontology/recherche-ergebnisse
# The MEM-Schule shapes and the FWU class chain they are checked over (plan M2, 70 KB)
COPY ontology/mem /srv/ontology/mem
# The published seed of the source register (python -m app.sources.seed), 2 MB
COPY data/seed /srv/data/seed
RUN python -m compileall -q /srv/backend/app
# The commit built from (docker build --build-arg REVISION=<sha>), in curricarta_build_info; after
# the last COPY and RUN, so a new revision rebuilds no layer before it
ARG REVISION=unknown
ENV CURRICARTA_REVISION=$REVISION
# Hugging Face's libraries never ask the net for a model: the converter reads them from MODELS_DIR.
# EasyOCR makes its folder (~/.EasyOCR) as it starts; the service's user has no home and the root is
# read-only, so it goes to the tmpfs (Docling's models of it still come from MODELS_DIR).
# pydantic-ai prints a banner on stderr at a process's first agent run where stderr is a terminal
# (docker compose exec without -T): a command's words for the operator would carry it
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    ONTOLOGY_DIR=/srv/ontology \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    EASYOCR_MODULE_PATH=/tmp/easyocr \
    PYDANTIC_AI_NO_BANNER=1
WORKDIR /srv/backend
USER 10001
# 8000 the public API, 9000 the internal port: /health, /ready, /metrics
EXPOSE 8000 9000
# A GET: /health answers HEAD with 405, and wget --spider sends HEAD. The worker answers
# /health on the same internal port, so the check serves both commands.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request; port = int(os.environ.get('INTERNAL_PORT') or 9000); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).status == 200 else 1)"]
CMD ["python", "-m", "app.serve"]
