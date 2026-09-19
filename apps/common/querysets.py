"""Общие QuerySet и менеджеры.

Менеджер объявлен классом, а не через `ActiveQuerySet.as_manager()`: после
`as_manager()` про метод `active()` знает только mypy с django-stubs, а
basedpyright видит обычный Manager и ругается на каждый вызов.
"""

from typing import Self, TypeVar

from django.db import models

_M = TypeVar("_M", bound=models.Model)


class ActiveQuerySet(models.QuerySet[_M]):
    """QuerySet моделей с флагом `is_active`."""

    def active(self) -> Self:
        """Только то, что показывается на сайте."""
        return self.filter(is_active=True)


class ActiveManager(models.Manager[_M]):
    """Менеджер, пробрасывающий `active()` наружу."""

    def get_queryset(self) -> ActiveQuerySet[_M]:
        return ActiveQuerySet(self.model, using=self._db)

    def active(self) -> ActiveQuerySet[_M]:
        return self.get_queryset().active()
