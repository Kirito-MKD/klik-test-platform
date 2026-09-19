"""Единый формат ошибки API.

Любая ошибка выглядит одинаково, чтобы фронт разбирал её одним кодом:

    {
      "error": {"code": "not_found", "message": "Ничего не найдено.", "details": {}},
      "meta": {"request_id": "6f1c…"}
    }

`details` заполняется, когда претензий несколько и они по полям — например,
на кривом параметре фильтра. `request_id` тот же, что в заголовке `X-Request-ID`:
по нему находят запрос в логах.
"""

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.common.middleware import get_request_id

VALIDATION_MESSAGE = "Запрос не прошёл проверку."
DEFAULT_CODE = "error"


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Оборачивает ответ DRF в общий конверт.

    Возвращает None на всём, что DRF не считает ошибкой API: такие исключения
    должны дойти до Django и попасть в логи как 500, а не превратиться в
    аккуратный JSON, который никто не заметит.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    # DRF подменяет эти два исключения у себя внутри — повторяем, чтобы добраться
    # до кода ошибки. Заодно меняем текст: внутри Http404 лежит техническое
    # «No Test matches the given query», наружу оно ехать не должно.
    if isinstance(exc, Http404):
        exc = NotFound()
        response.data = {"detail": exc.detail}
    elif isinstance(exc, DjangoPermissionDenied):
        exc = PermissionDenied()
        response.data = {"detail": exc.detail}

    message, details = split_detail(response.data)
    response.data = {
        "error": {
            "code": str(getattr(exc, "default_code", DEFAULT_CODE)),
            "message": message,
            "details": details,
        },
        "meta": {"request_id": get_request_id(context.get("request"))},
    }
    return response


def split_detail(data: Any) -> tuple[str, dict[str, Any]]:
    """Отделяет человеческое сообщение от разбора по полям."""
    if isinstance(data, dict):
        detail = data.get("detail")
        if detail is not None and len(data) == 1:
            return str(detail), {}
        return VALIDATION_MESSAGE, dict(data)
    if isinstance(data, list):
        return VALIDATION_MESSAGE, {"errors": data}
    return str(data), {}
