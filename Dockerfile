# syntax = docker/dockerfile:1.2

FROM cltl/eliza-base:latest

WORKDIR /cltl-chatui
COPY src requirements.txt makefile ./
COPY config ./config
COPY util ./util

RUN --mount=type=bind,target=/cltl-chatui/repo,from=cltl/cltl-requirements:latest,source=/repo \
        make docker-install project_repo=/cltl-chatui/repo/leolani project_mirror=/cltl-chatui/repo/mirror

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD python main.py