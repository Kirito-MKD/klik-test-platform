#!/usr/bin/env python
"""Точка входа Django. Настройки по умолчанию — локальные."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Django не найден. Установите зависимости: uv sync") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
