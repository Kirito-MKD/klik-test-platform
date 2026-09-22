"""Тест, его вопросы и варианты ответа.

Схема базы — в README. Количество вопросов в базе не хранится:
его считает `Test.objects.with_question_count()`, поэтому рассинхронизироваться
нечему. Порядок тестов и вариантов ответа задаёт фронт, в базе есть только
`Question.position` — номер вопроса внутри теста.
"""

from typing import TYPE_CHECKING, ClassVar, Self

from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q

from apps.catalog.models import Module
from apps.common.models import TimeStamped
from apps.common.querysets import ActiveManager, ActiveQuerySet

MIN_DURATION_MINUTES = 1
MAX_DURATION_MINUTES = 180
# Вопрос с одним вариантом — это не вопрос, а десяток вариантов ребёнок уже не читает.
# Правила проверяют и админка, и разбор загруженного JSON.
MIN_ANSWER_OPTIONS = 2
MAX_ANSWER_OPTIONS = 10

# Сообщение одно на все места, где тест пробуют показать на сайте:
# форму студии, кнопку «показать» и админку.
ACTIVE_TEST_EXISTS = "В этом блоке уже есть тест, который показывается на сайте."


class TestQuerySet(ActiveQuerySet["Test"]):
    def with_question_count(self) -> Self:
        """Добавляет `questions_count` — счётчика в таблице нет, считаем запросом."""
        return self.annotate(questions_count=models.Count("questions"))


class TestManager(ActiveManager["Test"]):
    def get_queryset(self) -> TestQuerySet:
        return TestQuerySet(self.model, using=self._db)

    def active(self) -> TestQuerySet:
        return self.get_queryset().active()

    def with_question_count(self) -> TestQuerySet:
        return self.get_queryset().with_question_count()


class Test(TimeStamped):
    """Тест внутри блока."""

    # pytest собирает классы с именем Test*: без этого флага он пытается сделать
    # тест-класс из модели и из всего, что её импортирует.
    __test__ = False

    if TYPE_CHECKING:
        # Не поле таблицы: счётчик приезжает из annotate() в with_question_count().
        questions_count: int

    module = models.ForeignKey(
        Module,
        verbose_name="блок",
        related_name="tests",
        on_delete=models.PROTECT,
    )
    title = models.CharField("название", max_length=200)
    duration_minutes = models.PositiveSmallIntegerField(
        "время на тест, мин",
        default=15,
        validators=[
            MinValueValidator(MIN_DURATION_MINUTES),
            MaxValueValidator(MAX_DURATION_MINUTES),
        ],
    )
    questions_file = models.FileField(
        "файл с вопросами",
        upload_to="tests/questions/%Y/%m/",
        blank=True,
        validators=[FileExtensionValidator(["json"])],
        help_text="Исходный JSON остаётся здесь как архив загрузки.",
    )
    is_active = models.BooleanField("показывать на сайте", default=True)

    objects = TestManager()

    class Meta:
        verbose_name = "тест"
        verbose_name_plural = "тесты"
        ordering = ("title",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("module", "title"),
                name="test_title_unique_per_module",
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__gte=MIN_DURATION_MINUTES)
                & Q(duration_minutes__lte=MAX_DURATION_MINUTES),
                name="test_duration_minutes_in_range",
            ),
            # Блок показывает ровно один тест, поэтому активный в нём только один.
            # Частичный уникальный индекс: скрытых тестов в блоке сколько угодно.
            models.UniqueConstraint(
                fields=("module",),
                condition=Q(is_active=True),
                name="test_one_active_per_module",
                violation_error_message=ACTIVE_TEST_EXISTS,
            ),
        ]

    def __str__(self) -> str:
        return self.title


class Question(models.Model):
    """Вопрос теста. Порядок внутри теста — `position`."""

    class Type(models.TextChoices):
        SINGLE = "single", "Один верный ответ"
        MULTIPLE = "multiple", "Несколько верных ответов"

    test = models.ForeignKey(
        Test,
        verbose_name="тест",
        related_name="questions",
        on_delete=models.CASCADE,
    )
    text = models.TextField("текст вопроса")
    type = models.CharField(
        "тип",
        max_length=10,
        choices=Type.choices,
        default=Type.SINGLE,
        help_text="multiple ставится, когда верных вариантов больше одного.",
    )
    position = models.PositiveSmallIntegerField("номер в тесте")

    class Meta:
        verbose_name = "вопрос"
        verbose_name_plural = "вопросы"
        ordering = ("position", "id")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # DEFERRABLE INITIALLY DEFERRED: иначе перестановку вопросов местами
            # не сохранить одной транзакцией — промежуточное состояние с двумя
            # одинаковыми position упало бы на первом же UPDATE.
            models.UniqueConstraint(
                fields=("test", "position"),
                name="question_position_unique_per_test",
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.position}. {self.text[:60]}"


class AnswerOption(models.Model):
    """Вариант ответа. Верных может быть несколько — тогда вопрос становится multiple."""

    question = models.ForeignKey(
        Question,
        verbose_name="вопрос",
        related_name="options",
        on_delete=models.CASCADE,
    )
    text = models.CharField("текст варианта", max_length=500)
    is_correct = models.BooleanField("верный", default=False)

    class Meta:
        verbose_name = "вариант ответа"
        verbose_name_plural = "варианты ответа"
        ordering = ("id",)

    def __str__(self) -> str:
        return self.text[:60]
