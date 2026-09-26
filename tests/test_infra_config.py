"""Инфраструктурные файлы не должны разъезжаться с настройками проекта."""

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.db.models import FileField

from apps.quizzes.models import Test

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


def test_nginx_does_not_serve_question_files() -> None:
    """Исходники вопросов лежат в медиа, и в них верные ответы — nginx их не отдаёт.

    Скачать файл можно только из студии, по правам. Каталог берём из модели:
    переедет upload_to — тест покажет, что закрытый путь устарел.
    """
    field = Test._meta.get_field("questions_file")
    assert isinstance(field, FileField)
    directory = str(field.upload_to).split("/", 1)[0]

    closed = re.search(rf"location /media/{directory}/ \{{\s*return 404;\s*\}}", _nginx_template())

    assert closed is not None, f"nginx отдаёт /media/{directory}/ всем желающим"


def test_nginx_keeps_the_request_id_from_the_caller() -> None:
    """Свой X-Request-ID фронта доезжает до приложения; nginx ставит свой, только если его нет.

    `proxy_set_header X-Request-ID $request_id` затирал id фронта, и логи
    фронта и бэкенда переставали сходиться.
    """
    template = _nginx_template()
    mapping = re.search(r"map \$http_x_request_id \$(\w+) \{(.*?)\}", template, re.DOTALL)

    assert mapping is not None
    variable, rules = mapping.groups()
    assert re.search(r"default\s+\$http_x_request_id;", rules)
    assert re.search(r'""\s+\$request_id;', rules)
    assert f"proxy_set_header X-Request-ID ${variable};" in template


def dockerignored(path: str) -> bool:
    """Отсечёт ли .dockerignore файл из контекста сборки.

    Правила Docker в том объёме, что нужен этому файлу: путь исключён, если
    шаблону отвечает он сам или любой его каталог; `!` возвращает путь обратно;
    побеждает последнее подходящее правило.
    """
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    parts = path.split("/")
    candidates = ["/".join(parts[: depth + 1]) for depth in range(len(parts))]
    ignored = False
    for line in lines:
        rule = line.strip()
        if not rule or rule.startswith("#"):
            continue
        keep = rule.startswith("!")
        pattern = rule.removeprefix("!").strip("/")
        if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
            ignored = not keep
    return ignored


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.prod",
        "backups/klik-2026-09-16_0300.dump",
        "deploy/certs/privkey.pem",
    ],
)
def test_dockerignore_keeps_secrets_out_of_the_image(path: str) -> None:
    """`COPY . .` в прод-образ не должен унести пароли, дампы базы и ключ сертификата."""
    assert dockerignored(path), f"{path} попадёт в образ"


def test_dockerignore_check_tells_ignored_from_kept() -> None:
    """Контроль самой проверки: исключение `!docs/examples/` и код остаются в образе."""
    assert dockerignored("docs/api.md")
    assert not dockerignored("docs/examples/questions.json")
    assert not dockerignored("apps/quizzes/models.py")


def test_backup_script_rotates_and_refuses_empty_dump() -> None:
    """Бэкап без ротации забьёт диск, а пустой дамп хуже отсутствующего."""
    script = (ROOT / "deploy" / "backup.sh").read_text(encoding="utf-8")

    assert "pg_dump" in script
    assert "-mtime" in script, "нет ротации старых дампов"
    assert "KLIK_BACKUP_KEEP_DAYS" in script
    assert 'if [ ! -s "$partial" ]' in script, "пустой дамп должен быть ошибкой"


def fake_docker(exit_code: int) -> str:
    """Подмена docker: печатает кусок дампа и завершается с нужным кодом."""
    return f"#!/bin/sh\nprintf 'PGDMP-dump'\nexit {exit_code}\n"


def run_backup(tmp_path: Path, docker_script: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Запускает backup.sh, где вместо docker — заданный скрипт."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(docker_script, encoding="utf-8", newline="\n")
    docker.chmod(0o755)
    (tmp_path / "backup.env").write_text(
        "POSTGRES_USER=klik\nPOSTGRES_DB=klik\n", encoding="utf-8", newline="\n"
    )

    sh = shutil.which("sh")
    assert sh is not None
    # Каталог самого sh — сразу за подменой: под Windows иначе вместо POSIX find
    # находится системный find.exe. Пути относительные: так их одинаково понимают
    # sh на Linux и sh из Git для Windows.
    path = os.pathsep.join([str(bin_dir), str(Path(sh).parent), os.environ.get("PATH", "")])
    result = subprocess.run(  # noqa: S603 — свой скрипт из репозитория, аргументы наши
        [sh, str(ROOT / "deploy" / "backup.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": path,
            "KLIK_ENV_FILE": "backup.env",
            "KLIK_BACKUP_DIR": "backups",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    return result, tmp_path / "backups"


@pytest.mark.skipif(shutil.which("sh") is None, reason="нужен POSIX sh")
def test_backup_leaves_no_truncated_dump_when_pg_dump_fails(tmp_path: Path) -> None:
    """Оборванный дамп не должен лежать среди бэкапов под видом целого.

    Иначе ротация честно удалит старые хорошие дампы, а при восстановлении
    окажется, что свежий — обрубок.
    """
    result, backups = run_backup(tmp_path, fake_docker(exit_code=1))

    assert result.returncode != 0
    assert list(backups.iterdir()) == []


@pytest.mark.skipif(shutil.which("sh") is None, reason="нужен POSIX sh")
def test_backup_keeps_a_complete_dump(tmp_path: Path) -> None:
    """Контроль к тесту выше: удачный дамп ложится на место под своим именем."""
    result, backups = run_backup(tmp_path, fake_docker(exit_code=0))

    dumps = list(backups.iterdir())
    assert result.returncode == 0, result.stderr
    assert [dump.name.startswith("klik-") and dump.suffix == ".dump" for dump in dumps] == [True]
    assert dumps[0].read_text(encoding="utf-8") == "PGDMP-dump"


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
