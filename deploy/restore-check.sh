#!/bin/sh
# Репетиция восстановления: разворачивает дамп в отдельную базу и печатает,
# сколько это заняло. Рабочую базу не трогает.
#
#   ./deploy/restore-check.sh backups/klik-2026-09-16_0300.dump
#
# Восстановление в саму рабочую базу делается руками по docs/deploy.md —
# такой шаг не должен быть однострочником, который легко запустить случайно.
set -eu

if [ $# -ne 1 ]; then
    echo "Использование: $0 <файл дампа>" >&2
    exit 2
fi

DUMP=$1
COMPOSE_FILE=${KLIK_COMPOSE_FILE:-compose.prod.yaml}
ENV_FILE=${KLIK_ENV_FILE:-.env.prod}
CHECK_DB=${KLIK_RESTORE_DB:-klik_restore_check}

# `.` без слэша ищет файл в PATH, а не в текущем каталоге — приводим путь к явному.
case "$ENV_FILE" in
    /* | ./* | ../*) ;;
    *) ENV_FILE="./$ENV_FILE" ;;
esac

# shellcheck disable=SC1090  # путь к файлу окружения задаётся снаружи
. "$ENV_FILE"

if [ ! -s "$DUMP" ]; then
    echo "Дампа нет или он пустой: $DUMP" >&2
    exit 1
fi

compose() {
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

started=$(date +%s)

compose exec -T db psql -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $CHECK_DB;" \
    -c "CREATE DATABASE $CHECK_DB OWNER $POSTGRES_USER;"

compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$CHECK_DB" --no-owner < "$DUMP"

tables=$(compose exec -T db psql -U "$POSTGRES_USER" -d "$CHECK_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")

finished=$(date +%s)

echo "Восстановление заняло $((finished - started)) с, таблиц в базе: $tables"
echo "Проверочную базу можно удалить: DROP DATABASE $CHECK_DB;"
