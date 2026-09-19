"""Админка тестов.

Вложенные inline Django не умеет, поэтому варианты ответа правятся на странице
вопроса — на неё ведёт ссылка из инлайна теста. Правила формсетов общие с студией
и лежат в `apps.quizzes.forms`: только в формсете видно и родителя, и строки,
пришедшие в том же запросе.
"""

from typing import cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.forms.models import BaseInlineFormSet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import URLPattern, path
from django.utils.text import Truncator

from apps.quizzes.forms import (
    AnswerOptionInlineFormSet,
    QuestionsImportForm,
    kept_rows,
)
from apps.quizzes.models import (
    MIN_ANSWER_OPTIONS,
    AnswerOption,
    Question,
    Test,
    TestQuerySet,
)
from apps.quizzes.services.import_questions import (
    ImportMode,
    QuestionsFileError,
    import_questions_from_file,
)


class QuestionInlineFormSet(BaseInlineFormSet[Question, Test, forms.ModelForm[Question]]):
    """Тест без вопросов не должен уехать на сайт."""

    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return
        if self.instance.is_active and not kept_rows(self):
            raise ValidationError(
                "Тест без вопросов нельзя показывать на сайте: добавьте вопросы "
                "или снимите галочку «показывать на сайте»."
            )


class QuestionInline(admin.TabularInline[Question, Test]):
    model = Question
    formset = QuestionInlineFormSet
    fields = ("position", "text", "type")
    ordering = ("position",)
    extra = 0
    show_change_link = True
    verbose_name_plural = "вопросы (варианты ответа — на странице вопроса)"


class AnswerOptionInline(admin.TabularInline[AnswerOption, Question]):
    model = AnswerOption
    formset = AnswerOptionInlineFormSet
    fields = ("text", "is_correct")
    extra = MIN_ANSWER_OPTIONS


@admin.register(Test)
class TestAdmin(admin.ModelAdmin[Test]):
    # Имя начинается с Test — pytest иначе пробует собрать класс как тест.
    __test__ = False

    list_display = (
        "title",
        "module",
        "category_name",
        "questions_number",
        "duration_minutes",
        "is_active",
    )
    list_filter = ("is_active", "module__category")
    list_select_related = ("module", "module__category")
    search_fields = ("title",)
    autocomplete_fields = ("module",)
    inlines = (QuestionInline,)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("module", "title", "duration_minutes", "is_active")}),
        (
            "Файл с вопросами",
            {
                "fields": ("questions_file",),
                "description": "Здесь лежит последний загруженный файл — как архив. "
                "Чтобы залить вопросы, нажмите «Загрузить вопросы из JSON» вверху страницы.",
            },
        ),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Test]:
        # Счётчика вопросов в таблице нет: считаем одним запросом вместе со списком,
        # иначе колонка «вопросов» даст N+1.
        queryset = cast("TestQuerySet", super().get_queryset(request))
        return queryset.with_question_count()

    @admin.display(description="категория", ordering="module__category__name")
    def category_name(self, quiz: Test) -> str:
        return quiz.module.category.name

    @admin.display(description="вопросов", ordering="questions_count")
    def questions_number(self, quiz: Test) -> int:
        return quiz.questions_count

    def get_urls(self) -> list[URLPattern]:
        own = [
            path(
                "<int:test_id>/import-questions/",
                self.admin_site.admin_view(self.import_questions_view),
                name="quizzes_test_import_questions",
            ),
        ]
        # Свой маршрут раньше стандартных: иначе его перехватит `<path:object_id>/`.
        return own + super().get_urls()

    def import_questions_view(self, request: HttpRequest, test_id: int) -> HttpResponse:
        """Страница за кнопкой «Загрузить вопросы из JSON»."""
        quiz = get_object_or_404(Test, pk=test_id)
        if not self.has_change_permission(request, quiz):
            raise PermissionDenied

        form = QuestionsImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                created = import_questions_from_file(
                    quiz,
                    form.cleaned_data["file"],
                    ImportMode(form.cleaned_data["mode"]),
                )
            except QuestionsFileError as error:
                # Претензии показываем у поля с файлом: человек видит их рядом с формой.
                for problem in error.problems:
                    form.add_error("file", problem)
            else:
                self.message_user(request, f"Загружено вопросов: {created}.", messages.SUCCESS)
                return redirect("admin:quizzes_test_change", quiz.pk)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "original": quiz,
            "title": f"Загрузка вопросов: {quiz.title}",
            "form": form,
        }
        return TemplateResponse(request, "admin/quizzes/test/import_questions.html", context)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin[Question]):
    list_display = ("position", "short_text", "test", "type")
    list_display_links = ("position", "short_text")
    list_filter = ("type", "test__module__category")
    list_select_related = ("test", "test__module")
    search_fields = ("text",)
    autocomplete_fields = ("test",)
    inlines = (AnswerOptionInline,)
    ordering = ("test", "position")

    @admin.display(description="вопрос")
    def short_text(self, question: Question) -> str:
        return Truncator(question.text).chars(80)
