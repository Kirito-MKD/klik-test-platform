"""Импорт вопросов из JSON.

Вся бизнес-логика здесь: и админка, и management-команда только приносят файл.
Запись идёт одной транзакцией — на кривом файле в базе не остаётся ни строки.
"""

import json
from enum import StrEnum

from django.core.files.base import File
from django.db import transaction
from pydantic import ValidationError

from apps.quizzes.models import AnswerOption, Question, Test
from apps.quizzes.schemas import QuestionsFile, describe_errors
from apps.quizzes.services.questions import next_position


class ImportMode(StrEnum):
    """Что делать с вопросами, которые уже есть в тесте."""

    REPLACE = "replace"
    APPEND = "append"


class QuestionsFileError(Exception):
    """Файл не подходит: не разбирается как JSON или нарушены правила формата.

    В `problems` — по строке на каждую претензию, с путём до поля.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def parse_questions(raw: bytes | str) -> QuestionsFile:
    """Разбирает и проверяет файл, не трогая базу."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise QuestionsFileError([f"Файл не разбирается как JSON: {error}"]) from error

    try:
        return QuestionsFile.model_validate(data)
    except ValidationError as error:
        raise QuestionsFileError(describe_errors(error)) from error


@transaction.atomic
def import_questions(
    test: Test,
    payload: QuestionsFile,
    mode: ImportMode = ImportMode.REPLACE,
) -> int:
    """Пишет вопросы в тест и возвращает их количество.

    `replace` стирает прежние вопросы (вместе с вариантами — каскадом),
    `append` дописывает в конец, продолжая нумерацию.
    """
    if mode is ImportMode.REPLACE:
        Question.objects.filter(test=test).delete()
        last_position = 0
    else:
        # Нумерацию продолжает тот же счётчик, что и у вопросов, заведённых руками.
        last_position = next_position(test) - 1

    questions = Question.objects.bulk_create(
        Question(
            test=test,
            text=question.text,
            type=question.type,
            position=last_position + number,
        )
        for number, question in enumerate(payload.questions, start=1)
    )
    AnswerOption.objects.bulk_create(
        AnswerOption(question=created, text=option.text, is_correct=option.is_correct)
        for created, question in zip(questions, payload.questions, strict=True)
        for option in question.options
    )
    return len(questions)


@transaction.atomic
def import_questions_from_file(
    test: Test,
    uploaded: File[bytes],
    mode: ImportMode = ImportMode.REPLACE,
) -> int:
    """Разбирает файл, пишет вопросы и оставляет исходник в `questions_file`."""
    uploaded.seek(0)
    payload = parse_questions(uploaded.read())
    created = import_questions(test, payload, mode)

    uploaded.seek(0)
    test.questions_file = uploaded
    test.save(update_fields=["questions_file", "updated_at"])
    return created
