"""Тесты: карточки тестов блока, вопросы с вариантами и проверка ответа.

Верные ответы наружу не отдаются: вместе с вариантами они были бы видны
в «Сети» браузера, и тест перестал бы быть проверкой. Правильность выясняется
отдельным запросом.
"""

from django.db.models import Prefetch, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Module
from apps.quizzes.models import AnswerOption, Question, Test


class TestSerializer(serializers.ModelSerializer[Test]):
    """Карточка теста: сколько вопросов и сколько минут."""

    # Имя начинается с Test — pytest иначе пробует собрать класс как тест.
    __test__ = False

    # Счётчика в таблице нет, значение приходит из annotate в queryset.
    question_count = serializers.IntegerField(source="questions_count", read_only=True)

    class Meta:
        model = Test
        fields = ("id", "title", "question_count", "duration_minutes")


class AnswerOptionSerializer(serializers.ModelSerializer[AnswerOption]):
    """Вариант ответа без признака верности — он живёт только на сервере."""

    class Meta:
        model = AnswerOption
        fields = ("id", "text")


class QuestionSerializer(serializers.ModelSerializer[Question]):
    options = AnswerOptionSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = ("id", "position", "type", "text", "options")


class AnswerCheckSerializer(serializers.Serializer[dict[str, int]]):
    """Тело запроса на проверку: три id, все обязательные."""

    test_id = serializers.IntegerField(min_value=1)
    question_id = serializers.IntegerField(min_value=1)
    option_id = serializers.IntegerField(min_value=1)


class AnswerCheckResultSerializer(serializers.Serializer[dict[str, bool]]):
    """Ответ проверки — он же в схеме OpenAPI."""

    is_correct = serializers.BooleanField()


@extend_schema(
    summary="Активные тесты блока",
    description=(
        "Плоский список без пагинации: в блоке может быть несколько активных "
        "тестов. 404 — если блок скрыт или его нет; пустой массив — если блок "
        "есть, но показывать в нём пока нечего."
    ),
)
class ModuleTestsView(generics.ListAPIView[Test]):
    """Активные тесты блока по `module_id`, по порядку названия."""

    __test__ = False

    serializer_class = TestSerializer
    # Тесты одного блока — это один экран, разбивать его на страницы незачем.
    pagination_class = None

    def get_queryset(self) -> QuerySet[Test]:
        # Блок проверяем отдельно: у скрытого блока и у блока без тестов
        # ответы должны различаться — 404 против пустого массива.
        module_is_visible = Module.objects.filter(
            pk=self.kwargs["module_id"], is_active=True, category__is_active=True
        ).exists()
        if not module_is_visible:
            raise NotFound("Блок не найден.")

        return (
            Test.objects.active()
            .with_question_count()
            .filter(module_id=self.kwargs["module_id"])
            .order_by("title", "id")
        )


@extend_schema(
    summary="Вопросы теста с вариантами ответа",
    description=(
        "Плоский список без пагинации, порядок — по `position`. Признака верности "
        "у вариантов нет: ответ проверяется запросом `POST /answers/check/`."
    ),
)
class TestQuestionsView(generics.ListAPIView[Question]):
    """Вопросы активного теста по `test_id`."""

    __test__ = False

    serializer_class = QuestionSerializer
    # Тест целиком — это один экран прохождения, разбивать его на страницы незачем.
    pagination_class = None

    def get_queryset(self) -> QuerySet[Question]:
        # Тест проверяем отдельно: иначе на скрытый тест и на тест без вопросов
        # фронт получал бы один и тот же пустой массив.
        if not Test.objects.active().filter(pk=self.kwargs["test_id"]).exists():
            raise NotFound("Активный тест не найден.")
        return (
            Question.objects.filter(test_id=self.kwargs["test_id"])
            .prefetch_related(Prefetch("options", queryset=AnswerOption.objects.order_by("id")))
            .order_by("position", "id")
        )


class AnswerCheckView(APIView):
    """Проверка одного варианта ответа.

    Единственный способ узнать правильность: в списке вопросов признака верности
    нет. У вопроса с несколькими верными ответами варианты проверяются
    по одному.
    """

    @extend_schema(
        summary="Проверка верности варианта ответа",
        request=AnswerCheckSerializer,
        responses={
            status.HTTP_200_OK: AnswerCheckResultSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request) -> Response:
        payload = AnswerCheckSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ids = payload.validated_data

        # Одним запросом проверяем и связку «тест → вопрос → вариант», и то, что
        # тест показывается на сайте: по отдельности это три похода в базу.
        option = (
            AnswerOption.objects.filter(
                pk=ids["option_id"],
                question_id=ids["question_id"],
                question__test_id=ids["test_id"],
                question__test__is_active=True,
            )
            .values_list("is_correct", flat=True)
            .first()
        )
        if option is None:
            raise NotFound("Вариант ответа не найден в этом вопросе теста.")
        return Response({"is_correct": option})
