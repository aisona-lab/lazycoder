# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
COPY fixtures ./fixtures

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --gid 10001 lazycoder \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin lazycoder

COPY --from=builder /opt/venv /opt/venv
COPY scripts /opt/lazycoder/scripts
COPY corpus/seed.jsonl corpus/seed.context.jsonl corpus/README.md /opt/lazycoder/corpus/

RUN chown -R lazycoder:lazycoder /opt/lazycoder

WORKDIR /workspace
USER lazycoder

ENTRYPOINT ["lazycoder"]
CMD ["--help"]
