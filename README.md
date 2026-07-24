# Dtel Access Manager

FastAPI-приложение для учёта ключей, сотрудников, управляющих компаний и
домофонных панелей, а также для записи ключей в CRM.

Основная база данных — PostgreSQL. Доступ к ней выполняется через SQLAlchemy 2
Session и драйвер psycopg 3. Структурой управляет Alembic.

## Требования

- Python 3.12+;
- Docker Compose или отдельный PostgreSQL;
- учётные данные CRM/панелей для реальных внешних операций.

## Первый запуск

Создайте виртуальное окружение и установите зависимости:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Создайте локальный `.env`:

```powershell
Copy-Item .env.example .env
```

Обязательно смените `POSTGRES_PASSWORD`, ту же строку укажите в
`DATABASE_URL`. `.env` не должен попадать в Git.

Запустите PostgreSQL:

```powershell
docker compose up -d postgres
docker compose ps
```

Создайте схему:

```powershell
alembic upgrade head
alembic current
```

## Перенос сотрудников и пользователей из SQLite

Скрипт переносит только `employees` и `users`, сохраняет ID и сверяет
количество строк:

```powershell
python scripts\migrate_sqlite_to_postgres.py --source data\app.db
```

Повторная проверка без записи:

```powershell
python scripts\migrate_sqlite_to_postgres.py `
  --source data\app.db `
  --verify-only
```

SQLite открывается в неизменяемом read-only режиме. Скрипт сверяет SHA-256 до
и после и не удаляет `data/app.db`. Если в PostgreSQL уже есть конфликтующая
строка с тем же ID, транзакция прерывается без перезаписи.

В исходном файле фактически найдены не только сотрудники и пользователи, но и
5 типов ключей, 3 ключа и 13 событий журнала. В соответствии с правилами
переноса эти записи игнорируются. Контрольные количества переносимых таблиц в
текущем снимке: `employees = 77`, `users = 2`.

## Проверка PostgreSQL

Транзакционный smoke-тест создаёт, читает, меняет и удаляет временные записи,
после чего полностью откатывает транзакцию:

```powershell
python scripts\smoke_postgres_crud.py
```

Запуск тестов проекта:

```powershell
python -m unittest discover -s tests -v
```

## Запуск приложения

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Открыть: <http://127.0.0.1:8000>

Приложение при старте проверяет соединение и наличие таблиц. Оно не создаёт
схему автоматически: если миграции не применены, будет показана подсказка
`alembic upgrade head`.

## Основные переменные окружения

```env
DATABASE_URL=postgresql+psycopg://dtel:change-me@127.0.0.1:5432/dtel
DATABASE_ECHO=false
DATABASE_CONNECT_TIMEOUT=5

CRM_BASE_URL=https://crm.dtel.ru
CRM_COOKIE=
CRM_LOGIN=
CRM_PASSWORD=
CRM_BUYER_ID=
DRY_RUN=false

PANEL_API_LOGIN=
PANEL_API_PASSWORD=
PANEL_API_TIMEOUT=3
```

`DRY_RUN=true` запрещает реальные изменения во внешних системах.

## Alembic

Текущая версия:

```powershell
alembic current
```

Обновление:

```powershell
alembic upgrade head
```

Создавать следующую ревизию после изменения `app/models.py`:

```powershell
alembic revision --autogenerate -m "описание изменения"
```

Автогенерацию всегда нужно проверить вручную до применения.

## Документация базы

Фактические таблицы, колонки, индексы, внешние ключи, `ON DELETE`, жизненный
цикл ключа, ER-схема и резервное копирование описаны в
[docs/database.md](docs/database.md).

## Резервное копирование

Перед миграциями:

```powershell
$pgUrl = $env:DATABASE_URL -replace '^postgresql\+psycopg:', 'postgresql:'
pg_dump --format=custom --no-owner --file=dtel_backup.dump --dbname=$pgUrl
```

Порядок восстановления и дополнительные рекомендации приведены в
[docs/database.md](docs/database.md#резервное-копирование-и-восстановление).
