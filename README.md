# Fable

Прототип текстовой RPG: опиши мир, завязку и героя, а языковая модель будет вести историю и отвечать на действия игрока. Ответы выводятся по мере генерации.

Повествованием управляет агент-мастер на официальном OpenAI Python SDK: собственный потоковый tool-loop читает и обновляет состояние игры и через инструменты вызывает отдельные LLM-роли спутников. Поддерживаются OpenAI-совместимые Chat Completions API (vLLM, llama.cpp, LM Studio, OpenRouter, OpenAI); для мастера сервер и модель должны поддерживать streaming tool calling.

Архитектура и единый язык предметной области: [docs/architecture.md](docs/architecture.md).

## Структура Python-пакета

`src/fable` разделён по слоям и контекстам: `domain/{game,companions,safety,users}`,
`application/{game,narrative,companions,safety,auth,prompts}`,
`infrastructure/{llm,agents,checks,persistence,memory,security}`,
`presentation/{web,cli}` и `evaluation`. Общая композиция — `bootstrap.py`.
Каждый промпт хранится отдельно в `src/fable/application/prompts/templates/*.md`;
ресурсы включены в wheel, placeholders имеют формат `${name}` (`string.Template`).
Тесты зеркалят слои и контексты в `tests/`; запуск:

```bash
poetry run python -m unittest discover -s tests
```

Python entry points: `fable.presentation.cli.main:main`,
`fable.presentation.web.app:main`, `fable.evaluation.cli:main`.

## Требования

- Python 3.12 или новее
- Poetry
- OpenAI-совместимый сервер с поддержкой Chat Completions и streaming

## Установка

```bash
poetry install
cp example.env .env
```

Заполни `.env` параметрами своего LLM-сервера:

```env
BASE_URL=
API_KEY=
MODEL=
ENABLE_THINKING=none
TEMPERATURE=0.7
```

Заполни `API_KEY`, `BASE_URL` и `MODEL` значениями своего LLM-сервера. Эти обязательные поля намеренно не имеют значений по умолчанию; если оставить их пустыми, приложение подскажет, что заполнить.

`ENABLE_THINKING` принимает `none`, `low`, `medium` или `xhigh`. `TEMPERATURE` принимает число от `0` до `2`. По умолчанию thinking выключен, а temperature равна `0.7`. Мастер и static-baseline передают `extra_body.chat_template_kwargs.enable_thinking`; при включённом thinking дополнительно `extra_body.reasoning_effort`. Вспомогательные роли не получают этих расширений. Поддержка полей зависит от сервера; это не универсальные параметры OpenAI.

Настройки SDK и структурированных ответов:

- `MODEL_PRICES` — JSON-словарь тарифов по **точному идентификатору модели**, USD за 1 млн входных/выходных токенов. По умолчанию `{}`: денежная стоимость неизвестна (`null`), в том числе для локальной модели без тарифа. Пример: `MODEL_PRICES='{"provider/model":{"input":0.15,"output":0.60}}'`. Оба неотрицательных конечных тарифа обязательны; `0` допустим для явно бесплатной модели.
- `LLM_TIMEOUT_SECONDS=120` — таймаут запроса SDK в секундах, больше 0; `LLM_MAX_RETRIES=2` — число автоматических повторов SDK, от 0. Применяются также к embeddings.
- `MAX_TOOL_ROUNDS=8` — максимум раундов выполнения tools за ход (от 0), затем один завершающий запрос с `tool_choice="none"`. Вызовы в одном раунде выполняются последовательно. Ошибки имени/аргументов возвращаются модели по-русски для исправления; результаты инструментов никогда не транслируются как текст сцены.
- `STRUCTURED_OUTPUT=json_schema` — модератор, consistency и судья запрашивают строгую JSON Schema из Pydantic. Для локального сервера можно выбрать `json_object` (JSON mode) или `prompt` (только инструкция со схемой). При явном API-отказе в поддержке формата выполняется по одному переходу `json_schema → json_object → prompt`; ошибки соединения/авторизации не вызывают таких повторов.

Во всех режимах ответ проверяется Pydantic, затем при необходимости прежним текстовым парсером (например, JSON внутри Markdown). При неразбираемом ответе или сбое модератор пропускает текст, consistency считает ход согласованным, а оценочный стенд помечает проверку/оценку невалидной — оценки не выдумываются.

Долгосрочная векторная память использует ChromaDB и включается после заполнения `EMBEDDING_MODEL` в `.env`. Укажи идентификатор модели, совместимой с OpenAI Embeddings API; если endpoint отличается от `BASE_URL`, задай `EMBEDDING_BASE_URL`. Пока модель не задана, векторные tools отключены. Воспоминания сохраняются напрямую через `chromadb.PersistentClient` локально в `.fable/chroma`, в коллекции `fable_story_memories`, и фильтруются по хешу описания кампании (`campaign_id`). Векторы создаются через SDK Embeddings API; встроенная модель Chroma не скачивается. Старые коллекции, созданные прежней LangChain-обёрткой, могут быть несовместимы (конфигурация embedding function/размерность): сохраните резервную копию и используйте новый `MEMORY_STORE_PATH` или переиндексируйте события той же embedding-моделью. JSON-сохранения игр не меняются.

Остальные настройки, которые можно переопределить: `HISTORY_LIMIT`, `DEFAULT_WORLD`, `DEFAULT_STORY`, `DEFAULT_CHARACTER_NAME`, `DEFAULT_CHARACTER_ROLE`, `DEFAULT_CHARACTER_GOAL` и `DEFAULT_GENRE`.

## Запуск

```bash
poetry run fable
```

Следуй подсказкам в терминале, чтобы описать игру и героя. Чтобы закончить игру, введи `выход`.

## Веб-интерфейс

Запусти backend из корня проекта (настройки LLM берутся из того же `.env`):

```bash
poetry install
poetry run fable-server
```

По умолчанию API доступен на `http://127.0.0.1:8000`. Адрес и порт можно изменить переменными окружения `FABLE_HOST` и `FABLE_PORT`, например `FABLE_PORT=8080 poetry run fable-server`. Эти две переменные задаются в окружении процесса, а не в `.env`.

В другом терминале запусти React-интерфейс (нужен Node.js):

```bash
cd frontend
npm install
npm run dev
```

Открой адрес, который покажет Vite (обычно `http://localhost:5173`). Dev-сервер проксирует `/api` на backend; CORS также разрешён для `localhost:5173` и `127.0.0.1:5173`. Если уже существует `frontend/dist`, backend раздаёт эту сборку по `/`.

## Авторизация

Веб-интерфейс требует регистрации или входа по имени пользователя и паролю. Имя содержит 3–32 латинских буквы, цифры или символы `_`, `.`, `-` и уникально без учёта регистра; пароль — 8–128 символов. Пароли хранятся только как scrypt-хеши. Сессия передаётся в HttpOnly cookie `fable_session` (SameSite=Lax), в SQLite сохраняется только SHA-256 токена. Выход отзывает сессию на сервере. После пяти неудачных попыток вход для этого имени временно блокируется на пять минут.

Настройки `.env`:

- `AUTH_DB_PATH` — SQLite с пользователями и сессиями, по умолчанию `.fable/fable.db` (в Docker `/data/fable.db`, в томе `fable-data`).
- `SESSION_TTL_DAYS=30` — срок жизни сессии в днях, минимум 1.
- `COOKIE_SECURE=false` — для локального HTTP; **за HTTPS обязательно задай `COOKIE_SECURE=true`**.
- `ALLOW_REGISTRATION=true` — разрешение создания аккаунтов; `false` не мешает входу существующих пользователей.

Без PostgreSQL каждый аккаунт видит только свои игры в `SESSIONS_PATH/<user_id>/`. Старые JSON-сохранения непосредственно в `SESSIONS_PATH` не показываются в веб-интерфейсе и остаются доступны через CLI. CLI работает без авторизации; при DATABASE_URL использует отдельное пространство игр с owner_id=NULL. Для запросов API из браузера передавай cookie (`credentials: "include"` при cross-origin); POST/DELETE с посторонним `Origin` отклоняются.

## Запуск в Docker

Нужны Docker и Docker Compose v2.24 или новее. Python, Poetry и Node.js на хосте не требуются: образ собирает React-интерфейс и запускает его вместе с API.

```bash
cp example.env .env
# Заполни API_KEY, BASE_URL и MODEL в .env
docker compose build
docker compose up -d
```

Compose запускает три сервиса: `fable`, `postgres` (PostgreSQL 17) и `redis` (Redis 7, AOF). Приложение ждёт healthy PostgreSQL/Redis; его HTTP-healthcheck не изменён. Порты баз наружу не публикуются. Для прежнего варианта **один контейнер, JSON/SQLite** используй отдельный файл (не override) и не задавай DATABASE_URL/REDIS_URL в `.env`:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Открой `http://localhost:8000`. Если LLM-сервер работает на хосте, вместо `localhost` в `BASE_URL` укажи `http://host.docker.internal:PORT/v1` (сохрани путь своего API). То же относится к `EMBEDDING_BASE_URL`. Сервер на хосте должен принимать соединения из Docker, а не только с loopback-интерфейса.

`.env` передаётся контейнеру при запуске и не попадает в образ. Compose допускает отсутствие файла, если обязательные настройки переданы другим способом; без них приложение не запустится. Векторная память находится в `/data/chroma`, локальные сохранения (одноконтейнерный режим) — в `/data/sessions`, SQLite — `/data/fable.db`; том `fable-data` сохраняет их между перезапусками. В полном стеке игры/аккаунты/cookie-сессии находятся в томе `postgres-data`, Redis AOF — в `redis-data`.

```bash
docker compose logs -f fable
docker compose down
```

`docker compose down` сохраняет данные; **`docker compose down -v` удалит все тома выбранного проекта, включая PostgreSQL, Redis и память**. Для интерактивного CLI с теми же настройками и томом:

```bash
docker compose run --rm -it --no-deps fable fable
```

Compose публикует порт `8000` на всех интерфейсах хоста; для доступа только с этой машины замени привязку на `127.0.0.1:8000:8000`. Для внешнего доступа используй HTTPS и `COOKIE_SECURE=true`, а после создания нужных аккаунтов при необходимости отключи регистрацию.

При установке Python-пакета отдельно путь к готовому интерфейсу можно задать переменной окружения процесса `FABLE_FRONTEND_DIST`; без неё сохраняется поиск `frontend/dist` в корне проекта.

## PostgreSQL и Redis

Локальный запуск без `DATABASE_URL` и `REDIS_URL` остаётся прежним: JSON-игры,
SQLite-аккаунты и сессии, блокировки и login rate limiter в памяти одного процесса.
PostgreSQL нужен для общего хранилища нескольких backend-воркеров, Redis — для
общих неблокирующих game-lock и ограничения входа. Настройки независимы, но
**несколько HTTP-воркеров разрешены только с обоими сервисами**.

```env
DATABASE_URL=postgresql://fable:fable@localhost:5432/fable
REDIS_URL=redis://localhost:6379/0
DB_POOL_MIN=1
DB_POOL_MAX=10
TURN_LOCK_TTL_SECONDS=600
```

URL выше — для сервисов с опубликованными локальными портами. В обычном Compose
уже заданы `postgres:5432` и `redis:6379`, healthchecks и постоянные тома.
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` имеют dev-значение `fable`;
**поменяй пароль перед развёртыванием**, а при изменении этих значений задай
соответствующий `DATABASE_URL`. Переменные инициализации PostgreSQL действуют
только при создании пустого тома. Для внешних сервисов задай свои URL.

Миграции `infrastructure/persistence/postgres/migrations/NNN_*.sql` входят в wheel
и применяются автоматически при создании приложения. Версии — в
`schema_migrations`; advisory lock сериализует старты, все изменения выполняются
в транзакции. Отдельная команда не требует настроек LLM и читает DATABASE_URL
**из окружения процесса**, а не из `.env`:

```bash
DATABASE_URL=postgresql://fable:fable@localhost:5432/fable poetry run fable-migrate
# Для запущенного Compose:
docker compose exec fable fable-migrate
# Воркеры: FABLE_WORKERS задаётся в окружении процесса (Compose передаёт его сам).
FABLE_WORKERS=2 poetry run fable-server
```

Каждый воркер создаёт собственный psycopg-пул (по умолчанию 1–10 соединений),
Redis-клиент и применяет миграции идемпотентно. При остановке lifespan закрывает
клиенты. Нет ORM и автоматического переключения на локальное хранилище при сбое
внешнего сервиса. Игры изолированы по owner_id, username уникален без учёта
регистра, cookie-токены в PostgreSQL тоже хранятся только как SHA-256.

В режиме PostgreSQL **или** Redis живой кэш LoadedGame отключён: GET читает
агрегат заново, ход дополнительно перечитывает его **после** получения game-lock.
Это дороже по чтению и созданию сессии, зато другой воркер не продолжит устаревшую
историю. Версия строки проверяется при сохранении (optimistic locking): конфликт
не перезаписывает чужой ход. До начала потока конфликт возвращает HTTP 409;
после отправки SSE-заголовков HTTP-статус уже нельзя изменить, поэтому конфликт
сохранения приходит как `event: error` с `status_code: 409` (без `done`). Busy,
повторный start и конкурирующее удаление по-прежнему возвращают HTTP 409.

Redis lock использует SET NX PX, случайный токен и compare-and-delete Lua;
продления TTL нет. **TURN_LOCK_TTL_SECONDS должен превышать самый долгий полный
ход** (включая tools, повторы SDK, спутников, summary и consistency), а не только
один LLM-запрос. Для медленной модели увеличь 600 секунд с запасом; проверка
версии дополнительно предотвращает потерю обновлений при истёкшем lock.
Rate limiter резервирует попытку атомарно до проверки пароля; успешный вход
сбрасывает счётчик. В памяти окно скользящее, в Redis — 5 попыток за фиксированные
300 секунд с первого запроса (INCR + EXPIRE в Lua), общее для всех воркеров.

Кэш списков в Redis пока **не добавлен**: индексированный SELECT прост и не
требует решения гонки заполнения кэша с invalidation или двойной записи при сбое
Redis. Redis здесь отвечает только за координацию. Автоматический импорт старых
JSON/SQLite тоже не реализован: подключение новой базы не переносит локальные
данные; сохрани резервную копию и не удаляй старый каталог/SQLite.
CLI может использовать PostgreSQL (owner_id=NULL), но его интерактивную сессию
не следует открывать одновременно в нескольких терминалах: CLI не использует
web game-lock, конфликт версии предотвращает перезапись, но не лишнюю генерацию.
Векторная Chroma-память не стала распределённой: для multi-worker оставь
EMBEDDING_MODEL незаданным; общий Chroma-сервер — отдельная задача.

### Интеграционные тесты

Обычный unit-набор не требует сервисов: integration-тесты пропускаются без
`FABLE_TEST_DATABASE_URL` / `FABLE_TEST_REDIS_URL`. Для реальных PostgreSQL 17 и Redis 7:

```bash
scripts/integration-test.sh
# Или с уже подготовленными тестовыми сервисами (например, GitLab CI):
FABLE_TEST_DATABASE_URL=postgresql://user:password@localhost/testdb \
FABLE_TEST_REDIS_URL=redis://localhost:6379/0 \
poetry run python -m unittest discover -s tests/integration -t . -v
```

Скрипт использует отдельный проект `fable-it-<pid>`, случайные loopback-порты,
healthchecks и trap teardown; не читает `.env` и не трогает другие стеки/тома.
Используй **только тестовую БД и Redis DB**: проверки создают и удаляют собственные
записи, схема остаётся после запуска против внешней БД.

## CI/CD (GitLab)

`.gitlab-ci.yml` запускается **только в GitLab**: наличие файла в GitHub не запускает
GitLab pipeline и не настраивает GitHub Actions. GitHub можно оставить основным remote,
а GitLab добавить вторым (предварительно создай пустой проект в GitLab):

```bash
git remote add gitlab <url>
git push gitlab --all
git push gitlab --tags
```

Pipeline создаётся для merge request, default branch, `develop` и тегов. Push в ветку
с открытым MR не создаёт второй pipeline. Этапы:

1. **lint** — Poetry 2.4.1: `poetry check --lock`, компиляция Python (`compileall`), без новых линтеров.
2. **test** — backend: установка из lock и unittest с JUnit-отчётом (CI-only formatter
   `unittest-xml-reporting`); frontend: Node 22, `npm ci`, восемь проверочных скриптов,
   `tsc --noEmit` и Vite build. `frontend/dist` хранится один день.
3. **integration** — настоящий PostgreSQL 17 и Redis 7 как job services, ожидание
   `SELECT 1`/`PING`, затем `tests/integration`. Тестовые URL не используют серверные секреты.
4. **build** — Docker 27 + DinD, cache-from `:latest`, сборка и запуск образа с dummy
   LLM-настройками до статуса healthy. MR только проверяет образ, без push; default
   branch/`develop`/теги публикуют `:$CI_COMMIT_SHORT_SHA`, default branch также
   `:latest`, тег также `:$CI_COMMIT_TAG`. Имена Git-тегов должны быть допустимыми
   Docker-тегами (например `v1.0.0`, без `/`).
5. **deploy** — ручной, только default branch/теги при заданном `DEPLOY_HOST`;
   развёртывает именно SHA-образ, сериализует production-деплои и ждёт healthy.

Нужен GitLab Runner с Docker executor и **privileged DinD**, общим TLS-каталогом
`/certs/client` для job/service; registry проекта должен быть включён. Не выдавай
такой runner недоверенным проектам. Python/Poetry и npm используют project-local
кэши с ключами по lock-файлам; `.venv` не кэшируется. `SKIP_TESTS=true` пропускает
lint/test/integration, но **не** Docker build и smoke test.

### CI/CD variables

В GitLab: Settings → CI/CD → Variables. Deploy-переменные ограничь production и
защищёнными refs; разреши deploy только доверенным пользователям. Секретные значения
делай masked/hidden, где GitLab поддерживает это для выбранного типа переменной.

| Переменная | Обязательность и назначение |
| --- | --- |
| `SSH_PRIVATE_KEY` | Для deploy: **File**, приватный ключ выделенного deploy-пользователя; либо вариант ниже. CRLF удаляется перед использованием. |
| `SSH_PRIVATE_KEY_B64` | Альтернатива File: base64 ключа; CRLF удаляется и из base64, и из декодированного ключа. Не задавай оба варианта. |
| `DEPLOY_HOST` | Для deploy: DNS-имя/IP сервера; без него job не появляется. SSH-порт 22. |
| `DEPLOY_USER` | Для deploy: SSH-пользователь с доступом к Docker и каталогу приложения. |
| `DEPLOY_PATH` | Необязательно: `/opt/fable`; абсолютный путь без пробелов, только буквы/цифры и `_./-`. |
| `DEPLOY_URL` | Необязательно: публичный HTTPS URL для ссылки environment `production`. |
| `SSH_KNOWN_HOSTS` | Рекомендуется: заранее проверенная строка/строки `known_hosts` (обычная variable, не File). Без неё используется `ssh-keyscan`, что не защищает первый контакт от MITM. |
| `CI_DEPLOY_USER`, `CI_DEPLOY_PASSWORD` | Рекомендуется: пара deploy token с `read_registry`. Если пара не задана, используются `CI_REGISTRY_USER` / `CI_JOB_TOKEN`; временный Docker login удаляется после deploy. Задавай обе переменные вместе. |
| `SKIP_TESTS` | Необязательно: строка `true` для пропуска lint/test/integration, например `git push -o ci.variable=SKIP_TESTS=true gitlab`. |

`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD` и
`CI_JOB_TOKEN` предоставляет GitLab. LLM API-ключи и пароль production PostgreSQL
**не нужны в CI** и не должны попадать в репозиторий, artifacts или Docker image.

### Однократная подготовка сервера

- Установи Docker Engine и Compose plugin **>= 2.24.4** (production override использует
  `!reset`/`!override`, чтобы удалить `build` и заменить, а не добавить публикацию порта).
- Создай deploy-пользователя, добавь публичный ключ в `authorized_keys`, проверь SSH
  host fingerprint отдельно. Доступ к Docker эквивалентен root: используй отдельный ключ.
- Создай `/opt/fable` (или `DEPLOY_PATH`), выдай deploy-пользователю права на каталог.
- Только на сервере создай `$DEPLOY_PATH/.env` с правами `600`: `API_KEY`, `BASE_URL`,
  `MODEL`, **сильный `POSTGRES_PASSWORD`**; при необходимости `POSTGRES_USER=fable`,
  `POSTGRES_DB=fable`, `ALLOW_REGISTRATION`, параметры embeddings и LLM. Для пароля
  используй длинную случайную URL-safe строку: он входит в PostgreSQL URL; символы
  `@`, `:`, `/`, `#`, `%` потребуют URL-кодирования. Не задавай отдельный `DATABASE_URL`:
  production override строит его из `POSTGRES_*`; Redis уже доступен как `redis:6379`.
- `COOKIE_SECURE` по умолчанию `true`; настрой HTTPS reverse proxy на
  `127.0.0.1:8000`. При необходимости измени `FABLE_PORT_BIND=127.0.0.1:8000`;
  не публикуй PostgreSQL/Redis наружу. `.env` никогда не копируется из CI.
- Настрой backup постоянных томов и восстановление. Инициализационный пароль
  PostgreSQL применяется только к новому тому; его смена в `.env` не меняет пароль
  уже созданной роли. Миграции применяются при старте приложения.
- Включи registry, настрой CI variables и runner, дождись успешного build на
  защищённой default branch/теге, затем нажми manual **deploy**. Job копирует только
  два Compose-файла, выполняет `pull`, `up -d --no-build --remove-orphans --wait`
  и проверяет health приложения. Для отката вручную выбери предыдущий SHA-образ:

```bash
cd /opt/fable
export FABLE_IMAGE=registry.gitlab.com/<namespace>/<project>:<previous-short-sha>
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build --remove-orphans --wait
```

## Сохранения и память

Без DATABASE_URL игры автоматически сохраняются после каждого завершённого ответа в `SESSIONS_PATH` (по умолчанию `.fable/sessions`). CLI при запуске предлагает продолжить одну из пяти последних игр; в веб-интерфейсе доступен список сохранений. CLI использует корневой каталог, а backend — отдельные подкаталоги пользователей; старые CLI-сохранения не отображаются в веб-интерфейсе.

Новые параметры `.env`:

- `SUMMARY_ENABLED=true` — сжатие старых реплик в резюме; `SUMMARY_MAX_CHARS=2000` ограничивает его длину. Полная история остаётся в сохранении.
- `SUMMARY_MODEL` — отдельная модель для резюме; если не задана, используется `MODEL`.
- `CONSISTENCY_CHECK_ENABLED=true` — проверка ответа на противоречия контексту и действиям героя. Замечание учитывается в следующем ответе.
- `CONSISTENCY_MODEL` — модель проверки; по умолчанию `MODEL`.
- `SESSIONS_PATH` — каталог JSON-сохранений.

Резюме и проверка согласованности используют дополнительные запросы к LLM с температурой `0`. Их можно отключить независимо. Модерация управляется `MODERATION_ENABLED` и `MODERATION_MODEL`, векторная память — `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `MEMORY_STORE_PATH` и `MEMORY_SEARCH_LIMIT`.

## Спутники

К герою можно добавить до трёх спутников: имя (до 40 символов), роль (до 80) и характер (до 1000). Имена обязательны, уникальны без учёта регистра и не должны совпадать с именем героя. В CLI после создания героя появится вопрос «Добавить спутника? (д/н)».

Мастер оркестрирует отдельные роли: вызывает `ask_companion(name, situation)`, передавая только увиденное и услышанное спутником, а затем включает его реакцию в сцену. Каждый вызов `ask_companion` — **дополнительный запрос к LLM**, поэтому сцена со спутниками может занимать больше времени и токенов. При сбое спутник молчит, ход мастера продолжается.

У каждого спутника своё отношение к герою от −100 до 100 (от «враждебно» до «доверяет»), присутствие рядом и до 20 заметок о том, что он узнал. Мастер фиксирует подтверждённые изменения через `update_companion`; за один вызов отношение меняется не более чем на 25 пунктов. Личный промпт спутника содержит только его заметки, а не знания других спутников; мастер должен сохранять эту границу при описании ситуации. Спутники не принимают решения за героя. Состояние сохраняется вместе с игрой; старые сохранения без спутников продолжают загружаться.

Настройки `.env`:

- `COMPANIONS_ENABLED=true` — отдельные агенты и инструменты спутников включены. При `false` профили и состояние остаются в игре и сохранениях, но оба инструмента отключены: спутников озвучивает сам мастер, без отдельных запросов и автоматического обновления их структурированного состояния.
- `COMPANION_MODEL` — отдельная модель для реплик; по умолчанию используется `MODEL` и тот же endpoint.
- `COMPANION_TEMPERATURE=0.8` — температура реплик спутников, от `0` до `2`.

API `POST /api/games` принимает необязательный массив `companions: [{"name": "Лис", "role": "разведчик", "personality": "осторожный"}]`. Ответы создания/чтения игры содержат `setup.companions` с этими профилями и `state.companions` с полями `name`, `role`, `attitude` (число), `attitude_label`, `present`, `notes`. То же состояние приходит в SSE-событии `done`. Неверные профили возвращают 422 с русской строкой `detail`; текст спутников проходит общую проверку безопасности.

## Эксперименты

Стенд для задачи 7 ВКР сравнивает модели и управление контекстом на одинаковых русскоязычных сценариях. Измеряются TTFT (до первого непустого текстового фрагмента), полная задержка хода, длина ответа в символах, доля нарушений согласованности и валидность структурированных ответов. Отдельный LLM-судья оценивает связность, соответствие герою, отсутствие противоречий и агентность игрока (1–5); факты-пробы проверяют воспроизведение ранних сведений.

```bash
poetry install
# Полностью офлайн: не читает .env, не вызывает LLM или embeddings.
poetry run fable-eval --dry-run --out eval/results/demo

# С доступным LLM endpoint из обычных настроек приложения:
poetry run fable-eval --scenarios eval/scenarios --configs static,agentic_full \
  --model MODEL_A --model MODEL_B --judge-model FIXED_JUDGE \
  --repeat 5 --out eval/results/comparison
```

Конфигурации: `static` — прямое продолжение с последними репликами, без tools/состояния; `static_summary` — тот же baseline с резюме; `agentic` — tools и состояние без резюме/проверки; `agentic_summary` — плюс резюме; `agentic_full` — плюс проверка согласованности; `agentic_full_companions` — отдельные роли спутников; `agentic_memory` — плюс векторная память (без `EMBEDDING_MODEL` пропускается с пояснением). Профили спутников при выключенных отдельных ролях озвучивает сам мастер. Вариант спутников пропускается в сценариях без спутников.

`--turns N` ограничивает число действий, не считая начальной сцены; `--history-limit 8` меняет окно для всех вариантов; `--override agentic_full.consistency=false` переопределяет отдельный фактор. Повторы задаются `--repeat N`, модели — повторяемым `--model`. Для сравнения всех условий рекомендуется один фиксированный `--judge-model`.

Результаты: `runs.jsonl` (каждая попытка хода), `transcripts/*.md` (стенограммы), `snapshots/*.json` (финальное состояние, резюме и судья), `manifest.json` (факторы и пропуски), `summary.csv` и `summary.md`. Без `--out` каталог создаётся в `eval/results/<timestamp>`; результаты исключены из Git, непустой каталог не перезаписывается. Офлайн-демо использует фиктивные оценки и время, **не** пригодные для выводов о качестве LLM.

Все Chat Completions-вызовы учитываются по ролям: master (каждый tool-round), companion, consistency, summarizer, moderator, plain и отдельно evaluation judge. Для streaming запрашивается финальный usage (`stream_options.include_usage`); при явной неподдержке параметра запрос один раз повторяется без него, и адаптер запоминает это для следующих запросов. Без usage используется грубая оценка `ceil(символы / 4)`, помеченная `estimated=true` / «≈»; это не токенизатор и не счёт провайдера. Embeddings в эти токены и стоимость не входят. Цена рассчитывается по `MODEL_PRICES`; если тариф хотя бы одной модели неизвестен, общий `cost_usd=null`. В UI расход хода раскрывается под ответом мастера, в панели мира показаны накопленные значения.

API: SSE `done.usage` и `entries[].usage` завершённого ответа содержат `{prompt_tokens, completion_tokens, total_tokens, llm_calls, estimated, cost_usd, duration_ms, by_role}`; `by_role` отображает роль в `{prompt_tokens, completion_tokens, total_tokens, calls}`. GET `/api/games/{id}` (также ответ создания игры) добавляет `usage_total` той же формы: суммы по сохранённым завершённым ответам, включая `by_role`; `duration_ms` суммируется. Неудачные/отклонённые ходы не прикрепляются к предыдущему ответу и не входят в игровые накопления. Старые сохранения загружаются без миграции: отсутствующие usage не восстанавливаются задним числом, сумма токенов покрывает только измеренные ходы, стоимость при пробелах неизвестна. В стенде неудачные попытки всё же учитываются, а затраты judge сохраняются отдельно от игровых ходов.

Методика, формулы метрик, формат сценариев, рубрика судьи и угрозы валидности: [docs/evaluation.md](docs/evaluation.md).

## Ограничения прототипа

- Поддерживается один герой, которым управляет игрок.
- Без PostgreSQL + Redis backend рассчитан на один процесс; для multi-worker включи оба адаптера (см. выше). Для внешнего доступа нужны HTTPS и безопасные настройки cookie.
- Для работы нужен доступный LLM-сервер с потоковой генерацией.
