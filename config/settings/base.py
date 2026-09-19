"""Базовые настройки KLIK.

Всё, что зависит от окружения, читается из переменных среды — в репозитории
нет ни одного секрета. Локальные и продовые отличия лежат в local.py и prod.py.
"""

from pathlib import Path

import django_stubs_ext
import environ

# Делает generic-классы Django (ModelAdmin[...], ModelForm[...], BaseInlineFormSet[...])
# подписываемыми в рантайме — на них стоит типизация админки.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env(
    # Списочные значения задаём схемой: так у геттеров ниже не нужен default,
    # на который ругается basedpyright (в стабах environ он типизирован сентинелом).
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_CORS_ALLOWED_ORIGINS=(list, []),
)
# .env необязателен: в контейнере и в CI переменные приходят из окружения.
env.read_env(BASE_DIR / ".env")

# ─── основное ───────────────────────────────────────────────────────
# Типизированные геттеры, а не env(...): и читается яснее, и чекеры типов довольны.
SECRET_KEY: str = env.str("DJANGO_SECRET_KEY")
DEBUG: bool = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS: list[str] = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Адрес админки выносим в окружение: на проде она не должна лежать на /admin/.
ADMIN_URL: str = env.str("DJANGO_ADMIN_URL", default="admin/")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Схема БД утверждена с bigint-первичными ключами.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── приложения ─────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS: list[str] = [
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
]
# Домен: apps.common — абстрактная модель и хелперы, таблиц у него нет.
LOCAL_APPS: list[str] = [
    "apps.common",
    "apps.catalog",
    "apps.quizzes",
    "apps.api",
    "apps.studio",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # CORS выше CommonMiddleware: заголовки нужны и на редиректах, и на ошибках.
    "corsheaders.middleware.CorsMiddleware",
    # Свой id запроса: он уезжает в ответ и в тело ошибки, по нему ищут в логах.
    "apps.common.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ─── база данных ────────────────────────────────────────────────────
# Нужен именно PostgreSQL: deferrable-констрейнты и CHECK с regex.
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DJANGO_CONN_MAX_AGE", default=60)
# Недоступная база должна давать ошибку, а не вешать воркер на минуты.
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": env.int("DJANGO_DB_CONNECT_TIMEOUT", default=5)
}

# ─── вход в студию ──────────────────────────────────────────────────
# Кабинет контент-менеджера живёт на /studio/ и не имеет отношения к админке:
# туда пускают по правам, а не по «статусу персонала».
LOGIN_URL = "studio:login"
LOGIN_REDIRECT_URL = "studio:index"
LOGOUT_REDIRECT_URL = "studio:login"

# ─── пароли админов ─────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── локализация ────────────────────────────────────────────────────
LANGUAGE_CODE = "ru-ru"
TIME_ZONE: str = env.str("DJANGO_TIME_ZONE", default="Europe/Moscow")
USE_I18N = True
USE_TZ = True

# ─── статика и медиа ────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Стили студии лежат вне приложений: это один файл на весь кабинет.
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Файл вопросов заливается в админке: 5 МБ с запасом хватает на любой JSON.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ─── API ────────────────────────────────────────────────────────────
# Общее для всех эндпоинтов: пагинация, троттлинг анонимов,
# единый формат ошибки и схема OpenAPI.
REST_FRAMEWORK = {
    # Browsable API включается только в local.py: на проде это лишняя поверхность.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Авторизации у детей нет — эндпоинты публичные.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    # Пустой список, а не умолчание DRF: с SessionAuthentication проверка ответа
    # (единственный POST) требовала бы CSRF-токен у всех, кто зашёл в админку
    # из того же браузера. Сессия для публичного API не нужна вовсе.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env.str("DJANGO_API_ANON_THROTTLE", default="60/min"),
    },
    "EXCEPTION_HANDLER": "apps.api.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "KLIK API",
    "DESCRIPTION": (
        "Каталог тестов KLIK. Авторизации нет. Блоки с категорией, тесты блока, "
        "вопросы теста и проверка варианта ответа."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Фронт ходит с другого домена. Списком, а не звёздочкой: открытый CORS нам не нужен.
CORS_ALLOWED_ORIGINS: list[str] = env.list("DJANGO_CORS_ALLOWED_ORIGINS")

# ─── логи ───────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env.str("DJANGO_LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "propagate": True},
    },
}
