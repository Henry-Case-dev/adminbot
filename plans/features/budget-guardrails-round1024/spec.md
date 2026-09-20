# Spec: budget-guardrails-round1024 (F23)

> Раунд 10.24 (UPD5-critical) · **Приоритет P1 (опционально)** · Шаг 4 @Builder · Тип: защитные пин-тесты / freeze-инварианты / R16–R18
> **ТЗ:** `plans/current_task.md`, строка 404 (сопровождение фикса бюджетов). Секреты не цитируются (R17/R18).
> **Baseline:** HEAD `379cfdd` (коммит iter0 F23); предшественники — F20 (`070f31c`), F21 (`4659173` + review `d8e09a6`), F22 (`cbc4f98` + review `268a8b1`).
> **Задачи:** `tasks.md` T-2376…T-2379. **ADR:** без нового; страховка к F20/F21/F22 (AMEND-контекст: ADR-1024-21/22/23, AMEND ADR-1019-3/1019-8).
> **Связано:** `tma-menu-freeze` (снят владельцем только для карточки изображений F5 10.24; для «Бюджетов» — **не снимать**).

## 1. Цель

Не дать бюджетному регрессу вернуться. После посадки master-тумблера бюджетов (F21)
и ремонта потерянных per-chat `overrides` (F22) закрепить **пин-тестами**:

1. **каталог/TAB_RULES** — точные значения рантайма и место `flags.budgets_enabled` (вкладка `mod_budgets`, без новой вкладки);
2. **freeze меню** — состав и порядок `MODULES`/`TABS` (новых вкладок/карточек нет — `tma-menu-freeze` для «Бюджетов» не снят);
3. **сквозные инварианты** — резолв master-флага (global/per-chat/fail-open ON), OFF → фон свободен и учёт ведётся, `manual-overrides-immutable`, read-only диагностика (`diag`/`audit-chat-overrides`), R16-аддитивность.

## 2. Что уже есть (координаты)

| Что | Где | Роль |
|---|---|---|
| Master-тумблер бюджетов | `services/budget_gate.py` (`KEY_BUDGETS_ENABLED`, `budgets_enabled`) | F21; fail-open ON |
| Каталог: ключ + группа | `services/param_catalog.py` (`BUDGETS_ENABLED` → `flags_module_budgets`, order 21) | F21, Δ каталога санкционирован в ADR-1024-22 D1 |
| Вкладка «Бюджеты» | `TAB_MOD_BUDGETS` (`mod_budgets`), rule = `flags_module_budgets` + `limits_chat_key/context/worker` | F3 + F21 |
| UI-витрина | `web/app.js` — `MODULES` (13 карточек), `TABS` (26 пунктов) | F5 + F21 (`mod_budgets` получил `toggleKey`, снят `noToggle`) |
| Enforcement direct/фон | `services/chat_usage.budget_snapshot`, `services/worker_budget.consume`/`global_degradation_allows` | F21 OFF-short-circuit |
| Ремонт/аудит | `services/chat_settings_seed.apply_chat_settings_seed`, `manage.py audit-chat-overrides` | F22 (plain-сид, read-only) |
| Существующие фич-тесты | `tests/test_budget_global_toggle_round1024.py`, `tests/test_budget_data_repair_round1024.py` | страховочная база для F23 |
| GUI-проверка витрины | `tests/js/round1024_budget_toggle_test.js` | node-level: 13 карточек/26 вкладок |

## 3. Что покрывают guard-тесты

Новый файл `tests/test_budget_guardrails_round1024.py` (Δ каталога/DDL = 0):

- **T-2376 (пины каталога/TAB_RULES + no-desync):** `REGISTRY=459`, `GROUPS=98`, `_TAB_BY_GROUP=96`, `TAB_RULES=21`, `TAB_NAV=21`, `CONFIG_TAB_TITLES=21`; `BUDGETS_ENABLED` → `flags.budgets_enabled` → `flags_module_budgets` (order 21) → `mod_budgets`; полный снапшот 21 `TAB_RULES`; синхронность Python↔JS для бюджетной вкладки (группы/подпись/`toggleKey`).
- **T-2377 (freeze меню):** точный **состав и порядок** `MODULES` (13) и `TABS` (26); уникальность id; карточка `mod_budgets` ссылается на существующую вкладку; группа `flags_module_budgets` имеет ровно один дом (JS и Python).
- **Guard-инварианты:** резолв master-флага (дефолт ON, global OFF, приоритет per-chat override, fail-open ON); OFF → `global_degradation_allows`/`consume` не блокируют и UPSERT-учёт ведётся; `manual-overrides-immutable` (plain-сид не трёт ручные, восстанавливает absent); read-only диагностика (`_collect_chat_overrides_audit`, `_collect_aliases_diag` — строго `SELECT`); R16-аддитивность снимка; Δ-DDL-пин (`DDL_STATEMENTS == 45`).

## 4. Frozen-contract (осознанный глобальный freeze)

Пины фиксируют **полный** состав каталога и витрины (`MODULES`/`TABS`), а не только
бюджетный контур. Это **осознанное решение** (не случайная избыточность), принятое
для закрытия риска **R1** («пин-тесты окажутся пустыми»): подмена вкладки при
сохранении количества (rev1: `oversight` → `oversight_evil`) должна детектиться.

**Правило обновления:** любое санкционированное изменение состава каталога/меню
(новая вкладка, карточка, флаг) **обязано** обновить соответствующий пин-лист
(`EXPECTED_TAB_RULES_IDS` / `EXPECTED_MODULE_IDS` / `EXPECTED_TAB_IDS` / счётчики)
в **том же коммите**. Это намеренное трение: изменение состава меню должно быть
явным и обозримым в диффе, а не «проезжать» на количестве. R2 («избыточный freeze
блокирует легитимные правки») принят как контролируемый: пин-листы правятся одной
строкой и не затрагивают логику.

## 5. Инварианты

- **Δ каталога = 0, Δ DDL = 0** — F23 добавляет только тесты и документы.
- **R16** — аддитивность: базовые ключи снимка обязаны присутствовать целиком; добавление новых не роняет страж.
- **R17/R18** — секреты не читаются/не логируются/не цитируются; в фикстурах — синтетические маркеры.
- **`manual-overrides-immutable`** — ручные `overrides` неприкосновенны; `--force` только по гейту.
- **`tma-menu-freeze`** — новых вкладок/карточек нет; у `mod_budgets` лишь тумблер на существующей карточке.
- **F20 write-path** (`web/api/routes.py`) не изменяется.

## 6. Критерии приёмки

1. Пин-тесты каталога/TAB_RULES и витрины (`MODULES`/`TABS`) зелёные и ловят мутацию состава (число И подмена id).
2. Freeze меню «Модули» не снят; состав консистентен.
3. Guard-тесты fail-open/фон/immutability/read-only/R16 — зелёные.
4. R16/R17/R18 — чисто; секреты не цитируются.
5. Полный `pytest` — **0 failed**; `node --check web/app.js` — OK; `git diff --check` — чисто.
6. Δ каталога = 0, Δ DDL = 0.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | Пин-тесты «пустые» (не ловят реальный регресс) | Medium | Пины на точный состав/множества + мутационная проверка (rev1 подтвердил детект составом `TABS`). |
| R2 | Избыточный freeze блокирует легитимные правки меню | Low | Freeze осознанный (см. §4): пин-листы правятся одной строкой в коммите фичи; R2 ограничен составом, не логикой. |
| R3 | Секретоподобные строки в фикстурах | Low | Синтетические маркеры; R17-редакция. |

## 8. Откат

- **Код:** `git revert` коммита F23 — удаляет только тесты/документы; runtime не затронут.
- **Данные/схема:** нет (Δ DDL = 0); откат данных не требуется.
- Побочный эффект отката: пропадает защита от бюджетного регресса (возврат к состоянию до F23).

## 9. Границы (вне scope)

- Реализация F21/F22 (уже в HEAD) — F23 их только **страхует**, не переписывает.
- Prod-прогон CLI на PG (read-only аудит/ремонт) — зона @DevOps (T-2379); локально PG нет.
- Сквозной R16/R17/R18-скан артефактов — @Reviewer (T-2378).
