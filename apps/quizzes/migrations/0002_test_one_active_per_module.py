"""Блок показывает один тест: активный в блоке может быть только один.

Перед установкой констрейнта наводим порядок в данных — иначе на базе, где
в одном блоке уже два активных теста, миграция упадёт. Оставляем активным
тот, что завели раньше, остальные скрываем: их видно в студии и можно
вернуть на сайт по одному.
"""

from django.db import migrations, models


def hide_extra_active_tests(apps, schema_editor):  # type: ignore[no-untyped-def]
    Test = apps.get_model("quizzes", "Test")

    seen: set[int] = set()
    extra: list[int] = []
    for test_id, module_id in (
        Test.objects.filter(is_active=True)
        .order_by("module_id", "id")
        .values_list("id", "module_id")
    ):
        if module_id in seen:
            extra.append(test_id)
        else:
            seen.add(module_id)

    if extra:
        Test.objects.filter(id__in=extra).update(is_active=False)


def noop(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Назад скрытые тесты не возвращаем: какие из них были активными, уже не узнать."""


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
        ("quizzes", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(hide_extra_active_tests, noop),
        migrations.AddConstraint(
            model_name="test",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("module",),
                name="test_one_active_per_module",
                violation_error_message="В этом блоке уже есть тест, который показывается на сайте.",
            ),
        ),
    ]
