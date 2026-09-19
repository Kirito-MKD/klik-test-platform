"""Каталог: категория (предмет) и блок с тестами.

Схема базы — в README. Порядок категорий и блоков в базе не хранится, его
задаёт фронт. `ordering` ниже — только чтобы выдача была устойчивой.
"""

from typing import ClassVar

from django.db import models
from django.db.models import Q

from apps.common.models import TimeStamped
from apps.common.querysets import ActiveManager
from apps.common.validators import HEX_COLOR_PATTERN, validate_hex_color


class Category(TimeStamped):
    """Категория (предмет) — верхний уровень каталога."""

    name = models.CharField("название", max_length=120, unique=True)
    bg_color = models.CharField(
        "цвет карточки",
        max_length=7,
        default="#C9E9F6",
        validators=[validate_hex_color],
        help_text="Фон карточки в формате #RRGGBB.",
    )
    image = models.ImageField("стикер", upload_to="categories/", blank=True)
    is_active = models.BooleanField("показывать на сайте", default=True)

    objects = ActiveManager["Category"]()

    class Meta:
        verbose_name = "категория"
        verbose_name_plural = "категории"
        ordering = ("name",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(bg_color__regex=HEX_COLOR_PATTERN),
                name="category_bg_color_is_hex",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Module(TimeStamped):
    """Блок с тестами внутри категории."""

    category = models.ForeignKey(
        Category,
        verbose_name="категория",
        related_name="modules",
        on_delete=models.PROTECT,
    )
    title = models.CharField("название", max_length=200)
    is_active = models.BooleanField("показывать на сайте", default=True)

    objects = ActiveManager["Module"]()

    class Meta:
        verbose_name = "блок"
        verbose_name_plural = "блоки"
        ordering = ("title",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("category", "title"),
                name="module_title_unique_per_category",
            ),
        ]

    def __str__(self) -> str:
        return self.title
