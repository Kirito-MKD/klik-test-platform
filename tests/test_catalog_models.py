"""Каталог: констрейнты проверяются на живой базе, а не только валидаторами форм."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalog.models import Category, Module
from tests.factories import CategoryFactory, ModuleFactory

pytestmark = pytest.mark.django_db


def test_category_name_is_unique() -> None:
    """Двух категорий с одинаковым названием в базе быть не может."""
    CategoryFactory.create(name="Математика")

    with pytest.raises(IntegrityError), transaction.atomic():
        CategoryFactory.create(name="Математика")


def test_category_bg_color_must_be_hex() -> None:
    """CHECK на #RRGGBB: мимо форм админки цвет тоже не подсунуть."""
    with pytest.raises(IntegrityError), transaction.atomic():
        CategoryFactory.create(bg_color="#12345")


def test_category_bg_color_allows_lowercase_hex() -> None:
    """Регистр букв в цвете значения не имеет — CHECK не должен на нём падать."""
    category = CategoryFactory.create(bg_color="#c9e9f6")

    assert Category.objects.filter(pk=category.pk, bg_color="#c9e9f6").exists()


def test_category_form_validation_reports_bad_color() -> None:
    """Валидатор поля даёт контент-менеджеру внятное сообщение вместо ошибки базы."""
    category = Category(name="Окружающий мир", bg_color="голубой")

    with pytest.raises(ValidationError) as error:
        category.full_clean()

    assert "bg_color" in error.value.message_dict


def test_module_title_is_unique_inside_category() -> None:
    """UNIQUE (category, title): в одной категории двух одинаковых блоков нет."""
    module = ModuleFactory.create(title="Дроби")

    with pytest.raises(IntegrityError), transaction.atomic():
        ModuleFactory.create(category=module.category, title="Дроби")


def test_module_title_may_repeat_in_another_category() -> None:
    """Уникальность именно в рамках категории, а не по всей таблице."""
    ModuleFactory.create(title="Дроби")
    other = ModuleFactory.create(title="Дроби")

    assert Module.objects.filter(title="Дроби").count() == 2
    assert other.pk is not None


def test_category_with_modules_is_protected_from_deletion() -> None:
    """PROTECT: категорию с блоками не удалить, пока блоки не разобраны."""
    module = ModuleFactory.create()

    with pytest.raises(ProtectedError):
        module.category.delete()

    assert Category.objects.count() == 1


def test_active_returns_only_visible_categories() -> None:
    """Менеджер `active()` отдаёт только то, что показывается на сайте."""
    visible = CategoryFactory.create(is_active=True)
    CategoryFactory.create(is_active=False)

    assert list(Category.objects.active()) == [visible]


def test_active_returns_only_visible_modules() -> None:
    """Тот же менеджер работает и у блоков."""
    visible = ModuleFactory.create(is_active=True)
    ModuleFactory.create(is_active=False)

    assert list(Module.objects.active()) == [visible]


def test_categories_are_ordered_by_name() -> None:
    """Порядок задаёт фронт, но список по умолчанию — по алфавиту."""
    CategoryFactory.create(name="Русский язык")
    CategoryFactory.create(name="Математика")
    CategoryFactory.create(name="Биология")

    assert [category.name for category in Category.objects.all()] == [
        "Биология",
        "Математика",
        "Русский язык",
    ]


def test_str_shows_name_and_title() -> None:
    """В админке и логах объект должен читаться, а не показывать `object (1)`."""
    module = ModuleFactory.create(category=CategoryFactory.create(name="Математика"), title="Дроби")

    assert str(module.category) == "Математика"
    assert str(module) == "Дроби"
