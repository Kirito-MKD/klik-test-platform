"""Пагинация по умолчанию для всего API."""

from rest_framework import pagination


class PageNumberPagination(pagination.PageNumberPagination):
    """Страницы по 20, размер можно попросить в `page_size`, но не больше 100.

    Ответ в привычном для DRF виде: `count`, `next`, `previous`, `results`.
    """

    page_size_query_param = "page_size"
    max_page_size = 100
