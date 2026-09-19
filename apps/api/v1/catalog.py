"""Каталог: список блоков вместе с характеристиками категории.

Фронт рисует экран со списком блоков, а оформление карточки — цвет и стикер —
берёт из категории. Поэтому категория едет вложенной, а не отдельным запросом.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers

from apps.catalog.models import Category, Module


class CategoryInlineSerializer(serializers.ModelSerializer[Category]):
    """Категория внутри блока: только то, чем фронт оформляет карточку."""

    class Meta:
        model = Category
        fields = ("id", "name", "bg_color", "image")


class ModuleSerializer(serializers.ModelSerializer[Module]):
    category = CategoryInlineSerializer(read_only=True)

    class Meta:
        model = Module
        fields = ("id", "title", "category")


@extend_schema(
    summary="Активные блоки с характеристиками категории",
    description=(
        "Плоский список без пагинации. Блоки скрытых категорий "
        "не показываются вместе с самой категорией."
    ),
)
class ModuleListView(generics.ListAPIView[Module]):
    """Блоки, которые показываются на сайте."""

    serializer_class = ModuleSerializer
    # Ответ — голый массив, каталог небольшой. Значение по умолчанию
    # в настройках остаётся: оно сработает на новых списках.
    pagination_class = None
    # Скрытая категория прячет и свои блоки: иначе на сайте останутся карточки
    # предмета, которого там уже нет. Порядок задан явно — он должен быть устойчивым.
    queryset = (
        Module.objects.active()
        .filter(category__is_active=True)
        .select_related("category")
        .order_by("title", "id")
    )
