# Архитектура Fable

Fable разделяет правила кампании, сценарии приложения и технические адаптеры.
Это небольшой модульный монолит, а не набор микросервисов: границы ниже помогают
объяснять ответственность кода, но не требуют отдельных процессов или баз данных.
Домен не зависит от FastAPI, OpenAI SDK, ChromaDB и файловой системы.

## Карта пакетов

Все пути ниже относятся к `src/fable/`; небольшие `__init__.py` обозначают пакеты.

```text
domain/         game/{game,setup,state,events}.py
                companions/companion.py, safety/{safety,consistency}.py, users/user.py
application/    game/{service,session,persistence}.py, narrative/{summary,consistency}.py
                companions/ports.py, safety/guardrails.py, auth/service.py, ports.py
                prompts/{loader,master,companion,start}.py, prompts/templates/*.md
infrastructure/ llm/{client,structured,embeddings}.py
                agents/{master,plain,companion,tools,master_tools}.py
                checks/{moderator,consistency,summarizer,judge}.py
                persistence/{session_store,game_repository,auth_store}.py
                memory/chroma.py, security/passwords.py
presentation/   web/{app,auth,schemas,sse}.py, cli/main.py
evaluation/     cli.py, configurations.py, factory.py, runner.py, reporting.py, scenarios.py
bootstrap.py    общая композиция; config.py — настройки; game.py — запуск через python -m
```

Тексты ролей, правил, начальной сцены, summary/consistency/moderator/judge,
инструкции baseline, служебные замечания и описания инструментов находятся каждый
в отдельном `application/prompts/templates/*.md`. `load_prompt(name)` читает UTF-8
через `importlib.resources` и кэширует строку **без strip и добавления перевода строки**.
`render_prompt` использует только `string.Template` (`${name}`): фигурные скобки JSON
остаются литералами, подставленные данные не обрабатываются повторно. Builders
сохраняют прежние JSON-профили, ограничения длины и точные байты вывода; snapshots
в `tests/fixtures/prompts_before_refactor.json` сняты до переноса.

Тесты зеркалят слои и контексты в `tests/{domain,application,infrastructure,presentation,evaluation}`;
во всех пакетах есть `__init__.py`. Проверка: `poetry run python -m unittest discover -s tests`
(также поддерживается `-t .`). CLI entry points: `presentation.cli.main:main`,
`presentation.web.app:main`, `evaluation.cli:main` (с префиксом `fable.`).

## Единый язык

| Термин | Значение |
| --- | --- |
| Игра / кампания | Одна история с неизменяемыми настройками, текущим состоянием мира и повествовательной сессией. Идентифицируется `Game.id`. |
| Мастер | Агент, который описывает сцены и оркестрирует инструменты; не принимает важные решения за героя. |
| Герой | Единственный персонаж игрока; профиль `Character` задаёт имя, роль, цель, описание и жанр. |
| Спутник | Персонаж с постоянным профилем `Companion` и изменяемым состоянием `CompanionState`: отношение, присутствие, личные знания. |
| Ход | Действие игрока и завершённый ответ мастера. Начальная сцена генерируется отдельно и не входит в счётчик ходов. |
| Состояние мира | `GameState`: текущая локация, инвентарь героя, подтверждённые факты, состояния спутников. Не полный текст рассказа. |
| Факт | Уже установленное обстоятельство мира, а не план, предположение или обещание мастера. |
| История | Полная последовательность сообщений игрока и мастера, включая метаданные проверки и событий. |
| Резюме | Сжатое изложение старых сообщений для контекста модели. Полная история остаётся в сохранении. |
| Вердикт согласованности | `ConsistencyVerdict`: согласован ли ответ с контекстом; замечания направляются мастеру на следующем ходе. Отрицательный вердикт не отменяет ход. |
| Доменное событие | Неизменяемое описание реально произошедшего изменения состояния. Не команда, не текстовый токен модели и не запись в векторной памяти. |
| Проверка безопасности | Проверка исходных настроек или действия. Блокировка действия не добавляет его в историю. |
| Сохранение | Агрегат игры и снимок повествовательной сессии: атомарная замена JSON-файла либо транзакционное сохранение JSONB в PostgreSQL с проверкой версии. |

## Ограниченные контексты

| Контекст | Модули и граница |
| --- | --- |
| Игровой процесс | `domain/game/game.py`, `domain/game/state.py`, `domain/game/events.py`; сценарии — `application/game/service.py`. Владеет кампанией и завершением хода. |
| Персонажи / спутники | `domain/game/setup.py`, `domain/companions/companion.py`; порт голоса — `application/companions/ports.py`, адаптер — `infrastructure/agents/companion.py`. Состояние спутника входит в кампанию, это не отдельный сохраняемый агрегат. |
| Повествовательная память | `application/game/session.py`, `application/narrative/summary.py`, `application/narrative/consistency.py`, `application/prompts/`; JSON-история, LLM-резюме и проверка, `infrastructure/memory/chroma.py`. Векторные воспоминания отделены от подтверждённых фактов мира. |
| Безопасность | `domain/safety/safety.py`, `application/safety/guardrails.py`, `infrastructure/checks/moderator.py`. Решение о допустимости отделено от генерации сцены. |
| Пользователи | `domain/users/user.py`, `application/auth/service.py`, `infrastructure/persistence/auth_store.py`, `infrastructure/security/passwords.py`, `presentation/web/auth.py`. Аутентификация, cookie, изоляция сохранений; не правила сюжета. |

Контексты пока связаны прямыми вызовами Python. События служат объяснимой лентой
изменений для игрока, а не распределённой шиной сообщений или event sourcing.

## Агрегат, сущности и объекты-значения

- **Корень агрегата `Game`** (`domain/game/game.py`): `id`, `owner_id`, `setup`, `state`,
  `created_at`, `updated_at`, `version` (optimistic concurrency PostgreSQL; 0 у нового агрегата). `Game.create(id, owner_id, setup, now)` проверяет
  настройки и создаёт начальные состояния спутников. `owner_id=None` допустим для
  CLI и старых файлов. `pull_events()` забирает и очищает события вложенного состояния.
- **Сущность состояния мира `GameState`** (`domain/game/state.py`): изменения только
  через `update()`, получение спутника через `companion(name)`. Пустые значения не
  добавляются; предметы и факты не дублируются без учёта регистра. Удаление предмета
  имеет приоритет над добавлением в одном вызове. Повтор той же локации не событие.
  `restore()` восстанавливает снимок на том же объекте и очищает события: инструменты
  и провайдер контекста удерживают ссылку на него.
- **Сущность `CompanionState`** (`domain/companions/companion.py`): идентифицируется именем
  внутри кампании. `change_attitude()` ограничивает шаг до ±25; итог в диапазоне
  −100…100. `remember()` убирает пробелы, не добавляет пустые/повторные заметки,
  хранит последние 20. `set_present()` фиксирует уход/возвращение. Загрузка личных
  знаний из файла не создаёт событий.
- **Объекты-значения `GameSetup`, `Character`, `Companion`, `Attitude`**:
  неизменяемые dataclass. Настройки разрешают до трёх спутников; имя непустое, до
  40 символов, уникальное без учёта регистра и отличное от имени героя; роль до
  80, характер до 1000 символов. `Attitude` задаёт число и русскую метку отношения.
- **Объекты-значения `ConsistencyVerdict`, `SafetyVerdict`, доменные события**:
  неизменяемые результаты проверок и описания изменений.
- **`User`** — отдельная идентичность контекста пользователей, не дочерняя
  сущность кампании. Каталоги пользователей выбираются доверенным адаптером.

`GameSession` не является доменной сущностью: это прикладная повествовательная
сессия с агентом, историей, резюме и проверками. `LoadedGame` связывает агрегат,
живую сессию и process-local lock; `StoredGame` — сохраняемый конверт агрегата
и снимка сессии. Так агент и история не проникают в чистую модель мира.

## Доменные события

Все классы находятся в `domain/game/events.py`, наследуют `DomainEvent`, заморожены и
предоставляют `type`, русское `describe()` и `to_dict()`.

| Класс | `type` | Дополнительные поля JSON | Условие |
| --- | --- | --- | --- |
| `LocationChanged` | `location_changed` | `location` | Изменилась непустая локация |
| `ItemAcquired` | `item_acquired` | `item` | Добавлен новый предмет |
| `ItemLost` | `item_lost` | `item` | Удалён имевшийся предмет |
| `FactEstablished` | `fact_established` | `fact` | Установлен новый факт |
| `CompanionAttitudeChanged` | `companion_attitude_changed` | `companion`, `delta`, `value`, `label` | Изменилось итоговое число отношения; `delta` — фактическая разница |
| `CompanionLearned` | `companion_learned` | `companion`, `note` | Добавлена новая личная заметка |
| `CompanionLeft` | `companion_left` | `companion` | Присутствие сменилось с true на false |
| `CompanionReturned` | `companion_returned` | `companion` | Присутствие сменилось с false на true |

Общие поля JSON: `type` и `text`. Нулевой шаг, достижение границы отношения,
дубли и другие no-op не создают событий. Буферы не входят в `state.to_dict()`;
после успешной генерации сервис забирает события и прикрепляет непустой список
к последнему ответу мастера **до сохранения**. Сбор идёт сначала из мира, затем
из состояний спутников в порядке профилей; это не глобальные временные метки.

API сохраняет прежние поля и добавляет:

- SSE `done`: `events: [{"type": "…", "text": "…", …}]` **всегда**, в том числе `[]`.
- `GET /api/games/{id}`: у ответа мастера в `entries[]` есть `events`, только если
  список непуст. Исторические записи без этого поля остаются допустимыми.

## Порты и адаптеры

| Порт / граница | Реализация / адаптер |
| --- | --- |
| `GameRepository` (`application/ports.py`) | `JsonGameRepository` поверх `JsonSessionStore` (по умолчанию); `PostgresGameRepository(pool, owner_id)` (`infrastructure/persistence/postgres/`) при DATABASE_URL. Оба: `get`, `add`, `save`, `delete`, `list_summaries` |
| `StreamingAgent` (`application/ports.py`; переэкспорт в `session.py`) | `GameMasterAgent` (`infrastructure/agents/master.py`): собственный streaming tool-loop через OpenAI SDK; `PlainStreamingAgent` — baseline без tools |
| `Guardrail` (`application/safety/guardrails.py`) | `RuleGuardrail`, `CompositeGuardrail`, `LLMModerator` (OpenAI SDK + Pydantic JSON Schema) |
| `Summarizer` (`application/narrative/summary.py`) | `LLMSummarizer` (OpenAI SDK, обычный текст) |
| `ConsistencyChecker` (`application/narrative/consistency.py`) | `LLMConsistencyChecker` (OpenAI SDK + Pydantic JSON Schema) |
| `CompanionVoice` (`application/companions/ports.py`) | `LLMCompanionVoice` (OpenAI SDK, обычный текст) |
| `StoryMemory` (`application/ports.py`; переэкспорт в `master_tools.py`) | `ChromaMemory`: прямой `chromadb.PersistentClient`, SDK embeddings, фильтр `campaign_id` |
| `AuthStore` (`application/auth/service.py`) | `SqliteAuthStore` (по умолчанию); `PostgresAuthStore(pool)` при DATABASE_URL |
| `LockManager` (`application/ports.py`) | `InMemoryLockManager`; при REDIS_URL — `RedisLockManager`: SET NX PX, token, Lua compare-and-delete |
| `LoginRateLimiter` (`application/ports.py`) | `InMemoryLoginRateLimiter` (скользящее окно); при REDIS_URL — `RedisLoginRateLimiter` (INCR + EXPIRE в Lua, фиксированное окно 5/300 секунд) |
| Фабрики репозитория и сессии, нормализация настроек, часы, генератор id | Внедряются в `GameService`; HTTP-композиция в `create_app`, создание LLM-компонентов в `bootstrap.py` |
| Входной HTTP-адаптер | `presentation/web/`: `app.py` — маршруты, ошибки и static mount; `schemas.py` — запросы, `sse.py` — сериализация и cleanup, `auth.py` — cookie |
| Входной CLI-адаптер | `presentation/cli/main.py`: интерактивный UX, тот же агрегат и репозиторий в корне каталога сохранений |

`application/ports.py` также переэкспортирует `Guardrail`, `Summarizer`,
`ConsistencyChecker`, `CompanionVoice`. Прямые импорты используют контекстные подпакеты; shim-модулей по прежним плоским путям нет.
Репозиторий возвращает `StoredGame | None`, не создаёт LLM-сессию при чтении и
сохраняет прежнюю структуру файла с добавлением необязательного `owner_id`.
Старые файлы без владельца/спутников читаются через `parse_game_record`;
если профили спутников есть, но состояния ещё нет, оно инициализируется из профилей.
Веб использует `SESSIONS_PATH/<user_id>`, CLI — корень. Проверки безопасного id и
символических ссылок, атомарная запись остались в `JsonSessionStore`.

## LLM-транспорт и инструменты

`infrastructure/llm/client.py` — единственная фабрика `OpenAI(base_url, api_key,
timeout, max_retries)`; `ChatModel` хранит идентификатор модели и параметры запроса.
Мастер и static-baseline используют общий `thinking_extra_body`; вспомогательные роли
сохраняют прежние температуры и не передают thinking-расширений.
`infrastructure/llm/structured.py` содержит схемы модерации, consistency, оценок и probes и общий helper структурированного ответа.
`complete_structured` запрашивает строгий `response_format=json_schema`, при отказе
сервера последовательно пробует `json_object` и инструкцию без response_format.
`STRUCTURED_OUTPUT` задаёт начальный режим. Pydantic-валидация и прежние парсеры
сохраняют fail-open игрового приложения, но не маскируют невалидные оценки в стенде.

`infrastructure/agents/tools.py` определяет минимальный `Tool`: имя, описание, JSON Schema из небольшой
Pydantic-модели аргументов и обработчик. `infrastructure/agents/master_tools.py` связывает их с доменом.
Мастер собирает tool-call deltas по индексу (id, имя, фрагменты JSON), сохраняет
assistant content и tool_calls в локальном контексте, последовательно исполняет
вызовы и добавляет сообщения `role=tool`. Неизвестный tool, неверный JSON или
ошибка валидации возвращают русское сообщение об ошибке, не обрывая ход.
В публичный поток поступает только `delta.content`, никогда не результаты tools.
После `MAX_TOOL_ROUNDS` раундов исполнения выполняется финальный запрос с
`tool_choice="none"`. Накопленные вызовы с непустым именем исполняются независимо от `finish_reason` (`tool_calls`, `stop`, `None`); в финальном раунде инструменты не исполняются. SDK-поток закрывается и при отмене генерации.

## Прикладной сервис

Публичный API `GameService`:

```python
create_game(owner: str | None, setup: GameSetup) -> LoadedGame
list_games(owner: str | None) -> list[dict]
get_game(owner: str | None, game_id: str) -> LoadedGame
delete_game(owner: str | None, game_id: str) -> None
start_stream(owner: str | None, game_id: str) -> TurnStream
play_turn_stream(owner: str | None, game_id: str, action: str) -> TurnStream
```

Ошибки приложения не знают HTTP: `GameNotFound`, `GameBusy`,
`GameAlreadyStarted`, `GameNotStarted`, `SetupRejected`, `InvalidSetup`,
`InvalidAction`. Веб-адаптер отображает их в прежние 404/409/422 и русские сообщения.
Поток выдаёт `Chunk`, `TurnCompleted`, `TurnBlocked`, `TurnFailed`, а не SSE-строки.
`TurnStream` нужно исчерпать либо закрыть (`close()` или контекстный менеджер).

CLI намеренно сохраняет собственный интерактивный цикл и прежние сообщения об
ошибках: использует агрегат и репозиторий, но не подменяет терминальный UX
веб-сценарием `TurnFailed`. Общее создание агента остаётся в `bootstrap.py`.

## Жизненный цикл хода

1. HTTP-адаптер проверяет cookie и получает пользователя. Сервис загружает игру
   только из его репозитория; восстановление кэша синхронизировано.
2. Сервис неблокирующе берёт lock конкретной игры. Конкурирующая генерация или
   удаление дают `GameBusy`. Проверка начата/не начата выполняется под этим lock.
3. Сохраняются снимки сессии, состояния мира и предыдущий `updated_at`.
4. Для действия сессия проверяет безопасность до записи в историю. При необходимости
   сжимает старые сообщения. Агент получает обычные role/content сообщения,
   не метаданные событий, и постоянный контекст.
5. Мастер генерирует текст и вызывает инструменты. Они изменяют мир только через
   `GameState.update` и методы `CompanionState`; доменные правила и события не
   дублируются в инструментах или HTTP-обработчиках. Куски текста сразу выдаются
   как `Chunk`, а HTTP-адаптер превращает их в SSE `chunk`.
6. После полного ответа сессия проверяет согласованность и записывает ответ.
   Сбой проверки не обрушает ход; отрицательный вердикт создаёт замечание для
   следующего запроса. Резюме и полный снимок истории сохраняются вместе.
7. Сервис забирает события агрегата, прикрепляет непустой список к ответу,
   обновляет время и сохраняет агрегат со снимком сессии через репозиторий.
8. Только после успешного сохранения выдаётся `TurnCompleted`; HTTP формирует
   `done` с вердиктом, состоянием, резюме и обязательным массивом событий.
9. При блокировке выдаётся `TurnBlocked`; при ошибке агента/сохранения — `TurnFailed`.
   При неуспехе или отмене восстанавливаются состояние на прежней ссылке,
   сессия, время; накопленные события отбрасываются. Успешно сохранённый ход не
   отменяется, если клиент отключился уже во время отправки `done`.
10. В `finally` закрывается генератор и освобождается lock. `GameStreamResponse`
    делает shielded cleanup и закрывает `TurnStream` даже при обрыве до первого
    чанка; освобождение идемпотентно, включая закрытие ещё не запущенного генератора.

## Слои и зависимости

```mermaid
flowchart TD
    HTTP["presentation/web/app.py — HTTP, auth, SSE"] --> SERVICE["application/game/service.py: GameService — сценарии и lock"]
    CLI["presentation/cli/main.py — терминал"] --> DOMAIN["domain/game + domain/companions"]
    CLI --> PORT["application/GameRepository + StoredGame"]
    SERVICE --> DOMAIN
    DOMAIN --> EVENTS["domain/game/events.py: DomainEvent — изменения"]
    SERVICE --> SESSION["application/game/session.py: GameSession — история, проверки, резюме"]
    SERVICE --> PORT
    JSON["infrastructure/persistence: JsonGameRepository"] -. реализует .-> PORT
    JSON --> STORE["JsonSessionStore — JSON"]
    SESSION --> AGENTPORT["StreamingAgent, Guardrail, Summarizer, ConsistencyChecker"]
    LLM["infrastructure/agents + checks + llm"] -. реализуют .-> AGENTPORT
    LLM --> DOMAIN
    ROOT["bootstrap.py + create_app — композиция"] -. внедряет .-> SERVICE
    ROOT -. создаёт .-> LLM
```

## Границы гарантий

По умолчанию блокировки и LoadedGame-кэш — в памяти одного backend-процесса.
Опциональный multi-worker режим требует DATABASE_URL + REDIS_URL:
`FABLE_WORKERS=N` запускает Uvicorn по import string с `factory=True`; родитель
не создаёт пул до fork/spawn. Каждый воркер имеет свой пул (DB_POOL_MIN=1,
DB_POOL_MAX=10), Redis-клиент; lifespan освобождает ресурсы. Выбор адаптеров и
owner-scoped фабрика находятся в `bootstrap.py`; без URL нет внешних подключений.

PostgreSQL хранит users (lower-unique username), auth_sessions (SHA-256 токена,
FK ON DELETE CASCADE, индекс expires_at), games (nullable owner_id FK для CLI,
JSONB setup/state/session, title, timestamps, turns, version). Индекс игр:
(owner_id, updated_at DESC). Общий `stored_game_record` строит JSON/JSONB-конверт,
`parse_game_record` восстанавливает legacy-состояния. `save` проверяет version и
инкрементирует её атомарно; неуспех даёт PersistenceConflict, а не lost update.
Нумерованные SQL из wheel применяются транзакционно под advisory lock, версии
учитываются в schema_migrations; отдельный entry point — `fable-migrate`.

При любом внешнем адаптере LoadedGame-кэш выключен: GET читает БД/файл заново,
ход повторяет чтение под game-lock, перед проверкой started и снимками отката.
Реконструкция агента на чтении — сознательная плата за отсутствие stale state.
GameService освобождает локальный и внешний lock также при отмене до итерации.
TTL Redis по умолчанию 600 секунд, без renewal: оператор должен выбрать TTL
больше максимального полного хода с учётом tools/SDK retries/вспомогательных LLM.
Optimistic version остаётся защитой при истечении аренды. После начала SSE
конфликт сохранения передаётся как error/status_code=409 (HTTP уже отправлен);
до потока — HTTP 409. Список summaries пока не кэшируется в Redis: прямой
индексированный SELECT избегает отдельного протокола race-free invalidation.
CLI использует то же PostgreSQL-хранилище для owner_id=NULL, но не web-lock;
не запускайте одну CLI-игру параллельно в нескольких терминалах.

Нет событийной шины и outbox. Отдельные вызовы векторной памяти не входят в
откат JSON/JSONB-состояния/истории; локальная Chroma не стала multi-process
сервисом. В multi-worker режиме оставьте EMBEDDING_MODEL незаданным до подключения
общего сервера векторной памяти.
`GameSession` по-прежнему владеет алгоритмами резюме и согласованности, а
существующие функции `build_game_record` / `parse_game_record` сохранены для
совместимости. Проверки не требуют живого LLM: используются fake-агенты,
временные хранилища, сервисные unit-тесты и ASGI-тесты отмены потока.
