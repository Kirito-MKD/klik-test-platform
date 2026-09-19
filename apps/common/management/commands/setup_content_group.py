"""Группа «Контент»: права на каталог и тесты — и ничего больше.

Команда, а не миграция данных: права создаёт сигнал post_migrate, и в миграции
их ещё может не быть. Запускается повторно сколько угодно раз.
"""

from typing import Any

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

CONTENT_GROUP_NAME = "Контент"
DOMAIN_APPS = ("catalog", "quizzes")


class Command(BaseCommand):
    help = "Создаёт или обновляет группу «Контент» с правами на категории, блоки и тесты."
    requires_migrations_checks = True

    def handle(self, *args: Any, **options: Any) -> None:
        group, created = Group.objects.get_or_create(name=CONTENT_GROUP_NAME)
        permissions = Permission.objects.filter(content_type__app_label__in=DOMAIN_APPS)
        # set(), а не add(): лишние права, выданные руками, тоже уедут.
        group.permissions.set(permissions)

        self.stdout.write(
            self.style.SUCCESS(
                f"Группа «{CONTENT_GROUP_NAME}» {'создана' if created else 'обновлена'}: "
                f"{permissions.count()} прав на приложения {', '.join(DOMAIN_APPS)}. "
                "Пользователю остаётся поставить «Статус персонала» и добавить его в группу."
            )
        )
