"""Маршруты первой версии API.

Адреса выписаны руками, а не собраны роутером: это четыре конкретных запроса
фронта, а не CRUD по каждой таблице, и роутер завёл бы лишние эндпоинты.
"""

from django.urls import URLPattern, URLResolver, path

from apps.api.v1.catalog import ModuleListView
from apps.api.v1.health import HealthView
from apps.api.v1.quizzes import AnswerCheckView, ModuleTestView, TestQuestionsView

app_name = "v1"

urlpatterns: list[URLPattern | URLResolver] = [
    path("health/", HealthView.as_view(), name="health"),
    # Активные блоки с характеристиками категории.
    path("modules/", ModuleListView.as_view(), name="module-list"),
    # Активный тест блока.
    path("modules/<int:module_id>/test/", ModuleTestView.as_view(), name="module-test"),
    # Вопросы теста с вариантами ответа.
    path("tests/<int:test_id>/questions/", TestQuestionsView.as_view(), name="test-questions"),
    # Проверка верности варианта ответа.
    path("answers/check/", AnswerCheckView.as_view(), name="answer-check"),
]
