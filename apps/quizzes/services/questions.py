"""Вопросы, заведённые руками.

Импорт файла лежит рядом, в `import_questions`: там вопросы приезжают пачкой,
здесь — по одному со страницы студии. Общее у них — нумерация: `position`
уникален внутри теста, поэтому номер нового вопроса и перенумерация после
удаления считаются в одном месте.
"""

from django.db import transaction
from django.db.models import Max

from apps.catalog.models import Module
from apps.quizzes.models import Question, Test


def next_position(test: Test) -> int:
    """Номер следующего вопроса теста — на единицу больше последнего."""
    last = Question.objects.filter(test=test).aggregate(Max("position"))["position__max"] or 0
    return last + 1


def has_questions(test: Test) -> bool:
    """Есть ли в тесте хоть один вопрос.

    От этого зависит, можно ли показывать тест на сайте: правило одно и то же
    в админке, в правке карточки и в кнопке «показать на сайте».
    """
    return Question.objects.filter(test=test).exists()


def active_test_of(module: Module, besides: Test | None = None) -> Test | None:
    """Тест, который уже показывается в этом блоке.

    Блок показывает один тест, это держит констрейнт базы. Формы и кнопки
    спрашивают заранее, чтобы вместо ошибки базы человек увидел, какой именно
    тест занимает место.
    """
    others = Test.objects.filter(module=module, is_active=True)
    if besides is not None and besides.pk:
        others = others.exclude(pk=besides.pk)
    return others.first()


@transaction.atomic
def after_questions_removed(test: Test) -> bool:
    """Приводит тест в порядок после того, как из него ушли вопросы.

    Нумерация снова идёт подряд, а тест, в котором не осталось ни одного
    вопроса, уходит с сайта: проходить в нём нечего. Правило одно для студии
    и админки. Возвращает True, если тест пришлось скрыть, — об этом стоит
    сказать человеку.
    """
    renumber(test)
    if test.is_active and not has_questions(test):
        test.is_active = False
        test.save(update_fields=["is_active", "updated_at"])
        return True
    return False


@transaction.atomic
def renumber(test: Test) -> None:
    """Сдвигает номера так, чтобы шли подряд с первого.

    Нужна после удаления вопроса: дырка в нумерации сама по себе не ломает
    ни порядок, ни констрейнт, но контент-менеджер видит «1, 2, 4» и идёт
    спрашивать, что случилось с третьим. Констрейнт deferrable, поэтому
    промежуточные совпадения номеров внутри транзакции допустимы.
    """
    for number, question in enumerate(
        Question.objects.filter(test=test).order_by("position", "id"), start=1
    ):
        if question.position != number:
            question.position = number
            question.save(update_fields=["position"])
