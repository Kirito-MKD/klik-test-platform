"""Маршруты студии.

Вход и выход — стандартные представления Django со своими шаблонами: своя форма
логина здесь не нужна, а поведение (проверка `next` на чужой адрес, новая сессия
после входа) уже проверено. Защиты от перебора паролей у LoginView нет.
"""

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import URLPattern, URLResolver, path

from apps.studio import views

app_name = "studio"

urlpatterns: list[URLPattern | URLResolver] = [
    path("", views.index, name="index"),
    path("login/", LoginView.as_view(template_name="studio/login.html"), name="login"),
    # LogoutView с Django 5 принимает только POST — в шапке стоит форма, не ссылка.
    path("logout/", LogoutView.as_view(next_page="studio:login"), name="logout"),
    path("tests/new/", views.test_create, name="test-create"),
    path("tests/<int:test_id>/", views.test_detail, name="test-detail"),
    path("tests/<int:test_id>/file/", views.test_source_file, name="test-file"),
    path("tests/<int:test_id>/edit/", views.test_edit, name="test-edit"),
    path("tests/<int:test_id>/upload/", views.test_upload, name="test-upload"),
    path("tests/<int:test_id>/toggle/", views.test_toggle_active, name="test-toggle"),
    path("tests/<int:test_id>/questions/new/", views.question_create, name="question-create"),
    path(
        "tests/<int:test_id>/questions/<int:question_id>/",
        views.question_edit,
        name="question-edit",
    ),
    path(
        "tests/<int:test_id>/questions/<int:question_id>/delete/",
        views.question_delete,
        name="question-delete",
    ),
    path("modules/new/", views.module_create, name="module-create"),
    path("categories/new/", views.category_create, name="category-create"),
    path("sample/", views.sample_download, name="sample"),
]
