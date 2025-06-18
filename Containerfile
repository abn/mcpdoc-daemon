ARG BASE_IMAGE=docker.io/python:3.13-slim
ARG TARGETPLATFORM
ARG BUILDPLATFORM

FROM --platform=$TARGETPLATFORM ${BASE_IMAGE} AS base

ENV PIP_CACHE_DIR=/opt/cache/pip
ENV POETRY_CACHE_DIR=/opt/cache/poetry
ENV POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /opt/app

RUN --mount=type=cache,target=${PIP_CACHE_DIR} \
    pip install \
        --no-python-version-warning \
        --no-cache-dir \
        --root-user-action=ignore \
        poetry

FROM base AS builder

WORKDIR /opt/app

COPY pyproject.toml poetry.lock ./

RUN --mount=type=cache,target=${POETRY_CACHE_DIR} \
    poetry install --only=main --no-root

# Copy application files (filtered by .dockerignore)
COPY . .

FROM builder AS runtime-base

RUN poetry build --format wheel
RUN /opt/app/.venv/bin/python -m pip install dist/*.whl --no-deps --no-cache-dir

FROM --platform=$TARGETPLATFORM ${BASE_IMAGE} AS runtime

COPY --from=runtime-base /opt/app/.venv /opt/app/.venv

ENV MCPDOC_CONFIG_DIR=/config
ENV MCPDOC_HOST=0.0.0.0
ENV MCPDOC_PORT=8080
ENV MCPDOC_LOG_LEVEL=INFO

WORKDIR /opt/app

EXPOSE 8080

VOLUME ["/config"]

ENTRYPOINT ["/opt/app/.venv/bin/mcpdoc-daemon"]
