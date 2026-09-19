"""Абстрактные модели, от которых наследуются доменные."""

from django.db import models


class TimeStamped(models.Model):
    """Отметки времени: есть у Category, Module и Test (см. схему БД)."""

    created_at = models.DateTimeField("создан", auto_now_add=True)
    updated_at = models.DateTimeField("изменён", auto_now=True)

    class Meta:
        abstract = True
