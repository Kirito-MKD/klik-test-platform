"""Локальная разработка: те же настройки, плюс удобства и никакой почты наружу."""

from .base import *
from .base import ALLOWED_HOSTS, REST_FRAMEWORK

# Хосты для docker compose и запуска напрямую.
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "localhost", "127.0.0.1", "0.0.0.0", "app", "testserver"]  # noqa: S104

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Browsable API — удобно смотреть эндпоинты глазами; на проде он выключен.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}
