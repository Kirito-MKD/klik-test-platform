"""Формы и правила формсетов, общие для админки и студии.

Правила вопроса («вариантов хотя бы два», «верный хотя бы один», «у single
верный ровно один») живут здесь, а не в админке: тот же вопрос теперь правится
и в студии, и разойтись эти проверки не должны.
"""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.forms.models import BaseInlineFormSet

from apps.quizzes.models import MIN_ANSWER_OPTIONS, AnswerOption, Question
from apps.quizzes.services.import_questions import ImportMode

MODE_CHOICES = (
    (ImportMode.REPLACE.value, "Заменить: стереть прежние вопросы теста"),
    (ImportMode.APPEND.value, "Дописать: добавить в конец, нумерация продолжится"),
)


class QuestionsImportForm(forms.Form):
    """Загрузка файла с вопросами на странице теста."""

    file = forms.FileField(
        label="Файл с вопросами",
        help_text="JSON строгого формата: объект с ключом questions. Образец — рядом на странице.",
        validators=[FileExtensionValidator(["json"])],
    )
    mode = forms.ChoiceField(
        label="Что делать с прежними вопросами",
        choices=MODE_CHOICES,
        initial=ImportMode.REPLACE.value,
        widget=forms.RadioSelect,
    )


def kept_rows(formset: BaseInlineFormSet[Any, Any, Any]) -> list[dict[str, Any]]:
    """Строки формсета, которые останутся после сохранения.

    Пустые добавочные формы и помеченные на удаление не считаем — иначе правила
    проверялись бы по тому, что видно на экране, а не по тому, что уедет в базу.
    """
    return [
        form.cleaned_data
        for form in formset.forms
        if form.cleaned_data and not form.cleaned_data.get("DELETE")
    ]


class AnswerOptionInlineFormSet(
    BaseInlineFormSet[AnswerOption, Question, forms.ModelForm[AnswerOption]]
):
    """Правила вопроса: вариантов хотя бы два, верный хотя бы один."""

    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return

        rows = kept_rows(self)
        if len(rows) < MIN_ANSWER_OPTIONS:
            raise ValidationError(f"Вариантов ответа должно быть не меньше {MIN_ANSWER_OPTIONS}.")

        correct = sum(1 for row in rows if row.get("is_correct"))
        if not correct:
            raise ValidationError("Отметьте хотя бы один верный вариант.")
        if correct > 1 and self.instance.type == Question.Type.SINGLE:
            raise ValidationError(
                "У вопроса с одним верным ответом верный вариант может быть только один: "
                "поменяйте тип на «Несколько верных ответов» или снимите лишние отметки."
            )
