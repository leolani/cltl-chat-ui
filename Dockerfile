# syntax = docker/dockerfile:1.2

FROM cltl/eliza-base:latest

WORKDIR /cltl-chatui
COPY src ./src

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "src/main.py"]
