# syntax = docker/dockerfile:1.4

ARG base_image=ghcr.io/leolani/cltl-base-slim:latest
FROM ${base_image}

LABEL org.opencontainers.image.source="https://github.com/leolani/cltl-containers"
LABEL org.opencontainers.image.description="Leolani Chat UI"
LABEL org.opencontainers.image.licenses="MIT"

COPY --from=leolani . /leolani/

WORKDIR /cltl-chatui
COPY setup.py requirements.txt README.md VERSION ./
COPY src ./src

RUN pip install --no-index --no-build-isolation --find-links=/leolani -r requirements.txt && \
    rm -rf /leolani && \
    find /usr/local/lib/python3.10 -type d -name __pycache__ -exec rm -rf {} +

# Probed with the interpreter rather than curl: python:3.10-slim ships no curl,
# and installing one solely for a liveness probe would add an apt layer to every
# image built on cltl-base-slim.
#
# The `except` is for readability rather than correctness -- an unhandled URLError
# already exits non-zero -- but without it `docker inspect` reports a failing probe
# as a multi-line traceback in `.State.Health.Log` instead of one line.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request\ntry:\n    sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)\nexcept Exception as e:\n    print(e)\n    sys.exit(1)"]

CMD ["python", "src/main.py"]
