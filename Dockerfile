# syntax=docker/dockerfile:1

FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Венв вне /app: в dev-режиме код монтируется томом и затёр бы .venv из образа.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./

# ─── разработка: с dev-зависимостями, код монтируется томом ─────────
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ─── прод: без dev-зависимостей, непривилегированный пользователь ───
FROM base AS prod
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY . .
# Статику собираем на билде: в рантайме образ работает с кодом только на чтение.
# Переменные тут фиктивные — collectstatic читает настройки и не ходит в базу,
# поэтому секрета в сборке не появляется.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-only-not-a-secret \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgres://klik:klik@db:5432/klik \
    python manage.py collectstatic --noinput
RUN useradd --system --uid 1001 --create-home app \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-"]
