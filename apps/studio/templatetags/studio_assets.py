"""Ссылки на стили и скрипт студии с отметкой времени правки.

В разработке браузер охотно держит `studio.css` в кеше: стили поправлены,
а страница выглядит по-старому, и это выглядит как сломанная вёрстка.
Тег дописывает к адресу время последней правки файла — после сохранения
браузер забирает новую версию сам.

На проде отметка не нужна: `ManifestStaticFilesStorage` уже кладёт хеш
содержимого в имя файла.
"""

from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def studio_asset(path: str) -> str:
    """Адрес файла из `static/`, в разработке — с отметкой времени."""
    url = static(path)
    if not settings.DEBUG:
        return url

    for directory in settings.STATICFILES_DIRS:
        candidate = Path(directory) / path
        if candidate.exists():
            return f"{url}?v={int(candidate.stat().st_mtime)}"
    return url
