# A8 `telegram-reactions-round1026` — Evidence (Builder, T-3671…T-3682)

- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 5 (продолжение) — A8
- **Risk:** **R2** (финальный; spec §13 / ADR-1026-21 D12). **`threat-failure-analysis.md` — `NOT_APPLICABLE`** (отдельной threat-задачи в `tasks.md` нет; см. D12).
- **Baseline anchor:** `e8646af` (HEAD == `origin/master`) + UNCOMMITTED epic-release tree A2–A7 (untouched/uncommitted). A8 built on top; **no commits, no tags, no version bump**.
- **Feature dir:** `plans/features/telegram-reactions-round1026/`
- **Spec:** `spec.md` (13 REQ → 15 SC) · **ADR:** `adr-1026-21-reaction-mechanics.md` (D1–D14, binding)
- **Release policy:** EPIC_ONLY — deploy **`DEFERRED_TO_EPIC`**; @DevOps not called.
- **APP_VERSION:** 2.58.30 (unchanged, no bump).

## Changed files (A8 contribution only)

Source:
- `config/settings.py:562–569` — env-only `ClassVar` kill-switch
  `REACTION_MECHANICS_ENABLED = _env_bool("REACTION_MECHANICS_ENABLED", True)`
  (перед `DYNAMIC_ANTICLICHE_ENABLED`; не каталог-параметр).
- `services/smartmodule_utils.py:93–234` — §41-механика исполнителя:
  - constants `REACTION_DEFAULT/LAUGH/APPROVE/FIRE`:98–101,
    `STANDARD_REACTION_EMOJIS`:102, `REACTION_FALLBACK_ORDER`:105,
    `MAX_REACTION_ATTEMPTS=2`:109; closed 7-outcome enum `REACTION_*`:112–123;
    classification markers:126–134;
  - `reaction_mechanics_enabled()`:137 (env-only, per-call, never raises);
  - `_classify_reaction_error(exc)`:147; `_reaction_candidates(primary)`:164;
  - `_warn_reaction_failed(...)`:173 (единая R17-safe WARNING-строка, сохраняет
    подстроку `"SmartModule: moai reaction failed"`);
  - `react_moai(bot, chat_id, message_id, *, reaction=None, reason_code=None) -> str`:184
    — legacy при `reaction is None` OR kill-switch OFF; иначе контекстный эмодзи +
    детерминированный fallback; единственный `await bot.set_message_reaction(`:204.
- `services/direct_chat_service.py`:
  - импорт эмодзи-констант + `reaction_mechanics_enabled`:133–135,140;
  - `_REACTION_BY_REASON`:512 + `_reaction_for_reason(reason)`:520 (дефолт 🗿,
    OFF → 🗿);
  - 4 `react`-ветки `_decision_pre_action`: значение эмодзи через
    `_reaction_for_reason(...)` — `:858`, `:865`, `:875`, `:888` (класс/приоритет/
    `action`/`reason_code` **не менялись**);
  - потребитель `pre_action == ACTION_REACT`: `:1313–1315` —
    `react_moai(bot, chat_id, pre_target, reaction=pre_reaction, reason_code=pre_reason)`
    (разрыв T-3678 закрыт).
  - safety-net `:1440/:1506` — **не тронуты** (legacy 3-аргументные вызовы).

Tests/artifacts:
- `tests/test_telegram_reactions_round1026.py` (**NEW**, **63** сценария) —
  карта/кандидаты, доступность+fallback, таксономия, rate-limit, no-text, R17,
  OFF-паритет/backward-compat, детерминизм, доставка выбора A7, цель/media-group,
  границы (канон/каталог/DDL/один call-site/прочие сайты/A9).
- `tests/test_smartmodule_utils.py` (**+4** аддитивных кейса, класс
  `TestReactMoaiMechanicsA8`:357–414).
- `tests/test_decision_making_round1026.py` (**A7-test re-pin, 2 assertion**):
  `test_laughter_reacts` / `test_image_reaction_on_own_image` теперь ожидают
  контекстный эмодзи 😂 (`REACTION_LAUGH`) вместо фиксированной 🗿 — это
  **санкционированная A8-механика** (ADR-1026-20 D5 / ADR-1026-21 D1; задача
  `tasks.md` §«Делегирование A7→A8»). Правила/классы/`action`/`reason_code` не
  менялись; добавлен импорт `REACTION_LAUGH`.
- `plans/features/telegram-reactions-round1026/evidence.md` (**NEW**, этот файл).
- `plans/features/telegram-reactions-round1026/tasks.md` — T-3671…T-3682 → `[x]`.

## T-3671…T-3682 — status

- [x] **T-3671 upgrade исполнителя реакции** — `react_moai` аддитивно принимает
  `reaction`/`reason_code`; позиционные 3 аргумента сохранены; единственный
  `set_message_reaction`; best-effort/silent.
- [x] **T-3672 scope-аудит прочих `react_moai`-сайтов (U11)** — D11 direct-only:
  все прочие сайты (`handlers/youtube.py`, `web.py`, `search.py`, `factcheck.py`,
  `checkup.py`, safety-net `direct_chat_service.py`) зовут 3-аргументную форму;
  тест `TestBoundaries::test_other_react_sites_untouched_legacy` +
  `test_direct_safety_net_calls_legacy` фиксируют отсутствие `reaction=`/`reason_code=`;
  `git diff --name-only` по handler-сайтам = пусто.
- [x] **T-3673 доступность + альтернатива/отказ** — реактивно (try-and-fallback,
  без `getChat`); `REACTION_INVALID` → следующий кандидат; ≤2 попытки; все
  недоступны → тихий отказ; фиксированный порядок; без `random`.
- [x] **T-3674 источник эмодзи / стандартный набор / вариативность (U1)** —
  карта `reason_code→эмодзи` (`image_reaction`/`laughter`→😂,
  `emoji_reaction`→👍, `emotion`→🔥, иначе/None →🗿); 🗿 — только дефолт/fallback;
  стандартный набор {🗿,😂,👍,🔥}; OFF → 🗿.
- [x] **T-3675 корректность цели** — реакция на trigger `message_id` (A7
  `pre_target`); `reply_to_id`/prev-bot не используются; media-group: id не
  подменяется, «первое неудалённое» — серверное поведение Telegram (D4).
- [x] **T-3676 error taxonomy + no-text fallback** — закрытый enum 7 исходов;
  только `unavailable` retryable; все fail-silently; ни один исход не вызывает
  `send_message`/`_send_direct_answer`; R17-логи (id/enum/reason).
- [x] **T-3677 права/типы чатов / лимиты** — реактивно: `forbidden` (права/блок),
  `rate_limited` (RetryAfter/429, без повтора), `service` (служебные),
  `message_gone`; проактивный `can_react_to_messages` не читается (D7).
- [x] **T-3678 интеграция `reaction`/`reason_code`** — `direct_chat_service.py:1313–1315`;
  контракт `CoordinatorDecision` не дублирован; A7-политика не переопределена;
  `reason_code` в чат не выводится.
- [x] **T-3679 тесты ядра** — новый файл покрывает §52.21, §53.5844,
  no-text, media-group, reply-ситуацию, OFF-паритет.
- [x] **T-3680 §54.9 + adversarial** — 429/RetryAfter, чат без прав,
  `message_id=None`, удалённое сообщение, детерминизм, R17-отсутствие контента,
  неожиданное исключение → `unknown`.
- [x] **T-3681 kill-switch + регресс + числа** — `REACTION_MECHANICS_ENABLED`
  env-only ON; OFF-паритет доказан; полный pytest 9459/0; JS 47/47; канон 12;
  Δ DDL=0 (SQLite v12); Δ каталога=0; APP_VERSION 2.58.30; `git diff --check`=0.
- [x] **T-3682 diff-аудит границ** — см. ниже.

## Verification commands + actual results

- `pytest -q` (full `.venv`) → **9459 passed / 0 failed** (153.4s).
  Baseline (A7 Step 0/rework) = **9392/0**; **+67** = 63 (новый файл) + 4
  (`test_smartmodule_utils`); 2 A7-assertion re-pin (без изменения числа тестов).
  **0 регрессий.**
- `tests/test_telegram_reactions_round1026.py` → **63 collected / passed**.
- `tests/test_telegram_reactions_round1026.py tests/test_smartmodule_utils.py
  tests/test_direct_chat.py tests/test_decision_making_round1026.py
  tests/test_tool_coordinator_round1026.py tests/test_agentic_ai_round1020.py
  tests/test_checkup_handlers.py tests/test_factcheck_handlers.py` → **526 passed**.
- `tests/test_settings_helpers.py tests/test_smartmodule_utils.py
  tests/test_telegram_reactions_round1026.py` → **145 passed** (проверка
  устойчивости к `importlib.reload(config.settings)`).
- `tests/test_database.py` → **98 passed** (SQLite `user_version == 12`, Δ DDL=0).
- F8: `python tools/gen_param_registry_round1025.py --check` →
  **`CHECK OK: реестр 473 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.`**
- Catalog canon (direct recompute): REGISTRY **473** · fields **430** ·
  categorized **448** · GROUPS **102** · `_TAB_BY_GROUP` **100** · `TAB_RULES` **21**
  → **Δ = 0** (U9/D9).
- JS: 47 файлов `tests/js/*.js` → **47/47 exit 0**.
- `git diff --check` → exit **0** (только LF→CRLF warning).
- `APP_VERSION` → **2.58.30** (без bump); канон `TOOL_CALLING_TOOLS` → **12**.
- `REACTION_MECHANICS_ENABLED` не в `param_catalog.REGISTRY` и не в
  `dataclasses.fields(Settings)` (env-only, Δ каталога не растёт).

### Reproduced key scenarios (exact)

- Карта: `image_reaction`/`laughter`→`😂`, `emoji_reaction`→`👍`,
  `emotion`→`🔥`, `None`/неизвестный→`🗿` (parametrized; `Settings=ON`).
- Fallback: primary `😂` + `REACTION_INVALID` → 2-й вызов `👍`, результат `ok`
  (`TestAvailabilityFallback::test_preferred_rejected_then_alternative_sent`).
- Полный отказ: primary `🔥`, оба кандидата `REACTION_INVALID` →
  `unavailable`, ровно **2** вызова, `send_message` не вызван.
- Порядок стабилен 25 прогонов → всегда `👍` (без `random`).
- `forbidden` → 1 вызов, без fallback; `retry_after` → 1 вызов, `rate_limited`.
- OFF: `reaction=🔥` + kill-switch OFF → 1 вызов `🗿`, результат `unavailable`
  (fallback не применён); `_reaction_for_reason(🔥-reason)` → 🗿.
- Backward-compat: `react_moai(bot, chat, 77)` → 1 вызов `🗿`, `is_big=False`;
  ошибка → 1 вызов; handler-сайты без kwargs (regex).
- T-3678 e2e: `"АХАХА"` → `handle()` → `set_message_reaction` = `😂` на trigger
  id; `😀` на своё изображение → `👍`; reply-ситуация цель = trigger, не `reply_to_id`.
- No-text: 6 типов ошибок (unavailable/forbidden/gone/service/429/RuntimeError)
  → `send_message` не вызван; лог содержит `code=...`/`reason=...` и не содержит
  пользовательский текст (R17).

## 12 acceptance invariants — status

1. Только официальный `setMessageReaction` → **OK** (один call-site
   `await bot.set_message_reaction(`; в `direct_chat_service` — 0; нет `Message.react`/HTTP).
2. Проверка доступности в чате → **OK** (реактивная классификация; `unavailable`
   обрабатывается альтернативой/отказом).
3. Запрет произвольного эмодзи → **OK** (только `STANDARD_REACTION_EMOJIS`,
   один `ReactionTypeEmoji`; не-наборный primary → 🗿).
4. Недоступно → альтернатива/отказ → **OK** (детерминированно, ≤2, без текста).
5. Ошибка реакции ≠ длинный текст → **OK** (0 send-вызовов на всех исходах).
6. Правильная цель → **OK** (trigger; reply/prev-bot исключены; media-group id
   без подмены).
7. Не одна и та же реакция всегда (механика) → **OK** (контекстная карта; 🗿 —
   дефолт/fallback).
8. Соответствие контексту/характеру (механика) → **OK** (доставленный эмодзи =
   `CoordinatorDecision.reaction`; e2e-тесты).
9. Правила §44 не переопределяются → **OK** (изменено только значение эмодзи в
   существующих react-ветках; классы/приоритеты/`action`/`reason_code` не тронуты).
10. Без A9-событий → **OK** (`test_no_a9_events`: нет `REACTION_SENT`/
    `MESSAGE_IGNORED`/ExecutionGraph).
11. Без нового инструмента/LLM-вызова → **OK** (канон 12; JSON-схемы не менялись;
    `CoordinatorDecision` не дублирован).
12. R17-логи + EPIC_ONLY → **OK** (только id/enum/reason/эмодзи/код ошибки;
    deploy `DEFERRED_TO_EPIC`; Δ DDL=0; Δ каталога=0).

## Boundary audit (T-3682)

- **A7-правила §44 / `_decision_pre_action`:** изменены **только** 4 возврата —
  значение эмодзи (`_reaction_for_reason(reason)` вместо `REACTION_MOAI`);
  структура ветвления, классы, приоритеты, `action`, `reason_code` — без правок.
  `test_policy_has_no_random` и A7 policy-тесты зелёные (2 assertion re-pin на
  новое значение эмодзи — санкционировано делегированием).
- **A9 (§49/§51):** событий/ExecutionGraph/апдейтов реакций нет.
- **A10 (§52–§54):** вне diff.
- **A1 `CoordinatorDecision`:** не дублирован (reuse `reaction`/`reason_code`/
  `target_message_id`).
- **A2–A6:** вне diff (правки A8 только в `smartmodule_utils.py`,
  `direct_chat_service.py`, `settings.py`, тестах).
- **Канон 12 / Δ DDL=0 (SQLite v12) / Δ каталога=0 / §104 no-go:** подтверждено.
- **Прочие `react_moai`-сайты (U11):** байт-в-байт legacy; `git diff --name-only`
  по `handlers/{youtube,web,search,factcheck,checkup}.py` = пусто; safety-net
  `:1440/:1506` не тронуты.
- **Второй исполнитель `setMessageReaction`:** отсутствует.
- **Нет текста на ошибку:** `send_message`/`_send_direct_answer` не вызываются
  ни на одном отказном исходе (unit + integration).

## R17 / R18

- **R17:** логи `react_moai` — `chat`/`msg`/`code`(enum)/`reason`(код)/`emoji`;
  содержимое сообщений/имена/ключи/промпты не логируются (тест
  `test_log_r17_safe`, `test_error_log_has_no_user_content`). Существующая
  подстрока `"SmartModule: moai reaction failed"` сохранена (регресс-совместимость
  `tests/test_smartmodule_utils.py`).
- **R18:** коммитов/тегов/веток не создавалось; `plans/current_task.md`,
  машинный блок, spec/ADR, backlog/metrics/ARCHITECTURE/MEMORY/durable-аудит не
  изменялись; бэкапы/`stash` целы.

## Threat artifact

- **`threat-failure-analysis.md` — `NOT_APPLICABLE`** (Risk **R2**, ADR-1026-21
  D12). Reviewer может повысить риск по фактическому diff; при R3 артефакт
  обязателен.

## Blockers / Checks not run

- Нет блокеров; все запланированные проверки выполнены.
- Сетевые/провайдерские/LLM-вызовы не выполнялись (unit + integration с fakes).
- Owner-gate A3 `PENDING OWNER VERIFICATION` — внешний, A8 его не закрывает.
- media-group «first non-deleted» — **серверное** поведение Telegram (verbatim
  Bot API); локально проверена неизменность переданного `message_id` (spec §14).

## Epic inputs contributed by this feature (release-candidate)

- Code: `services/smartmodule_utils.py` (механика §41),
  `services/direct_chat_service.py` (карта reason→эмодзи + проброс),
  `config/settings.py` (`REACTION_MECHANICS_ENABLED`).
- Tests: `tests/test_telegram_reactions_round1026.py` (new, 63) + 4 additive в
  `test_smartmodule_utils.py` + 2 A7-test re-pin.
- Deploy: **DEFERRED_TO_EPIC**; hot rollback `REACTION_MECHANICS_ENABLED=false`
  (legacy 🗿); cold `git revert` → `e8646af`; DDL-откат не нужен.
- Handoff → A9 (события `REACTION_SENT`/`MESSAGE_IGNORED`, ExecutionGraph) без
  переписывания механики A8.

## Manifest hints for Reviewer

- HEAD: `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- Working tree: modified `config/settings.py`, `services/direct_chat_service.py`,
  `services/smartmodule_utils.py`, `tests/test_smartmodule_utils.py`; untracked
  (`??`) `tests/test_telegram_reactions_round1026.py`,
  `tests/test_decision_making_round1026.py`, feature-папка.
- SHA-256 (рабочее дерево):
  - `services/smartmodule_utils.py` `e793b5261de20b5a25aafdead6c98f151134873be347cdf573bbcc1853b7f8c5`
  - `services/direct_chat_service.py` `b69879bbf621c62cf05bec0ada1b8d279c5c69981cbcf60b096f5dcac22eb795`
  - `config/settings.py` `ca9e42613163922080d4f34597304fbda7b63b8d8a960706f6c06375b22f646b`
  - `tests/test_smartmodule_utils.py` `2dd41ecfd2077ac16e023dd09ed03dc823d9be5227c94fff8fc08c683705bd00`
  - `tests/test_telegram_reactions_round1026.py` `1c11d40e2ca75e0ecfb30833ddedf89961de631a365614121ee2a2f78712a7d7`
  - `tests/test_decision_making_round1026.py` `1e9c7c58b80938ed2652eeb8f05b8acec9303c1913e9c843b55ac940b5f9f36a`
