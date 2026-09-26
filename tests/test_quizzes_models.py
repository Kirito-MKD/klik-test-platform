"""Тесты, вопросы и варианты ответа: констрейнты, каскады и счётчик вопросов."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from apps.catalog.models import Module
from apps.quizzes.models import AnswerOption, Question, Test
from tests.factories import (
    AnswerOptionFactory,
    QuestionFactory,
    TestFactory,
)

pytestmark = pytest.mark.django_db


def check_deferred_constraints() -> None:
    """Просит базу проверить отложенные констрейнты прямо сейчас.

    `question_position_unique_per_test` объявлен DEFERRABLE INITIALLY DEFERRED,
    то есть срабатывает на коммите. Внутри теста коммита нет — pytest-django
    откатывает транзакцию, — поэтому проверку запрашиваем явно.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_title_is_unique_inside_module() -> None:
    """UNIQUE (module, title): в одном блоке двух тестов с одним названием нет."""
    quiz = TestFactory.create(title="Сложение дробей")

    with pytest.raises(IntegrityError), transaction.atomic():
        TestFactory.create(module=quiz.module, title="Сложение дробей")


def test_only_one_active_test_per_module() -> None:
    """Блок показывает один тест: второй активный база не примет."""
    quiz = TestFactory.create(is_active=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        TestFactory.create(module=quiz.module, is_active=True)


def test_hidden_tests_in_a_module_are_not_limited() -> None:
    """Скрытых тестов в блоке сколько угодно — ограничение только на активные."""
    quiz = TestFactory.create(is_active=True)

    TestFactory.create_batch(3, module=quiz.module, is_active=False)

    assert Test.objects.filter(module=quiz.module).count() == 4


def test_active_test_may_repeat_in_another_module() -> None:
    """Ограничение живёт внутри блока: в соседнем блоке свой активный тест."""
    TestFactory.create(is_active=True)
    TestFactory.create(is_active=True)

    assert Test.objects.filter(is_active=True).count() == 2


def test_title_may_repeat_in_another_module() -> None:
    """Уникальность в рамках блока: в соседнем блоке то же название допустимо."""
    TestFactory.create(title="Итоговый")
    TestFactory.create(title="Итоговый")

    assert Test.objects.filter(title="Итоговый").count() == 2


@pytest.mark.parametrize("minutes", [0, 181])
def test_duration_outside_1_180_is_rejected(minutes: int) -> None:
    """CHECK на время теста: ноль и больше трёх часов база не примет."""
    with pytest.raises(IntegrityError), transaction.atomic():
        TestFactory.create(duration_minutes=minutes)


@pytest.mark.parametrize("minutes", [1, 180])
def test_duration_bounds_are_allowed(minutes: int) -> None:
    """Границы диапазона — допустимые значения, а не запрещённые."""
    quiz = TestFactory.create(duration_minutes=minutes)

    assert Test.objects.get(pk=quiz.pk).duration_minutes == minutes


def test_module_with_tests_is_protected_from_deletion() -> None:
    """PROTECT: блок с тестами не удаляется, тесты не пропадают молча."""
    quiz = TestFactory.create()

    with pytest.raises(ProtectedError):
        quiz.module.delete()

    assert Module.objects.count() == 1


def test_questions_file_accepts_only_json() -> None:
    """В `questions_file` кладут JSON — валидатор расширения ловит остальное."""
    quiz = TestFactory.create()

    quiz.questions_file = "tests/questions/2026/09/questions.txt"
    with pytest.raises(ValidationError) as error:
        quiz.full_clean()
    assert "questions_file" in error.value.message_dict

    quiz.questions_file = "tests/questions/2026/09/questions.json"
    quiz.full_clean()


def test_question_position_is_unique_inside_test() -> None:
    """UNIQUE (test, position): два вопроса с одним номером база не сохранит."""
    quiz = TestFactory.create()
    QuestionFactory.create(test=quiz, position=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        QuestionFactory.create(test=quiz, position=1)
        check_deferred_constraints()


def test_question_position_may_repeat_in_another_test() -> None:
    """Номер уникален внутри теста: первый вопрос есть у каждого."""
    QuestionFactory.create(test=TestFactory.create(), position=1)
    QuestionFactory.create(test=TestFactory.create(), position=1)

    assert Question.objects.filter(position=1).count() == 2


def test_questions_can_be_swapped_in_one_transaction() -> None:
    """Ради этого констрейнт и сделан отложенным: перестановка одной транзакцией.

    С обычным UNIQUE первый же UPDATE упал бы на промежуточном состоянии, где
    у двух вопросов одинаковый номер.
    """
    quiz = TestFactory.create()
    first = QuestionFactory.create(test=quiz, position=1)
    second = QuestionFactory.create(test=quiz, position=2)

    with transaction.atomic():
        Question.objects.filter(pk=first.pk).update(position=2)
        Question.objects.filter(pk=second.pk).update(position=1)
        check_deferred_constraints()

    assert list(Question.objects.filter(test=quiz).values_list("pk", flat=True)) == [
        second.pk,
        first.pk,
    ]


def test_deleting_test_removes_questions_and_options() -> None:
    """CASCADE: вопросы и варианты живут только вместе со своим тестом."""
    option = AnswerOptionFactory.create()

    option.question.test.delete()

    assert Question.objects.count() == 0
    assert AnswerOption.objects.count() == 0


def test_deleting_question_removes_its_options() -> None:
    """CASCADE у вариантов ответа — вопрос удаляется вместе с ними."""
    option = AnswerOptionFactory.create()

    option.question.delete()

    assert AnswerOption.objects.count() == 0


def test_with_question_count_counts_questions_of_each_test() -> None:
    """Счётчика вопросов в таблице нет — его считает запрос."""
    empty = TestFactory.create()
    filled = TestFactory.create()
    QuestionFactory.create_batch(3, test=filled)

    counts = {quiz.pk: quiz.questions_count for quiz in Test.objects.with_question_count()}

    assert counts == {empty.pk: 0, filled.pk: 3}


def test_questions_are_ordered_by_position() -> None:
    """Вопросы отдаются в порядке `position`, а не в порядке создания."""
    quiz = TestFactory.create()
    third = QuestionFactory.create(test=quiz, position=3)
    first = QuestionFactory.create(test=quiz, position=1)
    second = QuestionFactory.create(test=quiz, position=2)

    assert list(Question.objects.filter(test=quiz)) == [first, second, third]


def test_question_type_defaults_to_single() -> None:
    """По умолчанию вопрос с одним верным ответом — фронт рисует радиокнопки."""
    question = QuestionFactory.create()

    assert question.type == Question.Type.SINGLE


def test_active_returns_only_visible_tests() -> None:
    """Менеджер теста умеет и `active()`, и `with_question_count()`."""
    visible = TestFactory.create(is_active=True)
    TestFactory.create(is_active=False)

    assert list(Test.objects.active()) == [visible]
    assert list(Test.objects.active().with_question_count()) == [visible]


def test_visible_leaves_out_tests_of_hidden_modules_and_categories() -> None:
    """На сайте тест виден, только если показываются он сам, его блок и категория."""
    shown = TestFactory.create()
    TestFactory.create(is_active=False)
    TestFactory.create(module__is_active=False)
    TestFactory.create(module__category__is_active=False)

    assert list(Test.objects.visible()) == [shown]
    assert list(Test.objects.visible().with_question_count()) == [shown]


def test_str_shows_title_number_and_text() -> None:
    """В админке и логах объекты должны читаться, а не показывать `object (1)`."""
    quiz = TestFactory.create(title="Сложение дробей")
    question = QuestionFactory.create(test=quiz, position=7, text="Сколько будет два плюс два?")
    option = AnswerOptionFactory.create(question=question, text="Четыре")

    assert str(quiz) == "Сложение дробей"
    assert str(question).startswith("7. Сколько")
    assert str(option) == "Четыре"
