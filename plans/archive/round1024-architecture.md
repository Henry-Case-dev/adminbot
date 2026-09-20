# Round 10.24 — сквозной архитектурный слой (Step 2 @Architect, часть 1/2: backend-core)

> **Эпик:** «Disaster Recovery: UI & Backend Bloat» — 12 фич F1–F12 (багфикс-итерация после отклонённого UI-раунда 10.23).
> **Источники:** `plans/current_task.md` UPD2 (стр. 123–237) + **UPD3 (стр. 239–272)** — untracked, в git НЕ коммитить, секреты/креды в задачах и отчётах НЕ цитировать (R17/R18); `plans/backlog.md` §«Раунд 10.24»; `tasks.md` 12 фич-папок; отчёты @Memory Шага 0 (координаты багов).
> **Baseline:** HEAD `00eab85`; pytest **7424/0**; SQLite `v12`; каталог **REGISTRY 457 / GROUPS 96 / `_TAB_BY_GROUP` 94**; APP_VERSION 2.57.0; прод `4314ea4`.
> **Статус:** часть 1 из 2 — **F1, F2, F7, F8, F9, F12** (бэкенд/ядро). Часть 2 — UI/web (F3, F4, F5, F6, F10, F11).
> **ADR части 1:** ADR-1024-1 (логирование), ADR-1024-2 (retention/диск), ADR-1024-3 (лимит клише + крон), ADR-1024-4 (универсальный payload изображений + тест-подключения), ADR-1024-5 (живой дебаг/Empty State экстрактора), ADR-1024-6 (устойчивость фонового graph-extract).
> **Важное решение владельца (UPD3 п.7):** задача по embeddings (`requests`) **ОТМЕНЕНА** — код `services/llm_client.py:embed` **не трогать** (владелец сам меняет ключ/провайдер). В F1 остаётся только п.0a (graph-extract).

---

## 0. Что уже есть (не переизобретаем)

Round 10.24 — **не** новый функционал, а **ремонт** трёх контуров, которые молча деградировали:

| Контур | Симптом | Где живёт сейчас |
|---|---|---|
| Фоновый graph-extract | `LLMTimeoutError` на `nano-gpt.com`, батч сохраняется, **граф теряется**; крон не двигается с места | `services/summary_memory.py:3179-3268` → `services/llm_client.py:871-938,618-760` |
| Наблюдаемость | «тихий откат для юзера» = тишина в логах; нет тел ответов сторонних API, причин падения крона/экстрактора | лог-точки `image_generation`/`anticliche_worker`/`dream_worker` |
| Инфраструктура | диск +6 ГБ; крон клише не стартовал сам; лимит клише 20; мёртвый экстрактор; обложка зависит от модели | `memory_rebuild`/`memory_backup`, `anticliche_worker/cache`, `dream_worker`, `image_generation`/`summary_generator` |

Общие якоря System 2 (инварианты раунда 10.22/10.23) сохраняются и **этим раундом не переписываются**: физический двухвызовный конвейер, egress-реестры `SEND_POINTS`/`SEND_ALLOWLIST`, `parse_mode=None` plain-каналов, `imported-history-immutable`, `manual-overrides-immutable`.

---

## 1. Обзор 12 фич и их место

| # | Фича | Слой | Приоритет | Δ каталога | DDL | Часть |
|---|---|---|---|---|---|---|
| **F1** | `core-llm-error-fixes-round1024` — п.0a: устойчивость graph-extract (таймаут/чанки/метрика) | LLM/память | P0 | 0 | 0 | **1** |
| **F2** | `logging-infra-round1024` — единый R17-safe лог внешних API + трассировка крона/экстрактора | инфра (enabler) | P1 | 0 | 0 | **1** |
| **F3** | `token-metrics-nodeflow-round1024` — Node Flow последнего вызова | UI/web | P1 | 0 | 0 | 2 |
| **F4** | `dossier-live-feed-round1024` — вертикальная лента + клик → Досье | UI + API | P1 | 0 | 0 | 2 |
| **F5** | `image-module-toggle-round1024` — карточка «Генерация изображений» в «Модулях» | каталог + UI | P1 | +таб/группа | 0 | 2 |
| **F6** | `prompts-refactor-accordion-modes-round1024` — аккордеоны/fallback-режим/табы | каталог + UI | P1 | −ключ | 0 | 2 |
| **F7** | `anticliche-cron-limit-round1024` — лимит 200 (регулируемый) + фикс крона | worker/каталог | P1 | **+1 ключ, +1 группа** | 0 | **1** |
| **F8** | `dead-extractor-paradigms-round1024` — живой дебаг Сна, traits/paradigms, Empty State | backend + API | P0 | 0 | 0 | **1** |
| **F9** | `disk-space-audit-retention-round1024` — аудит/очистка/retention/отчёт | ops/данные | P0 | 0 | 0 | **1** |
| **F10** | `aliases-render-real-fix-round1024` — реальный data-binding алиасов | UI/web | P1 | 0 | 0 | 2 |
| **F11** | `byok-image-key-round1024` — сохранение image-ключа через `/api/config/keys/own` | UI + backend | P1 | 0 | 0 | 2 |
| **F12** | `summary-cover-model-compat-round1024` — универсальный payload изображений + тест-кнопка | backend + лог | P1 | 0 | 0 | **1** |

> **Итог Части 1:** Δ каталога = **+1 ключ + 1 группа** (только F7) → `REGISTRY 457→458`, `GROUPS 96→97`, `_TAB_BY_GROUP 94→95`. **Δ DDL = 0** (SQLite остаётся `v12`, новых PG-таблиц нет). Новые рубильники — только env-only `ClassVar` (default ON), вне `param_catalog`.
> **Порядок Части 1:** `F2 (лог-хуки) → F1 ∥ F7 ∥ F8 ∥ F9 ∥ F12` (F2 — enabler: даёт причину в логах для всех). F9 (ops) независима и может идти параллельно.

---

## 2. Карта изменений (файлы → владелец)

| Файл | Владелец (Часть 1) | Что меняется |
|---|---|---|
| `services/external_log.py` (**новый**) | **F2** | Helper `log_external_api`/`trace_step`/`log_dropped`/`redact_url`/`safe_text` |
| `services/disk_retention.py` (**новый**) | **F9** | `audit`/`plan_cleanup`/`apply_cleanup`/`prune_db_backups`/`forecast_monthly` |
| `services/llm_client.py` | **F1** (эксклюзив) | `generate_background(...)` + опциональные per-call `budget`/`max_retries` в `_post` (default None = байт-в-байт) |
| `services/summary_memory.py` | **F1** (граф) → F2 (лог) | Фазовый `_extract_and_save_graph` (extract→write), чанкование, счётчик dropped |
| `services/anticliche_cache.py` | **F2** (лог) → **F7** | `ANTICLICHE_MAX_PATTERNS` → динамический `max_patterns()` (default 200) |
| `services/anticliche_worker.py` | **F2** (лог) → **F7** | `build_patterns(max=resolved)`, промпт `{max}`, `next_run_time`, freshness-skip, фазы в лог |
| `services/dream_worker.py` | **F2** (трассировка) → **F8** | Декаплинг traits от paradigms, статусы/причины, трассировка этапов |
| `services/image_generation.py` | **F2** (лог) → **F12** | Минимальный payload, `probe()`, тела ошибок в лог |
| `services/summary_generator.py` | **F2** (лог) → **F12** | Кап/порядок промпта обложки, лог `style_present`/финального промпта |
| `services/memory_backup.py` | **F9** | `_rotate` делегирует `prune_db_backups` (единый источник) |
| `services/memory_rebuild.py` | **F9** | `create_safety_backup` вызывает `prune_db_backups` |
| `services/memory_maintenance.py` | **F9** | `imported_history_*.jsonl` помечается IMMUTABLE (не удаляется) |
| `services/param_catalog.py` | **F7** → (Часть 2: F5→F6) | +группа `limits_anticliche`, +ключ `ANTICLICHE_MAX_PATTERNS` |
| `config/settings.py` | F1→F2→F7→F8→F9→F12 (аддитивно) | env-only `ClassVar` (см. §3.3) |
| `manage.py` | **F9** | CLI `manage.py disk audit|cleanup` |
| `web/api/routes.py` (или новый `web/api/images.py`) | **F12** → (Часть 2: F11) | `POST /api/images/test` (RBAC global admin) |
| `web/api/anticliche.py` | F7 | `max_patterns` = резолвленное значение |
| `tests/…` | по фиче | Egress-сканер секретов, retention, cron, extractor, payload |

---

## 3. Общие контракты

### 3.1. Логирование (F2, ADR-1024-1) — `services/external_log.py`

Принцип владельца: **«тихий откат для конечного пользователя ≠ тишина в серверных логах»**.

Единый интерфейс (все точки раунда пишут ТОЛЬКО через него):

```python
# services/external_log.py
REDACTED = "***"

def redact_url(url: str, *, keep_query: bool = False) -> str: ...
    # убирает userinfo (://user:pass@) и query; keep_query=True → маскирует
    # только секрето-подобные параметры (key|token|secret|api|auth|password|sig)

def safe_text(text, *, limit: int | None = None) -> str: ...
    # log_ring.sanitize + схлопывание пробелов + обрезка до EXTERNAL_API_LOG_BODY_CHARS

def log_external_api(logger, *, provider, method=None, url=None, status=None,
                     reason=None, body=None, duration_ms=None,
                     attempt=None, level=logging.INFO) -> None: ...

def trace_step(logger, *, component, step, status, reason=None, chat_id=None,
               extra=None, level=None) -> None: ...   # event=pipeline_step

def log_dropped(logger, *, component, reason, count=1, chat_id=None,
                extra=None) -> None: ...                # event=dropped_metric
```

**Политика уровней:** штатный фоллбэк (сработал резерв) → `WARNING`/`INFO`; реальный сбой (4xx/5xx/исключение/потеря данных) → `ERROR`. Один вызов = одна строка с полями `event/provider/status/reason/url/body`.

**R17-инварианты хелпера:** тело внешнего ответа усекается (`EXTERNAL_API_LOG_BODY_CHARS`, default 1024), URL — без query/userinfo, `Authorization`/ключи маскируются `log_ring.sanitize` (Bearer, `sk-…`, `gsk_…`, `or-…`, `tvly-…`, URI-креды, литеральные секреты каталога). Тела пользовательских сообщений НЕ логируются (приватность). `SecretMaskFilter` на консольном хендлере (`bot.py`) остаётся defense-in-depth.

**Точки внедрения (обязательные):**
- `image_generation._generate_post`/`_generate_get`/`_download_bytes` — статус + тело ошибки провайдера; `generate()` — итоговая причина «тихого отката» в саммари.
- `anticliche_worker.refresh/tick` — фаза (`fetch|llm|parse|empty|write`), статус, число полученных/сохранённых, `next_run_time`; `exc_info` для исключений.
- `dream_worker._run_deep_once`/`_run_persona_traits_once`/`_write_paradigm` — сквозная трассировка этапов с `chat_id` и причиной skip/empty/error.
- `summary_memory._extract_and_save_graph` — тип исключения, число чанков/успехов, признак «батч отброшен».
- `llm_client._post` (embed/chat 4xx) — уже пишет `body_4xx`; формат может быть выровнен, **логика embeddings не меняется** (UPD3 п.7).

### 3.2. Retention и диск (F9, ADR-1024-2) — `services/disk_retention.py`

**Таксономия файлов (жёсткая):**

| Класс | Шаблоны | Политика |
|---|---|---|
| **IMMUTABLE** | `imported_history_*.jsonl` (сырые архивы истории чата), `media/**`, SQLite-БД, `.env` | **НЕ удалять никогда** (жёсткое исключение владельца) |
| DB-бэкапы | `local_database_*.db`, `memory_rebuild_*.db` | хранить **ровно 1** новейший суммарно |
| facts-export | `facts_*.txt` | хранить 1 (пара к БД) |
| JSONL-ротация | `memory_generated_*.jsonl` и прочие не-history `*.jsonl` | удалять старше **180 дней** |
| Логи | journald | **7 дней** (`SystemMaxUse`/`MaxRetentionSec`) |

**Единый источник истины:** `prune_db_backups(directory, *, keep=1)` вызывается и `memory_backup._rotate`, и `memory_rebuild.create_safety_backup` — это закрывает корневую причину роста (+802 МБ `memory_rebuild_*.db` не попадали в ротацию, т.к. `_rotate` смотрел только `local_database_*`).

Порядок безопасности (fail-closed): `снимок → план → проверка свежего валидного бэкапа → удаление → лог «удалено/освобождено»`. Без валидного бэкапа удаление запрещено. CLI по умолчанию — dry-run, `--apply` осознанно.

### 3.3. Конфиг-ключи и env-флаги Части 1

**Единственный Δ каталога Части 1 (F7):**
- группа `limits_anticliche` (category `limits`, title «Анти-клише: лимиты», замаплена на вкладку `prompts` — там живёт карточка монитора `data-block="anticliche-monitor"`);
- ключ `limits.anticliche_max_patterns` (int, default **200**, group `limits_anticliche`).

**Новые env-only `ClassVar` (default ON, вне `param_catalog` → Δ каталога = 0):**

| Фича | Флаг | Default | Смысл |
|---|---|---|---|
| F1 | `GRAPH_EXTRACT_RETRY_ENABLED` | True | kill-switch новых чанков/ретраев (OFF → прежний одиночный вызов) |
| F1 | `GRAPH_EXTRACT_CHUNK_CHARS` | 4000 | размер окна промпта на вызов |
| F1 | `GRAPH_EXTRACT_MAX_CHUNKS` | 3 | потолок чанков на батч |
| F1 | `GRAPH_EXTRACT_TIMEOUT_SECONDS` | 120.0 | дедлайн фонового вызова |
| F1 | `GRAPH_EXTRACT_MAX_ATTEMPTS` | 2 | bounded retry на чанк |
| F1 | `GRAPH_EXTRACT_MAX_BATCH_FAILURES` | 3 | порог явного «отброшен» (не молча) |
| F2 | `EXTERNAL_API_LOGGING_ENABLED` | True | kill-switch тел/URL (OFF → только статус/причина) |
| F2 | `EXTERNAL_API_LOG_BODY_CHARS` | 1024 | лимит длины тела |
| F2 | `EXTERNAL_API_LOG_URL_QUERY` | False | логировать query (с маскировкой) |
| F7 | `ANTICLICHE_FIRST_RUN_DELAY_MINUTES` | 5 | первый прогон после старта |
| F8 | `DEEP_SLEEP_EXTRACT_FIX_ENABLED` | True | kill-switch декаплинга traits |
| F9 | `DISK_RETENTION_ENABLED` | True | kill-switch retention |
| F9 | `DB_BACKUP_KEEP` | 1 (fixed guard) | строго 1 бэкап БД |
| F9 | `JSONL_NONHISTORY_RETENTION_DAYS` | 180 | окно не-history JSONL |
| F9 | `LOG_RETENTION_DAYS` | 7 | окно логов |
| F9 | `HISTORY_JSONL_IMMUTABLE` | True (hard) | история неприкосновенна |
| F12 | `SUMMARY_COVER_MODEL_COMPAT_ENABLED` | True | kill-switch универсального payload |
| F12 | `SUMMARY_COVER_PROMPT_MAX_CHARS` | 1000 | универсальный кап промпта обложки |

### 3.4. Метрики/наблюдаемость (F1/F2/F7/F8)

Метрика = **структурированная лог-строка с `event=` + in-process счётчик** (Δ DDL = 0, PG-таблиц не добавляем). Ключевые события:
- `graph_extract_failed` / `graph_extract_partial` / `graph_extract_dropped` (F1) — с `chat_id`, `chunks_ok`, `chunks_failed`;
- `ext_api` (F2) — `provider/status/reason/body`;
- `pipeline_step` (F2/F8) — `component/step/status/reason`;
- `anticliche_refresh` (F7) — `phase/status/count/next_run_time`.

---

## 4. Инварианты раунда (нарушать нельзя)

1. **physical-two-call-pipeline** — ровно 2 физических LLM-вызова в System 2 (Stage-1 + Stage-2). Фоновые вызовы (graph-extract, крон клише, Сон) — вне этого счётчика, но должны оставаться bounded.
2. **egress-реестр** — новые send-точки (`send_rich_message` из 10.23) не меняются; F12 не добавляет отправок.
3. **R16** — API расширяется аддитивно (новые поля `*_status`/`reason` не ломают парсеры); **R17** — логи/отчёты только коды/числа/усечённые тела без секретов; **R18** — секреты из `current_task.md` не коммитить/не цитировать.
4. **`parse_mode=None`** — plain-каналы сохраняют инвариант; F12/F8/F1 не трогают текстовую доставку.
5. **imported-history-immutable** — `smart_messages`/FTS/vec/`import_checkpoints` и файловые `imported_history_*.jsonl` **не мутируются и не удаляются**.
6. **manual-overrides-immutable** — `persona_dossier_overrides` не перезаписываются; F8 пишет только производные (`graph_facts`/`persona_state`).
7. **Δ DDL = 0** — ни одной новой таблицы/колонки/миграции в Части 1; SQLite остаётся `v12`.
8. **Δ каталога фиксирована** — Часть 1 добавляет только ключ+группу F7; любое отклонение фиксируется в spec фичи.
9. **Порядок роутеров `bot.py`** не сдвигается (только DI-kwargs/вызовы).
10. **Совместимость по умолчанию** — все env-флаги default ON сохраняют новое (исправленное) поведение; OFF возвращает байт-в-байт прежнее (kill-switch).
11. **`tma-menu-freeze`** — структура табов/меню не меняется; F7 добавляет группу внутрь существующей вкладки `prompts`.
12. **embeddings не трогаем** (UPD3 п.7) — `services/llm_client.py:embed`/провайдер-схема остаются как есть; логирование остаётся наблюдательным.

---

## 5. Ступени общих файлов (Часть 1)

| Файл | Ступень вливания |
|---|---|
| `config/settings.py` | **F1 → F2 → F7 → F8 → F9 → F12** (аддитивно, каждый — свой блок ClassVar) |
| `services/llm_client.py` | **F1** (эксклюзив; F2 только читает существующие лог-точки) |
| `services/summary_memory.py` | **F1** (граф) → **F2** (лог) |
| `services/image_generation.py` | **F2** (лог) → **F12** (payload/probe) |
| `services/summary_generator.py` | **F2** (лог) → **F12** (обложка) |
| `services/dream_worker.py` | **F2** (трассировка) → **F8** (логика) |
| `services/anticliche_worker.py` + `anticliche_cache.py` | **F2** (лог) → **F7** (лимит/крон) |
| `services/param_catalog.py` | **F7** → (Часть 2) **F5 → F6** |
| `web/api/anticliche.py` | **F7** |
| `web/api/routes.py` (или `web/api/images.py`) | **F12** → (Часть 2) **F11** |
| `manage.py` | **F9** |
| `web/index.html` / `web/app.js` | Часть 2: **F3 → F5 → F6 → F11 → F4 → F10** (F7/F8-UI встраиваются в очередь) |

Правило: общий файл вливается строго по ступеням; фича более поздней ступени читает результат предыдущей и не переписывает её блоки.

---

## 6. AMEND / RE-OPEN карта

| Решение | Действие | Причина (UPD2/UPD3) |
|---|---|---|
| ADR-1023-4 D2 («лимит правил ≤20») | **AMEND → ADR-1024-3** | UPD3 п.3: хардкод 20 убрать, default **200**, регулируемый |
| ADR-1023-5 D1 (жёсткие `size`/`response_format:"url"`, capability-map) | **AMEND → ADR-1024-4** | UPD3 п.8: без карты модель→параметры; payload строго по OpenAI-минимуму |
| ADR-1023-6 §2/§3.2 (`SUMMARY_COVER_PROMPT_MAX=300`, порядок style+visual) | **AMEND → ADR-1024-4** | UPD2 п.10.1: стиль может обрезаться, инструкция не доходит |
| Фиксы экстрактора 10.18/10.20 | **RE-OPEN → ADR-1024-5** | UPD2 п.6: экстрактор «простаивает», прошлые фиксы не подтвердились |
| Human Gate #5 10.24 (3 бэкапа / journald 500 МБ/14 дн) | **ЗАКРЫТ владельцем (UPD3 п.5)** → ADR-1024-2 | строго 1 бэкап; JSONL 6 мес; **архивы истории неприкосновенны**; логи 7 дней |
| Human Gate #3 10.24 (потолок клише) | **ЗАКРЫТ владельцем** → ADR-1024-3 | default 200 + регулируемое поле |
| Human Gate #7 10.24 (смена embed-эндпоинта) | **ОТМЕНЁН** (UPD3 п.7) | владелец меняет ключ сам; код embeddings не трогать |
| `S10.19-24` (ротация `imported_history_*.jsonl`) | **Won't Fix по политике владельца** | UPD3 п.5: архивы истории **неприкосновенны** |
| ADR-1023-6 «тихий фолбэк» | **Подтверждён + уточнён** (ADR-1024-1/4) | тихий для юзера, но полный лог причины |
| ADR-1023-5 D5 (каталог image +3/+5) | Без изменений Частью 1; учтётся в Части 2 (F5/F11) | — |

---

## 7. Human Gate: статус (UPD3)

**Закрыто владельцем (до Step 2):**
1. Карточка изображений — отдельный пункт «Модулей» (Часть 2, F5).
2. Режим по умолчанию — **не удалять**, переименовать в «Резервный режим (Fallback)», default `casual`, не влияет на штатный dynamic decision-maker (Часть 2, F6).
3. Лимит клише — **200 + регулируемое поле** (F7).
4. traits — self-факты приоритет; при отсутствии — **Empty State** с пояснением, не галлюцинировать; извлечение фактов/парадигм о **пользователях** чинить (F8).
5. Retention — 1 бэкап; JSONL 6 мес; история неприкосновенна; логи 7 дней (F9).
6. BYOK image-ключа — разрешён через безопасный эндпоинт (Часть 2, F11).
7. Embeddings `requests` — **ОТМЕНА** (F1 не трогает embed-код).
8. Модели изображений — без hardcode-карты; payload универсальный; кнопка «Проверить подключение» (F12).
9. Клик по факту из ленты — переход на чат + модалка Досье (Часть 2, F4).

**Остаточные вопросы к владельцу (не блокируют старт):** нет. Все вводные UPD3 достаточны; при имплементации допустимы только уточнения формулировок.

---

## 8. Что передаётся Части 2 (UI/web)

- **F3** (`token-metrics-nodeflow`) — Node Flow CSS/Grid на уже существующем API `llm_usage_events`; русский нейминг.
- **F4** (`dossier-live-feed`) — вертикальная медленная лента + клик → контекст чата факта → модалка «Досье» (API `user_id`).
- **F5** (`image-module-toggle`) — таб/карточка «Генерация изображений» в «Модулях», глобальный тумблер default ON (AMEND ADR-1023-5 каталога; «Модули» — разморожено владельцем).
- **F6** (`prompts-refactor-accordion-modes`) — убить аккордеоны, дропдаун переименовать в «Резервный режим (Fallback)» (`casual`), табы режимов внутрь карточек.
- **F10** (`aliases-render-real-fix`) — реальный data-binding JSON-словаря алиасов; обязательный live-чек из БД.
- **F11** (`byok-image-key`) — сохранение image-ключа отдельным запросом `/api/config/keys/own`, заглушка `••••••••••••`, блокировка/очистка поля в GET-режиме.
- **F7/F8 UI-подписи** встраиваются в web-очередь (без одновременного редактирования `web/**`): счётчик/поле лимита клише (F7) и Empty State экстрактора (F8).

---

## 9. Веб-ресёрч (обязателен; «не гадай — гугли»)

| Факт | Источник |
|---|---|
| `POST /v1/images/generations` — **required только `prompt`**; `model`/`n`/`size`/`quality`/`response_format` — опциональны; `response_format` default **`b64_json`**; `size` default `1024x1024` | https://github.com/pollinations/pollinations/blob/HEAD/APIDOCS.md |
| Community-модели (owner/model id) поддерживают **только `b64_json`**; `response_format:"url"` для них → HTTP 400 «Community image models support response_format "b64_json" only» | https://github.com/pollinations/pollinations/blob/be33dc3a/gen.pollinations.ai/src/routes/images.ts |
| Сервер Pollinations эмитит `width/height` **только если caller передал `size`** — иначе model-specific defaults (сохраняет `dimensionsExplicit` для части моделей) | там же (`resolveParams`) |
| OpenAI Images API: required — `prompt`; `model/n/size/response_format/quality` — optional; у GPT-image моделей `response_format` не поддерживается (всегда base64), `size` — ограниченный набор/`auto` | https://developers.openai.com/api/docs/guides/image-generation · https://openai-hd4n6.mintlify.app/api-reference/images/create-image |

**Вывод для F12:** универсальный payload = `{prompt, model, n:1}` (без `size`/`quality`/`response_format`); ответ принимать и как `data[0].url`, и как `data[0].b64_json`. Это устраняет зависимость обложки от модели.

---

## 10. Ссылки

- ADR-1024-1 `plans/features/logging-infra-round1024/ADR-1024-1.md`
- ADR-1024-2 `plans/features/disk-space-audit-retention-round1024/ADR-1024-2.md`
- ADR-1024-3 `plans/features/anticliche-cron-limit-round1024/ADR-1024-3.md`
- ADR-1024-4 `plans/features/summary-cover-model-compat-round1024/ADR-1024-4.md`
- ADR-1024-5 `plans/features/dead-extractor-paradigms-round1024/ADR-1024-5.md`
- ADR-1024-6 `plans/features/core-llm-error-fixes-round1024/ADR-1024-6.md`
- Спеки: `plans/features/<feature>-round1024/spec.md`
- Архив-образцы: `plans/archive/round1023-architecture.md`, `plans/archive/dynamic-anticliche-cache-round1023/ADR-1023-4.md`, `plans/archive/image-generation-tool-round1023/ADR-1023-5.md`, `plans/archive/summary-cover-rich-article-round1023/ADR-1023-6.md`
- Scanner/аудит: `plans/reports/round1023_scanner_audit.md`, `plans/reports/round1023_f*.md`, `plans/reports/audit_backlog.md`
