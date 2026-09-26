"""API первой версии: контракт фронта и общие договорённости.

Контракт — четыре запроса из README. Отдельно проверяется то, что общее
для всех эндпоинтов: конверт ошибки, id запроса, троттлинг, CORS и схема.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from django.http import Http404
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from pytest_django.fixtures import Settings
from rest_framework.throttling import AnonRateThrottle

from apps.api.exceptions import VALIDATION_MESSAGE, api_exception_handler, split_detail
from apps.api.pagination import PageNumberPagination
from apps.api.v1.catalog import ModuleListView
from apps.api.v1.health import HealthView
from apps.api.v1.quizzes import TestQuestionsView
from apps.quizzes.models import Question
from tests.factories import (
    AnswerOptionFactory,
    CategoryFactory,
    ModuleFactory,
    QuestionFactory,
    TestFactory,
)

pytestmark = pytest.mark.django_db

MODULES = "/api/v1/modules/"
CHECK = "/api/v1/answers/check/"
HEALTH = "/api/v1/health/"


def module_test_url(module_id: int) -> str:
    """Адрес второго запроса контракта — активный тест блока."""
    return f"/api/v1/modules/{module_id}/test/"


def questions_url(test_id: int) -> str:
    """Адрес третьего запроса контракта — вопросы теста."""
    return f"/api/v1/tests/{test_id}/questions/"


@pytest.fixture(autouse=True)
def _clean_throttle_history() -> Iterator[None]:
    """Троттлинг живёт в кэше: без очистки тесты влияли бы друг на друга."""
    cache.clear()
    yield
    cache.clear()


def body(response: Any) -> Any:
    return response.json()


def check(client: Client, **ids: int) -> Any:
    """POST на проверку ответа: тело только JSON, парсер форм у API выключен."""
    return client.post(CHECK, data=json.dumps(ids), content_type="application/json")


def tighten_throttle(monkeypatch: pytest.MonkeyPatch, rate: str = "1/min") -> None:
    """Ставит жёсткий лимит на время теста.

    Правим `THROTTLE_RATES` у самого класса, а не настройки: DRF читает частоты
    один раз при импорте, и подмена REST_FRAMEWORK на живой процесс уже не влияет.
    """
    monkeypatch.setattr(AnonRateThrottle, "THROTTLE_RATES", {"anon": rate})


# ─── 1. Блоки с характеристиками категории ──────────────────────────


def test_modules_list_has_the_contract_shape(client: Client) -> None:
    """Формат из требований: id, title и вложенная категория с оформлением."""
    module = ModuleFactory.create(title="Run Marco", category__name="design")

    data = body(client.get(MODULES))

    assert data == [
        {
            "id": module.pk,
            "title": "Run Marco",
            "category": {
                "id": module.category.pk,
                "name": "design",
                "bg_color": module.category.bg_color,
                "image": None,
            },
        }
    ]


def test_modules_list_is_a_bare_array(client: Client) -> None:
    """Контракт ждёт массив, а не конверт пагинации с `results`."""
    ModuleFactory.create()

    assert isinstance(body(client.get(MODULES)), list)


def test_modules_list_returns_only_active(client: Client) -> None:
    """«Только активные блоки» — прямое требование контракта."""
    visible = ModuleFactory.create(is_active=True)
    ModuleFactory.create(is_active=False)

    data = body(client.get(MODULES))

    assert [item["id"] for item in data] == [visible.pk]


def test_modules_of_a_hidden_category_are_not_shown(client: Client) -> None:
    """Скрытая категория прячет и свои блоки: предмета на сайте больше нет."""
    ModuleFactory.create(category__is_active=False)

    assert body(client.get(MODULES)) == []


def test_category_image_is_an_absolute_url(
    client: Client, settings: Settings, tmp_path: Path
) -> None:
    """Стикер уезжает абсолютной ссылкой — фронт вставляет её в src как есть."""
    settings.MEDIA_ROOT = tmp_path
    ModuleFactory.create(
        category__image=SimpleUploadedFile("sticker.png", b"png", content_type="image/png")
    )

    image = body(client.get(MODULES))[0]["category"]["image"]

    assert image.startswith("http://testserver/media/categories/")


def test_modules_list_does_not_query_per_row(client: Client) -> None:
    """Категория приезжает через select_related, а не отдельным запросом на блок."""
    category = CategoryFactory.create()
    ModuleFactory.create(category=category)

    with CaptureQueriesContext(connection) as one_row:
        client.get(MODULES)

    ModuleFactory.create_batch(4, category=category)
    with CaptureQueriesContext(connection) as five_rows:
        client.get(MODULES)

    assert len(five_rows) == len(one_row)


# ─── 2. Активный тест блока ─────────────────────────────────────────


def test_module_test_returns_the_card(client: Client) -> None:
    """Карточка теста: id, название, количество вопросов и время."""
    quiz = TestFactory.create(title="Проверочный тест", duration_minutes=20)
    QuestionFactory.create_batch(3, test=quiz)

    data = body(client.get(module_test_url(quiz.module.pk)))

    assert data == {
        "id": quiz.pk,
        "title": "Проверочный тест",
        "question_count": 3,
        "duration_minutes": 20,
    }


def test_module_test_skips_hidden_tests_of_the_same_module(client: Client) -> None:
    """В блоке отдаётся активный тест, скрытые соседи на выдачу не влияют."""
    module = ModuleFactory.create()
    TestFactory.create(module=module, title="Скрытый", is_active=False)
    visible = TestFactory.create(module=module, title="Видимый")

    assert body(client.get(module_test_url(module.pk)))["id"] == visible.pk


def test_module_test_ignores_tests_of_other_modules(client: Client) -> None:
    """Тест берётся из своего блока, а не первый попавшийся."""
    quiz = TestFactory.create()
    TestFactory.create()

    assert body(client.get(module_test_url(quiz.module.pk)))["id"] == quiz.pk


def test_hidden_test_is_not_given_out(client: Client) -> None:
    """Скрытый тест не отдаётся: у блока нет активного — значит 404."""
    quiz = TestFactory.create(is_active=False)

    assert client.get(module_test_url(quiz.module.pk)).status_code == 404


def test_test_of_a_hidden_module_is_not_given_out(client: Client) -> None:
    """Скрытый блок не отдаёт свой тест даже по прямой ссылке."""
    quiz = TestFactory.create(module__is_active=False)

    assert client.get(module_test_url(quiz.module.pk)).status_code == 404


def test_test_of_a_hidden_category_is_not_given_out(client: Client) -> None:
    """Скрытая категория прячет тест своего блока так же, как сам блок."""
    quiz = TestFactory.create(module__category__is_active=False)

    assert client.get(module_test_url(quiz.module.pk)).status_code == 404


def test_module_without_tests_answers_404(client: Client) -> None:
    """Блок без активного теста — 404 с общим конвертом ошибки."""
    module = ModuleFactory.create()

    response = client.get(module_test_url(module.pk))

    assert response.status_code == 404
    assert body(response)["error"]["code"] == "not_found"


# ─── 3. Вопросы теста с вариантами ответа ───────────────────────────


def test_questions_have_the_contract_shape(client: Client) -> None:
    """Формат из требований: вопрос с position, type, text и вариантами."""
    question = QuestionFactory.create(text="Что такое цикл?", position=1)
    right = AnswerOptionFactory.create(question=question, text="Повтор", is_correct=True)
    wrong = AnswerOptionFactory.create(question=question, text="Ошибка", is_correct=False)

    data = body(client.get(questions_url(question.test.pk)))

    assert data == [
        {
            "id": question.pk,
            "position": 1,
            "type": "single",
            "text": "Что такое цикл?",
            "options": [
                {"id": right.pk, "text": "Повтор"},
                {"id": wrong.pk, "text": "Ошибка"},
            ],
        }
    ]


def test_questions_do_not_give_away_correct_answers(client: Client) -> None:
    """Верный ответ остаётся на сервере: иначе тест видно во вкладке «Сеть».

    Единственный способ узнать правильность — запрос проверки варианта.
    """
    question = QuestionFactory.create()
    AnswerOptionFactory.create(question=question, is_correct=True)

    raw = client.get(questions_url(question.test.pk)).content.decode()

    assert "is_correct" not in raw


def test_questions_are_ordered_by_position(client: Client) -> None:
    """Порядок вопросов задаёт position, а не порядок создания."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=2)
    QuestionFactory.create(test=quiz, position=1)

    data = body(client.get(questions_url(quiz.pk)))

    assert [item["position"] for item in data] == [1, 2]


def test_questions_of_a_hidden_test_are_not_given_out(client: Client) -> None:
    """Скрытый тест не отдаёт вопросы: иначе его можно пройти мимо каталога."""
    quiz = TestFactory.create(is_active=False)
    QuestionFactory.create(test=quiz)

    assert client.get(questions_url(quiz.pk)).status_code == 404


def test_questions_of_a_hidden_module_are_not_given_out(client: Client) -> None:
    """Скрытый блок закрывает и вопросы своего теста, даже по прямой ссылке."""
    quiz = TestFactory.create(module__is_active=False)
    QuestionFactory.create(test=quiz)

    assert client.get(questions_url(quiz.pk)).status_code == 404


def test_questions_of_a_hidden_category_are_not_given_out(client: Client) -> None:
    """Скрытая категория закрывает вопросы тестов во всех своих блоках."""
    quiz = TestFactory.create(module__category__is_active=False)
    QuestionFactory.create(test=quiz)

    assert client.get(questions_url(quiz.pk)).status_code == 404


def test_questions_of_an_unknown_test_answer_404(client: Client) -> None:
    """Несуществующий тест — 404, а не пустой массив."""
    assert client.get(questions_url(999999)).status_code == 404


def test_questions_do_not_query_per_row(client: Client) -> None:
    """Варианты забираются одним prefetch, а не запросом на каждый вопрос."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz)

    with CaptureQueriesContext(connection) as one_row:
        client.get(questions_url(quiz.pk))

    QuestionFactory.create_batch(4, test=quiz)
    with CaptureQueriesContext(connection) as five_rows:
        client.get(questions_url(quiz.pk))

    assert len(five_rows) == len(one_row)


def test_multiple_question_keeps_its_type(client: Client) -> None:
    """Тип вопроса уезжает как есть: по нему фронт рисует чекбоксы вместо радио."""
    question = QuestionFactory.create(type=Question.Type.MULTIPLE)

    assert body(client.get(questions_url(question.test.pk)))[0]["type"] == "multiple"


# ─── 4. Проверка верности ответа ────────────────────────────────────


def test_check_says_true_for_the_correct_option(client: Client) -> None:
    """Верный вариант — true."""
    question = QuestionFactory.create()
    option = AnswerOptionFactory.create(question=question, is_correct=True)

    response = check(
        client,
        test_id=question.test.pk,
        question_id=question.pk,
        option_id=option.pk,
    )

    assert response.status_code == 200
    assert body(response) == {"is_correct": True}


def test_check_says_false_for_the_wrong_option(client: Client) -> None:
    """Неверный вариант — false, а не ошибка."""
    question = QuestionFactory.create()
    option = AnswerOptionFactory.create(question=question, is_correct=False)

    response = check(
        client,
        test_id=question.test.pk,
        question_id=question.pk,
        option_id=option.pk,
    )

    assert body(response) == {"is_correct": False}


def test_check_rejects_an_option_from_another_question(client: Client) -> None:
    """Связку «тест → вопрос → вариант» проверяем целиком, а не по одному id."""
    question = QuestionFactory.create()
    stranger = AnswerOptionFactory.create(is_correct=True)

    response = check(
        client,
        test_id=question.test.pk,
        question_id=question.pk,
        option_id=stranger.pk,
    )

    assert response.status_code == 404
    assert body(response)["error"]["code"] == "not_found"


def test_check_rejects_a_question_from_another_test(client: Client) -> None:
    """Чужой тест в связке — тоже 404."""
    question = QuestionFactory.create()
    option = AnswerOptionFactory.create(question=question, is_correct=True)
    other = TestFactory.create()

    response = check(client, test_id=other.pk, question_id=question.pk, option_id=option.pk)

    assert response.status_code == 404


def test_check_is_closed_for_a_hidden_test(client: Client) -> None:
    """Скрытый тест не проверяет ответы — его на сайте нет."""
    question = QuestionFactory.create(test__is_active=False)
    option = AnswerOptionFactory.create(question=question, is_correct=True)

    response = check(
        client,
        test_id=question.test.pk,
        question_id=question.pk,
        option_id=option.pk,
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "hidden",
    [
        pytest.param({"test__module__is_active": False}, id="hidden_module"),
        pytest.param({"test__module__category__is_active": False}, id="hidden_category"),
    ],
)
def test_check_is_closed_when_the_test_is_off_the_site(client: Client, hidden: Any) -> None:
    """Тест скрытого блока или категории тоже не проверяет ответы: на сайте его нет."""
    question = QuestionFactory.create(**hidden)
    option = AnswerOptionFactory.create(question=question, is_correct=True)

    response = check(
        client,
        test_id=question.test.pk,
        question_id=question.pk,
        option_id=option.pk,
    )

    assert response.status_code == 404


def test_check_requires_all_three_ids(client: Client) -> None:
    """Неполное тело — 400 с разбором по полям, а не 500."""
    response = client.post(CHECK, data=json.dumps({"test_id": 1}), content_type="application/json")
    details = body(response)["error"]["details"]

    assert response.status_code == 400
    assert set(details) == {"question_id", "option_id"}


def test_check_needs_no_csrf_token(client: Client) -> None:
    """Фронт ходит с другого домена без куки: CSRF-токена у него нет и быть не должно."""
    question = QuestionFactory.create()
    option = AnswerOptionFactory.create(question=question, is_correct=True)
    strict = Client(enforce_csrf_checks=True)

    response = strict.post(
        CHECK,
        data=json.dumps(
            {
                "test_id": question.test.pk,
                "question_id": question.pk,
                "option_id": option.pk,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200


def test_check_does_the_lookup_in_one_query(client: Client) -> None:
    """Связку и активность теста проверяем одним запросом, а не тремя."""
    question = QuestionFactory.create()
    option = AnswerOptionFactory.create(question=question, is_correct=True)

    with CaptureQueriesContext(connection) as queries:
        check(
            client,
            test_id=question.test.pk,
            question_id=question.pk,
            option_id=option.pk,
        )

    assert len(queries) == 1


# ─── общие договорённости ───────────────────────────────────────────


def test_contract_lists_opt_out_of_pagination() -> None:
    """Пагинация остаётся умолчанием для будущих списков, контрактные — без неё.

    Если кто-то уберёт `pagination_class = None`, фронт вместо массива получит
    конверт с `results` — эта проверка ловит такую правку.
    """
    assert ModuleListView.pagination_class is None
    assert TestQuestionsView.pagination_class is None
    assert PageNumberPagination.max_page_size == 100


def test_health_says_ok(client: Client) -> None:
    """Healthcheck контейнера: сервис жив и база отвечает."""
    response = client.get(HEALTH)

    assert response.status_code == 200
    assert body(response) == {"status": "ok", "database": "ok"}


def test_health_is_not_throttled(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Мониторинг стучится часто — ограничение частоты его не касается."""
    tighten_throttle(monkeypatch)

    assert HealthView.throttle_classes == ()
    assert client.get(HEALTH).status_code == 200
    assert client.get(HEALTH).status_code == 200


def test_health_reports_unavailable_database(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если база недоступна, healthcheck обязан сказать 503, а не 200."""

    def no_database() -> None:
        raise OperationalError("база недоступна")

    monkeypatch.setattr(connection, "ensure_connection", no_database)

    response = client.get(HEALTH)

    assert response.status_code == 503
    assert body(response)["database"] == "unavailable"


def test_error_has_the_common_envelope(client: Client) -> None:
    """Любая ошибка выглядит одинаково: error.code, error.message, meta.request_id."""
    response = client.get(module_test_url(999999))
    data = body(response)

    assert response.status_code == 404
    assert data["error"]["code"] == "not_found"
    # Не техническое «No Test matches the given query», а текст для человека.
    assert data["error"]["message"] == "Активный тест для этого блока не найден."
    assert data["error"]["details"] == {}
    assert data["meta"]["request_id"]


def test_request_id_from_the_caller_is_kept(client: Client) -> None:
    """Свой id запроса уважаем: по нему сходятся логи фронта и бэкенда."""
    response = client.get(module_test_url(999999), headers={"x-request-id": "abc123"})

    assert response.headers["X-Request-ID"] == "abc123"
    assert body(response)["meta"]["request_id"] == "abc123"


def test_request_id_is_generated_when_missing(client: Client) -> None:
    """Если id не пришёл, заводим свой — иначе в логах ошибку не найти."""
    response = client.get(MODULES)

    assert response.headers["X-Request-ID"]


def test_anonymous_requests_are_throttled(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Эндпоинты публичные, без ограничения частоты это открытая дверь."""
    tighten_throttle(monkeypatch)

    assert client.get(MODULES).status_code == 200
    response = client.get(MODULES)
    data = body(response)

    assert response.status_code == 429
    assert data["error"]["code"] == "throttled"
    assert data["meta"]["request_id"]


def test_spoofed_forwarded_for_does_not_reset_the_limit(
    client: Client, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """За nginx клиента опознаём по адресу, который дописал nginx, а не по всему заголовку.

    Левую часть X-Forwarded-For присылает сам клиент. Считай мы по строке
    целиком, каждый запрос с новым выдуманным адресом начинал бы лимит заново.
    """
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    tighten_throttle(monkeypatch)

    first = client.get(MODULES, headers={"x-forwarded-for": "10.0.0.1, 203.0.113.7"})
    second = client.get(MODULES, headers={"x-forwarded-for": "10.0.0.2, 203.0.113.7"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_cors_answers_only_the_configured_origin(client: Client, settings: Settings) -> None:
    """CORS списком, а не звёздочкой."""
    settings.CORS_ALLOWED_ORIGINS = ["https://klik.example"]

    allowed = client.get(MODULES, headers={"origin": "https://klik.example"})
    stranger = client.get(MODULES, headers={"origin": "https://chuzhoy.example"})

    assert allowed.headers["Access-Control-Allow-Origin"] == "https://klik.example"
    assert "Access-Control-Allow-Origin" not in stranger.headers


def test_handler_lets_unknown_errors_through() -> None:
    """Не наша ошибка — не наш конверт: 500 должен дойти до логов как есть."""
    assert api_exception_handler(RuntimeError("что-то сломалось"), {}) is None


def test_handler_wraps_http404() -> None:
    """Http404 приводим к тому же конверту и меняем технический текст на людской.

    Внутри Http404 обычно лежит «No Test matches the given query» — наружу ему
    ехать незачем.
    """
    response = api_exception_handler(Http404("No Test matches the given query"), {"request": None})

    assert response is not None
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"
    assert "No Test matches" not in response.data["error"]["message"]


def test_handler_wraps_django_permission_denied() -> None:
    """PermissionDenied из Django тоже приводим к общему виду."""
    response = api_exception_handler(PermissionDenied(), {"request": None})

    assert response is not None
    assert response.status_code == 403
    assert response.data["error"]["code"] == "permission_denied"
    assert response.data["meta"]["request_id"] == ""


@pytest.mark.parametrize(
    ("raw", "expected_message", "expected_details"),
    [
        (["так нельзя"], VALIDATION_MESSAGE, {"errors": ["так нельзя"]}),
        ("просто строка", "просто строка", {}),
        ({"detail": "не найдено"}, "не найдено", {}),
        ({"module": ["кривое значение"]}, VALIDATION_MESSAGE, {"module": ["кривое значение"]}),
    ],
)
def test_detail_is_split_into_message_and_fields(
    raw: Any, expected_message: str, expected_details: dict[str, Any]
) -> None:
    """Сообщение для человека и разбор по полям — разные части конверта."""
    assert split_detail(raw) == (expected_message, expected_details)


def test_schema_is_generated_from_code(client: Client) -> None:
    """Схема OpenAPI отдаётся эндпоинтом — отдельного документа фронту не нужно."""
    response = client.get(reverse("schema"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "openapi" in content
    assert "/api/v1/modules/" in content
    assert "/api/v1/modules/{module_id}/test/" in content
    assert "/api/v1/answers/check/" in content


def test_docs_page_opens(client: Client) -> None:
    """Страница документации открывается — на неё зовут фронт."""
    response = client.get(reverse("docs"))

    assert response.status_code == 200
