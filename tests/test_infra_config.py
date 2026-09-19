"""Инфраструктурные файлы не должны разъезжаться с настройками проекта."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    return data


def _prod_compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((ROOT / "compose.prod.yaml").read_text(encoding="utf-8"))
    return data


def _nginx_template() -> str:
    return (ROOT / "deploy" / "nginx" / "klik.conf.template").read_text(encoding="utf-8")


def test_compose_defines_db_and_app() -> None:
    services = _compose()["services"]
    assert set(services) == {"db", "app"}
    assert services["db"]["image"].startswith("postgres:17")


def test_app_waits_for_healthy_database() -> None:
    services = _compose()["services"]
    assert "healthcheck" in services["db"]
    assert services["app"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_env_example_lists_required_variables() -> None:
    """Новый разработчик копирует .env.example — там должно быть всё, что читают настройки."""
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = {
        line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.startswith("#")
    }
    required = {
        "DJANGO_SETTINGS_MODULE",
        "DJANGO_SECRET_KEY",
        "DJANGO_DEBUG",
        "DJANGO_ALLOWED_HOSTS",
        "DATABASE_URL",
    }
    assert required <= keys, f"в .env.example не хватает: {sorted(required - keys)}"


def test_dockerfile_uses_python_313_and_nonroot_user() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.13-slim" in text
    assert "USER app" in text


def test_dockerfile_keeps_venv_outside_bind_mount() -> None:
    """Венв обязан лежать вне /app.

    В dev-режиме код монтируется томом поверх /app и затирает .venv из образа —
    контейнер падал с ModuleNotFoundError: No module named 'django'.
    """
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "UV_PROJECT_ENVIRONMENT=/opt/venv" in text
    assert "/opt/venv/bin" in text


def test_prod_compose_runs_app_database_and_nginx() -> None:
    """Прод-контур — три сервиса; приложение наружу ходит только через nginx."""
    services = _prod_compose()["services"]

    assert set(services) == {"db", "app", "nginx"}
    assert services["nginx"]["ports"] == ["80:80", "443:443"]
    assert "ports" not in services["app"], "приложение должно быть доступно только nginx"


def test_prod_database_is_not_published_outside() -> None:
    """База на проде не торчит наружу: в неё ходят приложение и скрипт бэкапа."""
    assert "ports" not in _prod_compose()["services"]["db"]


def test_prod_app_healthcheck_asks_the_api() -> None:
    """Healthcheck контейнера — тот же адрес, что и у мониторинга."""
    app = _prod_compose()["services"]["app"]

    assert "/api/v1/health/" in " ".join(app["healthcheck"]["test"])
    assert app["depends_on"]["db"]["condition"] == "service_healthy"


def test_prod_services_restart_on_their_own() -> None:
    """Перезагрузка сервера не должна требовать человека."""
    services = _prod_compose()["services"]

    assert all(service["restart"] == "always" for service in services.values())


def test_nginx_upload_limit_matches_django() -> None:
    """Файл с вопросами должен упираться в проверку приложения, а не в nginx."""
    from django.conf import settings

    limit = re.search(r"client_max_body_size\s+(\d+)m", _nginx_template())

    assert limit is not None
    assert int(limit.group(1)) * 1024 * 1024 >= settings.DATA_UPLOAD_MAX_MEMORY_SIZE


def test_nginx_passes_the_forwarded_proto_header() -> None:
    """Без X-Forwarded-Proto прод-настройки уводят в бесконечный редирект на https.

    Что настройки ждут именно этот заголовок, проверяет test_settings.py.
    """
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in _nginx_template()


def test_nginx_serves_static_and_media_itself() -> None:
    """Статику и медиа отдаёт nginx: гонять их через gunicorn незачем."""
    template = _nginx_template()

    assert "location /static/" in template
    assert "location /media/" in template


def test_dockerfile_collects_static_at_build() -> None:
    """Статика собирается на билде — в рантайме код только читают."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "collectstatic --noinput" in text


def test_backup_script_rotates_and_refuses_empty_dump() -> None:
    """Бэкап без ротации забьёт диск, а пустой дамп хуже отсутствующего."""
    script = (ROOT / "deploy" / "backup.sh").read_text(encoding="utf-8")

    assert "pg_dump" in script
    assert "-mtime" in script, "нет ротации старых дампов"
    assert "KLIK_BACKUP_KEEP_DAYS" in script
    assert 'if [ ! -s "$target" ]' in script, "пустой дамп должен быть ошибкой"


def test_prod_env_example_lists_required_variables() -> None:
    """По .env.prod.example разворачивают контур — в нём должно быть всё нужное."""
    lines = (ROOT / ".env.prod.example").read_text(encoding="utf-8").splitlines()
    keys = {
        line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.startswith("#")
    }
    required = {
        "DJANGO_SETTINGS_MODULE",
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "POSTGRES_PASSWORD",
        "KLIK_DOMAIN",
        "KLIK_CERTS_DIR",
    }

    assert required <= keys, f"в .env.prod.example не хватает: {sorted(required - keys)}"


def test_gitignore_hides_secrets_and_media() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "/media/", ".venv/", "/backups/"):
        assert pattern in text, f"{pattern} должен быть в .gitignore"
