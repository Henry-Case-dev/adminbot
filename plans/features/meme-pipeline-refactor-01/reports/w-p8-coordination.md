# P8 / MEME-INIT-COORDINATION — независимость механизмов и координация публикаций

Исполнитель: Builder (lane `feat/meme-init-coord`).
Основание: `plans/owner_inputs/2026-11-03-initiative-independence-coordination.md`
(sha 42D6EB80) + `arch/initiative-coordination.md` (frozen).
База: `760916e8`. Коммиты — только в ветке `feat/meme-init-coord`.

## 1. Что сделано по восьми решениям владельца

| № | Решение | Где |
|---|---|---|
| 1 | Независимость: свой ростер мемов, отдельная обработка ошибок фаз, `chat_enabled` реально останавливает мемы, общего состояния сброса нет | `services/meme_initiative.py` (`meme_chat_roster`), `services/initiative_observer.py` (`run`, `_meme_phase`) |
| 2 | Мем виден общему журналу выводов: `output_kind="meme_initiative"` | `services/database.py` (`BOT_OUTPUT_KINDS`), `meme_initiative._record_meme_output` |
| 3 | Атомарный примитив «ровно одна публикация»: таблица v41 + CAS-UPSERT | `services/publication_coordination.py`, шаг `_migrate_publish_claim_v41` |
| 4 | Pre-send координация в обоих механизмах (дешёвая проверка + атомарная бронь), поведение проигравшего | `initiative_observer._evaluate_phase/_act_on_opportunity`, `meme_initiative.consider_chat` |
| 5 | Межтиповой интервал `initiative.cross_type_publication_interval_seconds` (глобально + per-chat, дефолт = `MIN_GAP_FLOOR_SECONDS`, `0` выключает, `max(свой кулдаун, интервал)`) | `publication_coordination.resolve_cross_type_interval/resolve_gap_seconds` |
| 6 | Случайность: один `RandomSourceService`, два purpose, общий формат трассы, fallback — валидный источник | `initiative_observer.random_trigger/build_draw_trace`, `meme_initiative.draw_trigger`, `mca_random_source.PURPOSE_INITIATIVE_TRIGGER` |
| 7 | `/meme` приоритетен: маркер ДО генерации, чужой `sending` → `publication_in_flight` | `handlers/meme_command.py`, `publication_coordination.claim_manual_priority` |
| 8 | Диагностика: восемь полей на механизм внутри существующего payload/журнала | `initiative_observer._note_decision/chat_block_state`, `meme_initiative._note_state/_availability_diagnostics` |

## 2. Схема: ровно одна аддитивная таблица, версия 41

```sql
CREATE TABLE IF NOT EXISTS chat_publish_claim (
  chat_id              INTEGER PRIMARY KEY,
  claim_id             TEXT    NOT NULL,
  holder_kind          TEXT    NOT NULL,
  holder_ref           TEXT    NOT NULL DEFAULT '',
  state                TEXT    NOT NULL,          -- claimed|sending|released|cancelled
  claimed_at           INTEGER NOT NULL,
  expires_at           INTEGER,                   -- NULL = аренды нет
  last_publish_ts      INTEGER,
  last_publish_kind    TEXT    NOT NULL DEFAULT '',
  last_publish_ref     TEXT    NOT NULL DEFAULT '',
  manual_priority_until INTEGER,
  updated_at           INTEGER NOT NULL
)
```

* индексов нет (PK `chat_id` достаточен), backfill не нужен, `CREATE TABLE IF NOT EXISTS`
  идемпотентен; PG-копии нет (состояние отправки — операционная SQLite рядом с
  `mca_bot_outputs`), в `pg_db.DDL_STATEMENTS` таблица не регистрируется;
* версия схемы: `_SCHEMA_VERSION_PUBLISH_CLAIM = 41`, шаг `chat_publish_claim_v41`,
  DDL живёт в модуле-владельце (`publication_coordination.CLAIM_DDL_SQLITE`), шаг его
  только применяет (одна схема — один владелец, как у v40);
* `BOT_OUTPUT_KINDS` += `"meme_initiative"` — DDL не меняется, только закрытый набор
  значений `output_kind`;
* откат — cold git revert: таблица инертна, код v40 её не читает.

## 3. Протокол брони (claim protocol)

1. **precheck** (ничего не пишет, объясняет): читает строку брони + последнюю публикацию
   ДРУГОГО типа из `mca_bot_outputs` (`kinds=PUBLICATION_KINDS`), берёт САМУЮ свежую из двух
   источников (журнал и watermark строки). Возвращает `ok/reason/detail` и все числа.
2. **acquire** — один стейтмент, атомарное решение (SQLite WAL). `rowcount==1` — бронь выдана.
   Условие выдачи: строка свободна (`released`/`cancelled`) ИЛИ аренда истекла
   (`expires_at <= now`) ИЛИ ручной запрос забирает чужой `claimed`; чужой
   `manual_priority_until` блокирует автоматический путь; межтиповой интервал проверяется
   И по журналу (`:other_ts`), И по watermark самой строки (внутри стейтмента — гонка
   send→claim не проходит). Своя публикация интервалом не ограничивается.
3. **claimed → sending** — отдельный `UPDATE ... WHERE chat_id AND claim_id AND state='claimed'
   AND expires_at > now AND (manual OR manual_priority_until IS NULL OR <= now)`.
   Только он разрешает звать sender; `rowcount==0` — отмена с причиной.
4. **release** — `state='released'`, `expires_at=NULL`; при `published=1` пишется
   `last_publish_ts/kind/ref`. Освобождается только СВОЯ бронь (`claim_id`).
5. TTL: `claimed` 90 с, `sending` 120 с, `manual_priority_until` 600 с.
6. Рестарт/обрыв: бронь в `sending` с истёкшим TTL переоценивается как «публикация, возможно,
   состоялась» (`last_publish_ts = claimed_at`, `last_publish_kind = holder_kind`,
   `detail = delivery_unknown`); повторной отправки старой бронью нет — её `claim_id`
   уже не совпадает.
7. Деградация: таблицы нет → **мем** останавливается на своём `schema_absent`
   (`detail=publish_claim_absent`); **текстовая инициатива** публикует с
   `coordination=degraded` и одним WARN (нельзя молча выключить основной механизм).
8. Запрещено и не введено: глобальный `asyncio.Lock`, advisory-locks, второй планировщик/
   воркер/очередь, второй генератор случайности. `asyncio.sleep`/`time.sleep`/`create_task`
   в модуле нет (проверяется тестом).

## 4. Наблюдаемые результаты (тесты, кандидат `feat/meme-init-coord`)

| Сценарий | Наблюдение |
|---|---|
| Одновременная готовность (оба порядка) | ровно 1 публикация; у проигравшего `publication_conflict` + `detail=cross_type_interval`; sender не вызван |
| 8 параллельных воркеров на одном файле SQLite | ровно один `claim_id` дошёл до `sending`, 7 отказов `publication_conflict` |
| 8 параллельных acquire одного типа | ровно одна выданная бронь (CAS сериализует) |
| Рестарт: `sending` с истёкшим TTL | следующий acquire проходит, `recovered_delivery_unknown=True`, watermark = `claimed_at`, повтор старой бронью запрещён (`publication_expired`) |
| TTL `claimed` | до истечения — `claim_held`, после — бронь переходит новому владельцу |
| Устаревший мем | окно изменилось после брони → `publication_stale`, sender не вызван, бронь освобождена без watermark |
| Свежее окно | тот же проход публикуется, `last_publish_ts/kind` записаны |
| `/meme` | маркер ставится ДО генерации (`delete → priority → pipeline`); авто-путь получает `manual_priority`; чужой `claimed` забирается, чужой `sending` → `publication_in_flight`, вторая публикация невозможна |
| Разные чаты | одновременные публикации в двух чатах обе успешны (глобальной блокировки нет) |
| Интервал `0` | другой тип проходит сразу |
| Интервал `< своего кулдауна` | мем всё равно ждёт (`SKIP_COOLDOWN`), зазор = `max()` |
| Текстовый pre-check | чат отсекается ДО LLM (`eval_skips.publication_conflict`), окно не «отработано» |
| Текстовый publish_guard | отказ → `cancelled/publication_conflict`, sender не вызван, intent `pending/deferred`, attempts=0 |
| Текстовая фаза падает | мем-фаза всё равно выполняется, статус задачи `failed` не скрыт (`text_phase_errors=1`) |
| Мем виден ledger | `mca_bot_outputs` получает `output_kind=meme_initiative`, `tg_message_id`, `delivered`; повтор job_id не двоит строку |
| Ростер мемов | тихий чат учитывается без текстового скана; не-групповые/выключенные отфильтрованы; лимит `MAX_CHATS_PER_PASS`, порядок — «дольше не проверяли» |
| `chat_enabled=false` | мем не публикует (`initiative_disabled`) |

**Мутационная проверка (тесты действительно падают):** отключение проверки свежести,
снятие интервала из CAS, снятие `claim_id` из предиката `claimed→sending`, разрешение
публикации без таблицы брони, обход `publish_guard` в `handle_initiative` — каждый раз
падал соответствующий тест (проверено, затем откатано).

## 5. Настройки и дефолты

| Ключ | Тип | Дефолт | Смысл |
|---|---|---|---|
| `initiative.cross_type_publication_interval_seconds` | int (с) | `MIN_GAP_FLOOR_SECONDS` = 1800 | ограничивает только пару разных типов; `0` — координация по интервалу выключена |
| `initiative.trigger_probability` | float 0..1 | `1.0` | вероятность попытки текстовой инициативы; при 1.0 draw не выполняется (паритет), при 0 — сразу `random_miss` без draw |
| `flags.meme_initiative_enabled` / `initiative.enabled` / `flags.initiative_observer_enabled` | — | как было | мастер/чат/мем-тумблеры сохранены; пересечений нет |

Резолв обоих новых ключей — существующий generic: `chat_params` override → `hot_config` →
дефолт (как у мем-настроек). **Записи в `param_catalog.py` не добавлены сознательно:**
каталог пиннится десятками «замороженных» тестов чужих пакетов (`test_rew*`,
`test_summary_*::test_catalog_zero_delta`, `test_round1025_f8_registry` и др.), а
витрина/UI по решению Архитектора (§4) — аддитивное поле **P4 (web)**. Ключи работают
и настраиваются через существующий путь без каталога — ровно как `initiative.meme_*`.
Если P4 будет добавлять запись каталога, обновление счётчиков-пиннов идёт одним пакетом
вместе с ней.

## 6. Тесты

Новый файл `tests/test_initiative_coordination.py` — 45 тестов (CONTRACT/REGRESSION):
независимость, ростер, `chat_enabled`, случайность (включая реальный `RandomSourceService`
на PRNG-пути и fallback как валидный источник), одновременная готовность в двух порядках,
8 воркеров, рестарт/устаревание/TTL, `/meme` (включая порядок «маркер до генерации»),
разные чаты, интервал и его границы, ledger-видимость и анти-дубль, диагностика,
схема v41, деградация без таблицы, текстовый pre-check и publish_guard.
Правки существующих: `tests/test_evol014_meme_initiative.py` (fallback-кейс «c» по решению
§2 — публикация с `source=pseudorandom`; пины версии схемы 40→41),
`tests/test_evol016_prompt_journal_v39.py` и `tests/test_mca17c_invariants_round1047.py`
(только пины «последняя версия схемы» 40→41 — та же практика, что применялась при v40).
`asyncio.sleep`/`time.sleep` в тестах нет; время — параметром.

Прогон затронутых наборов: **235 passed** (initiative/meme/coordination/v39/v41-инварианты).
Полный прогон сравнён с базой `760916e8` на одном и том же списке файлов:
**70 падений у меня = 70 у базы**, новых регрессий 0 (остальные — pre-existing:
webapp UI/JS, summary-golden, youtube-флаги, fc-admission — воспроизводятся на базе).

## 7. Что должен потреблять P9 (диагностика/UI)

*Текстовая инициатива* — `payload["chats"][chat]["last_decision"]` (durable `task_jobs`):
`ts`, `skip_reason` + `skip_label`, `random` (полный `DRAW_TRACE_FIELDS`),
`publication` (`ok/reason/detail/state/holder_kind/other_kind/other_age_seconds/
interval_seconds/manual_priority_until/coordination/checked_at`), `conditions`,
`cooldown` (`min_gap_seconds`, `last_initiative_age_seconds`,
`last_any_age_seconds`), `next_check_ts`.
Плюс `chat_block_state()["state"]`: те же `publication`, `random`, `last_decision`,
`next_eval_ts`, `cooldown_seconds` и новый гейт `publication` в `items`
(поле `gate == "publication"`).

*Мемы* — `payload["meme"]["chats"][chat]` и `payload["meme"]["roster"]`/`roster_source`:
`last_check_ts`, `next_check_ts`, `random`, `conditions` (счётчики стадий),
`reason` + `reason_label`, `cooldown_seconds`, `publication`
(`claim`/`sending`/`watermark`/`output`), `stage`, `job_id`, `published`.
Плюс `meme_initiative.availability(...)["diagnostics"]`:
`last_check_ts`, `next_check_ts`, `random`, `conditions`, `skip_reason`,
`cooldown_seconds`, `cooldown_remaining_seconds`, `publication` (с готовым
`conflict: bool`).

Важно для UI: блоки двух механизмов независимы, «нет данных» ≠ нули; `publication`
одного блока не подменяет другой; `coordination="degraded"` — честная метка
деградации, а не «всё хорошо».

## 8. Известные ограничения / риски

* `P5/P6` (`feat/meme-joke-speech`) ещё не влит в базу `760916e8`; мой коммит
  правит те же участки `meme_initiative.py` (стадия B). При мерже возможен конфликт
  в `consider_chat` — он локален (мой блок — координация публикаций + факты этапов).
* Интервал по умолчанию 1800 с означает: после мема текстовая инициатива ждёт до
  30 минут (и наоборот) — это и есть требуемое «не публиковаться друг за другом».
* Живая приёмка (`/meme` в чате владельца + отсутствие текстовой инициативы в пределах
  интервала) — по PET_PROJECT выполняется после релиза; из Builder-контура Telegram
  не трогался.
