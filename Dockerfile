# syntax = docker/dockerfile:1.4

ARG base_image=cltl/cltl-base:latest
FROM ${base_image}

COPY --from=leolani . /leolani/

WORKDIR /cltl-chatui
COPY setup.py requirements.txt README.md VERSION ./
COPY src ./src

RUN pip install --no-index --no-build-isolation --find-links=/leolani -r requirements.txt && \
    rm -rf /leolani && \
    find /usr/local/lib/python3.10 -type d -name __pycache__ -exec rm -rf {} +

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "src/main.py"]
