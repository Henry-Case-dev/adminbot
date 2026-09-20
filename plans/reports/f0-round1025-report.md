# F0 `f0-config-bugfixes-round1025` — отчёт §54 (п.1–6), T-2441

> Раунд 10.25, Эпик 1, Wave 0. Базовая линия HEAD `ce9f869` (docs-коммит после
> `da561bc`): pytest **7911/0**. Итог: pytest **7933 passed / 0 failed**
> (7911 + 22 новых). Тег отката `pre-round1025`/`pre-round1025-f0`; бэкап
> `var/backups/web-round1025-f0-<ts>/` + `.env.bak.round1025-f0`.
> R17/R18: секретов в документах/диффе нет; `plans/current_task.md` не
> коммитится.

## п.1. Первопричина 409

Одно действие (дропдаун «Резервный режим») порождало ДВЕ мутации одного
профиля с ОДНИМ и тем же optimistic-токеном: автосейв `savePromptFallbackMode`
(без `await`/guard) + sticky-SaveBar (`dirtyItems`) повторяли ключ
`prompts.verbilizer_default_mode`; серверный `UPDATE ... WHERE updated_at=$3`
давал 0 строк → `ChatParamsConflict` → 409, а UI показывал три противоречивых
сообщения (успех/409/«Не сохранено»). Вторично: RC-4 (токен уровня профиля),
RC-5 (неатомарный global-путь), RC-6 (null-токен), RC-7 (нет защиты двойного
тапа). Доказательство — `tests/test_save_state_machine_round1025.py`.

## п.2. Fallback сохраняется корректно

- Клиент: единый `persistItems()` (guard in-flight по ключу, scope-split,
  обязательный токен для chat, 409-recovery без авто-retry), `savePromptFallbackMode`
  и `selectPromptMode` → `await saveConfigItem` → `persistItems`.
- Сервер: `D-409-1` idempotent short-circuit (значение уже на сервере → 200
  `revalidated:true`, без 409); `D-409-2` сериализация мутаций профиля
  (in-process `asyncio.Lock` + PG advisory-lock).
- Проверка: re-read совпадает; двойной тап = один POST.

## п.3. Остальные механизмы сохранения

Аудит-карта (14 механизмов, «сирот» нет) и цикл
`load→edit→save→re-read→compare` — `plans/reports/f0-save-audit-round1025.md`.
Канон write-path: `persistItems` → `POST /api/config` → `set_chat_params`
(chat) / атомарный `ConfigCache.set_many` (global). Секреты — BYOK.

## п.4. Локальное ≠ глобальное

Тест `test_scope_isolation_chat_a_not_b`; namespace-мерж `set_chat_params`
сохраняет `overrides/gates/keys/perm_overrides/meta`; `global → local → global`
не теряет и не подменяет; копии конфигурации под визуальные экземпляры нет.

## п.5. Промпты / модели / секреты

Тексты промптов не менялись; модели/ключи сохранены; секреты наружу только
`{configured,last4}`, в логи/артефакты не попадают. Регресс:
`test_settings_persistence_round1014.py`, `test_webapp_api.py`.

## п.6. Причина ограничения анти-клише и фикс

`limits.anticliche_max_patterns` (200) использовался и как вместимость, и как
размер запроса к LLM → усечённый JSON / `llm_error`, кэш не пополнялся
(«20 / 200»), UI показывал ложную «Ошибка модели».

Исправление (F0.3, ADR-1025-3):
- разведены семантики: вместимость (`limits.anticliche_max_patterns`) vs
  партия (`ANTICLICHE_MAX_PATTERNS_PER_RUN`, env-only, default 40);
- пакетное bounded-пополнение (≤ `ANTICLICHE_MAX_ROUNDS`=3, бюджет
  `worker_budget.consume`), дедуп против БД и внутри партии, «0 новых» = успех;
- статусы честные (`empty`/`no_new` ≠ `llm_error`); UI: `сохранено N /
  вместимость M; за обновление ≤ K`, «ошибка провайдера» вместо «ошибки модели»;
- события `ANTI_CLICHE_*` (capacity/per_run/candidates/duplicates/saved и т.д.),
  без фраз/секретов (R17).
- Доказательство: `tests/test_anticliche_semantics_round1025.py`,
  `plans/reports/f0-5-db-lock-round1025.md` (F0.5).

## F0.4 — уведомления и SaveBar

Один итоговый тост на операцию (`notify(operationId, result)` идемпотентен;
err>warn>ok, очередь ≤3, дедуп, стабильный id); «Подробнее» для длинных
ошибок; safe-area `.toast-wrap` (max(env, --tg-*-safe-area-*)); единое
`saveState` формы.

## F0.5 — `database is locked`

Bounded retry + single-writer в main write-path; перевод `self.db.db`/`_db.db`
на публичный API; PRAGMA-паритет; `event=database_lock_exhausted` + счётчик;
kill-switch `DB_LOCK_RESILIENCE_ENABLED` (default ON). Детали и карта —
`plans/reports/f0-5-db-lock-round1025.md`.

## Регресс

- pytest: 7933 passed / 0 failed (было 7911/0).
- JS-гейты: `node --check web/app.js`, `tests/js/routing_test.js`,
  `tests/js/vue_mount_test.js`, все `tests/js/*` — зелёные.
- Δ DDL = 0 (`user_version=12`; DDL в диффе нет).
- Δ каталога = 0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96; тест-инвариант
  зелёный). Новые флаги — env-only `ClassVar`.

## НЕ сделано / вне scope @Builder

- T-2419/T-2433/T-2454 live-приёмка в Telegram (mobile/TMA, прод) — за
  @Reviewer/@DevOps.
- T-2453 ревью, T-2454 деплой — другие роли.
- Удаление бэкапа — только после утверждения владельцем.
