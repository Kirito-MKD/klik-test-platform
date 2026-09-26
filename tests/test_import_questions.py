"""Импорт вопросов из JSON: разбор файла, правила формата, транзакция, команда и админка.

Эталон `docs/examples/questions.json` проверяется этими же тестами: он уезжает
контент-менеджеру и фронту, поэтому не должен разойтись с кодом.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import Settings

from apps.quizzes.models import AnswerOption, Question, Test
from apps.quizzes.services.import_questions import (
    ImportMode,
    QuestionsFileError,
    import_questions,
    import_questions_from_file,
    parse_questions,
)
from tests.factories import QuestionFactory, TestFactory

pytestmark = pytest.mark.django_db

EXAMPLE_FILE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "questions.json"
EXAMPLE_QUESTIONS = 16


def one_question(**overrides: Any) -> dict[str, Any]:
    """Минимальный валидный файл, в котором тест подменяет нужный кусок."""
    question: dict[str, Any] = {
        "text": "Сколько будет два плюс два?",
        "type": "single",
        "options": [
            {"text": "Четыре", "is_correct": True},
            {"text": "Пять"},
        ],
    }
    question.update(overrides)
    return {"questions": [question]}


def as_upload(data: Any, name: str = "questions.json") -> SimpleUploadedFile:
    raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return SimpleUploadedFile(name, raw.encode(), content_type="application/json")


def test_example_file_creates_questions_with_options() -> None:
    """Эталонный файл из docs даёт 16 вопросов с вариантами и сквозной нумерацией."""
    quiz = TestFactory.create()
    payload = parse_questions(EXAMPLE_FILE.read_bytes())

    created = import_questions(quiz, payload)

    assert created == EXAMPLE_QUESTIONS
    assert list(Question.objects.filter(test=quiz).values_list("position", flat=True)) == list(
        range(1, EXAMPLE_QUESTIONS + 1)
    )
    assert AnswerOption.objects.count() == sum(
        len(question.options) for question in payload.questions
    )
    assert Question.objects.filter(test=quiz, type=Question.Type.MULTIPLE).exists()


def test_broken_json_is_reported() -> None:
    """Битый файл — понятная ошибка, а не трейсбек."""
    with pytest.raises(QuestionsFileError) as error:
        parse_questions('{"questions": [')

    assert "не разбирается как JSON" in str(error.value)


def test_file_not_in_utf8_is_reported() -> None:
    """Файл в cp1251 (так сохраняет старый Блокнот) — претензия про кодировку, а не 500."""
    raw = json.dumps(one_question(), ensure_ascii=False).encode("cp1251")

    with pytest.raises(QuestionsFileError) as error:
        parse_questions(raw)

    assert error.value.problems == [
        "Файл должен быть в кодировке UTF-8: пересохраните его с этой кодировкой."
    ]


def test_utf8_file_with_bom_is_accepted() -> None:
    """Метка BOM в начале файла — тоже UTF-8, отказывать из-за неё нельзя."""
    raw = json.dumps(one_question(), ensure_ascii=False).encode("utf-8-sig")

    assert len(parse_questions(raw).questions) == 1


def test_unknown_field_is_rejected() -> None:
    """extra=forbid: лишний ключ не проглатывается молча."""
    with pytest.raises(QuestionsFileError) as error:
        parse_questions(json.dumps(one_question(explanation="разбор будет позже")))

    assert "questions → 0 → explanation" in str(error.value)


def test_error_points_to_the_place_in_file() -> None:
    """В ошибке виден путь до поля: какой вопрос, какой вариант."""
    data = one_question()
    data["questions"].append(
        {"text": "Второй вопрос", "options": [{"text": ""}, {"text": "Ответ", "is_correct": True}]}
    )

    with pytest.raises(QuestionsFileError) as error:
        parse_questions(json.dumps(data))

    assert "questions → 1 → options → 0 → text" in str(error.value)


def test_one_option_is_not_enough() -> None:
    """Вопрос с единственным вариантом — не вопрос."""
    data = one_question(options=[{"text": "Четыре", "is_correct": True}])

    with pytest.raises(QuestionsFileError) as error:
        parse_questions(json.dumps(data))

    assert "questions → 0 → options" in str(error.value)


def test_more_than_ten_options_are_rejected() -> None:
    """Десяти вариантов достаточно: длинный список ребёнок не читает."""
    options: list[dict[str, Any]] = [{"text": f"Вариант {number}"} for number in range(11)]
    options[0]["is_correct"] = True

    with pytest.raises(QuestionsFileError) as error:
        parse_questions(json.dumps(one_question(options=options)))

    assert "questions → 0 → options" in str(error.value)


def test_question_without_correct_option_is_rejected() -> None:
    """Хотя бы один вариант должен быть верным."""
    data = one_question(options=[{"text": "Четыре"}, {"text": "Пять"}])

    with pytest.raises(QuestionsFileError) as error:
        parse_questions(json.dumps(data))

    assert "хотя бы один верный вариант" in str(error.value)


def test_single_question_with_two_correct_is_rejected() -> None:
    """У типа single верный ответ ровно один — в ошибке подсказка про multiple."""
    data = one_question(
        options=[{"text": "Четыре", "is_correct": True}, {"text": "Пять", "is_correct": True}]
    )

    with pytest.raises(QuestionsFileError) as error:
        parse_questions(json.dumps(data))

    assert "multiple" in str(error.value)


def test_multiple_question_with_two_correct_is_accepted() -> None:
    """Тот же вопрос с типом multiple разбирается без претензий."""
    data = one_question(
        type="multiple",
        options=[{"text": "Четыре", "is_correct": True}, {"text": "Два", "is_correct": True}],
    )

    payload = parse_questions(json.dumps(data))

    assert payload.questions[0].type == "multiple"


def test_bad_file_changes_nothing_in_database() -> None:
    """На кривом файле в базе не остаётся ни строки."""
    quiz = TestFactory.create()

    with pytest.raises(QuestionsFileError):
        import_questions_from_file(quiz, as_upload('{"questions": []}'))

    assert Question.objects.count() == 0
    assert Test.objects.get(pk=quiz.pk).questions_file.name in ("", None)


def test_failed_write_rolls_back_created_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если запись вариантов упадёт, вопросы тоже не останутся: транзакция одна."""
    quiz = TestFactory.create()
    payload = parse_questions(json.dumps(one_question()))

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("база отвалилась")

    monkeypatch.setattr(AnswerOption.objects, "bulk_create", boom)

    with pytest.raises(RuntimeError):
        import_questions(quiz, payload)

    assert Question.objects.count() == 0


def test_replace_mode_removes_previous_questions() -> None:
    """replace — по умолчанию: прежние вопросы стираются вместе с вариантами."""
    quiz = TestFactory.create()
    old = QuestionFactory.create(test=quiz, position=1)
    payload = parse_questions(json.dumps(one_question()))

    import_questions(quiz, payload, ImportMode.REPLACE)

    assert not Question.objects.filter(pk=old.pk).exists()
    assert list(Question.objects.filter(test=quiz).values_list("position", flat=True)) == [1]


def test_append_mode_continues_numbering() -> None:
    """append дописывает в конец, не ломая нумерацию прежних вопросов."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=1)
    QuestionFactory.create(test=quiz, position=2)
    payload = parse_questions(json.dumps(one_question()))

    import_questions(quiz, payload, ImportMode.APPEND)

    assert list(Question.objects.filter(test=quiz).values_list("position", flat=True)) == [1, 2, 3]


def test_file_is_kept_as_archive(settings: Settings, tmp_path: Path) -> None:
    """Исходник остаётся в questions_file — потом видно, из чего собран тест."""
    settings.MEDIA_ROOT = tmp_path
    quiz = TestFactory.create()

    import_questions_from_file(quiz, as_upload(one_question()))

    saved = Test.objects.get(pk=quiz.pk).questions_file
    assert saved.name is not None
    assert saved.name.endswith(".json")
    assert json.loads(saved.read())["questions"][0]["text"] == "Сколько будет два плюс два?"


def test_command_imports_example_file(settings: Settings, tmp_path: Path) -> None:
    """Команда для сеялки и демо-данных заводит вопросы из файла."""
    settings.MEDIA_ROOT = tmp_path
    quiz = TestFactory.create()

    call_command("import_questions", "--test", str(quiz.pk), "--file", str(EXAMPLE_FILE))

    assert Question.objects.filter(test=quiz).count() == EXAMPLE_QUESTIONS


def test_command_complains_about_missing_file() -> None:
    """Нет файла — понятная ошибка до всякой работы с базой."""
    quiz = TestFactory.create()

    with pytest.raises(CommandError, match="Файла нет"):
        call_command("import_questions", "--test", str(quiz.pk), "--file", "нет-такого.json")


def test_command_complains_about_unknown_test() -> None:
    """Неверный id теста — тоже ошибка команды, а не исключение модели."""
    with pytest.raises(CommandError, match="Теста с id="):
        call_command("import_questions", "--test", "999999", "--file", str(EXAMPLE_FILE))


def test_command_reports_file_problems(tmp_path: Path) -> None:
    """Претензии к файлу команда печатает списком, каждую с новой строки."""
    quiz = TestFactory.create()
    broken = tmp_path / "broken.json"
    broken.write_text('{"questions": [{"text": "Вопрос", "options": []}]}', encoding="utf-8")

    with pytest.raises(CommandError, match="Файл не подошёл"):
        call_command("import_questions", "--test", str(quiz.pk), "--file", str(broken))

    assert Question.objects.count() == 0


def test_import_button_is_on_test_page(admin_client: Client) -> None:
    """Кнопка загрузки видна на странице теста — иначе её никто не найдёт."""
    quiz = TestFactory.create()

    page = admin_client.get(reverse("admin:quizzes_test_change", args=[quiz.pk])).content.decode()

    assert reverse("admin:quizzes_test_import_questions", args=[quiz.pk]) in page
    assert "Загрузить вопросы из JSON" in page


def test_admin_import_creates_questions(
    admin_client: Client, settings: Settings, tmp_path: Path
) -> None:
    """Загрузка через админку: файл принят, вопросы на месте, редирект на тест."""
    settings.MEDIA_ROOT = tmp_path
    quiz = TestFactory.create()

    response = admin_client.post(
        reverse("admin:quizzes_test_import_questions", args=[quiz.pk]),
        data={"file": as_upload(EXAMPLE_FILE.read_text(encoding="utf-8")), "mode": "replace"},
    )

    assert response.status_code == 302
    assert Question.objects.filter(test=quiz).count() == EXAMPLE_QUESTIONS


def test_admin_import_shows_what_is_wrong(admin_client: Client) -> None:
    """Кривой файл: форма возвращается с путём до поля, в базе пусто."""
    quiz = TestFactory.create()
    data = one_question(options=[{"text": "Четыре"}, {"text": "Пять"}])

    response = admin_client.post(
        reverse("admin:quizzes_test_import_questions", args=[quiz.pk]),
        data={"file": as_upload(data), "mode": "replace"},
    )

    assert response.status_code == 200
    assert "хотя бы один верный вариант" in response.content.decode()
    assert Question.objects.count() == 0


def test_admin_import_rejects_non_json_file(admin_client: Client) -> None:
    """Расширение проверяет форма — до чтения содержимого."""
    quiz = TestFactory.create()

    response = admin_client.post(
        reverse("admin:quizzes_test_import_questions", args=[quiz.pk]),
        data={"file": as_upload(one_question(), name="questions.txt"), "mode": "replace"},
    )

    assert response.status_code == 200
    assert Question.objects.count() == 0


def test_admin_import_needs_change_permission(client: Client) -> None:
    """Сотрудник без прав на тесты страницу загрузки не откроет."""
    from django.contrib.auth.models import User

    quiz = TestFactory.create()
    staff = User.objects.create_user(username="без-прав", is_staff=True)
    client.force_login(staff)

    response = client.get(reverse("admin:quizzes_test_import_questions", args=[quiz.pk]))

    assert response.status_code == 403
