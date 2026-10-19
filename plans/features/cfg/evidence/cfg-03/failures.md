# CFG-03 — реестр сбоев/отклонений (R3, формат P0A-PERSIST-AUDIT)

Каждая строка: причина → затронутые пути → кодовая правка → автотест →
evidence → статус. Нумерация CFG03-F{n}.

## F1. «Мёртвые ручки» изображали действующие настройки (5 шт.)

* **Причина:** параметры созданы в каталоге (видимы в UI, сохраняются в
  PG/overrides), но рантайм их не читает: нет ни литерала `pg_key`, ни
  чтения settings-поля, ни env-чтения, ни динамического шаблона (repo-wide
  скан, включая JS-витрину; комментарии исключены).
* **Затронутые пути (класс):** `limits.chat_budget_response_ratio`,
  `limits.chat_lock_max_entries`, `limits.dig_year_back_window_days`,
  `limits.youtube_transcript_proxy_locations`,
  `limits.youtube_transcript_proxy_retries`.
* **Кодовая правка:** `services/param_catalog.py` — описания дополнены
  «Не влияет: значение сохраняется в конфиге, но рантайм его не читает…»
  (честная витрина CFG-03.6; вывод из UI не делался — это продуктовый выбор
  владельца, отдельное согласование).
* **Автотесты:** `tests/test_cfg03_param_audit.py::TestConsumerCoverage::
  test_dead_knobs_honest_descriptions` (RED→GREEN),
  `::test_visible_dead_knobs_are_exactly_documented` (точный список).
* **Evidence:** `red-baseline.txt`, `red-green.txt`, `e2e-log.json`
  (карточки в реальном рендере), `ui/01…06*.png`.
* **Статус:** FIXED (static + e2e). Live preprod — Ф6.

## F2. Каталог-тип не совпадал с factory-дефолтом (2 шт.) — DEFERRED

* **Причина:** ключи создавались с типом `int`, при этом `Settings` хранит
  `float` (`IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS` = 300.0, env `_env_float`;
  рантайм читает `float(...)`) и `str` (`YOUTUBE_TRANSCRIPT_PROXY_RETRIES` =
  "", env `_env_str`; рантайм не читает вовсе).
* **Затронутые пути:** `limits.image_freq_limit_cooldown_seconds`,
  `limits.youtube_transcript_proxy_retries` (оба — visible в UI).
* **Почему не исправлено в этом слайсе:** тип каталога пинуют тесты ЧУЖИХ
  слайсов, вне write_scope CFG-03:
  `tests/test_cfg02b_image_freq_limits.py:266` (`retries/cooldown == "int"`),
  `tests/test_hot_migration.py:225` (`retries.type == "int"`).
  Правка этих файлов — расширение scope (решение PM) либо отдельный
  мини-коммит «catalog delta + re-pin» (процедура §3.4).
* **Текущее состояние:** расхождения документированы в тесте
  (`TYPE_FAMILY_EXCEPTIONS`) и в `inventory.json`/`audit-summary.json`
  (`kind=default_type_mismatch`); пользовательской поломки нет: значение
  `300.5` не теряется (`_cast_to_type` возвращает как есть), ключ `retries`
  не читается рантаймом (F1).
* **Автотест:** `test_settings_field_type_family` (исключения перечислены
  явно — новые расхождения падают).
* **Статус:** DEFERRED (scope; рекомендация: включить 2 пина + 2 типа в
  следующий catalog-коммит, например в окно CFG-04/07B).

## F3. Флаг в группе лимитов (документированное исключение, не дефект)

* `flags.chat_context_budgets_enabled` (тумблер) живёт в группе
  `limits_chat_budgets` (секция лимитов бюджетов на «Ответах в чате») —
  осознанная разметка; проверено, что рендер не ломается (e2e-окна модулей).
* **Статус:** DOCUMENTED (allowlist в `GROUP_CATEGORY_EXCEPTIONS`).

## F4. env-only без Python-читателя (7 шт.) — задокументировано

* `postgres_db`, `postgres_user`, `postgres_password`, `telegram_api_id`,
  `telegram_api_hash`, `cobalt_http_proxy` — читаются **docker-compose.yml**
  (вне Python-рантайма) — не дефект, документировано в тесте
  (`DOCKER_ENV`).
* `media_base` — читается в `Settings` при старте, но нигде не используется;
  UI-места нет (api-only). Решение о выводе из `.env` — за владельцем,
  не блокирует (см. R4).
* **Статус:** DOCUMENTED.

## F5. Pre-existing (не CFG-03)

* `tests/test_asap7_direct_settings.py::test_migration_v35_idempotent_twice`,
  `::test_backup_guard_fires_before_pending_step` — падают и на базовом
  worktree `71c12bfe` (проверено первопричинно; ранее зафиксировано в
  CFG-01 evidence как pre-existing v35).
* `tests/test_summary_publish_integration_round1026.py::TestOnDelivery::
  test_on_l1_not_usable_level2_l2_publishes_article` — падает и на базе
  (проверено на worktree `71c12bfe`).
* **Статус:** PRE-EXISTING (вне слайса; в бласте отмечены).
