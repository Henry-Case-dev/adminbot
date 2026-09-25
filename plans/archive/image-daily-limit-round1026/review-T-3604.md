# A5 `image-daily-limit-round1026` — Review T-3604 (единый Reviewer gate, R3)

- **Feature-ID:** `image-daily-limit-round1026`
- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 3
- **Risk-Level:** **R3** (spec §10 / ADR-1026-17 D12; подтверждён — blast radius: разделяемый `worker_budget`, Δ DDL, каталог, UI, money-like квота при конкуренции)
- **Status:** **Approved** (feature gate: включение в pending epic-release Эпика 3; **НЕ** деплой)
- **Gate type:** feature gate. Aggregate epic-release gate — отдельно, на границе эпика.
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash (recipe v1):** `b57f1f0ede7563e2b8c31f63093b830fedf99cf29729609c50018c5cea23077c`
  - recipe v1 = sha256 файла-manifest со строками: `tracked_diff_sha256=9e898663…b15` (полный `git diff e8646af`), `status_sha256=e517f0b9…c87` (`git status --porcelain`), `file:tests/test_image_daily_limit_round1026.py=f5426113…fe9` (sha256 untracked A5-теста). Фиксирует staged+unstaged+untracked на момент ревью.
- **Spec-Hash (sha256 spec.md):** `428c44b477b3d2c40bb59b258ad54f72d64d967b22c98aaacc6f976fdac80601`
- **Вспомогательно:** A5-sanctioned diff (`git diff e8646af` по worker_budget/pg_db/image_generation/settings/param_catalog/app.js/index.html/tool_router) `git hash-object` = `16616a3ba3784a7ce1311407c01ea42aeb2d5e38`.
- **Release policy:** EPIC_ONLY. Деплой/коммит/тег/бамп **не выполнялись** (APP_VERSION = 2.58.30).

## Git base и inspected change scope

- База: `e8646af` (== baseline-анкер). Рабочее дерево содержит незакоммиченный pending epic-release код A2/A3 (`tool_loop`, `tool_router` (A3-часть), `tool_schemas`, `direct_chat_service`, `smartmodule_urls`, `bot.py`) — ожидаемо; в скоуп A5 не зачитывается.
- A5-sanctioned файлы (проверены полностью): `services/worker_budget.py` (+547), `services/pg_db.py` (+30, DDL), `services/image_generation.py` (A5-слой поверх A3), `config/settings.py` (+42), `services/param_catalog.py` (+19), `web/app.js` (+37), `web/index.html` (+35), `tests/test_image_daily_limit_round1026.py` (новый, 545 строк).
- Границы: нет `summaries/*.py`, нет промптов, нет `image_context_memory.py`/`user_context.py`/`url_factcheck.py` (A4/A6/A7 отсутствуют — `git diff --name-only e8646af` пусто по этим путям). Канон инструментов = **11**. `plans/current_task.md` не изменён.
- **A5-деталь, выходящая за заявленную границу (см. F3):** `services/tool_router.py` — A5 добавил `source="tool"` в legacy-OFF-ветку `generate_and_send` (плюс комментарий). Это корректный integration point для idem-дискриминатора, но заявленное «tool_router untouched by A5 except none» неточно.

## Checks performed (фактические выводы)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (независимо) | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **9170 passed, 1 warning in 182.56s** (0 failed) — совпадает с claimed |
| A5-тесты | `pytest tests/test_image_daily_limit_round1026.py -q` | **13 passed in 2.94s** |
| Затронутые сьюты | `pytest tests/test_pg_db.py tests/test_param_catalog.py tests/test_webapp_gates_api.py tests/test_budget_guardrails_round1024.py -q` | **98 passed** |
| JS | `node tests/js/*.js` (node v24.16.0) | **47/47 exit 0** |
| Каталог | прямой подсчёт `param_catalog`/`Settings` | **REGISTRY 470 · Settings 427 · categorized 445 · GROUPS 101 · _TAB_BY_GROUP 99 · TAB_RULES 21** |
| Дерево | `git diff --check` | **exit 0** (только LF→CRLF informational) |
| DDL | `len(pg_db.DDL_STATEMENTS)` | **46** (было 45; +1 блок `image_reservation`+2 индекса) |
| SQLite | `git diff e8646af -- *.py` | нет `user_version`/`PRAGMA`/ALTER `worker_budget` |
| Версия/теги | `APP_VERSION`; `git tag`; `git stash list` | **2.58.30**; пер-фича тега нет; stash не тронут (R18) |

## Requirement/evidence coverage (Lens 1)

| REQ | SC | Реализация | Независимое подтверждение | Итог |
|---|---|---|---|---|
| REQ-A5-01 | SC-A5-01 | `RESERVE_INCREMENT_SQL` — одиночный conditional UPSERT `... DO UPDATE SET used=used+1 WHERE worker_budget.used < $4 RETURNING used`; отказ не инкрементирует (`worker_budget.py:75-90`, `reserve_image` `:621-716`) | Код-инспекция + `TestA1`/`TestA3` | ✅ |
| REQ-A5-02 | SC-A5-02 | `reservation_key` PK; `RESERVATION_INSERT_SQL ON CONFLICT DO NOTHING`; replay-ветка | `TestA4` (2 теста), `TestA5` replay | ✅ |
| REQ-A5-03 | SC-A5-03 | `_commit_or_release(generation_failed=True)` → `release_image`; guard `reserved→released` | `TestA3.test_generation_failure_release_restores` | ✅ |
| REQ-A5-04 | SC-A5-04 | Все проверки серверные; shared+chat в одной транзакции; conditional UPSERT | `TestA2` + код; см. F1 (ограничение силы теста) | ✅ (с оговоркой) |
| REQ-A5-05 | SC-A5-05 | `_metric_limit`: global = env-only 200; per-chat = каталожный `limits.image_daily_limit` через `_resolve_limit` (chat→global→env 60) | `test_image_usage_additive_fields` (60 vs 200, источник), web-тест | ✅ |
| REQ-A5-06 | SC-A5-06 | `_chat_tz_name`/`image_day`/`image_timezone`/`image_next_reset`; shared — `today()` (`WORKER_BUDGET_TZ`) | `TestA6` (2 теста) | ✅ |
| REQ-A5-07 | SC-A5-07 | `image_usage_summary` из журнала: requests/success/errors/denied/delivery_failed; `expenses="N/A"` | web-тест (success=3/requests=3); код | ✅ |
| REQ-A5-08 | SC-A5-08 | commit ДО отправки; сбой доставки → `commit(delivery_failed=True)`; повторной генерации нет | `TestA5` (`calls==1`) | ✅ |
| REQ-A5-09 | SC-A5-09 | Врезка `data-image-limits` в `mod_images` (лимит/N/M/источник/сброс/TZ + read-only shared); без отдельной панели | web-тест; f5 tabs; UI-код | ✅ |
| REQ-A5-10 | SC-A5-10…14 | §104 core SAME; канон 11; Δ DDL по санкции; Δ каталога +1/+1; второй счётчик отсутствует; EPIC_ONLY | AST-гейт, DDL-пины, каталог-счётчики, границы | ✅ |

- **Idempotency-ключ** `{chat_id}:{message_id}:{source}`: `build_image_idem_key` (`image_generation.py:212-230`) + PK журнала. `message_id` = текущий (`reply_to_message_id=message.message_id`, `direct_chat_service.py`). ✅
- **Failure flow:** generation fail → release; delivery fail → commit + `delivery_failed`; второй платной генерации нет. ✅
- **Scope D4:** shared env-200 и per-chat catalog-60 показаны разными строками; независимый механизм настроек не создан. ✅
- **TZ:** календарный день по TZ чата; точный `next_reset_at`; смена лимита не обнуляет `used` (`TestA6`). ✅
- **Учёт:** только из ledger + единственного счётчика `worker_budget.used`; второго агрегата нет. ✅
- **Kill-switch:** `IMAGE_DAILY_LIMIT_ENABLED=OFF` → legacy `consume` (байт-в-байт), fail-open PG → legacy с честным WARNING. `TestA7` (4 теста). ✅

## Focused audit coverage (Lens 2)

- **Δ DDL verbatim:** PG `image_reservation` + 2 индекса в `pg_db.py` дословно совпадают с ADR-1026-17 §«Санкция» (`IF NOT EXISTS`, `CHECK status IN (reserved/committed/released/denied)`). Идемпотентно; multi-statement `execute` без аргументов поддержан asyncpg (официальная документация: «can execute many SQL commands at once, when no arguments are provided»). SQLite Δ=0, `worker_budget` PK `(day,scope,metric)` без изменений, второй счётчик отсутствует. ✅
- **Δ каталога:** +1 ParamSpec `IMAGE_DAILY_LIMIT` (pg_key `limits.image_daily_limit` резолвится через `_BY_PG_KEY` — проверено) +1 GroupSpec `limits_images` (tab `mod_images`) — ровно по D9, счётчики подтверждены. Дублирующих форм настройки нет. ✅
- **§104:** AST-гейт `test_104_generator_functions_ast_identical` держит `generate`/`generate_image`/`generate_image_verbose`/`extract_prompt`/`is_image_keyword` SAME vs `e8646af`; из set-equality санкционированно исключён только `generate_and_send` (wrapper). ✅
- **R17:** таблица хранит только `reservation_key/chat_id/source/message_id/day/status/error_code/delivery_failed`; idem-ключ — из id/enum; логи — числа/chat/source/status/reason. Сырых промптов/URL/ключей нет. ✅
- **Индексы/рост:** запросы журнала покрыты `(day,status)` и `(chat_id,day)`; retention `IMAGE_RESERVATION_RETENTION_DAYS` (default 30) + opportunistic purge ≤1/сутки/процесс. Неограниченного роста нет. ✅
- **R3-атака:** все 12 угроз `threat-failure-analysis.md` привязаны к именованным тестам/пробам; rollback-story согласован (hot = env OFF, cold = `git revert e8646af`, DDL-откат не нужен; таблица инертна). ✅

## Counterexamples checked

- **Гонка при остатке 1:** рассмотрен stub `_Conn` (A5-тест `:100-106`) — проверка+мутация без `await` моделируют атомарность одиночного SQL. **Оговорка F1:** stub не может «сфальсифицировать» регресс к check-after-increment (его UPSERT тоже атомарен), поэтому тест подтверждает исход, но не является доказательством от противного. Продуктовый код при этом — одиночный условный UPSERT (нет read-then-write `used`), что снимает риск.
- **Повторная доставка update:** replay `reserved/committed` → `already`, второй генерации нет (`TestA4`/`TestA5`).
- **Сбой PG в середине резерва:** `_BoomConn` → транзакция целиком откатывается, budget/res пусты, `reason=failopen` (`TestA7`).
- **Освобождение при сбое генерации:** `release_image` guard `reserved→released`; двойной release не откатывает дважды (`TestA3`).
- **Смена суток между reserve/release:** shared-день вычисляется из `created_at` в `WORKER_BUDGET_TZ`, chat-день — из журнала → откат попадает в тот же день.
- **Смена лимита:** `used` берётся из счётчика, лимит — из каталога; `TestA6` подтверждает `used=1` до/после 5→10.
- **Master budgets OFF:** `_reserve_or_consume` → `('legacy','','budgets_off')` (`TestA7`).
- **Второй счётчик/дубль настройки:** не обнаружены (журнал — ledger; один ParamSpec).

## Blocking findings

**Нет.** Critical/High отсутствуют; requirement-blocking Medium отсутствует.

## Non-blocking debt / findings

| ID | Severity | Location | Observation | Evidence | Impact | Required action / status |
|---|---|---|---|---|---|---|
| F1 | Medium (evidence-strength, не блокирует) | `tests/test_image_daily_limit_round1026.py:100-106,288-307` | Race-тест `TestA2` доказывает исход «ровно один резерв», но stub (атомарный read+write без yield) не отличает корректный conditional UPSERT от baseline check-after-increment — оба дадут [False,True]. | Stub `RESERVE_INCREMENT_SQL` читает и пишет без `await`; baseline-подобная реализация на том же stub прошла бы. Продуктовый код проверен независимо (одиночный `WHERE used < $4`). | Ограничение силы R3-доказательства SC-A5-04, не дефект продукта | Рекомендация (не блокер): добавить stub с yield между чтением и записью **или** ассерт, что `reserve_image` шлёт `RESERVE_INCREMENT_SQL` с `WHERE worker_budget.used <`. Open |
| F2 | Medium (scope/completeness, не блокирует) | `services/image_generation.py:974-1001` (`generate_image_verbose`) | Путь обложки саммари (`generate_image_verbose` → `_consume_budget`) остаётся на legacy `consume` (check-after-increment): атомарного резерва/idempotency/release для него нет. | `_consume_budget` не заменён; T-3592 санкционировал замену на call-site `generate_and_send`/`maybe_handle_keyword`, не на verbose. | На пути обложки сохраняется baseline-утечка/гонка по `image_calls`; на пользовательский (direct/tool) путь не влияет | Явно задокументировать исключение verbose в evidence/spec **или** расширить резерв на verbose (отдельная санкция). Open; проверить на агрегатном gate эпика |
| F3 | Low (accuracy) | `services/tool_router.py` (legacy-OFF ветка `_generate_image`) | A5 добавил `source="tool"` (+комментарий), тогда как заявлено «tool_router untouched by A5 except none». | `git diff e8646af -- services/tool_router.py` содержит `+ source="tool")` | Изменение корректное (idem-дискриминатор), но декларация границы неточна | Скорректировать evidence-декларацию. Open |
| F4 | Low (cosmetic) | ~40 `tests/*.py` | Добавлен UTF-8 BOM (`\ufeff`) в начало файлов при редактировании. | `git diff` строки `-"""` → `+"""` | Безвредно (Python читает UTF-8 BOM), но шумит в diff | При желании нормализовать кодировку. Open |
| F5 | Low (consistency) | `services/image_generation.py:1120-1132` | Replay ранее `denied`-резерва возвращает `reason=error_code` (`limit_chat`/`limit_global`), а свежий deny — `reason=budget`. | `_reserve_or_consume` replay-ветка vs свежий deny | Небольшая неоднородность контракта причины | Нормализовать reason для replay. Open |
| F6 | Low (semantics) | `services/worker_budget.py` `_retention_days` | `max(1, int(...))` — при `IMAGE_RESERVATION_RETENTION_DAYS=0` даёт 1 день, а retention-канон трактует `0` как «вечно». | Код `_retention_days` | Расхождение с `budget_limits.retention_state`. Env-default 30 не затронут | Документировать/выровнять. Open |
| F7 | Low (edge) | `services/worker_budget.py` `reserve_image` (вызов `_maybe_purge_reservations` внутри `try`) | Если `today()`/`_retention_days()` бросит до внутреннего `try` purge, успешный резерв вернётся как `failopen` (журнал/счётчик уже закоммичены). | Код: purge-вызов в success-`try`, его `marker = str(today())` вне внутреннего `try` | Маловероятная неверная классификация результата | Обернуть purge полностью fail-safe. Open |

## C-fix audit (14 заявленных обновлений + сопутствующие)

Все проверенные обновления — **легитимные обновления контракта**, ослабления, маскирующего регресс, не выявлено; фактические счётчики/поведение перепроверены независимо (9170/0, 47/47, каталог, DDL=46, AST-гейт).

| # | Файл | Изменение | Вердикт |
|---|---|---|---|
| 1 | `tests/test_summary_l2_writer.py` | Settings 426→427, REGISTRY 469→470, GROUPS 100→101, mapped 98→99, categorized 444→445 | Легитимно (санкция D9) |
| 2 | `tests/test_summary_execution_graph_round1026.py` | forbidden-list: убраны image_generation (A3) и param_catalog (A5), добавлены NOTE | Легитимно |
| 3 | `tests/test_summary_publish_integration_round1026.py` | counts + forbidden-list (param_catalog/bot.py/изображения) + NOTE | Легитимно |
| 4 | `tests/test_summary_deploy_round1026.py` | counts; forbidden-list, убрано `"web"` (allowlist app.js/index.html) | Легитимно; F4-замечание: `web/*` стал шире, но api/routes.py остаётся запрещён |
| 5 | `tests/test_tool_coordinator_round1026.py` | forbidden-list + web-allowlist + counts + канон 10→11 (A2) | Легитимно |
| 6 | `tests/test_unified_image_request_round1026.py` | AST-гейт: исключён `generate_and_send`, core SAME; `source` kwarg в stubs | Легитимно (§104 core остаётся SAME — проверено) |
| 7 | `tests/test_token_analytics_round1023.py` | `_fake_send` принимает `source`/`**kwargs` | Легитимно (аддитивный kwarg) |
| 8 | `tests/test_hotfix5_summary_cover_window_round1025.py` | per-chat image теперь каталожный: `_resolve_limit` awaited, key=`limits.image_daily_limit` | Легитимно и усилено (проверка ключа) |
| 9 | `tests/test_webapp_f5_round1025.py` | tabs mod_images += `limits`; counts | Легитимно |
| 10 | `tests/test_param_catalog.py` | поля 426→427; GROUPS 101; limits 198→199 | Легитимно |
| 11 | `tests/test_budget_settings_round1019.py` | counts | Легитимно |
| 12 | `tests/test_settings_persistence_round1014.py` | counts | Легитимно |
| 13 | `tests/test_pg_db.py` | DDL-таблиц 18→19 ×2 | Легитимно (Δ DDL санкционирован) |
| 14 | `tests/test_budget_data_repair_round1024.py` / `test_budget_guardrails_round1024.py` / `test_budget_global_toggle_round1024.py` / `test_webapp_gates_api.py` / `test_frontend_tab_mapping.py` + webapp-маркеры | DDL 45→46, counts, точное `{flags_module_images, limits_images}`, аддитивный `image_usage`-тест | Легитимно (точные set-ассерты сохранены) |

## Unavailable checks

- **Реальный PG-интеграционный прогон** `PgDatabase.init()` + конкуренция на живой БД недоступен в среде (используется in-memory stub). Атомарность conditional UPSERT подтверждена код-инспекцией и семантикой PostgreSQL (READ COMMITTED, ON CONFLICT DO UPDATE с WHERE), но не воспроизведена на реальной БД.
- **Playwright/DOM-прогон** UI-врезки не запускался; UI проверен статически (index.html/app.js) + API-тестом аддитивных полей. Для R3 UI-риск низкий (read-only отображение).
- **Context7** недоступен (invalid API key); версия asyncpg подтверждена по официальной документации/исходнику.

## Binding / staleness

Approval привязан к состоянию выше. Любое последующее изменение A5-файлов, A5-теста, `spec.md`, конфигурации/DDL/каталога или generated release inputs делает approval устаревшим. Aggregate epic-release gate обязателен отдельно на границе Эпика 3. Деплой/коммит/тег не выполнялись.

## Verdict

**Approved** — feature gate. Обе линзы (requirements/correctness и focused change audit) поддержаны доказательствами; блокеров нет. Findings F1–F7 — не блокирующие (Medium evidence/scope + Low). Декларация границы «tool_router untouched» неточна (F3) — рекомендовано исправить в evidence.
