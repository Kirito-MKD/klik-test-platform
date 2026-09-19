"""Живость сервиса: для healthcheck контейнера и внешнего мониторинга."""

from django.db import OperationalError, connection
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Отвечает 200, пока жив сам сервис и доступна база."""

    # Мониторинг стучится часто — троттлинг здесь только мешал бы.
    # Пустой кортеж, а не список: изменяемое значение в теле класса линтер не пропустит.
    throttle_classes = ()

    @extend_schema(
        summary="Живость сервиса",
        responses={
            status.HTTP_200_OK: OpenApiTypes.OBJECT,
            status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request) -> Response:
        try:
            connection.ensure_connection()
        except OperationalError:
            return Response(
                {"status": "error", "database": "unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok", "database": "ok"})
