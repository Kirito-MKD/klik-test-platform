"""Окружение для pytest.

Лежит в корне, а не в tests/: переменные среды должны быть выставлены до того,
как pytest-django поднимет Django. setdefault — чтобы CI и локальный .env могли
их переопределить.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("DJANGO_DEBUG", "false")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,localhost")
os.environ.setdefault("DATABASE_URL", "postgres://klik:klik@localhost:5432/klik")
