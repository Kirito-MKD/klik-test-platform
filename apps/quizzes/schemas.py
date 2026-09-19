"""Формат файла с вопросами.

Строгая схема: лишние ключи не проглатываем молча, а называем. Ошибки pydantic
несут путь до поля, поэтому контент-менеджер видит, в каком именно вопросе беда,
а не «файл не подошёл».

Формат файла:

    {
      "questions": [
        {
          "text": "Сколько будет два плюс два?",
          "type": "single",
          "options": [
            {"text": "Четыре", "is_correct": true},
            {"text": "Пять"}
          ]
        }
      ]
    }

Эталон целиком — `docs/examples/questions.json`.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from apps.quizzes.models import MAX_ANSWER_OPTIONS, MIN_ANSWER_OPTIONS

STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnswerOptionIn(BaseModel):
    """Вариант ответа из файла."""

    model_config = STRICT

    text: Annotated[str, Field(min_length=1, max_length=500)]
    is_correct: bool = False


class QuestionIn(BaseModel):
    """Вопрос из файла. Порядок задаётся местом в массиве, поле position не нужно."""

    model_config = STRICT

    text: Annotated[str, Field(min_length=1)]
    type: Literal["single", "multiple"] = "single"
    options: Annotated[
        list[AnswerOptionIn],
        Field(min_length=MIN_ANSWER_OPTIONS, max_length=MAX_ANSWER_OPTIONS),
    ]

    @model_validator(mode="after")
    def check_correct_options(self) -> Self:
        correct = sum(1 for option in self.options if option.is_correct)
        if not correct:
            raise ValueError("нужен хотя бы один верный вариант (is_correct: true)")
        if self.type == "single" and correct > 1:
            raise ValueError(
                'у вопроса с типом single верный вариант ровно один — поставьте "type": "multiple"'
            )
        return self


class QuestionsFile(BaseModel):
    """Корень файла."""

    model_config = STRICT

    questions: Annotated[list[QuestionIn], Field(min_length=1)]


def describe_errors(error: ValidationError) -> list[str]:
    """Ошибки pydantic в виде «путь до поля: что не так».

    Нумерация в пути — как в файле, с нуля: `questions → 3 → options → 1 → text`
    читается вместе с открытым JSON.
    """
    return [
        f"{' → '.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
