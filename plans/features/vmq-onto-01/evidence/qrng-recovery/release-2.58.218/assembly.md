# Release 2.58.218 — QRNG-RECOVERY-01 / F-01 (activation self-check batch scope)

**Дата сборки:** 19.11.2026
**База (развёрнутый checkout):** `f68e7631dede326995b985bf8c3849d62def1bcb` (2.58.217, content `b6c9bb0b`, схема 48, PG DDL 0).
**Ветка:** `release/qrng-f01-2.58.218` (без force-push).
**Content tip:** `50b1dd6b32160d1ffbe393ebfa1701987fdde7b6` (F-01 product + bump/pins; evidence добавляется docs-only коммитом после).
**Статус:** REVIEW сборки. Продуктовый F-01 независимо одобрен ранее
(`f01-activation-reserve/review-r1.md`, коммит `a46825de`); эта релизная сборка
ожидает независимой проверки, VERIFIED не заявлен. Деплой не выполнялся,
production не затрагивался.

## 1. Состав поезда (2 коммита продукта + evidence)

| # | Что | Коммит |
|---|---|---|
| 1 | F-01 product+tests: `cherry-pick -x` одобренного `00d9ce3f84b4b83126d3f5544268c627e82df13c` | `6f2b7da62b94b09175bb9360866887c631ab5e9b` |
| 2 | Bump 2.58.217 → 2.58.218 + стандартная волна пинов | `50b1dd6b32160d1ffbe393ebfa1701987fdde7b6` |
| 3 | Release evidence (docs-only, этот каталог) | evidence-коммит ветки |

Выбран `cherry-pick -x`, а не `merge --no-ff` tip `15ca32f3d`: tip F-01-ветки
содержит evidence-only коммит (`implementation.md`, `tests.json`, RED/мутации),
и релиз должен содержать ровно одобренный продуктовый коммит. Перенос
проверяем: содержимое продукта байт-идентично `00d9ce3f8` (см. §2).

## 2. Точное равенство одобренному продукту

| Проверка | Результат |
|---|---|
| `git diff 00d9ce3f8 6f2b7da62 -- services/mca_random_source.py tests/test_qrng_f01_activation_batch_scope.py` | пусто, rc=0 |
| blob `services/mca_random_source.py` в `6f2b7da62` и `00d9ce3f8` | `4192f0338fa4c6766dc721c68c4989ab73538589` (оба) |
| blob `tests/test_qrng_f01_activation_batch_scope.py` | `17d754ab6a23f879c09a1696867e3f2fc977ba3a` (оба) |
| sha256 продукта | `0827075acf8f63004d16f31b8fa33e08c2c353f23d7717b141c2bf98f8d58111` — совпадает с `tests.json` F-01 |
| sha256 теста | `fb7f6951d33934d71b754b545175293e6d2a50760cc1a983e73400123bacc09a` — совпадает с F-01 evidence |
| `git diff --numstat f68e7631d..6f2b7da62` | `services/mca_random_source.py` 36+/5−, `tests/test_qrng_f01_activation_batch_scope.py` 234+/0− |

Иных продуктовых изменений в F-01-коммите нет.

## 3. Полный diff поезда

`git diff --shortstat f68e7631d..50b1dd6b3`: **32 files changed, +302 / −37**.

- Продуктовые файлы: `services/mca_random_source.py` (F-01) и `config/settings.py`
  (только строка `APP_VERSION`/changelog).
- Тесты: новый `tests/test_qrng_f01_activation_batch_scope.py` (234 строки) и
  24 файла пинов версии (по 1–2 строки).
- Метаданные: `plans/docs/param-registry-round1025.meta.md` (APP_VERSION/HEAD).
- `deploy_v2.9.2.py`, `services/pg_db.py`, `services/database.py`, `web/`, `handlers/`,
  `bot.py` — байт-идентичны `f68e7631d` (blob-хеши совпали).
- Новых флагов, эндпоинтов, промптов, моделей, агентов, планировщиков нет;
  `RandomStore` один, `reserve_chunk` один; composer не менялся.

## 4. Схема и DDL

- `services/database.py` байт-идентичен базе: схема остаётся **v48**
  (`_SCHEMA_VERSION_RANDOM_BATCH_PROVENANCE = 48`, шаг
  `random_batch_provenance_v48`), новых миграций/DDL нет.
- Две nullable-колонки `mca_random_batches.config_fingerprint` / `external_ref`
  уже добавлены релизом 2.58.217; F-01 их не трогает.
- PostgreSQL: `services/pg_db.py` байт-идентичен, **DDL 0**, шаг v48 — SQLite-only.
- Temp-DB smoke (временный каталог, удалён после прогона): `user_version=48`,
  обе колонки присутствуют, повторный `initialize()` — no-op.

## 5. Инварианты F-01 в собранном дереве

1. `RandomStore.reserve_chunk(..., batch_id=None)` — keyword-only, аддитивный;
   `None` сохраняет прежний oldest-first выбор для refill/dream chunk.
2. Пустой/пробельный `batch_id` даёт `AND 0` (пустой предикат), а не «любую партию».
3. `_confirm_activation(batch_id)` резервирует строго `batch_id=str(batch_id)` и
   отвергает чужую партию (contract guard); журнал/`activation_batch_id` строятся
   из фактически израсходованного item.
4. Нет значения в целевой партии → `_confirm_activation` возвращает `False`:
   чужая партия не расходуется, journal/state не пишутся; `activate()` отдаёт
   прежнюю ветку `validation_failed` / `deposited=false`.
5. Конфигурация, заводские значения, гейты и остальные random-пути не менялись.

## 6. Версия, каталог, Settings

| Инвариант | Значение |
|---|---|
| `APP_VERSION` | **2.58.218** (changelog: F-01 + `Prior 2.58.217`) |
| `REGISTRY` | **648** |
| `GROUPS` | **121** |
| `_TAB_BY_GROUP` | **119** |
| `TAB_RULES` | **23** |
| `Settings` (dataclass fields) | **472** |
| `gen_param_registry_round1025.py --check` | exit 0, «реестр 648 == REGISTRY» |
| `deploy_v2.9.2.py` | не изменён |

Стандартная волна пинов: 30 файлов / 32 замены (25 py/meta, 4 JS в escaped-виде,
`settings.py`), BOM (`EF BB BF`) и CRLF `settings.py` сохранены байтово
(3645 CRLF / 3646 LF до и после).

## 7. Проверки

Точные команды, результаты и базовые сравнения — `tests-2.58.218.json`. Кратко:
F-01 focused **4/0**, random/P1/P2/P3/blocks/QND **314/0**, mandatory **386/0**,
schema/apps **197/0**, JS **118/4** (те же 4 файла, что и на базе), `node --check`
rc=0, `git diff --check` rc=0, gen-check rc=0. RED и мутации F-01 не
переисполнялись в этой сборке и заново не заявляются — они уже доказаны в
`f01-activation-reserve/` и независимо воспроизведены ревьюером.

## 8. Намеренно не сделано

- Деплой, production-настройки/ключи/флаги, миграция production-БД.
- Живая активация с реальным ANU-ключом (не наблюдалась; `not_checked`).
- IBM paid jobs / реальные платные запросы не выполнялись.
