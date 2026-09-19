"""Админка — рабочее место контент-менеджера, поэтому проверяем её через сам admin.

Не вызовы методов по отдельности, а запросы: так же, как это делает человек
в браузере, включая формсеты инлайнов и права группы «Контент».
"""

from pathlib import Path
from typing import Any

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from factory.django import ImageField
from pytest_django.fixtures import Settings

from apps.catalog.admin import CategoryAdmin
from apps.catalog.models import Category, Module
from apps.common.management.commands.setup_content_group import CONTENT_GROUP_NAME
from apps.quizzes.admin import QuestionAdmin, TestAdmin
from apps.quizzes.models import AnswerOption, Question, Test
from tests.factories import (
    AnswerOptionFactory,
    CategoryFactory,
    ModuleFactory,
    QuestionFactory,
    TestFactory,
)

pytestmark = pytest.mark.django_db

DOMAIN_PERMISSIONS = 20  # пять моделей × четыре права


def management_form(prefix: str, total: int, initial: int = 0) -> dict[str, str]:
    """Служебные поля формсета — без них админка не примет ни один инлайн."""
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": str(initial),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


def quiz_form(quiz: Test, *, is_active: bool, questions: int = 0) -> dict[str, Any]:
    """Данные формы теста так, как их шлёт браузер.

    Имя не с `test_`: иначе pytest собирает помощник как тест.
    """
    data: dict[str, Any] = {
        "module": str(quiz.module.pk),
        "title": quiz.title,
        "duration_minutes": str(quiz.duration_minutes),
        "questions_file": "",
        "_save": "Сохранить",
        **management_form("questions", total=questions),
    }
    if is_active:
        data["is_active"] = "on"
    for index in range(questions):
        data[f"questions-{index}-id"] = ""
        data[f"questions-{index}-text"] = f"Вопрос {index + 1}?"
        data[f"questions-{index}-type"] = Question.Type.SINGLE
        data[f"questions-{index}-position"] = str(index + 1)
    return data


def question_form(quiz: Test, *, question_type: str, correct: list[bool]) -> dict[str, Any]:
    """Данные формы вопроса с вариантами ответа."""
    data: dict[str, Any] = {
        "test": str(quiz.pk),
        "text": "Сколько будет два плюс два?",
        "type": question_type,
        "position": "1",
        "_save": "Сохранить",
        **management_form("options", total=len(correct)),
    }
    for index, is_correct in enumerate(correct):
        data[f"options-{index}-id"] = ""
        data[f"options-{index}-text"] = f"Вариант {index + 1}"
        if is_correct:
            data[f"options-{index}-is_correct"] = "on"
    return data


def test_domain_models_are_registered() -> None:
    """Контент-менеджер должен видеть четыре раздела; варианты правятся инлайном."""
    assert site.is_registered(Category)
    assert site.is_registered(Module)
    assert site.is_registered(Test)
    assert site.is_registered(Question)
    assert not site.is_registered(AnswerOption)


def test_category_list_shows_color_square(admin_client: Client) -> None:
    """В списке категорий видно, каким цветом карточка будет на сайте."""
    CategoryFactory.create(name="Математика", bg_color="#C9E9F6")

    response = admin_client.get(reverse("admin:catalog_category_changelist"))

    assert response.status_code == 200
    assert "background:#C9E9F6" in response.content.decode()


def test_category_sticker_preview_is_dash_without_image() -> None:
    """Без стикера в колонке прочерк, а не пустая ячейка и не ошибка."""
    category = CategoryFactory.create()

    assert CategoryAdmin(Category, site).sticker_preview(category) == "—"


def test_category_sticker_preview_shows_image(settings: Settings, tmp_path: Path) -> None:
    """Со стикером в колонке видно саму картинку."""
    settings.MEDIA_ROOT = tmp_path  # картинка теста не должна попасть в media/ репозитория
    category = CategoryFactory.create(image=ImageField(width=10, height=10))

    assert "<img" in CategoryAdmin(Category, site).sticker_preview(category)


def test_test_columns_show_category_and_question_count() -> None:
    """Колонки «категория» и «вопросов» берут данные из аннотации и select_related."""
    category = CategoryFactory.create(name="Математика")
    quiz = TestFactory.create(module=ModuleFactory.create(category=category))
    QuestionFactory.create_batch(3, test=quiz)

    annotated = Test.objects.with_question_count().get(pk=quiz.pk)
    admin_model = TestAdmin(Test, site)

    assert admin_model.category_name(annotated) == "Математика"
    assert admin_model.questions_number(annotated) == 3


def test_question_column_shortens_long_text() -> None:
    """Длинный вопрос в списке обрезается, иначе таблица разъезжается."""
    question = QuestionFactory.create(text="а" * 200)

    assert len(QuestionAdmin(Question, site).short_text(question)) <= 80


def test_test_list_does_not_query_per_row(admin_client: Client) -> None:
    """Список тестов не должен ходить в базу за каждой строкой."""
    module = ModuleFactory.create()
    TestFactory.create(module=module)
    url = reverse("admin:quizzes_test_changelist")
    admin_client.get(url)  # прогрев: сессия и права уже прочитаны

    with CaptureQueriesContext(connection) as one_row:
        admin_client.get(url)

    TestFactory.create_batch(4, module=module)
    with CaptureQueriesContext(connection) as five_rows:
        admin_client.get(url)

    assert len(five_rows) == len(one_row)


def test_test_without_questions_cannot_be_published(admin_client: Client) -> None:
    """Пустой тест на сайт не уедет: форма возвращается с объяснением."""
    quiz = TestFactory.create(is_active=False)

    response = admin_client.post(
        reverse("admin:quizzes_test_change", args=[quiz.pk]),
        data=quiz_form(quiz, is_active=True),
    )

    assert response.status_code == 200
    assert "Тест без вопросов нельзя показывать на сайте" in response.content.decode()
    assert Test.objects.get(pk=quiz.pk).is_active is False


def test_test_with_questions_can_be_published(admin_client: Client) -> None:
    """Тот же тест с вопросами сохраняется и включается."""
    quiz = TestFactory.create(is_active=False)

    response = admin_client.post(
        reverse("admin:quizzes_test_change", args=[quiz.pk]),
        data=quiz_form(quiz, is_active=True, questions=2),
    )

    assert response.status_code == 302
    assert Test.objects.get(pk=quiz.pk).is_active is True
    assert Question.objects.filter(test=quiz).count() == 2


def test_half_filled_question_row_reports_field_error(admin_client: Client) -> None:
    """Строка вопроса без текста — ошибка поля; тест при этом не публикуется."""
    quiz = TestFactory.create(is_active=False)
    data = quiz_form(quiz, is_active=True, questions=1)
    data["questions-0-text"] = ""

    response = admin_client.post(reverse("admin:quizzes_test_change", args=[quiz.pk]), data=data)

    assert response.status_code == 200
    assert Question.objects.count() == 0
    assert Test.objects.get(pk=quiz.pk).is_active is False


def test_half_filled_option_row_reports_field_error(admin_client: Client) -> None:
    """Пустой вариант с галочкой «верный» не сохраняется молча."""
    quiz = TestFactory.create()
    data = question_form(quiz, question_type=Question.Type.SINGLE, correct=[True, False])
    data["options-0-text"] = ""

    response = admin_client.post(reverse("admin:quizzes_question_add"), data=data)

    assert response.status_code == 200
    assert Question.objects.count() == 0


def test_question_needs_two_options(admin_client: Client) -> None:
    """Вопрос с одним вариантом админка не примет."""
    quiz = TestFactory.create()

    response = admin_client.post(
        reverse("admin:quizzes_question_add"),
        data=question_form(quiz, question_type=Question.Type.SINGLE, correct=[True]),
    )

    assert response.status_code == 200
    assert "не меньше 2" in response.content.decode()
    assert Question.objects.count() == 0


def test_question_needs_a_correct_option(admin_client: Client) -> None:
    """Вопрос без верного ответа бессмыслен — форма возвращается с ошибкой."""
    quiz = TestFactory.create()

    response = admin_client.post(
        reverse("admin:quizzes_question_add"),
        data=question_form(quiz, question_type=Question.Type.SINGLE, correct=[False, False]),
    )

    assert response.status_code == 200
    assert "Отметьте хотя бы один верный вариант" in response.content.decode()
    assert Question.objects.count() == 0


def test_single_question_rejects_two_correct_options(admin_client: Client) -> None:
    """У типа single верный ответ ровно один: иначе подсказка поменять тип."""
    quiz = TestFactory.create()

    response = admin_client.post(
        reverse("admin:quizzes_question_add"),
        data=question_form(quiz, question_type=Question.Type.SINGLE, correct=[True, True]),
    )

    assert response.status_code == 200
    assert "может быть только один" in response.content.decode()
    assert Question.objects.count() == 0


def test_multiple_question_accepts_two_correct_options(admin_client: Client) -> None:
    """Тот же вопрос с типом multiple сохраняется вместе с вариантами."""
    quiz = TestFactory.create()

    response = admin_client.post(
        reverse("admin:quizzes_question_add"),
        data=question_form(quiz, question_type=Question.Type.MULTIPLE, correct=[True, True]),
    )

    assert response.status_code == 302
    question = Question.objects.get()
    assert question.type == Question.Type.MULTIPLE
    assert AnswerOption.objects.filter(question=question, is_correct=True).count() == 2


def test_existing_question_keeps_its_options(admin_client: Client) -> None:
    """Правка текста не должна требовать заново заводить варианты ответа."""
    question = QuestionFactory.create(text="Старый текст", position=1)
    first = AnswerOptionFactory.create(question=question, text="Четыре", is_correct=True)
    second = AnswerOptionFactory.create(question=question, text="Пять")

    data: dict[str, Any] = {
        "test": str(question.test.pk),
        "text": "Новый текст",
        "type": Question.Type.SINGLE,
        "position": "1",
        "_save": "Сохранить",
        **management_form("options", total=2, initial=2),
        "options-0-id": str(first.pk),
        "options-0-text": first.text,
        "options-0-is_correct": "on",
        "options-1-id": str(second.pk),
        "options-1-text": second.text,
    }
    response = admin_client.post(
        reverse("admin:quizzes_question_change", args=[question.pk]), data=data
    )

    assert response.status_code == 302
    assert Question.objects.get(pk=question.pk).text == "Новый текст"
    assert AnswerOption.objects.filter(question=question).count() == 2


def test_content_group_gets_rights_only_for_domain_apps() -> None:
    """Группа «Контент» — пять доменных моделей и ничего больше."""
    call_command("setup_content_group")

    group = Group.objects.get(name=CONTENT_GROUP_NAME)
    app_labels = set(group.permissions.values_list("content_type__app_label", flat=True))

    assert app_labels == {"catalog", "quizzes"}
    assert group.permissions.count() == DOMAIN_PERMISSIONS


def test_setup_content_group_cleans_up_extra_rights() -> None:
    """Команда идемпотентна и убирает права, выданные группе мимо неё."""
    call_command("setup_content_group")
    group = Group.objects.get(name=CONTENT_GROUP_NAME)
    group.permissions.add(Permission.objects.get(codename="add_user"))

    call_command("setup_content_group")

    assert group.permissions.count() == DOMAIN_PERMISSIONS
    assert not group.permissions.filter(codename="add_user").exists()


def test_content_manager_sees_only_domain_sections(client: Client) -> None:
    """Человек из группы «Контент» не видит в админке пользователей и группы."""
    call_command("setup_content_group")
    editor = User.objects.create_user(username="content-manager", is_staff=True)
    editor.groups.add(Group.objects.get(name=CONTENT_GROUP_NAME))
    client.force_login(editor)

    page = client.get(reverse("admin:index")).content.decode()

    assert "Категории" in page
    assert "Тесты" in page
    assert "Пользователи" not in page
