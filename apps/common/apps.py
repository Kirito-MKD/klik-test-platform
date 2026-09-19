from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Своих таблиц нет — здесь живут абстрактная модель и общие хелперы."""

    name = "apps.common"
    label = "common"
    verbose_name = "Общее"
