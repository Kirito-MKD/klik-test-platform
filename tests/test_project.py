"""Проект собирается и держит инварианты, на которые опирается CI."""

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
from django.db.migrations.state import ProjectState
from django.urls import reverse
from django.utils import translation


def test_system_checks_pass() -> None:
    """manage.py check — бросит SystemCheckError, если конфигурация сломана."""
    call_command("check")


def test_no_missing_migrations() -> None:
    """Модели и миграции не расходятся.

    Автодетектор вместо `makemigrations --check`: с connection=None он не лезет
    в базу, поэтому тест быстрый и не зависит от того, поднят ли постгрес.
    В CI живая база есть, и там тот же инвариант проверяется ещё и командой.
    """
    # Без отключения переводов сравниваются русские verbose_name из contrib-приложений
    # с английскими из их миграций — сама команда makemigrations делает то же самое.
    with translation.override(None):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        autodetector = MigrationAutodetector(
            loader.project_state(),
            ProjectState.from_apps(apps),
            NonInteractiveMigrationQuestioner(specified_apps=set(), dry_run=True),
        )
        changes = autodetector.changes(graph=loader.graph, trim_to_apps=None, convert_apps=None)
    assert not changes, f"Модели изменились без миграции: {sorted(changes)}"


def test_admin_is_mounted_on_configured_url() -> None:
    assert reverse("admin:index") == "/" + settings.ADMIN_URL


def test_timezone_is_moscow_and_tz_aware() -> None:
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "Europe/Moscow"


def test_upload_limit_fits_questions_json() -> None:
    """Файл с вопросами заливают через админку — 5 МБ должно хватать."""
    assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE >= 5 * 1024 * 1024


def test_database_connection_has_timeout() -> None:
    """Мёртвая база не должна вешать воркер: соединение с таймаутом."""
    assert settings.DATABASES["default"]["OPTIONS"]["connect_timeout"] <= 10
