"""Формы студии.

Своих моделей у студии нет: это страницы поверх `apps.catalog` и `apps.quizzes`.
Форма загрузки файла и правила вариантов ответа переиспользуются из
`apps.quizzes.forms` — проверять одно и то же по-разному студия и админка
не должны.
"""

from typing import Any, ClassVar

from django import forms
from django.core.validators import FileExtensionValidator
from django.db.models import QuerySet
from django.forms.models import BaseInlineFormSet, inlineformset_factory

from apps.catalog.models import Category, Module
from apps.quizzes.forms import AnswerOptionInlineFormSet
from apps.quizzes.models import MAX_ANSWER_OPTIONS, AnswerOption, Question, Test
from apps.quizzes.services.questions import active_test_of

FILE_HELP = (
    "Необязательно. Приложите готовый JSON — или оставьте поле пустым "
    "и наберите вопросы руками на следующем шаге."
)


class ModuleChoiceField(forms.ModelChoiceField[Module]):
    """Выпадающий список блоков, где сразу видно категорию.

    Без категории в подписи два блока «Числа и счёт» из разных предметов
    неразличимы, а именно так их и называют.
    """

    def label_from_instance(self, obj: Module) -> str:
        return f"{obj.category.name} · {obj.title}"


def active_modules() -> QuerySet[Module]:
    """Блоки, в которые есть смысл класть тест."""
    return Module.objects.select_related("category").order_by("category__name", "title")


class TestForm(forms.ModelForm[Test]):
    """Поля теста. Файл с вопросами живёт отдельно — он не просто поле модели."""

    module = ModuleChoiceField(
        queryset=Module.objects.none(),
        label="Блок",
        empty_label="Выберите блок",
        help_text="Если нужного блока нет, заведите его на странице «Новый блок».",
    )

    class Meta:
        model = Test
        fields = ("module", "title", "duration_minutes", "is_active")
        labels: ClassVar[dict[str, str]] = {
            "title": "Название теста",
            "duration_minutes": "Время на тест, мин",
            "is_active": "Показывать на сайте",
        }
        help_texts: ClassVar[dict[str, str]] = {
            "title": "Так тест увидят дети. В одном блоке названия не повторяются.",
            "duration_minutes": "От 1 до 180 минут.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Queryset считается на каждый запрос, а не один раз при импорте модуля:
        # иначе только что заведённый блок не появился бы в списке до перезапуска.
        self.fields["module"].queryset = active_modules()  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        """Второй активный тест в блоке не пропускаем.

        То же самое держит констрейнт базы, но там ошибка приходит без имени
        теста, который занимает место, — а его и нужно показать.
        """
        cleaned: dict[str, Any] = super().clean() or {}
        module = cleaned.get("module")
        if cleaned.get("is_active") and module is not None:
            busy = active_test_of(module, besides=self.instance)
            if busy is not None:
                self.add_error(
                    "is_active",
                    f"В блоке «{module.title}» уже показывается тест «{busy.title}». "
                    "Сначала скройте его — на сайте блок показывает один тест.",
                )
        return cleaned


class TestCreateForm(TestForm):
    """Новый тест: сразу с файлом вопросов или пустой, под ручной набор.

    Файл необязателен. Требовать его значило заставлять готовить JSON даже там,
    где вопросов три и их быстрее набрать руками; без файла тест создаётся
    пустым, и сразу открывается страница первого вопроса.
    """

    file = forms.FileField(
        label="Файл с вопросами",
        required=False,
        help_text=FILE_HELP,
        validators=[FileExtensionValidator(["json"])],
    )

    def clean(self) -> dict[str, Any]:
        """Пустой тест не может быть сразу показан на сайте."""
        cleaned: dict[str, Any] = super().clean()
        if cleaned.get("is_active") and not cleaned.get("file"):
            self.add_error(
                "is_active",
                "Показывать нечего: приложите файл с вопросами или снимите галочку — "
                "вопросы можно будет добавить руками, а потом вернуть тест на сайт.",
            )
        return cleaned


class ModuleForm(forms.ModelForm[Module]):
    class Meta:
        model = Module
        fields = ("category", "title", "is_active")
        labels: ClassVar[dict[str, str]] = {
            "category": "Категория",
            "title": "Название блока",
            "is_active": "Показывать на сайте",
        }
        help_texts: ClassVar[dict[str, str]] = {
            "title": "В одной категории названия блоков не повторяются."
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("name")  # type: ignore[attr-defined]
        self.fields["category"].empty_label = "Выберите категорию"  # type: ignore[attr-defined]


class CategoryForm(forms.ModelForm[Category]):
    class Meta:
        model = Category
        fields = ("name", "bg_color", "image", "is_active")
        labels: ClassVar[dict[str, str]] = {
            "name": "Название категории",
            "bg_color": "Цвет карточки",
            "image": "Стикер",
            "is_active": "Показывать на сайте",
        }
        help_texts: ClassVar[dict[str, str]] = {
            "bg_color": "Формат #RRGGBB, например #C9E9F6.",
            "image": "Картинка для карточки на сайте. Необязательно.",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "bg_color": forms.TextInput(attrs={"placeholder": "#C9E9F6"})
        }


class QuestionForm(forms.ModelForm[Question]):
    """Сам вопрос. Варианты ответа идут отдельным формсетом ниже."""

    class Meta:
        model = Question
        fields = ("text", "type")
        labels: ClassVar[dict[str, str]] = {"text": "Текст вопроса", "type": "Тип вопроса"}
        help_texts: ClassVar[dict[str, str]] = {
            "type": "«Несколько верных» — когда правильных вариантов больше одного."
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "text": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Например: Сколько будет 2 + 2?"}
            )
        }


def options_formset(
    extra: int,
) -> type[BaseInlineFormSet[AnswerOption, Question, forms.ModelForm[AnswerOption]]]:
    """Формсет вариантов ответа: правила одни, разное только число пустых строк."""
    return inlineformset_factory(
        Question,
        AnswerOption,
        formset=AnswerOptionInlineFormSet,
        fields=("text", "is_correct"),
        labels={"text": "Текст варианта", "is_correct": "Верный"},
        extra=extra,
        max_num=MAX_ANSWER_OPTIONS,
        validate_max=True,
        can_delete=True,
        # Галочка «убрать» — только у сохранённых вариантов: на пустой строке
        # убирать нечего, и она сбивает с толку.
        can_delete_extra=False,
    )


# У нового вопроса строк ещё нет — показываем три пустые, остальные добавляются кнопкой.
NewOptionsFormSet = options_formset(extra=3)
# При правке к существующим вариантам добавляется одна пустая строка.
OptionsFormSet = options_formset(extra=1)
