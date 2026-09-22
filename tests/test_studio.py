"""Студия — страницы загрузки тестов вне админки.

Проверяем так, как это делает человек в браузере: заходит по адресу, отправляет
форму, видит ошибку или результат. Права — те же, что у админки, но «статус
персонала» студии не нужен.
"""

import json
import re
from typing import Any

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.models import QuerySet
from django.test import Client
from django.test.utils import CaptureQueriesContext
from pytest_django.fixtures import Settings

from apps.catalog.models import Module
from apps.common.management.commands.setup_content_group import CONTENT_GROUP_NAME
from apps.quizzes.models import (
    MAX_ANSWER_OPTIONS,
    MIN_ANSWER_OPTIONS,
    AnswerOption,
    Question,
    Test,
)
from apps.quizzes.services.import_questions import parse_questions
from apps.quizzes.services.questions import renumber
from apps.studio.prompt import questions_prompt
from apps.studio.sample import SAMPLE, sample_json
from apps.studio.templatetags.studio_assets import studio_asset
from tests.factories import (
    AnswerOptionFactory,
    CategoryFactory,
    ModuleFactory,
    QuestionFactory,
    TestFactory,
)

pytestmark = pytest.mark.django_db

INDEX = "/studio/"
LOGIN = "/studio/login/"
CREATE = "/studio/tests/new/"


def detail_url(test_id: int) -> str:
    return f"/studio/tests/{test_id}/"


def upload_url(test_id: int) -> str:
    return f"/studio/tests/{test_id}/upload/"


def edit_url(test_id: int) -> str:
    return f"/studio/tests/{test_id}/edit/"


def toggle_url(test_id: int) -> str:
    return f"/studio/tests/{test_id}/toggle/"


def question_create_url(test_id: int) -> str:
    return f"/studio/tests/{test_id}/questions/new/"


def question_edit_url(test_id: int, question_id: int) -> str:
    return f"/studio/tests/{test_id}/questions/{question_id}/"


def question_delete_url(test_id: int, question_id: int) -> str:
    return f"/studio/tests/{test_id}/questions/{question_id}/delete/"


def options_of(question: Question) -> QuerySet[AnswerOption]:
    """Варианты вопроса по порядку создания.

    Через менеджер, а не через `question.options`: обратный аксессор
    basedpyright не видит, и каждая такая строка становится ошибкой проверки.
    """
    return AnswerOption.objects.filter(question=question).order_by("id")


def question_data(**overrides: str) -> dict[str, str]:
    """Форма вопроса вместе с формсетом вариантов — так их шлёт браузер."""
    data = {
        "text": "Сколько будет 2 + 2?",
        "type": "single",
        "options-TOTAL_FORMS": "2",
        "options-INITIAL_FORMS": "0",
        "options-MIN_NUM_FORMS": "0",
        "options-MAX_NUM_FORMS": str(MAX_ANSWER_OPTIONS),
        "options-0-text": "4",
        "options-0-is_correct": "on",
        "options-1-text": "5",
    }
    data.update(overrides)
    return data


def questions_file(payload: Any = None, name: str = "questions.json") -> SimpleUploadedFile:
    """Файл с вопросами так, как его выбирают в форме."""
    raw = json.dumps(payload if payload is not None else SAMPLE, ensure_ascii=False)
    return SimpleUploadedFile(name, raw.encode(), content_type="application/json")


@pytest.fixture
def editor() -> User:
    """Контент-менеджер: группа «Контент», без статуса персонала."""
    call_command("setup_content_group")
    user = User.objects.create_user(username="editor", password="studio-pass")
    user.groups.add(Group.objects.get(name=CONTENT_GROUP_NAME))
    return user


@pytest.fixture
def studio(client: Client, editor: User) -> Client:
    """Клиент, уже вошедший в студию."""
    client.force_login(editor)
    return client


# ─── доступ ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [INDEX, CREATE, "/studio/modules/new/", "/studio/categories/new/", "/studio/sample/"],
)
def test_anonymous_is_sent_to_login(client: Client, url: str) -> None:
    """Аноним не видит ни одной страницы студии — его ведут на форму входа."""
    response = client.get(url)

    assert response.status_code == 302
    assert response.headers["Location"].startswith(LOGIN)


def test_user_without_rights_gets_403(client: Client) -> None:
    """Вошёл, но прав на тесты нет — 403, а не список чужого контента."""
    client.force_login(User.objects.create_user(username="stranger", password="pass"))

    assert client.get(INDEX).status_code == 403


def test_login_page_opens_and_lets_in(client: Client, editor: User) -> None:
    """Вход работает логином и паролем от админки."""
    assert client.get(LOGIN).status_code == 200

    response = client.post(LOGIN, {"username": "editor", "password": "studio-pass"})

    assert response.status_code == 302
    assert response.headers["Location"] == INDEX


def test_logout_returns_to_login(studio: Client) -> None:
    """Выход — POST из шапки, после него снова форма входа."""
    response = studio.post("/studio/logout/")

    assert response.status_code == 302
    assert studio.get(INDEX).headers["Location"].startswith(LOGIN)


def test_staff_status_is_not_required(studio: Client, editor: User) -> None:
    """Студия открыта тому, кому в саму админку заходить незачем."""
    assert not editor.is_staff
    assert studio.get(INDEX).status_code == 200


# ─── список тестов ──────────────────────────────────────────────────


def test_index_shows_tests_with_counts(studio: Client) -> None:
    """В списке видно название, блок с категорией и количество вопросов."""
    quiz = TestFactory.create(title="Проверочный тест", module__title="Числа и счёт")
    QuestionFactory.create_batch(3, test=quiz)

    page = re.sub(r"\s+", " ", studio.get(INDEX).content.decode())

    assert "Проверочный тест" in page
    assert "Числа и счёт" in page
    assert 'data-label="Вопросов"> 3 <' in page


def test_index_warns_about_tests_without_questions(studio: Client) -> None:
    """Пустой тест виден сразу: на сайт его всё равно не пустят."""
    TestFactory.create()

    page = studio.get(INDEX).content.decode()

    assert "Тестов без вопросов: 1" in page


def test_index_search_filters_by_title(studio: Client) -> None:
    """Поиск по названию — по тесту и по блоку."""
    TestFactory.create(title="Дроби")
    TestFactory.create(title="Углы")

    page = studio.get(INDEX, {"q": "Дроб"}).content.decode()

    assert "Дроби" in page
    assert "Углы" not in page


def test_index_filters_by_category(studio: Client) -> None:
    """Фильтр по категории — рабочий инструмент, когда предметов много."""
    wanted = TestFactory.create(title="Дроби")
    TestFactory.create(title="Углы")

    page = studio.get(INDEX, {"category": wanted.module.category.pk}).content.decode()

    assert "Дроби" in page
    assert "Углы" not in page


def test_index_explains_the_first_step_when_empty(studio: Client) -> None:
    """Пустое состояние объясняет следующий шаг, а не просто «нет данных»."""
    page = studio.get(INDEX).content.decode()

    assert "Здесь пока пусто" in page
    assert "Новый тест" in page


# ─── создание теста ─────────────────────────────────────────────────


def test_create_test_with_questions(studio: Client) -> None:
    """Главный сценарий: выбрал блок, заполнил поля, приложил файл — тест готов."""
    module = ModuleFactory.create()

    response = studio.post(
        CREATE,
        {
            "module": module.pk,
            "title": "Сложение",
            "duration_minutes": 10,
            "is_active": "on",
            "file": questions_file(),
        },
    )

    quiz = Test.objects.get(title="Сложение")
    assert response.status_code == 302
    assert response.headers["Location"] == detail_url(quiz.pk)
    assert quiz.module == module
    assert Question.objects.filter(test=quiz).count() == len(SAMPLE["questions"])
    assert AnswerOption.objects.filter(question__test=quiz).count() == 6


def test_created_test_keeps_the_source_file(studio: Client) -> None:
    """Загруженный файл остаётся при тесте как архив исходника."""
    module = ModuleFactory.create()

    studio.post(
        CREATE,
        {
            "module": module.pk,
            "title": "Сложение",
            "duration_minutes": 10,
            "file": questions_file(name="matematika.json"),
        },
    )

    stored = Test.objects.get(title="Сложение").questions_file.name or ""
    assert "matematika" in stored


def test_broken_file_leaves_no_test_behind(studio: Client) -> None:
    """Кривой файл не должен оставить тест-пустышку: одна транзакция на всё."""
    module = ModuleFactory.create()

    response = studio.post(
        CREATE,
        {
            "module": module.pk,
            "title": "Сложение",
            "duration_minutes": 10,
            "file": questions_file({"questions": [{"text": "Без вариантов"}]}),
        },
    )
    page = response.content.decode()

    assert response.status_code == 200
    assert not Test.objects.filter(title="Сложение").exists()
    assert "options" in page


def test_not_a_json_file_is_rejected_by_extension(studio: Client) -> None:
    """Файл не того расширения отсекается до разбора."""
    module = ModuleFactory.create()

    response = studio.post(
        CREATE,
        {
            "module": module.pk,
            "title": "Сложение",
            "duration_minutes": 10,
            "file": SimpleUploadedFile("questions.txt", b"{}", content_type="text/plain"),
        },
    )

    assert response.status_code == 200
    assert not Test.objects.filter(title="Сложение").exists()


def test_duplicate_title_in_a_module_is_named(studio: Client) -> None:
    """Два теста с одним названием в блоке — ошибка формы, а не 500 из базы."""
    quiz = TestFactory.create(title="Сложение")

    response = studio.post(
        CREATE,
        {
            "module": quiz.module.pk,
            "title": "Сложение",
            "duration_minutes": 10,
            "file": questions_file(),
        },
    )

    assert response.status_code == 200
    assert Test.objects.filter(title="Сложение").count() == 1
    assert "уже существует" in response.content.decode()


def test_create_page_shows_the_file_format(studio: Client) -> None:
    """Образец формата стоит на той же странице, где просят файл."""
    page = studio.get(CREATE).content.decode()

    assert "Формат файла с вопросами" in page
    assert "is_correct" in page


def test_module_select_shows_the_category(studio: Client) -> None:
    """В списке блоков видно категорию: одинаковые названия блоков не редкость."""
    ModuleFactory.create(title="Числа и счёт", category__name="Математика")

    page = studio.get(CREATE).content.decode()

    assert "Математика · Числа и счёт" in page


# ─── карточка теста ─────────────────────────────────────────────────


def test_detail_shows_questions_with_correct_options(studio: Client) -> None:
    """На карточке видно и текст вопроса, и какой вариант верный."""
    question = QuestionFactory.create(text="Что такое цикл?", position=1)
    AnswerOptionFactory.create(question=question, text="Повтор", is_correct=True)
    AnswerOptionFactory.create(question=question, text="Ошибка")

    page = studio.get(detail_url(question.test.pk)).content.decode()

    assert "Что такое цикл?" in page
    assert "Повтор" in page
    assert "верный" in page


def test_detail_of_an_unknown_test_is_404(studio: Client) -> None:
    """Несуществующий тест — 404."""
    assert studio.get(detail_url(999999)).status_code == 404


def test_upload_replaces_previous_questions(studio: Client) -> None:
    """Режим «заменить» стирает прежние вопросы теста."""
    quiz = TestFactory.create()
    QuestionFactory.create_batch(4, test=quiz)

    response = studio.post(upload_url(quiz.pk), {"file": questions_file(), "mode": "replace"})

    assert response.status_code == 302
    assert Question.objects.filter(test=quiz).count() == len(SAMPLE["questions"])


def test_upload_appends_and_continues_numbering(studio: Client) -> None:
    """Режим «дописать» продолжает нумерацию, а не начинает заново."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=1)

    studio.post(upload_url(quiz.pk), {"file": questions_file(), "mode": "append"})

    positions = list(
        Question.objects.filter(test=quiz).order_by("position").values_list("position", flat=True)
    )
    assert positions == [1, 2, 3]


def test_upload_error_keeps_old_questions(studio: Client) -> None:
    """Ошибка в файле не трогает то, что уже загружено."""
    quiz = TestFactory.create()
    QuestionFactory.create_batch(2, test=quiz)

    response = studio.post(
        upload_url(quiz.pk),
        {"file": questions_file({"questions": []}), "mode": "replace"},
    )

    assert response.status_code == 200
    assert Question.objects.filter(test=quiz).count() == 2


def test_upload_without_a_file_names_the_field(studio: Client) -> None:
    """Отправили форму без файла — ошибка у поля, а не пустая страница."""
    quiz = TestFactory.create()

    response = studio.post(upload_url(quiz.pk), {"mode": "replace"})

    assert response.status_code == 200
    assert "Обязательное поле" in response.content.decode()


def test_upload_needs_the_change_right(client: Client) -> None:
    """Загрузка закрыта для того, у кого нет права менять тесты."""
    quiz = TestFactory.create()
    client.force_login(User.objects.create_user(username="stranger", password="pass"))

    response = client.post(upload_url(quiz.pk), {"file": questions_file(), "mode": "replace"})

    assert response.status_code == 403


def test_edit_saves_the_card(studio: Client) -> None:
    """Название, блок и время правятся на той же странице."""
    quiz = TestFactory.create(title="Старое название", duration_minutes=10)
    QuestionFactory.create(test=quiz)

    response = studio.post(
        edit_url(quiz.pk),
        {
            "module": quiz.module.pk,
            "title": "Новое название",
            "duration_minutes": 25,
            "is_active": "on",
        },
    )

    quiz.refresh_from_db()
    assert response.status_code == 302
    assert (quiz.title, quiz.duration_minutes) == ("Новое название", 25)


def test_empty_test_cannot_be_shown_on_the_site(studio: Client) -> None:
    """Правило админки работает и здесь: тест без вопросов на сайт не уедет."""
    quiz = TestFactory.create(is_active=False)

    response = studio.post(
        edit_url(quiz.pk),
        {
            "module": quiz.module.pk,
            "title": quiz.title,
            "duration_minutes": quiz.duration_minutes,
            "is_active": "on",
        },
    )

    quiz.refresh_from_db()
    assert response.status_code == 200
    assert not quiz.is_active
    assert "сначала добавьте вопросы" in response.content.decode()


def test_edit_with_a_bad_duration_shows_the_error(studio: Client) -> None:
    """Время вне диапазона — ошибка у поля, а не падение на констрейнте базы."""
    quiz = TestFactory.create()

    response = studio.post(
        edit_url(quiz.pk),
        {
            "module": quiz.module.pk,
            "title": quiz.title,
            "duration_minutes": 999,
            "is_active": "",
        },
    )

    quiz.refresh_from_db()
    assert response.status_code == 200
    assert quiz.duration_minutes != 999


def test_detail_does_not_query_per_question(studio: Client) -> None:
    """Варианты ответа забираются одним prefetch, а не запросом на вопрос."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz)

    with CaptureQueriesContext(connection) as one_question:
        studio.get(detail_url(quiz.pk))

    QuestionFactory.create_batch(4, test=quiz)
    with CaptureQueriesContext(connection) as five_questions:
        studio.get(detail_url(quiz.pk))

    assert len(five_questions) == len(one_question)


# ─── каталог ────────────────────────────────────────────────────────


def test_module_is_created_from_the_studio(studio: Client) -> None:
    """Блок заводится здесь же: иначе тест некуда положить."""
    category = CategoryFactory.create()

    response = studio.post(
        "/studio/modules/new/",
        {"category": category.pk, "title": "Числа и счёт", "is_active": "on"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == CREATE
    assert Module.objects.filter(category=category, title="Числа и счёт").exists()


def test_category_is_created_from_the_studio(studio: Client) -> None:
    """Категория — тоже: путь «категория → блок → тест» проходится целиком."""
    response = studio.post(
        "/studio/categories/new/",
        {"name": "Математика", "bg_color": "#C9E9F6", "is_active": "on"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/studio/modules/new/"


def test_category_color_must_be_hex(studio: Client) -> None:
    """Цвет проверяется формой: в базу кривое значение не уедет."""
    response = studio.post(
        "/studio/categories/new/",
        {"name": "Математика", "bg_color": "голубой", "is_active": "on"},
    )

    assert response.status_code == 200
    assert "#RRGGBB" in response.content.decode()


# ─── образец файла ──────────────────────────────────────────────────


def test_sample_downloads_as_a_file(studio: Client) -> None:
    """Образец можно скачать, поправить и загрузить обратно."""
    response = studio.get("/studio/sample/")

    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert json.loads(response.content)["questions"]


def test_sample_is_a_valid_questions_file(studio: Client) -> None:
    """Образец обязан проходить тот же разбор, что и загруженный файл."""
    module = ModuleFactory.create()

    studio.post(
        CREATE,
        {
            "module": module.pk,
            "title": "Из образца",
            "duration_minutes": 10,
            "file": SimpleUploadedFile(
                "sample.json",
                studio.get("/studio/sample/").content,
                content_type="application/json",
            ),
        },
    )

    assert Question.objects.filter(test__title="Из образца").count() == 2


# ─── страницы целиком ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [INDEX, CREATE, "/studio/modules/new/", "/studio/categories/new/", LOGIN],
)
def test_pages_render_with_the_studio_stylesheet(client: Client, editor: User, url: str) -> None:
    """Каждая страница отдаёт свою вёрстку и стили, а не голый HTML админки."""
    client.force_login(editor)

    page = client.get(url).content.decode()

    assert "studio/studio.css" in page
    assert "Студия" in page


# ─── показать и скрыть тест ─────────────────────────────────────────


def test_toggle_hides_the_test(studio: Client) -> None:
    """Скрыть тест — одна кнопка, без открывания формы и правки полей."""
    quiz = TestFactory.create(is_active=True)
    QuestionFactory.create(test=quiz)

    response = studio.post(toggle_url(quiz.pk))

    quiz.refresh_from_db()
    assert response.status_code == 302
    assert response.headers["Location"] == detail_url(quiz.pk)
    assert not quiz.is_active


def test_toggle_shows_the_test_again(studio: Client) -> None:
    """Скрытый тест с вопросами возвращается на сайт той же кнопкой."""
    quiz = TestFactory.create(is_active=False)
    QuestionFactory.create(test=quiz)

    studio.post(toggle_url(quiz.pk))

    quiz.refresh_from_db()
    assert quiz.is_active


def test_toggle_refuses_to_publish_an_empty_test(studio: Client) -> None:
    """Правило то же, что в админке: пустой тест на сайт не уедет."""
    quiz = TestFactory.create(is_active=False)

    response = studio.post(toggle_url(quiz.pk), follow=True)

    quiz.refresh_from_db()
    assert not quiz.is_active
    assert "сначала добавьте вопросы" in response.content.decode()


def test_toggle_from_the_list_returns_to_the_list(studio: Client) -> None:
    """Нажали в списке — остаёмся в списке, а не улетаем в карточку."""
    quiz = TestFactory.create(is_active=True)
    QuestionFactory.create(test=quiz)

    response = studio.post(toggle_url(quiz.pk), {"back": "list"})

    assert response.headers["Location"] == INDEX


def test_toggle_needs_the_change_right(client: Client) -> None:
    """Скрывать и показывать тесты может только тот, кому можно их менять."""
    quiz = TestFactory.create()
    client.force_login(User.objects.create_user(username="stranger", password="pass"))

    assert client.post(toggle_url(quiz.pk)).status_code == 403


def test_toggle_is_not_available_by_link(studio: Client) -> None:
    """Переключение меняет данные, поэтому только POST: ссылкой его не дёрнуть."""
    quiz = TestFactory.create()

    assert studio.get(toggle_url(quiz.pk)).status_code == 405


def test_list_has_a_button_for_every_test(studio: Client) -> None:
    """Кнопка стоит прямо в строке списка."""
    quiz = TestFactory.create(is_active=True)

    page = studio.get(INDEX).content.decode()

    assert toggle_url(quiz.pk) in page
    assert "Скрыть" in page


# ─── промпт для подготовки файла ────────────────────────────────────


def test_create_page_offers_the_prompt(studio: Client) -> None:
    """Промпт лежит там же, где просят файл: материал обычно в обычном тексте."""
    page = studio.get(CREATE).content.decode()

    assert "Промпт: сделать JSON из обычного текста" in page
    assert "Скопировать промпт" in page


def test_detail_page_offers_the_prompt(studio: Client) -> None:
    """На карточке теста промпт тоже под рукой — рядом с повторной загрузкой."""
    quiz = TestFactory.create()

    assert "Скопировать промпт" in studio.get(detail_url(quiz.pk)).content.decode()


def test_prompt_carries_the_real_rules() -> None:
    """Промпт описывает тот формат, который проверяет разбор файла.

    Числа и пример подставляются из тех же констант и образца, поэтому промпт
    не может разойтись со схемой после правки формата.
    """
    prompt = questions_prompt()

    assert f"от {MIN_ANSWER_OPTIONS} до {MAX_ANSWER_OPTIONS}" in prompt
    assert sample_json() in prompt
    # Пример внутри промпта — валидный файл: разбираем его тем же кодом.
    assert len(parse_questions(sample_json()).questions) == len(SAMPLE["questions"])


def test_pages_load_the_script(studio: Client) -> None:
    """Кнопка копирования работает скриптом — он должен быть подключён."""
    assert "studio/studio.js" in studio.get(CREATE).content.decode()


# ─── вопросы руками ─────────────────────────────────────────────────


def test_question_page_opens_with_empty_rows(studio: Client) -> None:
    """Страница нового вопроса открывается и сразу даёт строки под варианты."""
    quiz = TestFactory.create()

    page = studio.get(question_create_url(quiz.pk)).content.decode()

    assert "Варианты ответа" in page
    assert "options-TOTAL_FORMS" in page
    assert "Добавить вариант" in page


def test_question_edit_page_shows_current_options(studio: Client) -> None:
    """На правке видно текст вопроса и его варианты, а не пустая форма."""
    question = QuestionFactory.create(text="Что такое цикл?", position=1)
    AnswerOptionFactory.create(question=question, text="Повтор", is_correct=True)

    page = studio.get(question_edit_url(question.test.pk, question.pk)).content.decode()

    assert "Что такое цикл?" in page
    assert "Повтор" in page
    assert "Удалить вопрос" in page


def test_question_is_added_by_hand(studio: Client) -> None:
    """Главное, чего не хватало: вопрос заводится прямо в студии, без файла."""
    quiz = TestFactory.create()

    response = studio.post(question_create_url(quiz.pk), question_data())

    question = Question.objects.get(test=quiz)
    assert response.status_code == 302
    assert response.headers["Location"] == detail_url(quiz.pk)
    assert question.text == "Сколько будет 2 + 2?"
    assert question.position == 1
    assert list(options_of(question).values_list("text", "is_correct")) == [
        ("4", True),
        ("5", False),
    ]


def test_added_question_goes_to_the_end(studio: Client) -> None:
    """Новый вопрос встаёт в конец, нумерация продолжается."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=1)

    studio.post(question_create_url(quiz.pk), question_data())

    positions = list(
        Question.objects.filter(test=quiz).order_by("position").values_list("position", flat=True)
    )
    assert positions == [1, 2]


def test_question_needs_two_options(studio: Client) -> None:
    """Вопрос с одним вариантом — не вопрос: форма возвращается с ошибкой."""
    quiz = TestFactory.create()

    response = studio.post(question_create_url(quiz.pk), question_data(**{"options-1-text": ""}))

    assert response.status_code == 200
    assert not Question.objects.filter(test=quiz).exists()
    assert "не меньше 2" in response.content.decode()


def test_question_needs_a_correct_option(studio: Client) -> None:
    """Без отмеченного верного варианта вопрос не сохранить."""
    quiz = TestFactory.create()

    response = studio.post(
        question_create_url(quiz.pk), question_data(**{"options-0-is_correct": ""})
    )

    assert response.status_code == 200
    assert not Question.objects.filter(test=quiz).exists()
    assert "хотя бы один верный" in response.content.decode()


def test_single_question_rejects_two_correct_options(studio: Client) -> None:
    """У вопроса с одним верным ответом отметка может быть только одна."""
    quiz = TestFactory.create()

    response = studio.post(
        question_create_url(quiz.pk), question_data(**{"options-1-is_correct": "on"})
    )

    assert response.status_code == 200
    assert not Question.objects.filter(test=quiz).exists()
    assert "только один" in response.content.decode()


def test_multiple_question_accepts_two_correct_options(studio: Client) -> None:
    """С типом «несколько верных» две отметки — норма."""
    quiz = TestFactory.create()

    studio.post(
        question_create_url(quiz.pk),
        question_data(type="multiple", **{"options-1-is_correct": "on"}),
    )

    question = Question.objects.get(test=quiz)
    assert question.type == Question.Type.MULTIPLE
    assert options_of(question).filter(is_correct=True).count() == 2


def test_question_text_is_required(studio: Client) -> None:
    """Пустой текст вопроса — ошибка у поля, а не сохранение пустышки."""
    quiz = TestFactory.create()

    response = studio.post(question_create_url(quiz.pk), question_data(text=""))

    assert response.status_code == 200
    assert not Question.objects.filter(test=quiz).exists()


def test_question_is_edited(studio: Client) -> None:
    """Текст вопроса и верный вариант правятся на той же странице."""
    question = QuestionFactory.create(text="Старый текст", position=1)
    first = AnswerOptionFactory.create(question=question, text="4", is_correct=True)
    second = AnswerOptionFactory.create(question=question, text="5", is_correct=False)

    response = studio.post(
        question_edit_url(question.test.pk, question.pk),
        question_data(
            text="Новый текст",
            **{
                "options-INITIAL_FORMS": "2",
                "options-0-id": str(first.pk),
                "options-0-is_correct": "",
                "options-1-id": str(second.pk),
                "options-1-is_correct": "on",
            },
        ),
    )

    question.refresh_from_db()
    assert response.status_code == 302
    assert question.text == "Новый текст"
    assert list(options_of(question).values_list("is_correct", flat=True)) == [
        False,
        True,
    ]


def test_option_is_removed_on_edit(studio: Client) -> None:
    """Лишний вариант убирается галочкой «убрать»."""
    question = QuestionFactory.create(position=1)
    first = AnswerOptionFactory.create(question=question, text="4", is_correct=True)
    second = AnswerOptionFactory.create(question=question, text="5")
    third = AnswerOptionFactory.create(question=question, text="6")

    studio.post(
        question_edit_url(question.test.pk, question.pk),
        question_data(
            **{
                "options-TOTAL_FORMS": "3",
                "options-INITIAL_FORMS": "3",
                "options-0-id": str(first.pk),
                "options-1-id": str(second.pk),
                "options-1-is_correct": "",
                "options-2-id": str(third.pk),
                "options-2-text": "6",
                "options-2-DELETE": "on",
            },
        ),
    )

    assert list(options_of(question).values_list("text", flat=True)) == ["4", "5"]


def test_last_options_cannot_be_removed(studio: Client) -> None:
    """Убрать так, чтобы остался один вариант, форма не даст."""
    question = QuestionFactory.create(position=1)
    first = AnswerOptionFactory.create(question=question, text="4", is_correct=True)
    second = AnswerOptionFactory.create(question=question, text="5")

    response = studio.post(
        question_edit_url(question.test.pk, question.pk),
        question_data(
            **{
                "options-INITIAL_FORMS": "2",
                "options-0-id": str(first.pk),
                "options-1-id": str(second.pk),
                "options-1-is_correct": "",
                "options-1-DELETE": "on",
            },
        ),
    )

    assert response.status_code == 200
    assert options_of(question).count() == 2


def test_question_is_deleted_and_the_rest_renumbered(studio: Client) -> None:
    """После удаления номера идут подряд, без дырок."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=1)
    second = QuestionFactory.create(test=quiz, position=2)
    QuestionFactory.create(test=quiz, position=3)

    response = studio.post(question_delete_url(quiz.pk, second.pk))

    positions = list(
        Question.objects.filter(test=quiz).order_by("position").values_list("position", flat=True)
    )
    assert response.status_code == 302
    assert positions == [1, 2]


def test_deleting_the_last_question_hides_the_test(studio: Client) -> None:
    """Вопросов не осталось — тест сам уходит с сайта, а не висит пустым."""
    quiz = TestFactory.create(is_active=True)
    question = QuestionFactory.create(test=quiz, position=1)

    studio.post(question_delete_url(quiz.pk, question.pk))

    quiz.refresh_from_db()
    assert not quiz.is_active


def test_question_of_another_test_is_not_reachable(studio: Client) -> None:
    """Чужой вопрос по адресу этого теста не открывается."""
    quiz = TestFactory.create()
    stranger = QuestionFactory.create()

    assert studio.get(question_edit_url(quiz.pk, stranger.pk)).status_code == 404


@pytest.mark.parametrize("method", ["get", "post"])
def test_question_pages_need_rights(client: Client, method: str) -> None:
    """Заводить и править вопросы может только тот, кому можно."""
    quiz = TestFactory.create()
    client.force_login(User.objects.create_user(username="stranger", password="pass"))

    response = getattr(client, method)(question_create_url(quiz.pk))

    assert response.status_code == 403


def test_detail_invites_to_add_a_question(studio: Client) -> None:
    """С карточки теста видно, что вопрос можно завести и поправить руками."""
    question = QuestionFactory.create(position=1)

    page = studio.get(detail_url(question.test.pk)).content.decode()

    assert question_create_url(question.test.pk) in page
    assert "Добавить вопрос" in page
    assert question_edit_url(question.test.pk, question.pk) in page


def test_renumber_closes_gaps(studio: Client) -> None:
    """Перенумерация — отдельная функция домена, проверяем её напрямую."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=2)
    QuestionFactory.create(test=quiz, position=7)

    renumber(quiz)

    positions = list(
        Question.objects.filter(test=quiz).order_by("position").values_list("position", flat=True)
    )
    assert positions == [1, 2]


# ─── тест без файла ─────────────────────────────────────────────────


def test_test_is_created_without_a_file(studio: Client) -> None:
    """Файл необязателен: тест заводится пустым, чтобы набрать вопросы руками."""
    module = ModuleFactory.create()

    response = studio.post(
        CREATE,
        {"module": module.pk, "title": "Сложение", "duration_minutes": 10},
    )

    quiz = Test.objects.get(title="Сложение")
    assert response.status_code == 302
    # Сразу ведём на первый вопрос: пустой тест сам по себе бесполезен.
    assert response.headers["Location"] == question_create_url(quiz.pk)
    assert not Question.objects.filter(test=quiz).exists()
    assert not quiz.is_active


def test_test_without_a_file_cannot_be_active(studio: Client) -> None:
    """Показывать нечего: без вопросов галочка «на сайте» не проходит."""
    module = ModuleFactory.create()

    response = studio.post(
        CREATE,
        {
            "module": module.pk,
            "title": "Сложение",
            "duration_minutes": 10,
            "is_active": "on",
        },
    )

    assert response.status_code == 200
    assert not Test.objects.filter(title="Сложение").exists()
    assert "Показывать нечего" in response.content.decode()


def test_create_page_explains_both_ways(studio: Client) -> None:
    """На странице видно оба пути: набрать руками или загрузить файлом."""
    page = studio.get(CREATE).content.decode()

    assert "Набрать руками" in page
    assert "Загрузить файлом" in page


# ─── статика не залипает в кеше браузера ────────────────────────────


def test_styles_link_carries_a_version(studio: Client, settings: Settings) -> None:
    """К адресу стилей дописано время правки.

    Без этого браузер держит старый `studio.css`, и поправленная вёрстка
    выглядит сломанной — ровно это и случилось при первой проверке страницы.
    Отметка ставится в разработке, поэтому включаем DEBUG: в самих тестах
    pytest-django держит его выключенным.
    """
    settings.DEBUG = True

    page = studio.get(CREATE).content.decode()

    assert "studio/studio.css?v=" in page
    assert "studio/studio.js?v=" in page


def test_asset_version_is_dropped_outside_debug(settings: Settings) -> None:
    """На проде отметка не нужна: в имя файла уже зашит хеш содержимого."""
    settings.DEBUG = False

    assert studio_asset("studio/studio.css") == "/static/studio/studio.css"


def test_asset_survives_a_missing_file(settings: Settings) -> None:
    """Неизвестный файл не должен ронять страницу — отдаём обычный адрес."""
    settings.DEBUG = True

    assert studio_asset("studio/no-such-file.css") == "/static/studio/no-such-file.css"


# ─── в блоке один активный тест ─────────────────────────────────────


def test_second_active_test_is_refused_on_create(studio: Client) -> None:
    """Блок занят: второй тест туда не создать сразу активным."""
    busy = TestFactory.create(title="Первый", is_active=True)

    response = studio.post(
        CREATE,
        {
            "module": busy.module.pk,
            "title": "Второй",
            "duration_minutes": 10,
            "is_active": "on",
            "file": questions_file(),
        },
    )

    assert response.status_code == 200
    assert not Test.objects.filter(title="Второй").exists()
    assert "уже показывается тест «Первый»" in response.content.decode()


def test_second_test_can_be_created_hidden(studio: Client) -> None:
    """Скрытым — можно: ограничение только на тот, что показывается."""
    busy = TestFactory.create(is_active=True)

    response = studio.post(
        CREATE,
        {
            "module": busy.module.pk,
            "title": "Второй",
            "duration_minutes": 10,
            "file": questions_file(),
        },
    )

    assert response.status_code == 302
    assert not Test.objects.get(title="Второй").is_active


def test_second_active_test_is_refused_on_edit(studio: Client) -> None:
    """Правка карточки тоже не пропускает второй активный тест в блоке."""
    busy = TestFactory.create(title="Первый", is_active=True)
    quiz = TestFactory.create(module=busy.module, title="Второй", is_active=False)
    QuestionFactory.create(test=quiz)

    response = studio.post(
        edit_url(quiz.pk),
        {
            "module": quiz.module.pk,
            "title": quiz.title,
            "duration_minutes": quiz.duration_minutes,
            "is_active": "on",
        },
    )

    quiz.refresh_from_db()
    assert response.status_code == 200
    assert not quiz.is_active
    assert "уже показывается тест «Первый»" in response.content.decode()


def test_active_test_stays_editable(studio: Client) -> None:
    """Сам активный тест правится свободно: себя он не блокирует."""
    quiz = TestFactory.create(title="Первый", is_active=True)
    QuestionFactory.create(test=quiz)

    response = studio.post(
        edit_url(quiz.pk),
        {
            "module": quiz.module.pk,
            "title": "Первый, исправленный",
            "duration_minutes": 25,
            "is_active": "on",
        },
    )

    quiz.refresh_from_db()
    assert response.status_code == 302
    assert quiz.title == "Первый, исправленный"
    assert quiz.is_active


def test_toggle_refuses_when_module_is_busy(studio: Client) -> None:
    """Кнопка «показать» отказывает с тем же объяснением, что и форма."""
    busy = TestFactory.create(title="Первый", is_active=True)
    quiz = TestFactory.create(module=busy.module, title="Второй", is_active=False)
    QuestionFactory.create(test=quiz)

    response = studio.post(toggle_url(quiz.pk), follow=True)

    quiz.refresh_from_db()
    assert not quiz.is_active
    assert "уже показывается тест «Первый»" in response.content.decode()


def test_toggle_works_after_the_busy_test_is_hidden(studio: Client) -> None:
    """Освободили блок — и тест показывается."""
    busy = TestFactory.create(is_active=True)
    quiz = TestFactory.create(module=busy.module, is_active=False)
    QuestionFactory.create(test=quiz)

    studio.post(toggle_url(busy.pk))
    studio.post(toggle_url(quiz.pk))

    quiz.refresh_from_db()
    busy.refresh_from_db()
    assert quiz.is_active
    assert not busy.is_active
