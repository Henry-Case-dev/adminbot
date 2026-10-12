# F5 — Module dependency truth (отчёт)

Baseline: master `a12e6bf` (2.58.76). Архитектура: §5 (решение (а)); ТЗ: §11, §18H, §9/M6, §10/M7, §28.10–13. Режим: writer, worktree поверх актуального HEAD (в дереве присутствуют незакоммиченные F6/F8 — не пересекались по строкам, кроме fixture-обновлений общего каталога, см. §8).

## 1. §18H(2) — bootstrap отделён от Summary-флага (bot.py:421–624 → реструктуризация)

**Важно (scope-acceptance reconciliation):** WRITE_SCOPE брифа говорил «bot.py только обёртки :836–874», но mapped-приёмка M2 («Summary global OFF до старта → их функции работают») и §18H(2) («common bootstrap отделён») невыполнимы без разъёдинвания bootstrap-блока `bot.py:423–624`, где под `if flags.summary_enabled` находился ВЕСЬ общий DI (LLMClient, aliases, MemoryManager, Search/YouTube/Web/Checkup/Factcheck/Direct/Voice, MemoryMaintenance). Реализован минимально-рискованный вариант: **dedent без изменения логики** — общий bootstrap выполняется всегда, под флагом остался только Summary-собственный контур (генератор + `setup_summary` + планировщик). Ни один вызов не переупорядочен. Рецензенту — обратить внимание первым пунктом.

До:
```python
if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
    _llm_client = LLMClient(...)        # ← общий bootstrap
    aliases = AliasResolver(...)
    memory = MemoryManager(...)
    ... setup_search / setup_youtube / setup_web / setup_checkup /
        setup_factcheck / setup_direct_chat / setup_voice_transcription ...
    MemoryMaintenanceService(...).start()
else:
    logger.info("SmartModule Summary disabled")
```

После:
```python
_llm_client = LLMClient(...)            # общий bootstrap — ВСЕГДА
aliases = AliasResolver(...)
memory = MemoryManager(...)
if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
    generator = SummaryGenerator(...)   # Summary-собственный контур
    setup_summary(generator, db, aliases, bot.id)
    _summary_service = SummarySchedulerService(...); start()
else:
    logger.info("... общие сервисы инициализированы (F5: bootstrap ≠ фича)")
# далее — общий DI безусловен (dedent): search/youtube/web/checkup/
# factcheck/direct/tool_router/voice-DI/memory_backup/memory_maintenance
```

Побочный честный эффект: Dream/Nostalgia/Relations при Summary OFF больше не деградируют по NameError-фейл-опену (`memory`/`aliases` теперь всегда определены; их условные `memory if flags.summary_enabled else None` инъекции НЕ тронуты — осознанно, вне скоупа).

## 2. §18H(3)+R3 — регистрация роутеров 0a–0i (bot.py:836–874)

Карта обёрток до/после (порядок include — бит-в-бит прежний, маркеры `# 0a.`…`# 0i.` на месте):

| # | Роутер | До | После |
|---|---|---|---|
| 0a | summary_observer | `if flags.summary_enabled:` | безусловно |
| 0b | summary | `if flags.summary_enabled:` | безусловно |
| 0c | factcheck | `if flags.summary_enabled:` | безусловно |
| 0d | search | `if flags.summary_enabled:` | безусловно |
| 0e | youtube | `if flags.summary_enabled:` | безусловно |
| 0f | web | `if flags.summary_enabled:` | безусловно |
| 0g | checkup | `if flags.summary_enabled:` | безусловно |
| 0h | direct_chat | `if flags.summary_enabled:` | безусловно |
| 0i | voice_transcription | `if flags.summary_enabled AND flags.enable_voice_transcription:` | безусловно (AND удалён) |

Негативный тест R3: `test_r3_registration_order_preserved_and_unconditional` — точный порядок 9 include + запрет `if flags.summary_enabled` в секции регистрации.

## 3. §18H(4) — runtime-гейты на границах исполнения

| Гейт | Где теперь |
|---|---|
| `flags.summary_enabled` | `handlers/summary.py::_summary_enabled()` на входе `summary_observer` / `summary_observer_edited` / `cmd_summary` (OFF → UNHANDLED, паритет «роутер не зарегистрирован») |
| `flags.enable_voice_transcription` | `handlers/voice_transcription.py::voice_transcription_handler` на входе; `summary_enabled` из гейта **удалён** (DI-ось флага — прежний startup-гейт в bootstrap) |
| `flags.direct_chat_botword_enabled` | `handlers/direct_chat.py::_is_direct_trigger` — master на ВСЕЙ триггерной поверхности (reply/mention/имя/keyword; раньше — только keyword-ветка :194–197). Команды `/clear /persona /tone /style /forget` — вне гейта (явные управленческие действия) |
| factcheck (:384) / search (:119) / web (:143) / checkup (:97) / youtube (:1355) | собственные гейты — не тронуты (verified тестом `test_m18_own_runtime_gates_present_in_handlers`) |

## 4. §5.2 — reason-модель UI (web/app.js)

- `parentGate: 'flags.summary_enabled'` удалён у 7 карточек (Direct/Factcheck/Search/Transcription/Video/Web/Checkup) — все independent (ТЗ §11.3). Механика `parentGate` сохранена как `parent_off` (зарезервировано, ни одна карточка не объявляет).
- Новый `_moduleRuntimeReason(m)` + `reasonNoticeText()` + аддитивное поле `reason` в `getModuleState`. Enum: `chat_off` («Выключено в этом чате») / `global_off` («Выключено глобально» — текст ТОЛЬКО при selected scope = global) / `env_off` (registry env-ось) / `provider_unavailable` и `parent_off` (зарезервированы, producer'ов сейчас нет — задокументировано в коде).
- M3-устранение: в chat scope унаследованное-от-глобали OFF → состояние «Выключен» БЕЗ текста «отключён глобально»; старая ложь «Включён, но не работает: отключён глобально» при chat scope исчезла вместе с parentGate. Истинные тексты §43 сохранены (inert override, blocked при global_value=false).

## 5. §5.3/M7 — Random: product master

- `param_catalog.py`: +1 PG-only ParamSpec `memory.random_enabled` (bool, группа `memory_random` — существующая, категория memory, per-chat, default ON; прецедент `memory.random_uses_*`: Settings-поля нет, рантайм читает pg-ключ fail-open True).
- `mca_gates.random_source_enabled()` = env `MCA_RANDOM_SOURCE_ENABLED` (аварийная AND-ось, семантика K1 прежняя) AND hot `memory.random_enabled`. Все ~14 call-sites контура получают мастер бесплатно (низший слой-владелец).
- `module_registry.py`: Random `master_param="memory.random_enabled"`, rationale без «no master», `PRODUCT_DEFAULTS` + ключ; env-ось осталась в `ENV_GATES`/`MODULE_ENV_GATES` (§3.3-семантика: env OFF → `emergency_env`, product OFF → `product_toggle`).
- §28.12 закрыт: Random больше не «managed by env only».

## 6. §5.4/M6 — Experience: global worker + per-chat opted-in

- `mca_experience_jobs.py`: новый `learning_enabled_for_chat(chat_id)` — семантика U4: глобальная ось `memory.experience_learning_enabled` — master (OFF → все чаты выключены, важнее override); ON → chat-override (`chat_params.overrides` через `get_chat_param` — hot per-chat override → глобальная ось → дефолт); None-чат (технический контур) — не гейтится.
- Глобальный worker (`ExperienceReviewRunner._capture_feedback` / `_capture_tool_events`) пропускает chat-scoped capture не-opted-in чатов; курсор продвигается (без цикла). `memory_maintenance.py` НЕ тронут (вся логика в jobs-файле — ниже по слоям, F6/F8-изменения не задеты).
- `module_registry`: Experience `runtime_gate="per_chat"`, description «Worker глобальный; обучение включается по чатам», rationale обновлён. Catalog per-chat (`param_catalog.py:2327–2343`) — НЕ менялся (продуктовое намерение; runtime/registry подведены под него).

## 7. Тесты

Новый `tests/test_asap8_f5_module_truth.py` — 19 тестов (TEST-LIFECYCLE: CONTRACT owner=asap8/F5):
- R3-негатив порядка регистрации + безусловность; §18H(2) AST-гвард bootstrap (общий DI вне флага, Summary-контур под флагом); §18H(5) — отсутствие voice-AND с Summary.
- M2 runtime-гейты: observer/cmd OFF → UNHANDLED без записи; voice — только свой флаг (Summary OFF не мешает); direct master на reply/mention.
- M1/M3: parentGate==0 у 7 unrelated карточек; reason-enum полный.
- M7: master default ON; product_toggle/emergency_env; каталог+migratable+validate_spec.
- M6: resolver inherit/ON/OFF; global master OFF глушит все чаты; worker пропускает не-opted-in (capture-spy), None-чат проходит; registry-тексты согласованы.
- §28.10: `hot.get("flags.summary_enabled"` в handlers/ — только summary.py.

Обновления существующих (осознанные, §18.1 — пины закрепляли дефект/старый контракт):
- `tests/test_asap7_module_completeness.py`: пин :225–226 → Random как обычный product-модуль (+env-AND-кейс), :283–284 → master_param/rationale.
- `tests/test_webapp_f4_round1025.py` D3: parentGate 7 → **0** (запрет + «ни одна карточка не объявляет»).
- `tests/js/round1025_f4_module_store_test.js` (k): parent-гейт кейсы (лживые «Не работает: отключён глобально») → F5-кейсы (unrelated не зависит от Summary OFF; chat_off; global scope global_off; M3-негатив).
- `tests/js/round1025_f5_workspace_route_test.js` (f): харнесс-ctx дополнен `_moduleRuntimeReason` (новый шов getModuleState).
- `tests/test_direct_chat_handlers.py` TestBotwordTriggers: 2 теста «flag false → reply/mention работают» (закрепляли старый partial-гейт) → master-семантика OFF блокирует, ON — прежний приоритет.

Каталог-конвенция (bump+пины, прецедент `_asap7_f4_reissue_f8.py`):
- `tools/gen_param_registry_round1025.py` emit → `plans/docs/{param-registry-round1025.tsv,meta.md,screen-map-round1025.md}` (561/150, `--check` EXIT=0).
- `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`: counts 560→561, delta 149→150, registry_keys+1, sha256 param_catalog, superseded_by-нота.
- Счётчик-пины: `== 560` → `== 561` (50 файлов), `categorized == 535` → `536` (16), `delta == 149` → `150` (2), `len(tsv) 561` → `562` (1), `memory: 46` → `47` (1), meta-пины «560/149» → «561/150» (2).

**Прогон (числа):**
- `pytest tests/test_asap8_f5_module_truth.py tests/test_asap7_module_completeness.py tests/test_asap7_module_registry.py -q` → **48 passed**.
- Handlers/смежные: direct_chat + epic33/37/72 + mca03/mca17 + status_service + memory_maintenance → **203 passed**.
- mca09/mca10/mca16 семьи → **313 passed**; registry/catalog/param -k семья → **1730 passed**; webapp -k семья → **1169 passed**; summary -k семья → **1689 passed**; param_catalog/ia_inventory/frontend_tab_mapping/f8_registry → зелёные.
- `node --check web/app.js` → OK; JS: f4_module_store, f5_workspace_route, f4_catalog_ui, random_source, experience_lessons, f9_proxy, mca12/mca17c, vue_mount → **9/9 GREEN**.

## 8. UI evidence (обе обязательные половины)

Стенд из РЕАЛЬНЫХ артефактов: шаблон `<article class="module-card">` — точный extract `web/index.html`; методы/комьютеды — `web/app.js` (Vue-стаб на загрузке, mount реальным self-host Vue 3.5.42); сценарии = configItems+scope. Scratch: `OpenCodeScratch/adminbot-ccef72c25768/f5/` (gen_harness.js, f5_harness.html).

- **Playwright** (детерминированный DOM-flow, 5 сценариев, 0 console errors):
  - S1 global+Summary OFF: Summary «Выключен · ⚠ Выключено глобально» (global scope — по архитектуре); Checkup «Включён» без лжи.
  - S2 **chat+Summary OFF (главный M1/M3)**: Summary — inert-текст («Отключение для этой области не влияет…»); Direct/Factcheck/Checkup «Включён»; **0 вхождений «отключён глобально»** на unrelated.
  - S3 chat inherit-off: «Выключен» БЕЗ global_off-текста. S4 chat_off: «⚠ Выключено в этом чате». S5 §43-сохранён: «Включён, но не работает · Не работает: отключён глобально (локальное значение сохранено)» (true).
  - Скриншоты: `.playwright-mcp/f5_desktop_1280.png`, `.playwright-mcp/f5_narrow_390.png` (390px: card 327px, overflowX=false).
- **Browser Use** (реальный Chrome, вкладка закрыта после проверки): DOM-проверка тех же сценариев идентична — `s2_global_off_lies: 0`, `s1: ⚠ Выключено глобально`, `s4: ⚠ Выключено в этом чате`; рендер сверен скриншотом (карточки/тумблеры/amber-notice целы).
- **LIVE_UNVERIFIED (owner/после деплоя):** поведение на живом TMA против прод-PG (hot-toggle Summary в реальном чате и рестарт с env OFF) — в этой среде недоступно; контракт покрыт source-гвардами (§18H(2)/(3)), handler-тестами и двумя браузерными каналами.

## 9. Incidental findings

1. **pre-existing (исправлен механически):** `tests/test_mca10b_random_applications_block_d_round1041.py:335` пиннил routes-sha `8855…`, а `web/api/routes.py` с F9 (dc9ca1c, REV-F9 Approved) = `1b04e524…` — ассерт был красным на HEAD до F5 (переиздание F9 его пропустило; d204ccb это документировала). Пере-пин на Approved-хэш с комментарием.
2. **related-nonblocking (не моё):** `round1020_ui_test.js`, `round1020_ui_rework_test.js`, `round1024_budget_toggle_test.js` красные на HEAD-версии app.js (меню-пины «вкладок 26/27») — уже задокументировано в f9-report §9 как чужие пины этой волны; мои диффы app.js меню/TABS не трогают (проверено stash-прогоном).
3. **uncertain (flaky, не my-lane):** однократный красный `test_mca09_intents_block_e…::test_handle_initiative_sent_single_transport_chunks` (attempts 0 vs 1) в широком -k прогоне; не воспроизводится ни в одиночном, ни в повторном прогоне (313 passed повторно); time-based окно инициативы — зона F6. Записано, не чинено.
4. **related-nonblocking:** fixture `catalog_baseline.json` и count-пины — общие для волн; F8-лейн тоже менял `summary_memory.py` и др. — мои правки fixtures/pins выполнены поверх актуального рабочего дерева, конфликтов строк с F6/F8-диффами нет (проверено `git status`/stash-бисекцией).

## 10. Риски / остаток

- R3 соблюдён: порядок регистрации и DI-последовательность не менялись (dedent только); негативный тест — источник.
- Env kill-switch'es не удалены: Summary/voice/direct — hot-флаги на runtime-границах; `MCA_RANDOM_SOURCE_ENABLED` — аварийная AND-ось; KILL_SWITCHES-инвариант完整性 (completeness M2) зелёный.
- Рестарт-семантика voice-DI сохранена как была (флаг OFF на старте → DI нет; hot-toggle OFF → runtime-гейт; hot ON после старта с OFF-DI → UNHANDLED до рестарта — прежняя честная асимметрия, задокументирована в коде).
- Random: read-путь статуса (`status_service` «Источник случайности») теперь показывает effective (env AND product) — честнее прежнего.
