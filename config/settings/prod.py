"""Продовые настройки: HTTPS, строгие куки, статика через whitenoise."""

from django.core.exceptions import ImproperlyConfigured

from .base import *
from .base import DEBUG, MIDDLEWARE, REST_FRAMEWORK, STORAGES, env

if DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG=true с продовыми настройками — так нельзя.")

# ─── безопасность ───────────────────────────────────────────────────
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000  # год
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# ─── API за прокси ──────────────────────────────────────────────────
# Троттлинг считает запросы по адресу клиента. За nginx это последнее звено
# X-Forwarded-For — его дописывает сам nginx; всё, что левее, прислал клиент
# и мог выдумать. Без NUM_PROXIES DRF берёт заголовок целиком, и лимит
# обходится новым выдуманным адресом в каждом запросе.
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": env.int("DJANGO_NUM_PROXIES", default=1)}

# ─── статика ────────────────────────────────────────────────────────
MIDDLEWARE = [
    MIDDLEWARE[0],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
