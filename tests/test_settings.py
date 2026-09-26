"""Настройки читаются из окружения — проверяем именно это, а не значения в .env."""

import importlib
import os
from collections.abc import Iterator
from types import ModuleType
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured

MINIMAL_ENV = {
    "DJANGO_SECRET_KEY": "secret-for-tests",
    "DATABASE_URL": "postgres://user:pass@db:5432/klik",
}


def load(module_name: str, env: dict[str, str]) -> ModuleType:
    """Перечитывает модуль настроек с заданным окружением.

    base перезагружается всегда: prod и local тянут значения из него звёздочкой,
    и без перезагрузки они увидят предыдущее состояние.
    """
    with (
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch("environ.Env.read_env"),  # .env разработчика не должен влиять на тесты
    ):
        importlib.reload(importlib.import_module("config.settings.base"))
        return importlib.reload(importlib.import_module(module_name))


@pytest.fixture(autouse=True)
def _restore_settings_modules() -> Iterator[None]:
    """Возвращает модули настроек в предсказуемое состояние.

    Именно в предсказуемое, а не «как было»: локальный .env разработчика может
    содержать DEBUG=true, и тогда перезагрузка prod падала бы на его же проверке.
    """
    yield
    for name in ("config.settings.base", "config.settings.local", "config.settings.prod"):
        load(name, {**MINIMAL_ENV, "DJANGO_DEBUG": "false"})


def test_debug_is_off_when_env_is_silent() -> None:
    base = load("config.settings.base", MINIMAL_ENV)
    assert base.DEBUG is False


def test_secret_key_is_required() -> None:
    with pytest.raises(ImproperlyConfigured):
        load("config.settings.base", {"DATABASE_URL": MINIMAL_ENV["DATABASE_URL"]})


def test_database_url_is_parsed_into_postgres() -> None:
    base = load("config.settings.base", MINIMAL_ENV)
    default = base.DATABASES["default"]
    assert default["ENGINE"] == "django.db.backends.postgresql"
    assert default["NAME"] == "klik"
    assert default["CONN_MAX_AGE"] == 60


def test_allowed_hosts_are_split_by_comma() -> None:
    base = load(
        "config.settings.base",
        {**MINIMAL_ENV, "DJANGO_ALLOWED_HOSTS": "klik.ru,www.klik.ru"},
    )
    assert base.ALLOWED_HOSTS == ["klik.ru", "www.klik.ru"]


def test_admin_url_is_configurable() -> None:
    base = load("config.settings.base", {**MINIMAL_ENV, "DJANGO_ADMIN_URL": "sluzhebnaya/"})
    assert base.ADMIN_URL == "sluzhebnaya/"


def test_primary_keys_are_bigint_as_in_approved_schema() -> None:
    base = load("config.settings.base", MINIMAL_ENV)
    assert base.DEFAULT_AUTO_FIELD == "django.db.models.BigAutoField"


def test_prod_settings_are_hardened() -> None:
    prod = load("config.settings.prod", {**MINIMAL_ENV, "DJANGO_DEBUG": "false"})
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_HSTS_SECONDS >= 31_536_000
    assert prod.X_FRAME_OPTIONS == "DENY"
    # За nginx Django узнаёт про https только из этого заголовка — иначе редирект по кругу.
    assert prod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in prod.MIDDLEWARE
    assert "whitenoise" in prod.STORAGES["staticfiles"]["BACKEND"]


def test_browsable_api_is_off_outside_local() -> None:
    """На проде HTML-страница API — лишняя поверхность, там только JSON."""
    prod = load("config.settings.prod", {**MINIMAL_ENV, "DJANGO_DEBUG": "false"})
    local = load("config.settings.local", {**MINIMAL_ENV, "DJANGO_DEBUG": "false"})

    assert prod.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] == [
        "rest_framework.renderers.JSONRenderer"
    ]
    assert any(
        "BrowsableAPI" in renderer for renderer in local.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"]
    )


def test_cors_is_a_list_of_origins_not_a_wildcard() -> None:
    """Открытый CORS нам не нужен: домены фронта перечисляются явно."""
    base = load(
        "config.settings.base",
        {**MINIMAL_ENV, "DJANGO_CORS_ALLOWED_ORIGINS": "https://klik.ru,https://www.klik.ru"},
    )

    assert base.CORS_ALLOWED_ORIGINS == ["https://klik.ru", "https://www.klik.ru"]
    assert getattr(base, "CORS_ALLOW_ALL_ORIGINS", False) is False


def test_anonymous_throttle_rate_comes_from_environment() -> None:
    """Эндпоинты публичные — частоту ограничиваем и настраиваем окружением."""
    base = load("config.settings.base", {**MINIMAL_ENV, "DJANGO_API_ANON_THROTTLE": "10/min"})

    assert base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["anon"] == "10/min"


def test_prod_counts_proxies_in_front_of_the_app() -> None:
    """За nginx адрес клиента для троттлинга — последнее звено X-Forwarded-For.

    Без NUM_PROXIES DRF берёт заголовок целиком, а левую его часть присылает
    сам клиент: новый выдуманный адрес — новый счётчик, и лимита нет.
    """
    # load() перезагружает тот же модуль, поэтому значение снимаем сразу.
    one_hop = load("config.settings.prod", {**MINIMAL_ENV, "DJANGO_DEBUG": "false"})
    assert one_hop.REST_FRAMEWORK["NUM_PROXIES"] == 1

    two_hops = load(
        "config.settings.prod",
        {**MINIMAL_ENV, "DJANGO_DEBUG": "false", "DJANGO_NUM_PROXIES": "2"},
    )
    assert two_hops.REST_FRAMEWORK["NUM_PROXIES"] == 2


def test_api_authenticates_nobody() -> None:
    """Сессионной аутентификации у API быть не должно.

    С `SessionAuthentication` проверка ответа (единственный POST) потребовала бы
    CSRF-токен у всех, кто открыл админку в том же браузере, — а фронт ходит
    вообще без куки.
    """
    base = load("config.settings.base", MINIMAL_ENV)

    assert base.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == []


def test_studio_styles_are_collected() -> None:
    """Стили студии должны попадать в collectstatic, иначе на проде она голая."""
    base = load("config.settings.base", MINIMAL_ENV)

    assert base.BASE_DIR / "static" in base.STATICFILES_DIRS
    assert (base.BASE_DIR / "static" / "studio" / "studio.css").exists()


def test_login_leads_to_the_studio_not_to_the_admin() -> None:
    """Контент-менеджера с закрытой страницы ведут в студию, а не в админку."""
    base = load("config.settings.base", MINIMAL_ENV)

    assert base.LOGIN_URL == "studio:login"
    assert base.LOGIN_REDIRECT_URL == "studio:index"


def test_prod_refuses_to_start_with_debug() -> None:
    with pytest.raises(ImproperlyConfigured):
        load("config.settings.prod", {**MINIMAL_ENV, "DJANGO_DEBUG": "true"})
