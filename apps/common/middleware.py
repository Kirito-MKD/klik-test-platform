"""Сквозные middleware."""

import uuid
from collections.abc import Callable
from typing import Any, Protocol

from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_META = "KLIK_REQUEST_ID"


class HasMeta(Protocol):
    """И HttpRequest, и Request из DRF — оба отдают META."""

    @property
    def META(self) -> dict[str, Any]: ...  # noqa: N802


class RequestIDMiddleware:
    """Даёт каждому запросу id: он уходит в заголовок ответа и в тело ошибки API.

    Пришедший снаружи id (от nginx или фронта) не перебиваем — иначе записи
    в логах перестанут сходиться между звеньями.

    Храним в `request.META`, а не в атрибуте запроса: так значение видно и из
    DRF-обработчика, и чекеры типов не спорят с дописанным на ходу полем.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.META[REQUEST_ID_META] = request_id

        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response


def get_request_id(request: HasMeta | None) -> str:
    """Id запроса или пустая строка, если middleware не отработала (например, в тестах)."""
    if request is None:
        return ""
    return str(request.META.get(REQUEST_ID_META, ""))
