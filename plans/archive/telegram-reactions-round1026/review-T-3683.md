# T-3683 — единый Reviewer gate (R2) — A8 `telegram-reactions-round1026`

- **Feature-ID:** `telegram-reactions-round1026` (Epic 3 «Agentic Intelligence», Wave 5; Раунд 10.26)
- **Задача:** T-3683 (единый gate; @Scanner отсутствует — обе линзы в одном проходе)
- **Risk-Level:** **R2** (spec §13 / ADR-1026-21 D12 — подтверждён по фактическому diff)
- **Status:** **Approved**
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` (HEAD; `origin/master`)
- **Working-Tree-Hash (sha256):** `ec57a9518e8f7ea8003701af42d133eeb5103f78a31e6c38748bc4239bd1bc97`
- **Spec-Hash (sha256 `spec.md`):** `6e5cfc80df5c6eaf7e6333a748b51805c6973b9cd5257f23fb81edc56ce0e4ef`
  (совпадает с ожидаемым префиксом `6e5cfc80…` от @Architect — подтверждено)
- **Release policy:** EPIC_ONLY. Данный вердикт — **feature gate**; он разрешает включение A8 в pending epic-release Эпика 3 и **НЕ** авторизует деплой. Агрегатный epic-гейт — отдельное решение.

## Git base и инспектированный scope

- **Base:** `e8646af` + **незакоммиченное epic-дерево A2–A7/A8** (как и заявлено baseline spec/ADR). Коммитов/тегов/bump не создавалось; `APP_VERSION` = **2.58.30**.
- **A8-санкционированный diff (проверено по содержимому/маркерам):**
  - `services/smartmodule_utils.py` — механика `react_moai` + константы/карта исходов (`:93–234`);
  - `services/direct_chat_service.py` — импорт эмодзи-констант (`:132–140`), `_REACTION_BY_REASON`/`_reaction_for_reason` (`:507–526`), 4 react-ветки `_decision_pre_action` (значение эмодзи), проброс `reaction`/`reason_code` (`:1313–1315`); safety-net `:1440`/`:1506` — legacy;
  - `config/settings.py` — env-only kill-switch `REACTION_MECHANICS_ENABLED` (`:562–569`);
  - `tests/test_telegram_reactions_round1026.py` (new, 63); `tests/test_smartmodule_utils.py` (+4); `tests/test_decision_making_round1026.py` (2 re-pin + import);
  - feature-артефакты (`spec.md`, ADR-1026-21, `tasks.md`, `evidence.md`).
- **Scope-creep проверка (чисто):** репозиторный grep `set_message_reaction` — ровно **один** call-site (`smartmodule_utils.py:204`; в `direct_chat_service.py` — 0). A8-маркеров (`REACTION_MECHANICS|reaction_mechanics|_reaction_for_reason|REACTION_LAUGH|FIRE|APPROVE`) в `param_catalog.py`, `tool_loop.py`, `tool_router.py`, `tool_schemas.py`, `worker_budget.py`, `handlers/{youtube,web,search,factcheck,checkup}.py` — **нет**. `handlers/*.py` в `git status` не изменены вовсе; `requirements.txt` не менялся.
- **Ограничение проверки (см. «Unavailable checks»):** A7-код незакоммичен, отдельного A7-снапшота/commit нет → точный byte-diff A7→A8 по `_decision_pre_action` git-средствами невычислим. Заменено структурной инспекцией + A7-тестами + line-baseline из ADR.

## Проверенные проверки (фактические результаты, воспроизведено независимо)

| Проверка | Результат (Reviewer) |
|---|---|
| `pytest -q` (полный) | **9459 passed / 0 failed** (154.14s, 1 warning) — совпало с evidence |
| `test_telegram_reactions_round1026.py` + `test_smartmodule_utils.py` + `test_decision_making_round1026.py` | **186 passed** |
| collection A8-файла | **63 tests collected** |
| JS `tests/js/*.js` (47 файлов, `node`) | **47 ok / 0 fail** |
| `git diff --check` | **exit 0** (только LF→CRLF warnings) |
| F8 `gen_param_registry_round1025.py --check` | **CHECK OK: 473 == REGISTRY, карта полна, R17-чисто, идемпотентно** |
| Каталог (direct recompute) | REGISTRY **473** · fields **430** · categorized **448** · GROUPS **102** · `_TAB_BY_GROUP` **100** · `TAB_RULES` **21** → Δ=0 |
| Канон инструментов | **12** |
| `APP_VERSION` | **2.58.30** (без bump) |
| SHA-256 6 A8-файлов | совпали с `evidence.md` (integrity OK) |
| aiogram | **3.31.0** (требование `>=3.31.0,<4.0.0`); `Bot.set_message_reaction(chat_id, message_id, reaction=None, is_big=None, request_timeout=None)` — подтверждено `inspect` |
| A9-маркеры repo-wide (`REACTION_SENT|MESSAGE_IGNORED|reaction_sent|message_ignored`) | **отсутствуют** |

## Линза 1 — требования/корректность

REQ-A8-01…-13 → SC-A8-01…-15: покрытие подтверждено тестами и кодом (таблица ниже). Orphan-REQ/SC не обнаружено.

| REQ | SC | Реализация | Тест | Вердикт |
|---|---|---|---|---|
| -01 официальный `setMessageReaction` | -01 | `smartmodule_utils.py:204` — единственный вызов | `test_single_official_call_site` + repo grep | OK |
| -02 доступность в чате | -02 | реактивная классификация `:219–226` | `TestAvailabilityFallback` | OK |
| -03 только стандартный набор/одна реакция | -03 | `STANDARD_REACTION_EMOJIS`, `_reaction_candidates`, один `ReactionTypeEmoji` | `test_standard_set_closed`, `test_candidates_fixed_no_random`; probe: `"X-bomb"` → 🗿, 1 тип | OK |
| -04 недоступно → альтернатива/отказ | -04/-09 | `REACTION_UNAVAILABLE` retryable, ≤2, иначе отказ | `test_preferred_rejected_then_alternative_sent`, `test_all_unavailable_silent_decline` | OK |
| -05 ошибка ≠ текст | -05/-14 | ни один исход не вызывает send | `TestNoTextOnError` (6 исходов), `test_integration_error_produces_no_text` | OK |
| -06/-07 правильная цель | -06/-07 | `target_message_id` = trigger; `reply_to_id`/prev-bot не используются | `TestTargetCorrectness` | OK |
| -08 не одна и та же всегда | -08 | `_REACTION_BY_REASON` | `test_distinct_contexts_distinct_emojis` | OK |
| -09 детерминизм | -09 | фиксированный порядок, без `random` | `test_same_reason_100_runs`, `test_order_stable_across_runs` (25), `test_executor_has_no_random` | OK |
| -10 доставка выбора A7 | -10 | проброс `:1313–1315` | `TestDeliveryFromDecision` | OK |
| -11 §52.21 | -11 | альтернатива/отказ без текста | `TestAvailabilityFallback` | OK |
| -12 §53.5844 | -12 | trigger-id при reply/media-group | `test_reply_situation_targets_trigger_not_reply`, `test_media_group_id_not_rewritten` | OK |
| -13 §54.9 | -13 | evidence + прогоны реакций/молчания | `evidence.md` §Verification | OK |
| (cross) | -14 | OFF-паритет/регресс/0 текста | `TestLegacyParity` + полный pytest | OK |
| (cross) | -15 | границы A7/A9/канон/DDL/каталог | `TestBoundaries` | OK |

**Поведенческие инварианты, проверенные контрпримерами:**
- Недоступная primary → детерминированная альтернатива (😂→инвалид→👍, 2 вызова, `ok`); все недоступны → `unavailable`, ровно 2 вызова, 0 текста.
- `forbidden` (BadRequest) → 1 вызов, **без** fallback; `TelegramRetryAfter` → 1 вызов, `rate_limited`, **без** повтора.
- `message_id=None`/`bot=None` → `unknown`, 0 вызовов (no-op).
- Произвольный/не-наборный вход (`"X-bomb"`) → coerced к 🗿 (REQ-A8-03).
- OFF kill-switch: контекстный 🔥 + OFF → 1 вызов 🗿, `unavailable`, fallback не применяется; `_reaction_for_reason(...) = 🗿`.
- 3-аргументный legacy-вызов → 1 вызов 🗿, `is_big=False`; ошибка → 1 вызов (без fallback).
- R17: лог отказа содержит `code=…`/`reason=…`/id, не содержит пользовательского текста («АХАХА» отсутствует).

## Линза 2 — focused change audit

- **Дом/архитектура:** механика — аддитивный апгрейд единственного примитива `react_moai`; второго исполнителя/HTTP/`Message.react` нет. `CoordinatorDecision` (A1) переиспользуется, не дублируется. Проброс `pre_reaction`/`pre_reason` закрывает T-3678.
- **Границы:** не-direct сайты — legacy 3-аргументная форма (файлы не изменены, тест `test_other_react_sites_untouched_legacy`); safety-net `direct_chat_service.py:1440/1506` — legacy (`test_direct_safety_net_calls_legacy`: ровно 2 вызова). A9/ExecutionGraph — вне diff. Δ DDL=0. Δ каталога=0. §104 `generate_image` — A8-маркеров нет.
- **Безопасность:** секретов/приватного контента в логах нет (R17); чтение `exc.message` только lowercase-substring; внешних вызовов кроме `set_message_reaction` нет; состояние не хранится (stateless, без гонок/idempotency-риска).
- **Производительность/ресурсы:** ≤2 API-вызова на реакцию, без `sleep`, без очередей; на 429 — останов. Регресс-риск отсутствует (OFF → точный legacy).
- **Деплой-чувствительность:** только env-only kill-switch; hot-откат `REACTION_MECHANICS_ENABLED=false`; cold — revert к `e8646af`; DDL-откат не нужен.

### Adjudication: 2 re-pinned A7-теста (`test_laughter_reacts`, `test_image_reaction_on_own_image`)

**Вердикт: санкционированная делегация (НЕ A7-регрессия).**
- ADR-1026-20 **D5** прямо делегирует A7→A8: «полная §41-механика … выбор `skip vs reply`/альтернативный эмодзи — **A8**»; «разнообразие эмодзи через доступный набор — §41/A8»; «контекстная реакция — дальняя волна/A8». Фиксированная 🗿 в A7 — временное interim-значение.
- ADR-1026-21 **D1** определяет карту `reason_code → эмодзи`; `tasks.md` §«Делегирование A7→A8».
- Diff re-pin: изменены **только** ожидания значения эмодзи (`REACTION_MOAI → REACTION_LAUGH`) + импорт `REACTION_LAUGH`; оба теста по-прежнему утверждают `action == ACTION_REACT` и те же `reason_code` (`laughter`/`image_reaction`). Классы/приоритеты/`action`/`reason_code` не тронуты. Прочих A7-re-pin нет (grep `REACTION_MOAI` в A7-файле — только import и конструктор `CoordinatorDecision`). Все A7 policy-тесты зелёные.

### Adjudication: Section 44 rules untouched (доказательство)

- `_decision_pre_action` возвращает те же 4-кортежи; в 4 react-ветках (`:858`, `:865`, `:875`, `:888`) изменён **только** аргумент эмодзи (`_reaction_for_reason(reason)` вместо константы). `REACTION_MOAI` в теле функции не встречается. `_reaction_for_reason` (`:520–526`) — pure dict-get + kill-switch; без изменения ветвления/порогов.
- A7 policy-тесты (`TestPolicy`, `_decision_message_class`, `test_policy_has_no_random`, `test_deterministic_no_randomness`) — зелёные; изменения приоритетов/классов/`action`/`reason_code` дали бы каскад падений, которого нет (полный pytest 9459/0 при re-pin лишь 2 assertion).
- Line-baseline ADR-1026-21 (написан после завершения A7): `_decision_pre_action:801–869`, react-ветки `:832/839/847/859`, `REACTION_MOAI:477`. Текущие позиции (`:827–898`, ветки `:858/865/875/888`, `REACTION_MOAI:481`) сдвинуты на +4…+29 строк — ровно на объём A8-вставок до/внутри функции; структура тела сохранена.
- **Ограничение:** это структурное доказательство, а не byte-diff (A7 не закоммичен). См. «Unavailable checks».

### Adjudication: threat N/A (ADF-1026-21 D12)

**Вердикт: `threat-failure-analysis.md` NOT_APPLICABLE — обоснованно, R2 подтверждён.**
- Изменение — локальная механика исполнения (один примитив + одна точка потребления), без LLM-вызова, без DDL/миграций, без нового пайплайна/каталога, без изменения auth/секретов/прав доступа, без персистентного состояния и без деструктивных операций. Все отказные пути fail-silently и **без текста**.
- Ни один R3-триггер spec §13 не сработал: не-direct сайты не менялись; OFF-паритет доказан; текст на ошибку отсутствует; произвольный/custom emoji исключён; A7-правила не переопределены; R17-утечки нет; fallback ограничен ≤2 вызовами и не повторяет 429; второго `setMessageReaction` нет.
- Blast radius ограничен direct-чатом и значением эмодзи; hot-откат env-only возвращает точный legacy. **R3-артефакт не требуется.**

## Findings

### Blocking
**Нет.** Critical/High/requirement-blocking Medium не выявлено.

### Non-blocking (Low)

**L-1 (Low, non-blocking) — real HTTP 403 не классифицируется как `forbidden`.**
- **Location:** `services/smartmodule_utils.py:213–230` (цепочка `except`), маркеры `:127–130` (в т.ч. `"bot was blocked"`).
- **Observation (воспроизведено):** `TelegramForbiddenError` НЕ является подклассом `TelegramBadRequest` (проверено MRO: `TelegramForbiddenError → TelegramAPIError → …`). Probe: `react_moai` при `TelegramForbiddenError("Forbidden: bot was blocked by the user")` → `REACTION_UNKNOWN`, 1 вызов; при этом `TelegramBadRequest("not enough rights")` → `REACTION_FORBIDDEN`.
- **Impact:** расходится только enum/лог (`unknown` вместо `forbidden`). Поведение безопасности идентично: тихий отказ, без fallback, без текста, без повтора. Продуктового/безопасностного ущерба нет; REQ-A8-02/-05 соблюдены.
- **Причина:** D5 сформулирован как классификация по `TelegramBadRequest.message` и «прочий Exception → unknown»; реальный 403 приходит отдельным классом. Это неточность спеки, а не нарушение санкции.
- **Требуемый фикс (follow-up, вне A8-гейта):** добавить `except TelegramForbiddenError: return REACTION_FORBIDDEN` (с тем же R17-safe `_warn_reaction_failed`) перед generic-handler, либо классифицировать по типу/статусу исключения. **Метод верификации:** unit-тест на `TelegramForbiddenError` → `forbidden`, 1 вызов, 0 текста.
- **Статус:** OPEN (bounded follow-up; блокирующим не является).

## Non-blocking debt / follow-up
- L-1 (выше) — рекомендуется закрыть в A9 или отдельным мелким hotfix-коммитом без изменения механики/поведения.
- Опциональный warm-кэш `available_reactions` (ADR D2) — явно вне scope; genuine unknown для PM, не дефект.

## Unavailable checks (честно)
- **Точный A7→A8 byte-diff `_decision_pre_action`:** недоступен, т.к. A7 незакоммичен и A7-снапшота нет (последний бэкап `var/backups/a2-…` — pre-A7). Компенсировано структурной инспекцией, line-baseline ADR и A7-тестами. Не блокер, т.к. поведенческая эквивалентность A7-правил подтверждена.
- **Серверное поведение Telegram** (media-group «first non-deleted», реальные error-коды/классы 403/400) локально эмулировано fakes; сетевых вызовов не делалось (соответствует scope). Это ограничение дизайна, а не дефект.

## Binding-рецепт (воспроизводимо)

- **Reviewed-Commit:** `git rev-parse HEAD` → `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`.
- **Spec-Hash:** `Get-FileHash -Algorithm SHA256 plans/features/telegram-reactions-round1026/spec.md` → `6E5CFC80…`.
- **Working-Tree-Hash:** sha256 от манифеста:
  1. `git diff HEAD` (полные bytes, staged+unstaged; здесь всё unstaged) → `DIFF`;
  2. `git ls-files --others --exclude-standard`, отсортировать; для каждого — `<path>\t<sha256(content)>\n` → `UNTRACKED`;
  3. `hash = sha256("GITDIFF\0" + DIFF + "\0UNTRACKED\0" + UNTRACKED)` → `ec57a9518e8f7ea8003701af42d133eeb5103f78a31e6c38748bc4239bd1bc97` (48 untracked-файлов, diff ≈ 704 956 bytes на момент ревью).
  - Настоящий файл `review-T-3683.md` создан **после** снятия хеша → единственная ожидаемая дельта манифеста. Hаш вердикт привязан к состоянию кода без review-артефакта.
- **Стейл-условие:** любые последующие правки кода/тестов/спеки/ADR/генеративных входов делают вердикт недействительным и требуют пересчёта binding.

## Handoff
- **Тип гейта:** feature gate (не агрегатный epic-гейт).
- **Статус:** **Approved** — обе линзы поддержаны независимо; блокеров нет.
- **Разрешение:** включение A8 в pending epic-release Эпика 3. Деплой **не** разрешён (EPIC_ONLY, `DEFERRED_TO_EPIC`).
- **Следующие шаги:** @Architect merge §90 + ADR-1026-21 → Accepted (T-3684) → @PM архивация → T-3685 `DEFERRED_TO_EPIC` → T-3686 handoff → A9. @DevOps не вызывается.
- **Open debt L-1** (403→forbidden) — передать A9/PM; не блокирует.
