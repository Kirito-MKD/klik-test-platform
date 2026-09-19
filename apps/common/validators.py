"""Валидаторы, общие для нескольких приложений."""

from django.core.validators import RegexValidator

# Та же строка уходит в CHECK-констрейнт Category.bg_color: валидатор ловит ошибку
# в форме админки, констрейнт — всё остальное (шелл, импорт, миграции данных).
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

validate_hex_color = RegexValidator(
    regex=HEX_COLOR_PATTERN,
    message="Цвет задаётся в формате #RRGGBB, например #C9E9F6.",
    code="invalid_hex_color",
)
