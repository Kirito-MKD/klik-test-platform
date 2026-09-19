"""Корневые маршруты: админка, студия, первая версия API и её схема."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

admin.site.site_header = "KLIK — управление контентом"
admin.site.site_title = "KLIK"
admin.site.index_title = "Категории, блоки и тесты"

urlpatterns: list[URLPattern | URLResolver] = [
    path(settings.ADMIN_URL, admin.site.urls),
    # Страницы загрузки тестов для контент-менеджера — отдельно от админки.
    path("studio/", include("apps.studio.urls")),
    path("api/v1/", include("apps.api.v1.urls")),
    # Схема генерируется из кода, отдельного документа для фронта писать не нужно.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
