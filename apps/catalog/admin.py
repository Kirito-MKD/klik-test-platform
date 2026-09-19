"""Админка каталога: категории и блоки.

Контент-менеджер работает здесь же, поэтому в списках сразу видно, как карточка
выглядит на сайте: квадрат с цветом и сам стикер.
"""

from django.contrib import admin
from django.utils.html import format_html

from apps.catalog.models import Category, Module

NO_VALUE = "—"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin[Category]):
    list_display = ("name", "color_preview", "sticker_preview", "is_active")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "is_active")}),
        ("Карточка на сайте", {"fields": ("bg_color", "image")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="цвет", ordering="bg_color")
    def color_preview(self, category: Category) -> str:
        return format_html(
            '<span style="display:inline-block;width:18px;height:18px;border:1px solid #ccc;'
            'border-radius:3px;background:{};vertical-align:middle"></span> {}',
            category.bg_color,
            category.bg_color,
        )

    @admin.display(description="стикер")
    def sticker_preview(self, category: Category) -> str:
        if not category.image:
            return NO_VALUE
        return format_html('<img src="{}" style="height:32px" alt="">', category.image.url)


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin[Module]):
    list_display = ("title", "category", "is_active")
    list_editable = ("is_active",)
    list_filter = ("category", "is_active")
    list_select_related = ("category",)
    search_fields = ("title",)
    autocomplete_fields = ("category",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("category", "title", "is_active")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
