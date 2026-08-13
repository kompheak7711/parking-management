# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --upgrade "pip>=25,<27" "build>=1.3,<2" \
    && python -m build --wheel \
    && python -m pip install --prefix=/install dist/*.whl

FROM python:3.11-slim AS runtime

ARG APP_BUILD_VERSION=development
ENV APP_BUILD_VERSION=${APP_BUILD_VERSION} \
    HOME=/home/app \
    PATH=/home/app/.local/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY --from=builder /install /usr/local

USER 10001:10001
WORKDIR /home/app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).read()"]

CMD ["uvicorn", "property_rental.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
