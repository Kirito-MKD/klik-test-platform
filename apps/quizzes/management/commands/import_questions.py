"""Загрузка вопросов в тест из файла — для сеялки, демо-данных и разбора аварий.

manage.py import_questions --test 12 --file docs/examples/questions.json
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.quizzes.models import Test
from apps.quizzes.services.import_questions import (
    ImportMode,
    QuestionsFileError,
    import_questions_from_file,
)


class Command(BaseCommand):
    help = "Загружает вопросы в тест из JSON-файла."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--test", type=int, required=True, help="id теста")
        parser.add_argument("--file", type=Path, required=True, help="путь к JSON-файлу")
        parser.add_argument(
            "--mode",
            choices=[mode.value for mode in ImportMode],
            default=ImportMode.REPLACE.value,
            help="replace стирает прежние вопросы, append дописывает в конец",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["file"]
        if not path.is_file():
            raise CommandError(f"Файла нет: {path}")

        try:
            test = Test.objects.get(pk=options["test"])
        except Test.DoesNotExist as error:
            raise CommandError(f"Теста с id={options['test']} нет.") from error

        try:
            with path.open("rb") as handle:
                created = import_questions_from_file(
                    test, File(handle, name=path.name), ImportMode(options["mode"])
                )
        except QuestionsFileError as error:
            # Каждую претензию с новой строки: список ошибок в одну строку не читается.
            problems = "\n".join(f"  — {problem}" for problem in error.problems)
            raise CommandError(f"Файл не подошёл:\n{problems}") from error

        self.stdout.write(
            self.style.SUCCESS(f"Тест «{test.title}»: загружено вопросов — {created}.")
        )
