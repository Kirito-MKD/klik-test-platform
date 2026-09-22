"""Страницы студии — загрузка тестов без админки Django.

Права те же, что у админки: группа «Контент» (`manage.py setup_content_group`).
Статус персонала при этом не нужен — в студию можно пустить того, кому в саму
админку заходить незачем.

Представления функциональные: у каждого одно право и один способ запроса, так
проверка доступа видна прямо над телом, а не собирается из миксинов.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Q, QuerySet
from django.forms.models import BaseInlineFormSet, ModelForm
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import Category
from apps.quizzes.forms import QuestionsImportForm
from apps.quizzes.models import AnswerOption, Question, Test
from apps.quizzes.services.import_questions import (
    ImportMode,
    QuestionsFileError,
    import_questions_from_file,
)
from apps.quizzes.services.questions import (
    active_test_of,
    has_questions,
    next_position,
    renumber,
)
from apps.studio.forms import (
    CategoryForm,
    ModuleForm,
    NewOptionsFormSet,
    OptionsFormSet,
    QuestionForm,
    TestCreateForm,
    TestForm,
)
from apps.studio.prompt import questions_prompt
from apps.studio.sample import SAMPLE, SAMPLE_FILE_NAME, sample_json

EMPTY_TEST_REFUSAL = "Тест без вопросов нельзя показывать на сайте: сначала добавьте вопросы."


def tests_for_list(search: str, category_id: str) -> QuerySet[Test]:
    """Список тестов для главной страницы: сразу с блоком, категорией и счётчиком."""
    # Счётчик вопросов считает тот же метод, что и админка с API: своего annotate
    # здесь быть не должно, иначе «вопросов» в трёх местах начнёт расходиться.
    tests = (
        Test.objects.with_question_count()
        .select_related("module", "module__category")
        .order_by("module__category__name", "module__title", "title")
    )
    if search:
        tests = tests.filter(Q(title__icontains=search) | Q(module__title__icontains=search))
    if category_id.isdigit():
        tests = tests.filter(module__category_id=int(category_id))
    return tests


@login_required
@permission_required("quizzes.view_test", raise_exception=True)
def index(request: HttpRequest) -> HttpResponse:
    """Все тесты: что где лежит, сколько вопросов и видно ли на сайте."""
    search = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "")
    tests = list(tests_for_list(search, category_id))

    return render(
        request,
        "studio/index.html",
        {
            "tests": tests,
            "search": search,
            "category_id": category_id,
            "categories": Category.objects.order_by("name"),
            # Пустых тестов быть не должно, но если такой завёлся — это видно сверху.
            "empty_tests": sum(1 for quiz in tests if quiz.questions_count == 0),
        },
    )


@login_required
@permission_required("quizzes.add_test", raise_exception=True)
def test_create(request: HttpRequest) -> HttpResponse:
    """Новый тест: с готовым файлом вопросов или пустой, под ручной набор."""
    form = TestCreateForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["file"]
        if not uploaded:
            quiz = form.save()
            messages.success(
                request,
                f"Тест «{quiz.title}» создан. Добавьте первый вопрос — "
                "после этого тест можно будет показать на сайте.",
            )
            return redirect("studio:question-create", test_id=quiz.pk)

        try:
            # Одна транзакция на карточку и вопросы: на кривом файле не должно
            # остаться теста-пустышки, к которому потом никто не вернётся.
            with transaction.atomic():
                quiz = form.save()
                created = import_questions_from_file(quiz, uploaded)
        except QuestionsFileError as error:
            for problem in error.problems:
                form.add_error("file", problem)
        else:
            messages.success(request, f"Тест «{quiz.title}» создан. Вопросов: {created}.")
            return redirect("studio:test-detail", test_id=quiz.pk)

    return render(
        request,
        "studio/test_form.html",
        {"form": form, "sample": sample_json(), "prompt": questions_prompt()},
    )


def render_detail(
    request: HttpRequest,
    quiz: Test,
    edit_form: TestForm | None = None,
    upload_form: QuestionsImportForm | None = None,
) -> HttpResponse:
    """Карточка теста. Формы приходят связанными, когда возвращаемся с ошибкой."""
    questions = (
        Question.objects.filter(test=quiz).prefetch_related("options").order_by("position", "id")
    )
    return render(
        request,
        "studio/test_detail.html",
        {
            "quiz": quiz,
            "questions": questions,
            "edit_form": edit_form or TestForm(instance=quiz),
            "upload_form": upload_form or QuestionsImportForm(),
            "sample": sample_json(),
            "prompt": questions_prompt(),
        },
    )


@login_required
@permission_required("quizzes.view_test", raise_exception=True)
def test_detail(request: HttpRequest, test_id: int) -> HttpResponse:
    """Тест целиком: поля, вопросы с вариантами и повторная загрузка файла."""
    quiz = get_object_or_404(Test.objects.select_related("module", "module__category"), pk=test_id)
    return render_detail(request, quiz)


@login_required
@permission_required("quizzes.change_test", raise_exception=True)
@require_POST
def test_edit(request: HttpRequest, test_id: int) -> HttpResponse:
    """Правка карточки теста. Вопросы здесь не трогаем."""
    quiz = get_object_or_404(Test.objects.select_related("module", "module__category"), pk=test_id)
    form = TestForm(request.POST, instance=quiz)

    if not form.is_valid():
        return render_detail(request, quiz, edit_form=form)

    # Тест без вопросов на сайт не пускаем — то же правило, что и в админке.
    if form.cleaned_data["is_active"] and not has_questions(quiz):
        form.add_error("is_active", EMPTY_TEST_REFUSAL)
        return render_detail(request, quiz, edit_form=form)

    form.save()
    messages.success(request, "Карточка теста сохранена.")
    return redirect("studio:test-detail", test_id=quiz.pk)


@login_required
@permission_required("quizzes.change_test", raise_exception=True)
@require_POST
def test_upload(request: HttpRequest, test_id: int) -> HttpResponse:
    """Повторная загрузка вопросов: заменить прежние или дописать в конец."""
    quiz = get_object_or_404(Test.objects.select_related("module", "module__category"), pk=test_id)
    form = QuestionsImportForm(request.POST, request.FILES)

    if form.is_valid():
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
            messages.success(request, f"Загружено вопросов: {created}.")
            return redirect("studio:test-detail", test_id=quiz.pk)

    return render_detail(request, quiz, upload_form=form)


@login_required
@permission_required("quizzes.change_test", raise_exception=True)
@require_POST
def test_toggle_active(request: HttpRequest, test_id: int) -> HttpResponse:
    """Показать тест на сайте или убрать его оттуда — одной кнопкой.

    Отдельное действие, а не галочка в форме: скрыть тест обычно нужно быстро
    и прямо из списка, не открывая карточку и не трогая остальные поля.
    """
    quiz = get_object_or_404(Test.objects.select_related("module"), pk=test_id)
    busy = active_test_of(quiz.module, besides=quiz)

    if quiz.is_active:
        quiz.is_active = False
        quiz.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"Тест «{quiz.title}» скрыт с сайта.")
    elif not has_questions(quiz):
        messages.error(request, EMPTY_TEST_REFUSAL)
    elif busy is not None:
        # Блок показывает один тест: тот же запрет, что в форме и в базе.
        messages.error(
            request,
            f"В блоке «{quiz.module.title}» уже показывается тест «{busy.title}». "
            "Сначала скройте его.",
        )
    else:
        quiz.is_active = True
        quiz.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"Тест «{quiz.title}» показывается на сайте.")

    # Куда вернуться, решает страница, с которой нажали: подставлять сюда полный
    # адрес из запроса нельзя — это открытый редирект.
    if request.POST.get("back") == "list":
        return redirect("studio:index")
    return redirect("studio:test-detail", test_id=quiz.pk)


def render_question_form(
    request: HttpRequest,
    quiz: Test,
    form: QuestionForm,
    options: BaseInlineFormSet[AnswerOption, Question, ModelForm[AnswerOption]],
    *,
    question: Question | None = None,
) -> HttpResponse:
    """Страница вопроса — одна и та же для нового и для правки."""
    return render(
        request,
        "studio/question_form.html",
        {"quiz": quiz, "form": form, "options": options, "question": question},
    )


@login_required
@permission_required("quizzes.add_question", raise_exception=True)
def question_create(request: HttpRequest, test_id: int) -> HttpResponse:
    """Новый вопрос руками — без файла и без админки."""
    quiz = get_object_or_404(Test.objects.select_related("module", "module__category"), pk=test_id)
    question = Question(test=quiz, position=next_position(quiz))
    form = QuestionForm(request.POST or None, instance=question)
    options = NewOptionsFormSet(request.POST or None, instance=question)

    if request.method == "POST":
        # Обе проверки выполняем всегда: на коротком замыкании ошибки вариантов
        # не показались бы, пока не исправлен сам вопрос.
        form_is_valid = form.is_valid()
        options_are_valid = options.is_valid()
        if form_is_valid and options_are_valid:
            with transaction.atomic():
                form.save()
                options.save()
            messages.success(request, f"Вопрос {question.position} добавлен.")
            return redirect("studio:test-detail", test_id=quiz.pk)

    return render_question_form(request, quiz, form, options)


@login_required
@permission_required("quizzes.change_question", raise_exception=True)
def question_edit(request: HttpRequest, test_id: int, question_id: int) -> HttpResponse:
    """Правка вопроса и его вариантов."""
    quiz = get_object_or_404(Test.objects.select_related("module", "module__category"), pk=test_id)
    question = get_object_or_404(Question, pk=question_id, test=quiz)
    form = QuestionForm(request.POST or None, instance=question)
    options = OptionsFormSet(request.POST or None, instance=question)

    if request.method == "POST":
        form_is_valid = form.is_valid()
        options_are_valid = options.is_valid()
        if form_is_valid and options_are_valid:
            with transaction.atomic():
                form.save()
                options.save()
            messages.success(request, f"Вопрос {question.position} сохранён.")
            return redirect("studio:test-detail", test_id=quiz.pk)

    return render_question_form(request, quiz, form, options, question=question)


@login_required
@permission_required("quizzes.delete_question", raise_exception=True)
@require_POST
def question_delete(request: HttpRequest, test_id: int, question_id: int) -> HttpResponse:
    """Удаление вопроса. Варианты уходят каскадом, нумерация подтягивается."""
    quiz = get_object_or_404(Test, pk=test_id)
    question = get_object_or_404(Question, pk=question_id, test=quiz)
    position = question.position

    with transaction.atomic():
        question.delete()
        renumber(quiz)
        # Последний вопрос убрали — показывать на сайте больше нечего.
        if quiz.is_active and not has_questions(quiz):
            quiz.is_active = False
            quiz.save(update_fields=["is_active", "updated_at"])
            messages.warning(request, "Вопросов не осталось, тест скрыт с сайта.")

    messages.success(request, f"Вопрос {position} удалён.")
    return redirect("studio:test-detail", test_id=quiz.pk)


@login_required
@permission_required("catalog.add_module", raise_exception=True)
def module_create(request: HttpRequest) -> HttpResponse:
    """Новый блок: без него тест некуда положить."""
    form = ModuleForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        module = form.save()
        messages.success(request, f"Блок «{module.title}» создан.")
        return redirect("studio:test-create")

    return render(request, "studio/module_form.html", {"form": form})


@login_required
@permission_required("catalog.add_category", raise_exception=True)
def category_create(request: HttpRequest) -> HttpResponse:
    """Новая категория — верхний уровень каталога."""
    form = CategoryForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        category = form.save()
        messages.success(request, f"Категория «{category.name}» создана.")
        return redirect("studio:module-create")

    return render(request, "studio/category_form.html", {"form": form})


@login_required
@permission_required("quizzes.view_test", raise_exception=True)
def sample_download(request: HttpRequest) -> JsonResponse:
    """Образец файла с вопросами — скачать, поправить, загрузить."""
    response: JsonResponse = JsonResponse(
        SAMPLE, json_dumps_params={"ensure_ascii": False, "indent": 2}
    )
    response["Content-Disposition"] = f'attachment; filename="{SAMPLE_FILE_NAME}"'
    return response
