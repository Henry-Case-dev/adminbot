# Release 2.58.217 — QRNG-RECOVERY-01, сборка кандидата REVIEW

**Дата сборки:** 18.11.2026
**База:** развёрнутый checkout `5046090c7c3a9cdc59a37a0082a5effbdda9f1c7` (2.58.216, branch `release/p0-2.58.216`, content tip `faa2125c7`, схема 47, PG DDL 0).
**Ветка:** `release/qrng-2.58.217` (не force-push).
**Content tip:** `b6c9bb0bdec0f26ee72a3b7ab54c0a19f26610a0` (bump + пины + две ассемблерные правки; evidence-файлы добавляются docs-коммитом после).
**Статус:** REVIEW. Независимое ревью не пройдено, VERIFIED не заявлен, деплой не выполнялся, production не затрагивался.

## 1. Состав поезда

Порядок merge-коммитов (без rebase/force):

| # | Что | Кандидат | Merge в ветке |
|---|---|---|---|
| 1 | P1 isolation/honesty | `2e4c11cf52583b6f7631d377df0a7c8562cc27b9` (product `40be2117` на `f6451669`) | `aed8e5eae` |
| 2 | P2 LfDR adapter | `84abc2e554ab512e2cb5a170bbb090c0b8f56d7d` | `ed05dcdb0` |
| 3 | P3 selector/fallback corrective | `6cf4c32cc9bca3c58d16e22ccf499209b4cc80ab` | `28f980092` |
| 4 | P3 docs accuracy + N1 | `8137273209c02284cf4862bcee42ed04ab42ee75` (не ancestor P4) | `1c5266756` |
| 5 | P4 UI | `7f0e50ac89ba4f39abb7ce8d9900ca531895ceb6` (product `52662927`) | `d5eff3073` |
| 6 | Bump 2.58.217 + стандартная волна пинов | — | `dc3d666b8` |
| 7 | Согласование каталог/вкладки/routes-пинов | — | `a63fe4b18` |
| 8 | Ассемблерные правки webapp-контракта | — | `b6c9bb0bd` |

P5/IBM adapters и paid jobs **не включены**. IBM остаётся `external_wait`: в реестре есть id/метаданные, адаптера и job-lifecycle нет, UI не рисует его зелёным.

## 2. Конфликты и решения

| Файл | Решение |
|---|---|
| `plans/docs/param-registry-round1025.meta.md` (P3, P4) | Взят провенанс deployed-базы (2.58.216 / `faa2125c7`) + QRNG-счётчики; после поезда переэмитирован генератором: `648/121/119/23`, APP_VERSION 2.58.217. |
| `tests/fixtures/round1025/f8_baseline.json` (P3, P4) | Базовая B3-заметка сохранена, добавлены P3/P4-записи; baseline переэмитирован `tools/_qrng_p3_reissue_f8.py` / `_qrng_p4_reissue_f8.py`, TAB_RULES 23. |
| `tests/test_round1025_f8_registry.py` (P3, P4) | `PARAM_CATALOG_SHA256_FOLLOWUP` и `ROUTES_SHA256_F11` переутверждены по фактическому дереву; hidden 16→17 (`keys.random_quantum_provider`); TAB_RULES 23. |
| `tests/js/mod_acl_ux_m4a_w2b_history_test.js` (P4) | Оставлена deployed-схема `HISTORY_MODULES` (2.58.214 B3 уже включает `mod_random`); вариант P4 с ручным списком id отброшен как устаревший. |
| `web/app.js` `WORKSPACE_TABS.mod_random` | Дубликат, добавленный P4, удалён: deployed-база 2.58.214 B3 уже объявляет `mod_random: ['overview','settings','history']`. Комментарий B3 обновлён на `config_tab = mod_random`. |
| `tests/test_webapp_nav_disclosure_ui.py` | В набор memory-вкладок добавлен `mod_random` (P4 перенёс `memory_random` со «Сна»); счётчик групп 5 не ослаблен. |
| `tests/test_webapp_f5_round1025.py` | P4/LLM-01 осознанно переставил «Время ответа и защита» последней группой; устаревшее утверждение «policy первой» заменено на «policy последней», поля 180/360 не менялись. |
| `tests/test_mca10b_random_applications_block_d_round1041.py`, `tests/test_mca19_block_f_round1043.py`, summary/webapp-пины | `TAB_RULES/TAB_NAV/CONFIG_TAB_TITLES` 22→23 и `hidden` 16→17 согласованы с фактическим каталогом; assertions не ослаблены. |
| P4 provider-group порядок | Сохранён вариант P4 (модели/подключения первыми, `prov_policy` последней), подтверждён его mutation-пробой; deployed-порядок 2.58.206 здесь осознанно заменён санкционированным LLM-01. |
| PNG-evidence `plans/features/evol/audit/evidence/*` | Перезаписаны прогоном legacy webapp-тестов; возвращены к committed-байтам. В кандидат не входят. |

## 3. Объём и сохранность deployed-базы

`git diff --shortstat 5046090c7 b6c9bb0bd`: **164 files changed, +12523 / −693** (107 M, 57 A, 0 D).

- Продуктовые зоны: `services/mca_random_source.py`, `services/database.py`, `services/mca_gates.py`, `services/status_service.py`, `services/param_catalog.py`, `services/module_registry.py`, `services/config_cache.py`, `web/api/routes.py`, `web/app.js`, `web/index.html`, `config/settings.py`.
- `services/mca_vision.py`, `services/media_download.py`, `handlers/voice_transcription.py`, `services/voice_transcripts.py`, `bot.py` — **байт-идентичны** 5046090c7. Единственный затронутый смежный файл — `web/api/routes.py` (QRNG RBAC/scope/валидация), это ожидаемая зона.
- История 2.58.214 B3 (`module_registry`, `oversight:summary`, web app/index), 2.58.215 P0 L1/Vision/планировщик и 2.58.216 voice/telegram-local сохранена: их тесты входят в mandatory/webapp-наборы и проходят наравне с базой (см. `tests-2.58.217.json`).
- Новых RandomSource/store/scheduler/keys API нет; изменения аддитивны к существующему владельцу.

## 4. Схема и DDL

- SQLite: `47 → 48` шагом `random_batch_provenance_v48` — ровно две nullable-колонки `mca_random_batches.config_fingerprint` / `external_ref`, `ALTER TABLE ... ADD COLUMN` под guard `PRAGMA table_info`, повтор — no-op, строки не переписываются.
- PostgreSQL: `services/pg_db.py` байт-идентичен 5046090c7, **DDL 0**; шаг v48 — SQLite-only.
- Проверено: чистая БД (`user_version=48`), копия schema-47 (7 легаси-строк сохранены, идентичны, книга 48 = 1 строка, повторный запуск no-op, backfill 7/0, чужой ключ 0). См. `tests-2.58.217.json` → `migration_validation`.
- Code rollback на 2.58.216 после v48 безопасен: старый код колонки не читает, runner видит `current=48` и не имеет pending-шагов; данные не откатываются.

## 5. Каталог, Settings, версия

Фактическое дерево после поезда:

| Инвариант | Значение |
|---|---|
| `REGISTRY` | **648** |
| `GROUPS` | **121** |
| `_TAB_BY_GROUP` | **119** |
| `TAB_RULES` | **23** (P4 `mod_random`) |
| `Settings` (dataclass fields) | **472** |
| delta 411→ | **247** |
| `gen_param_registry_round1025.py --check` | exit 0 |

- `APP_VERSION = "2.58.217"`, changelog описывает P1–P4 и прямо фиксирует v48/DDL и каталог.
- Стандартная волна пинов: 30 файлов / 31 замена (25 py, 4 JS в escaped-виде, `meta.md`, `settings.py`), BOM/CRLF сохранены байтово.
- Схемные пины в тестах — 48 (exact equality, без ослабления).

## 6. Проверки

Полный матрикс, точные команды, RED на базе, мутации и smoke — `tests-2.58.217.json`. Кратко:

- P1 29 / P2 63 / P3 51 passed; random/QND 196; расширенный 310; schema/apps 197; mandatory 386 passed.
- Webapp: 1454 passed / 34 failed; на базе 5046090c7 — те же 1454/34 и **тот же набор** 34 node id (кандидатских падений нет). Ожидание 1455/33 из старого evidence сегодня не воспроизводится даже на базе.
- JS: 118 passed / 4 failed; на базе 117/4 с теми же 4 файлами; +1 новый тест P4.
- P4 Playwright: 35/35 checks, `ok=true`, 3 карточки/3 опции, Lizaonair отсутствует, draft-подсказка честная, страница без ошибок.
- M4A catalog e2e (W2a/W2b): failures=0, скриншоты только во временном run-dir.
- Свои мутации: fallback failover, deposited=false, fingerprint scoping — 3/3 killed, исходник восстановлен (sha256 совпал).
- Read-only smoke на временной БД: реестр ровно 3 id, default `ibm_quantum`, порядок `anu→lfdr`, strict reserve 8+8, `last_batch` без `config_fingerprint`, выбор `deferred` без PRNG.
- `node --check web/app.js` = 0; `git diff --check` по коду/тестам/инструментам = 0; полный diff поезда имеет whitespace только в унаследованных evidence `.txt/.md` кандидатов (не продукт, не переписаны).

## 7. Что не сделано намеренно

- Деплой, production-настройки/флаги/ключи, миграция production-БД — вне задачи.
- IBM P5, paid jobs, реальные значения Lizaonair — не включались.
- UI effective-state после деплоя и живой selector-статус — только postdeploy-runbook, не заявляются проверенными.
