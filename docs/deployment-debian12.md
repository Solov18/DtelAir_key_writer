# Развёртывание CRM на Debian 12

Документ рассчитан на `crm3.dtel.ru`, Debian 12, 4 CPU и 5.7 ГБ RAM.
Приложение запускается не от `root`, слушает только `127.0.0.1:8100`, а
PostgreSQL принимает локальные подключения. Рекомендуется **3 Uvicorn worker**.

## 1. Пакеты и системный пользователь

```bash
sudo apt update
sudo apt install -y \
  nginx \
  python3.11 python3.11-venv python3-pip \
  build-essential libpq-dev git rsync curl ca-certificates \
  util-linux

sudo adduser --system --group --home /opt/key-writer \
  --shell /usr/sbin/nologin key-writer
sudo install -d -o key-writer -g key-writer -m 0750 /opt/key-writer
sudo install -d -o root -g key-writer -m 0750 /etc/key-writer
sudo install -d -o key-writer -g key-writer -m 0700 /var/backups/key-writer
```

Отдельный `/var/log/key-writer` не нужен: приложение и backup пишут в
`journald`, где настроены системная ротация и ограничение доступа.

## 2. PostgreSQL

Исходная рабочая база работает на PostgreSQL 18.4, поэтому на новом сервере
нужна та же major-версия: **PostgreSQL 18**. Устанавливайте последний доступный
minor-релиз ветки 18 из официального PGDG repository (на момент обновления
документа — 18.6). Не используйте метапакет `apt install postgresql`: Debian 12
может установить штатную более старую major-версию.

Официальная автоматическая настройка PGDG для Debian 12 (`bookworm`):

```bash
sudo apt update
sudo apt install -y postgresql-common ca-certificates curl
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt update
sudo apt install -y postgresql-18 postgresql-client-18
```

Проверьте, что сервер и все утилиты переноса относятся к major 18:

```bash
apt-cache policy postgresql-18 postgresql-client-18
/usr/lib/postgresql/18/bin/postgres --version
/usr/lib/postgresql/18/bin/pg_dump --version
/usr/lib/postgresql/18/bin/pg_restore --version
/usr/lib/postgresql/18/bin/psql --version
sudo -u postgres /usr/lib/postgresql/18/bin/psql -X -Atqc \
  "SELECT current_setting('server_version'), current_setting('server_version_num');"
```

`pg_dump` не умеет безопасно выгружать сервер более новой major-версии, чем
сама утилита, а восстановление dump в более старую major-версию не
гарантируется. Поэтому dump PostgreSQL 18.4 создаётся `pg_dump` 18.x и
восстанавливается `pg_restore` 18.x в PostgreSQL 18.x. Для проверок используйте
`psql` 18.x. Переход 18.4 → более новый minor-релиз 18.x не является downgrade.

PostgreSQL по умолчанию должен слушать только локальный интерфейс. Не
добавляйте `0.0.0.0/0` в `pg_hba.conf` и не открывайте порт 5432 в firewall.

Для новой установки без переноса создайте роль и БД здесь. Для первичного
переноса существующей базы пропустите следующие SQL-команды и выполните их в
разделе 5.2 непосредственно перед restore.

```bash
sudo -u postgres psql
```

В интерактивном `psql`:

```sql
CREATE ROLE key_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
\password key_writer
CREATE DATABASE key_writer OWNER key_writer TEMPLATE template0 ENCODING 'UTF8';
REVOKE ALL ON DATABASE key_writer FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE key_writer TO key_writer;
\q
```

Создайте отдельную тестовую базу только на машине CI/разработчика. На
production-сервере `key_writer_test` приложению не нужна.

## 3. Код и Python 3.11

Передавайте на сервер только исходный код. Не копируйте `.env`, `.git`,
`data/`, `backups/`, `outputs/`, `reports/`, `.venv*`, `*.dump`, `*.xlsx`.
Сначала обязательно выполните dry-run и просмотрите все строки удаления:

```bash
sudo rsync -a --delete-delay --safe-links --itemize-changes --dry-run \
  --chown=key-writer:key-writer \
  --exclude='/.git/***' --exclude='/.env' --exclude='/.env.*' \
  --exclude='/.venv/***' --exclude='/.venv-*/***' \
  --exclude='/data/***' --exclude='/backups/***' \
  --exclude='/outputs/***' --exclude='/reports/***' \
  --exclude='*.dump' --exclude='*.backup' --exclude='*.xlsx' \
  /path/to/release/ /opt/key-writer/

# Только после проверки dry-run повторите без --dry-run:
sudo rsync -a --delete-delay --safe-links --itemize-changes \
  --chown=key-writer:key-writer \
  --exclude='/.git/***' --exclude='/.env' --exclude='/.env.*' \
  --exclude='/.venv/***' --exclude='/.venv-*/***' \
  --exclude='/data/***' --exclude='/backups/***' \
  --exclude='/outputs/***' --exclude='/reports/***' \
  --exclude='*.dump' --exclude='*.backup' --exclude='*.xlsx' \
  /path/to/release/ /opt/key-writer/

if test -e /opt/key-writer/.venv; then test -d /opt/key-writer/.venv; fi
if test -L /opt/key-writer/.env; then readlink -f /opt/key-writer/.env; fi

sudo -u key-writer python3.11 -m venv /opt/key-writer/.venv
sudo -u key-writer /opt/key-writer/.venv/bin/pip install --upgrade pip wheel
sudo -u key-writer /opt/key-writer/.venv/bin/pip install \
  --requirement /opt/key-writer/requirements-prod.txt
```

Исключения с начальным `/` относятся именно к корню
`/opt/key-writer`. Не добавляйте `--delete-excluded`: этот флаг снял бы защиту
исключённых `.venv` и `.env`. Файлы `/etc/key-writer/key-writer.env`,
`/etc/key-writer/pgpass`, `/etc/key-writer/pg_service.conf` и каталог
`/var/backups/key-writer` находятся вне destination root и эта команда `rsync`
физически не может их удалить. `--chown` применяется только к переданным
файлам и заменяет небезопасно широкий `chown -R /opt/key-writer`.

## 4. Production environment и секреты

```bash
sudo cp /opt/key-writer/deploy/env.production.example \
  /etc/key-writer/key-writer.env
sudo chown root:key-writer /etc/key-writer/key-writer.env
sudo chmod 0640 /etc/key-writer/key-writer.env
sudo ln -sfn /etc/key-writer/key-writer.env /opt/key-writer/.env
openssl rand -hex 32
```

Заполните `DATABASE_URL`, уникальный `SESSION_SECRET`, CRM/API-реквизиты.
Первый запуск оставьте с `DRY_RUN=true`. До фактического включения HTTPS
разрешён только ограниченный HTTP smoke-test с:

```env
APP_ENVIRONMENT=staging
TRUSTED_HOSTS=crm3.dtel.ru,localhost,127.0.0.1
SESSION_HTTPS_ONLY=false
DRY_RUN=true
```

После фактического включения и проверки HTTPS переключите окружение на:

```env
APP_ENVIRONMENT=production
SESSION_HTTPS_ONLY=true
DRY_RUN=true
```

Не выставляйте `SESSION_HTTPS_ONLY=true` до появления рабочего HTTPS: браузер
не отправит Secure cookie по HTTP. Staging-конфигурацию не используйте для
штатной эксплуатации или в production systemd.

Только в env должны оставаться: `DATABASE_URL`, `SESSION_SECRET`,
`CRM_COOKIE`, `CRM_LOGIN`, `CRM_PASSWORD`, `CRM_BUYER_ID`,
`PANEL_API_LOGIN`, `PANEL_API_PASSWORD`, `DRY_RUN`, адреса сервисов и timeout.
Секретные значения никогда не вводятся в systemd unit или Nginx config.

## 5. Первичный перенос текущей рабочей PostgreSQL-базы

Этот сценарий предназначен для переноса уже заполненной `key_writer` с
Windows в новую пустую PostgreSQL 18 на Debian. Для финального dump согласуйте
окно обслуживания и остановите запись данных в локальную CRM: `pg_dump`
создаёт согласованный снимок, но изменения, внесённые после начала dump, на
новый сервер не попадут. Исходную локальную базу после переноса не удаляйте.

### 5.1. Windows: проверка источника и создание dump

Команды выполняются из корня проверенного release. Используйте именно клиент
PostgreSQL 18; пароль передавайте через `%APPDATA%\postgresql\pgpass.conf` либо
вводите по запросу `-W`, но не помещайте его в командную строку.

```powershell
$pgBin = "C:\Program Files\PostgreSQL\18\bin"
$dump = "$PWD\key_writer_initial.dump"
$counts = "$PWD\key_writer_source_counts.csv"
$dbArgs = @("-h", "127.0.0.1", "-p", "5432", "-U", "key_writer", "-d", "key_writer")

& "$pgBin\psql.exe" --version
& "$pgBin\pg_dump.exe" --version
& "$pgBin\pg_restore.exe" --version
& "$pgBin\psql.exe" @dbArgs -X -W -v ON_ERROR_STOP=1 -c `
  "SELECT version(), current_database(), current_schema();"

& .\.venv\Scripts\python.exe -m alembic current
& .\.venv\Scripts\python.exe -m alembic heads
& .\.venv\Scripts\python.exe scripts\production_preflight.py `
  --expect-database key_writer
```

Перед следующим шагом прекратите пользовательские записи в локальную CRM.
Затем зафиксируйте контрольные количества и сделайте custom-format dump:

```powershell
$countSql = @"
SELECT 'users' AS table_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'employees', COUNT(*) FROM employees
UNION ALL SELECT 'panels', COUNT(*) FROM panels
UNION ALL SELECT 'keys', COUNT(*) FROM keys
UNION ALL SELECT 'uk_groups', COUNT(*) FROM uk_groups
UNION ALL SELECT 'operation_log', COUNT(*) FROM operation_log
ORDER BY table_name;
"@

& "$pgBin\psql.exe" @dbArgs -X -W -v ON_ERROR_STOP=1 --csv `
  -c $countSql | Set-Content -Encoding ascii $counts

& "$pgBin\pg_dump.exe" @dbArgs -W --format=custom --compress=6 `
  --no-acl --file=$dump
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }

& "$pgBin\pg_restore.exe" --list $dump | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pg_restore --list failed" }

$hash = (Get-FileHash -Algorithm SHA256 $dump).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($dump))" |
  Set-Content -NoNewline -Encoding ascii "$dump.sha256"
Get-Content "$dump.sha256"
```

Передайте dump, checksum и исходные counts по SSH/SCP в каталог пользователя,
а не сразу в web-root или backup-каталог:

```powershell
$server = "DEPLOY_USER@192.168.96.22"
scp $dump "$dump.sha256" $counts "${server}:~/"
```

### 5.2. Debian: checksum, пустая база и restore

До restore не запускайте CRM и не выполняйте `alembic upgrade` на пустой базе.
Сначала повторно проверьте major-версию, каталог dump и SHA256:

```bash
/usr/lib/postgresql/18/bin/pg_restore --version
sudo install -o postgres -g postgres -m 0600 \
  ~/key_writer_initial.dump /var/tmp/key_writer_initial.dump

expected=$(cut -d ' ' -f 1 ~/key_writer_initial.dump.sha256)
actual=$(sudo sha256sum /var/tmp/key_writer_initial.dump | cut -d ' ' -f 1)
test "$expected" = "$actual" || { echo "SHA256 mismatch" >&2; exit 1; }
sudo -u postgres /usr/lib/postgresql/18/bin/pg_restore --list \
  /var/tmp/key_writer_initial.dump >/dev/null
```

На новом сервере создайте отдельную непривилегированную роль и пустую базу из
`template0`. Пароль задаётся интерактивно и затем тем же значением заполняется
`/etc/key-writer/pgpass` и `DATABASE_URL`:

```bash
sudo -u postgres /usr/lib/postgresql/18/bin/psql -X -v ON_ERROR_STOP=1
```

```sql
CREATE ROLE key_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
\password key_writer
CREATE DATABASE key_writer OWNER key_writer TEMPLATE template0 ENCODING 'UTF8';
REVOKE ALL ON DATABASE key_writer FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE key_writer TO key_writer;
\q
```

Восстановите архив одной транзакцией. `--role=key_writer` оставляет объекты во
владении прикладной роли, а `--no-owner --no-acl` не переносит Windows-роли и
локальные права источника:

```bash
sudo -u postgres /usr/lib/postgresql/18/bin/pg_restore \
  --dbname=key_writer --role=key_writer --no-owner --no-acl \
  --exit-on-error --single-transaction \
  /var/tmp/key_writer_initial.dump
sudo -u postgres /usr/lib/postgresql/18/bin/psql -X -d key_writer \
  -v ON_ERROR_STOP=1 -c "ANALYZE;"
```

### 5.3. Проверка восстановленной базы до запуска CRM

Сначала проверьте ревизию напрямую, затем через приложение. Если восстановлена
не head-ревизия, сначала сделайте успешный safety-backup, выполните preflight и
только затем `alembic upgrade head`:

```bash
sudo -u postgres /usr/lib/postgresql/18/bin/psql -X -d key_writer \
  -v ON_ERROR_STOP=1 -c "TABLE alembic_version;"

cd /opt/key-writer
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic current
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic heads
sudo -u key-writer /opt/key-writer/deploy/scripts/preflight.sh

# Только если current отстаёт от heads и safety-backup завершился успешно:
# Перед этой веткой настройте backup-аутентификацию из раздела 6.
sudo -u key-writer /opt/key-writer/deploy/scripts/backup-postgres.sh
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic upgrade head
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic current
```

Сравните counts с сохранённым Windows-файлом без расхождений:

```bash
sudo -u postgres /usr/lib/postgresql/18/bin/psql -X -d key_writer \
  -v ON_ERROR_STOP=1 --csv -c "
SELECT 'users' AS table_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'employees', COUNT(*) FROM employees
UNION ALL SELECT 'panels', COUNT(*) FROM panels
UNION ALL SELECT 'keys', COUNT(*) FROM keys
UNION ALL SELECT 'uk_groups', COUNT(*) FROM uk_groups
UNION ALL SELECT 'operation_log', COUNT(*) FROM operation_log
ORDER BY table_name;" > /tmp/key_writer_target_counts.csv
diff --strip-trailing-cr -u \
  ~/key_writer_source_counts.csv /tmp/key_writer_target_counts.csv
```

Проверьте валидность FK и индексов, наличие unique constraints/indexes и
несколько реальных карточек. Запросы ниже read-only и не выводят пароли:

```bash
sudo -u postgres /usr/lib/postgresql/18/bin/psql -X -d key_writer \
  -v ON_ERROR_STOP=1 <<'SQL'
SELECT conrelid::regclass AS table_name, conname
FROM pg_constraint
WHERE contype = 'f' AND NOT convalidated;

SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public' AND indexdef ILIKE '%UNIQUE%'
ORDER BY tablename, indexname;

SELECT c.relname AS index_name, i.indisvalid, i.indisready
FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
WHERE NOT i.indisvalid OR NOT i.indisready;

SELECT id, full_name, position, enabled FROM employees ORDER BY id LIMIT 10;
SELECT id, number, hex_value, status FROM keys ORDER BY id LIMIT 10;
SELECT id, address, entrance, mac, ip FROM panels ORDER BY id LIMIT 10;
SELECT id, name, archived_at FROM uk_groups ORDER BY id LIMIT 10;
SQL
```

Первый запуск разрешён только если checksum, restore, Alembic, counts,
constraints и выборочная проверка успешны. Оставьте `DRY_RUN=true`; реальные
CRM/API-запросы включаются отдельным решением после smoke-test. Локальную БД и
исходный dump сохраните как минимум до приёмки сервера и первого проверенного
server-side backup.

## 6. Backup-аутентификация без пароля в командной строке

```bash
sudo cp /opt/key-writer/deploy/postgresql/pg_service.conf.example \
  /etc/key-writer/pg_service.conf
sudo cp /opt/key-writer/deploy/postgresql/pgpass.example \
  /etc/key-writer/pgpass
sudo chown root:key-writer /etc/key-writer/pg_service.conf
sudo chown key-writer:key-writer /etc/key-writer/pgpass
sudo chmod 0640 /etc/key-writer/pg_service.conf
sudo chmod 0600 /etc/key-writer/pgpass
sudo editor /etc/key-writer/pgpass
sudo chmod 0750 /opt/key-writer/deploy/scripts/*.sh
```

`pg_service.conf` не содержит пароль, а `pgpass` никогда не попадает в Git,
аргументы процесса или журнал.

## 7. Alembic и первый запуск схемы

Этот раздел используется только для совершенно новой пустой установки без
переноса данных. При переносе существующей `key_writer` выполняйте раздел 5 и
не создавайте схему Alembic до `pg_restore`.

На новой пустой базе:

```bash
cd /opt/key-writer
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic heads
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic upgrade head
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic current
```

Ожидается одна head-ревизия `20260814_09`. На существующей базе перед
миграцией выполните read-only preflight:

```bash
sudo -u key-writer /opt/key-writer/deploy/scripts/preflight.sh
```

Миграция намеренно остановится, если уже есть одинаковые непустые HEX или
логины, отличающиеся только регистром. Скрипт не исправляет и не удаляет такие
данные автоматически.

## 8. systemd

Готовые units находятся в `deploy/systemd/`:

```bash
sudo cp /opt/key-writer/deploy/systemd/key-writer.service /etc/systemd/system/
sudo cp /opt/key-writer/deploy/systemd/key-writer-backup.service /etc/systemd/system/
sudo cp /opt/key-writer/deploy/systemd/key-writer-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable key-writer.service
sudo systemctl enable --now key-writer-backup.timer
```

На первичном переносе пока не запускайте `key-writer.service`. Его запуск
разрешён только после успешных проверок раздела 5 и выбранного HTTPS-сценария
раздела 9. Первый запуск всегда выполняется с `DRY_RUN=true`.

Unit использует 3 worker, `127.0.0.1:8100`, ограниченные filesystem/capability
права и пользователя `key-writer`. Пул каждого worker: 5 постоянных + максимум
2 временных соединения. На время физической записи допускается ещё не более
2 отдельных advisory-lock соединений на worker: жёсткая верхняя граница — 27
соединений, обычная — не более 21.

После разрешённого финального запуска проверяйте service так:

```bash
systemctl status key-writer --no-pager
sudo systemctl restart key-writer
journalctl -u key-writer -n 200 --no-pager
journalctl -u key-writer -f
curl --fail http://127.0.0.1:8100/healthz
```

## 9. Nginx и HTTPS

Сервер находится в DMZ, поэтому способ выпуска сертификата заранее согласуется
с системным администратором. `certbot --nginx` работает только если выбранный
ACME challenge действительно доступен центру сертификации; наличие DNS-записи
само по себе этого не гарантирует.

Базовый HTTP-конфиг можно включить для короткого smoke-test только из
корпоративной/административной сети:

```bash
sudo cp /opt/key-writer/deploy/nginx/crm3.dtel.ru.conf \
  /etc/nginx/sites-available/crm3.dtel.ru
sudo ln -sfn /etc/nginx/sites-available/crm3.dtel.ru \
  /etc/nginx/sites-enabled/crm3.dtel.ru
sudo nginx -t
sudo systemctl enable --now nginx
```

В этот момент оставьте `APP_ENVIRONMENT=staging`, `DRY_RUN=true` и
`SESSION_HTTPS_ONLY=false`. После успешных проверок БД из раздела 5 запустите
один временный процесс в отдельном терминале, выполните smoke-test и остановите
его `Ctrl+C` после завершения HTTP/HTTPS-проверок; не открывайте временный HTTP
всему Интернету:

```bash
cd /opt/key-writer
sudo -u key-writer /opt/key-writer/.venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port 8100 --workers 1
```

```bash
curl --fail http://127.0.0.1:8100/healthz
curl --fail http://crm3.dtel.ru/healthz
```

Вариант A — Let's Encrypt, только если администратор подтвердил доступность
ACME HTTP-01/DNS-01 и внешнюю достижимость, необходимую выбранному challenge:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d crm3.dtel.ru
sudo nginx -t
sudo systemctl reload nginx
curl -I https://crm3.dtel.ru/healthz
```

Вариант B — сертификат корпоративного/internal CA. Администратор выдаёт
сертификат с SAN `crm3.dtel.ru`, приватный ключ и цепочку доверия, размещает их
в закрытом системном каталоге и добавляет в Nginx `listen 443 ssl`,
`ssl_certificate` и `ssl_certificate_key`. Корневой CA должен быть доверенным
на рабочих станциях. После `nginx -t`, reload и проверки цепочки выполните:

```bash
curl --fail --show-error https://crm3.dtel.ru/healthz
```

Только после успешной HTTPS-проверки установите
`APP_ENVIRONMENT=production`, `SESSION_HTTPS_ONLY=true`, сохраните
`DRY_RUN=true` и запустите штатный service:

```bash
sudo systemctl start key-writer.service
curl --fail https://crm3.dtel.ru/healthz
```

FastAPI и PostgreSQL нельзя публиковать внешними firewall-правилами. Код не
ограничивает панели конкретной подсетью: HTTP URL строится из IP, сохранённого
у каждой панели в реестре. Для любой текущей или будущей панели сервер
`192.168.96.22` должен иметь маршрут, DNS не требуется, и разрешённый исходящий
TCP-доступ к её IP/порту API. Текущие подсети панелей фиксируются только в
сетевой документации/firewall. Новая подсеть требует изменения маршрутизации
или firewall, но не кода CRM.

## 10. Автоматический и ручной backup

Timer запускается ежедневно в 02:15 с случайной задержкой до 30 минут.
Хранятся 21 день (допустимо 14–30). Dump создаётся во временный файл,
проверяется `pg_restore --list`, получает mode `0600` и лишь затем публикуется.

```bash
systemctl list-timers key-writer-backup.timer
sudo systemctl start key-writer-backup.service
journalctl -u key-writer-backup -n 100 --no-pager
sudo -u key-writer /opt/key-writer/deploy/scripts/backup-postgres.sh
sudo -u key-writer pg_restore --list \
  /var/backups/key-writer/key_writer_YYYYMMDDTHHMMSSZ.dump >/dev/null
```

Любой backup перед deploy/migration обязан завершиться успешно.
Off-host копию следует добавить в будущем, но она не заменяет проверку
восстановлением.

### 10.1. Периодическая ручная проверка backup восстановлением

Не ограничивайтесь `pg_restore --list`. Периодически выбирайте готовый dump и
восстанавливайте его в одноразовую локальную БД. Команды не подключаются к
рабочей `key_writer` и не запускают приложение:

```bash
dump=/var/backups/key-writer/key_writer_YYYYMMDDTHHMMSSZ.dump
restore_db="key_writer_restore_check_$(date -u +%Y%m%d%H%M%S)"

sudo -u postgres /usr/lib/postgresql/18/bin/pg_restore --list "$dump" >/dev/null
sudo -u postgres createdb --owner=key_writer --template=template0 "$restore_db"
trap 'sudo -u postgres dropdb --if-exists --force "$restore_db"' EXIT

sudo -u postgres /usr/lib/postgresql/18/bin/pg_restore \
  --dbname="$restore_db" --role=key_writer --no-owner --no-acl \
  --exit-on-error --single-transaction "$dump"

restored_revision=$(sudo -u postgres /usr/lib/postgresql/18/bin/psql \
  -X -At -d "$restore_db" -v ON_ERROR_STOP=1 \
  -c "SELECT version_num FROM alembic_version")
expected_head=$(cd /opt/key-writer && sudo -u key-writer \
  /opt/key-writer/.venv/bin/python -m alembic heads | awk 'NR=1 {print $1}')
test "$restored_revision" = "$expected_head"

sudo -u postgres /usr/lib/postgresql/18/bin/psql \
  -X -d "$restore_db" -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'users' AS table_name, COUNT(*) FROM users
UNION ALL SELECT 'employees', COUNT(*) FROM employees
UNION ALL SELECT 'panels', COUNT(*) FROM panels
UNION ALL SELECT 'keys', COUNT(*) FROM keys
UNION ALL SELECT 'uk_groups', COUNT(*) FROM uk_groups
UNION ALL SELECT 'operation_log', COUNT(*) FROM operation_log
ORDER BY table_name;

SELECT id, full_name, position FROM employees ORDER BY id LIMIT 5;
SELECT id, number, status FROM keys ORDER BY id LIMIT 5;
SELECT id, address, entrance, mac FROM panels ORDER BY id LIMIT 5;
SQL

sudo -u postgres dropdb --if-exists --force "$restore_db"
trap - EXIT
```

Результат, дату, имя dump, Alembic revision и counts зафиксируйте в журнале
эксплуатации. Удаляется только одноразовая `key_writer_restore_check_*`; рабочая
база и исходный dump не изменяются.

## 11. Восстановление

Остановите приложение, выберите проверенный dump и явно подтвердите имя БД:

```bash
sudo systemctl stop key-writer
sudo -u key-writer /opt/key-writer/deploy/scripts/restore-postgres.sh \
  --dump /var/backups/key-writer/key_writer_YYYYMMDDTHHMMSSZ.dump \
  --confirm key_writer
sudo -u key-writer /opt/key-writer/.venv/bin/python -m alembic current
sudo systemctl start key-writer
curl --fail http://127.0.0.1:8100/healthz
```

Скрипт по умолчанию делает safety-backup текущего состояния, проверяет каталог
dump и восстанавливает одной транзакцией. `--skip-safety-backup` используйте
только если исходная БД физически недоступна.

## 12. Обновление без потери данных

1. Зафиксировать текущую Git-ревизию и Alembic revision.
2. Подготовить release вне `/opt/key-writer` и прогнать тесты на
   `key_writer_test`.
3. Скопировать release с перечисленными выше exclude.
4. Выполнить `sudo /opt/key-writer/deploy/scripts/upgrade.sh`.
5. Проверить health, `alembic current`, вход, реестры, журналы и только затем
   отключать `DRY_RUN` после отдельной контролируемой проверки.

Скрипт останавливается при неуспешном backup/preflight/migration и не печатает
секреты.

## 13. Откат

При ошибке приложения без изменения схемы верните предыдущий release,
переустановите `requirements-prod.txt` и перезапустите service. Если миграция
изменила данные/схему, надёжный откат — восстановление обязательного backup из
раздела 11. Не применяйте `alembic downgrade` вслепую к рабочим данным.

## 14. Проверки после первого запуска

- `systemctl is-active key-writer nginx postgresql`;
- `/healthz` локально и через HTTPS возвращает 200 без секретов;
- `alembic current` совпадает с `alembic heads` (`20260814_09`);
- приложение доступно только через Nginx, порты 5432/8100 не слушают внешний IP;
- вход/выход, CSRF и Secure session cookie работают;
- открываются сотрудники, ключи, панели, УК, журнал и настройки;
- роли и права применяются на следующем запросе;
- три worker видны в `systemctl status`, но мониторинг ведёт один leader;
- `system_settings` читается всеми worker;
- ручной backup создан, имеет mode 0600 и читается `pg_restore --list`;
- в `journalctl` нет DATABASE_URL, паролей, Cookie и токенов;
- до разрешённой проверки `DRY_RUN=true`, реальных запросов к CRM/панелям нет.
