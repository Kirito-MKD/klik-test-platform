# pyright: reportPrivateImportUsage=false
# factory-boy не реэкспортирует имена деклараций явно: factory.Sequence — это
# публичный API библиотеки, но для pyright — приватный импорт.
"""Фабрики factory-boy: дерево категория → блок → тест → вопрос собирается одной строкой.

`QuestionFactory()` сам создаёт тест, блок и категорию, поэтому в тестах руками
заводится только то, что для теста существенно.
"""

import factory
from factory.django import DjangoModelFactory

from apps.catalog.models import Category, Module
from apps.quizzes.models import AnswerOption, Question, Test


class CategoryFactory(DjangoModelFactory[Category]):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Категория {n}")
    bg_color = "#C9E9F6"


class ModuleFactory(DjangoModelFactory[Module]):
    class Meta:
        model = Module

    category = factory.SubFactory(CategoryFactory)
    title = factory.Sequence(lambda n: f"Блок {n}")


class TestFactory(DjangoModelFactory[Test]):
    # Тот же флаг, что и у модели: имя начинается с Test, и pytest пытается
    # собрать фабрику как тест-класс.
    __test__ = False

    class Meta:
        model = Test

    module = factory.SubFactory(ModuleFactory)
    title = factory.Sequence(lambda n: f"Тест {n}")


class QuestionFactory(DjangoModelFactory[Question]):
    class Meta:
        model = Question

    test = factory.SubFactory(TestFactory)
    text = factory.Sequence(lambda n: f"Вопрос {n}?")
    # Позиция уникальна в рамках теста: сквозная нумерация фабрики не даст совпасть
    # двум вопросам одного теста, а там, где номер важен, он передаётся явно.
    position = factory.Sequence(lambda n: n + 1)


class AnswerOptionFactory(DjangoModelFactory[AnswerOption]):
    class Meta:
        model = AnswerOption

    question = factory.SubFactory(QuestionFactory)
    text = factory.Sequence(lambda n: f"Вариант {n}")
    is_correct = False
