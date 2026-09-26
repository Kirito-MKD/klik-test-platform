#!/bin/sh
# Бэкап базы KLIK с ротацией. Запускается по cron на сервере:
#
#   0 3 * * * cd /srv/klik && ./deploy/backup.sh >> /var/log/klik-backup.log 2>&1
#
# Формат custom (-Fc): сжат сам по себе и восстанавливается выборочно через pg_restore.
set -eu

COMPOSE_FILE=${KLIK_COMPOSE_FILE:-compose.prod.yaml}
ENV_FILE=${KLIK_ENV_FILE:-.env.prod}
BACKUP_DIR=${KLIK_BACKUP_DIR:-./backups}
KEEP_DAYS=${KLIK_BACKUP_KEEP_DAYS:-14}

# `.` без слэша ищет файл в PATH, а не в текущем каталоге — приводим путь к явному.
case "$ENV_FILE" in
    /* | ./* | ../*) ;;
    *) ENV_FILE="./$ENV_FILE" ;;
esac

# shellcheck disable=SC1090  # путь к файлу окружения задаётся снаружи
. "$ENV_FILE"

mkdir -p "$BACKUP_DIR"
stamp=$(date +%Y-%m-%d_%H%M)
target="$BACKUP_DIR/klik-$stamp.dump"
# Дамп пишется во временный файл и получает имя бэкапа, только когда готов.
# Упавший на середине pg_dump иначе оставил бы обрубок под видом целого дампа.
partial="$target.partial"
trap 'rm -f "$partial"' EXIT

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$partial"

# Пустой дамп — это не бэкап: лучше упасть сейчас, чем узнать при восстановлении.
if [ ! -s "$partial" ]; then
    echo "$(date '+%F %T') ОШИБКА: дамп пустой, бэкап не сохранён" >&2
    exit 1
fi
mv "$partial" "$target"

find "$BACKUP_DIR" -name 'klik-*.dump' -type f -mtime "+$KEEP_DAYS" -delete

echo "$(date '+%F %T') готово: $target ($(du -h "$target" | cut -f1)), храним $KEEP_DAYS дней"
