"""Образец файла с вопросами — тот, что показывается и скачивается в студии.

Держим в коде, а не читаем `docs/examples/questions.json` с диска: страница не
должна зависеть от того, попала ли папка с документацией в образ контейнера.
Там лежит более полный пример для документации, здесь — короткий учебный.
"""

import json
from typing import Any

SAMPLE_FILE_NAME = "questions-example.json"

SAMPLE: dict[str, Any] = {
    "questions": [
        {
            "text": "Сколько будет 2 + 2?",
            "options": [
                {"text": "3"},
                {"text": "4", "is_correct": True},
                {"text": "5"},
            ],
        },
        {
            "text": "Какие числа чётные?",
            "type": "multiple",
            "options": [
                {"text": "2", "is_correct": True},
                {"text": "3"},
                {"text": "4", "is_correct": True},
            ],
        },
    ]
}


def sample_json() -> str:
    """Образец в том же виде, в каком его увидят на странице и в скачанном файле."""
    return json.dumps(SAMPLE, ensure_ascii=False, indent=2)
