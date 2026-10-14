# W1-COVER-MODULES — отчёт Builder-полосы (B04 / B06 / B07)

HEAD на старте: `bc91b90`. Коммит НЕ делался (запрещено брифом). Все изменения — в рабочем дереве.
Тесты новые: `tests/test_asap8_v63_b04_edit_contract.py`, `tests/test_asap8_v63_b04_scene_delivery.py`, `tests/test_asap8_v63_b06_summary_scope.py`, `tests/test_asap8_v63_b07_temporal_factcheck.py` — суммарно **60 passed**.

---

## 1. Реализации

### B04 — Style Edit: EDIT, не GENERATE (`services/cover_style_jobs.py`, канон текстов — `services/cover_prompt_assembly.py`)

**B04.1 — Base bitmap = источник сцены.** `compile_style_prompt` переписан на
компактный EDIT-контракт: `compile_style_edit_components()` собирает ровно
`content_preservation (P0) → runtime_invariants (P0) → style_instruction (P1) →
scene_anchor (P1, опционально) → references (P2) → base_style_prompt (P3)`.
`story_scene`/`CoverBrief` (summary) в текст **не переносятся** — источник сцены
передаваемая Base bitmap; pure text-to-image (base cover) не смешан — свой
сборщик `cover_prompt_assembly.compose_base_cover_prompt` (тест: канон
`STORY → CONTEXT → STYLE` цел). Замер на типовом профиле: 528 chars (дефект
«1133/800» устранён архитектурно, тест
`test_compact_payload_fits_confirmed_limit`).

**B04.2 — компактная инструкция, один язык.** «Что изменить» = инструкция
профиля; «что оставить» = компактный preservation (RU-канон
`EDIT_PRESERVATION_RU`, EN — прежний канон §5.3); язык сборки =
язык инструкции профиля (`edit_content_language`: кириллица→ru, латиница→en);
EN-дубли исключены (тест `test_ru_instruction_ru_components_no_en_duplicates`).
Сцена максимум ОДИН раз; логотип — «графический образец» + labels
(`edit_reference_roles_text`); «PERMsoc один раз, выпуск один раз» —
protected-токены нормализатора (см. B04.3), тест
`test_brand_and_issue_once_in_text`.

**B04.3 — нормализатор + preflight.** `normalize_style_edit_components()`:
semantic dedupe НА УРОВНЕ ПРЕДЛОЖЕНИЙ — точные дубли, near-дубли
(stemming RU-флексий + стоп-слова + Jaccard ≥0.8 / overlap ≥0.75 — не слепая
подстрока, тест `test_semantic_dedupe_not_blind_substring`), protected-токены
(номер выпуска, бренд-токены labels референсов) живут в тексте один раз,
легитимная новая инструкция с брендом сохраняется. Scene anchor — опциональный
и краткий: `scene_anchor_policy()` env `COVER_STYLE_EDIT_SCENE_ANCHOR`
(`auto|on|off`, default auto), auto = короткий якорь только для компактного
сюжета ≤240 симв., первое предложение, ≤200 симв.; причина skip фиксируется
(`empty/policy_off/scene_too_long/cut`). Preflight: `style_edit_headroom_chars()`
env `COVER_STYLE_EDIT_HEADROOM_CHARS` (default 0) вычитается из известного
лимита (тест `test_headroom_preflight`); при confirmed 800 итоговый payload
укладывается, иначе `exceeded → style_publish_skip_reason == prompt_limit_exceeded`
и платный вызов НЕ делается (тесты overflow/no-call: `test_overflow_no_paid_call`,
run-уровень `TestFailSoftPublication.test_overflow_no_paid_call_base_with_manifest_marker`).
Неизвестный image-модель лимит не выдумывается (тест
`test_unknown_limit_no_invented_number`).
Textual story-floor требование ИЗЪЯТО из compile/retry-ядра
(`story_identity_dropped` больше не триггерится компиляцией; reason-код
остался для истории/манифестов) — семантику результата теперь проверяет
image-comparison (B04.6). Длинное русское summary — негатив-тест
`test_long_russian_summary_negative`.

**B04.4 — production-identical preview.** `style_edit_preview_report()` — ТОТ
ЖЕ `compile_style_prompt` (без test-контекста), отдаёт: `limited_preview: true`,
`image_input_used {base, references}`, model/provider/route, `limit_source`/
`limit_value`/`limit_unit`, `language`, `original_chars`/`deduped_chars`/
`final_chars`, `dedupe_dropped[]` + `dropped[]` (с reason), `exceeded`/
`overflow_reason`, **точный `final_prompt`** (тесты
`TestStyleEditPreviewReport` + parity run-уровня
`test_run_style_job_preview_mode_uses_same_compiler`).
Манифест честен: `cpa.build_style_manifest` получил аддитивные
`preservation_sent`/`runtime_sent` + авто-детект RU-варианта по факту промпта
(манифест описывает отправленное, а не канон-EN; default — прежний канон).
UI-рендер панели — handoff (см. §5); готовый API-патч — §4.

**B04.5 — доставка / late recovery.** Решение зафиксировано ЯВНО:
recovery по умолчанию Telegram НЕ вызывает (C03A-инвариант сохранён);
статус доставки — durable-поле `CoverJobState.telegram_delivery` + поле
`telegram_delivery` события `COVER_STYLE_RECOVERED` и результата action:
`not_attempted_policy_off` (default), `replaced`,
`rich_message_edit_unsupported`, `publication_reference_missing`.
Включение замены — env `COVER_STYLE_TELEGRAM_REPLACE_ENABLED`.
`replace_published_cover_image()` — идемпотентная `editMessageMedia`
(меняется ТОЛЬКО media; caption/article/нумерация не трогаются). Проверено по
коду/окружению: aiogram 3.29.1 **не имеет** `editRichMessage` (и в этой среде
отсутствует даже `InputRichMessageMedia` — предсуществующий дефект
`services/telegram_send.build_cover_media`, см. §6), rich-публикация
(`sendRichMessage`) отвечает 400 на editMessageMedia → исход честно
классифицируется `rich_message_edit_unsupported`, дубль-публикация НЕ
создаётся, артефакт остаётся привязан к run (manifest+provenance).
`lookup_published_message_id()` — message_id публикации из durable
`SUMMARY_RUN_DONE` (usage_json.message_id, §109), fallback по chat_id —
best-effort «последняя публикация чата» (задокументировано тестом).
Политика доставки: предложенная (для согласования владельцем) — env ON в
проде + честный статус `unsupported` в Inspector; вторая публикация запрещена.
Тесты: `TestDeliveryReplacement` (+C03A case-2 расширен: delivery default off,
durable-поле в state round-trip).

**B04.6 — control сюжета.** `format_valid` и `scene_preserved` — РАЗНЫЕ
сигналы: `_styled_payload_signal` (magic bytes JPEG/PNG/WEBP vs текст vs мусор)
→ `semantic_verification.format_valid` (true/false); bounded image-comparison
`verify_scene_preserved()` (Base vs styled: люди/поза/событие/композиция,
один compare-вызов ≤60s, любой сбой → честный `unknown`) →
`scene_preserved` ∈ {pass, replaced, unknown} с detail. Прозрачная политика
`scene_verify_mode()` env `COVER_STYLE_SCENE_VERIFY` (`preview|off|all`):
запуск на preview (+на всех прогонах при `all`); **активация — только явным
env** (каждый compare — платный вызов; молчаливых платных вызовов нет),
инъекция verifier (тесты/канарейка) снимает только требование env и только
для preview. `replaced` на preview/canary → НЕ успешный styled:
fail-soft Base c `semantic_preservation_failed` (тест
`test_replaced_not_published_as_styled`), формат при этом `format_valid=true`
(разделение сигналов). Прод без активации — `unknown` с причиной политики
(не молчаливое true). Манифест получает `semantic_verification` во всех
исходах. Слово «vision» в cover_style_jobs.py не используется — гвард
`test_no_third_mandatory_call` (§93: ровно один image-call) сохранён без
ослабления.

### B06 — Per-chat Summary управляет runtime

**B06.1 — единый резолвер** (`services/summary_scheduler.py` — владелец):
`summary_effective_enabled(chat_id) -> (enabled, source)`:
`emergency env (`SUMMARY_EMERGENCY_DISABLE`, env-only) → explicit chat
override `flags.summary_enabled` (chat_params, категория flags → per_chat) →
global default (hot)`. Источник честен: `emergency_env | chat | global`.
Точки применения (все реальные, не только /api/config):
- `SummarySchedulerService._tick` — cron пропускает чат с OFF (reason в логе), гоняет chat-ON при global OFF (тесты `TestSchedulerFollowsResolver`);
- `SummaryGenerator.generate_and_send` — единая точка producer/queue/trigger/manual/retry: гейт ДО слота пула; manual получает честный UX (`_UX_SUMMARY_OFF_CHAT` / `_UX_SUMMARY_OFF_EMERGENCY`), cron молчит (тесты `TestMatrixRealGeneration` на РЕАЛЬНОМ пайплайне: FakeLLM 0/1 вызовов);
- `handlers/summary.py::cmd_summary` — `_summary_allowed_for_chat()`: emergency → chat override (только группы) → global; ЛС — прежний global-гейт (F-14 S4: manual в ЛС не зависит от DM-override; тест `test_cmd_summary_manual_per_chat_gate`);
- observer НЕ изменён (global-гейт): вход бегущего конспекта (summary_memory — не трогал по запрету) не зависит от периодических сводок;
- producer-существование: bot.py (см. §4 патчи) — `if global ON AND not emergency OR (not emergency AND any chat opted in)` — канон §18H(2) сохранён (флаг остаётся в If-выражении; тест `test_bot_producer_gate_condition_keeps_flag_in_if`), `summary_any_chat_opted_in(pg)` сканирует chat_profiles на явный true.
Негативы DoD: `global ON, A OFF, B inherit` и `global OFF, A ON, B inherit` — на реальной генерации; inherit через сброс override; инверсия global без записей чата; рестарт (резолвер state-free, чат-слой персистентен); сохранение A не меняет B; emergency бьёт chat ON.

**B06.2 — матрица и честные чтения.** Задокументирована и покрыта тестами
(`TestCatalogRuntimeMatrix`):
- `flags.summary_enabled` — per_chat в каталоге (category flags, не секрет), runtime теперь реально читает per-chat (было: только global, карточка «inert» — закрыто);
- per-chat по факту контракта: `flags.summary_enabled` (+ `flags.chat_running_summary_enabled` — уже per-chat для ЛС через `chat_summary_enabled`, бегущий конспект — вне B06), `memory.experience_learning_enabled` (F5 chat-resolver — существующий);
- global-only оси (тумблер чата — read-only, UI handoff): initiative, factcheck, factcheck_temporal, vision, nostalgia, sleep, stories, character, random, embeddings (`runtime_gate="global"` — тест);
- `models.*`/`keys.*`/`temporal.*` — `per_chat=False` (инертный override создать нельзя: POST chat-scope → 422, source-гвард `if not spec.per_chat:` в routes);
- расхождение чтения закрыто: `temporal.tool_enabled` читался только из статического Settings — переведён на hot (`services/tool_schemas.py`, §4 патч); mass-перевода 21 карточки в per-chat НЕТ.
UI-часть (moduleRuntimeNotice «не влияет; глобально», read-only тумблеры) — handoff W2; backend уже отдаёт `per_chat`/`chat_source`/`global_value` в items и `runtime_gate` в modules.

**B06.3 — краевые случаи.** Покрыто: смена scope двух чатов, сброс/инверсия global default, рестарт, save-A-не-B (тесты `TestTwoChatsAndRestart`); конфликт 409 и role deny — СУЩЕСТВУЮЩИЕ web-контракты (не дублировал): optimistic 409 — `web/api/routes.py::_post_config_global` + `tests/test_global_config_optimistic_round1025.py`, chat-conflict — `ChatParamsConflict` + `tests/test_chat_params.py`, role deny — `access_srv.can_edit_param` (тест в B07-файле) + `tests/test_webapp_api.py` (403/422 матрица). Одновременное сохранение двух админов — тот же optimistic-механизм (409 при несовпадении updated_at).

### B07 — Temporal = функция Фактчека

**B07.1 — настройки внутри Фактчека (backend-резолвинг).** Каталог
`temporal_factcheck` (вкладка mod_factcheck) уже содержал: режимы
`contextual/current/historical_truth/knowable_at_time` (select,
`resolve_requested_mode`), TTL вердиктов ×2, `temporal.tool_enabled` — тест
`test_select_modes_and_ttl_specs`. Runtime-гейт: `fact_check`-инструмент
читает hot `temporal.tool_enabled` (без рестарта) + env-оси K1/K2 остаются
аварийными AND (тест `test_env_emergency_axis_still_works`). Временная линия
evidence в детализации — существующие events/inspector не тронуты
(`temporal.factcheck` процесс жив, тест `test_factcheck_temporal_absent_from_cards_output`). UI-секция — handoff W2.

**B07.2 — сид CATEGORY_TEMPORAL.** `pg_db.SEED_CATEGORIES += temporal`
(confirmed code cause); сид `INSERT .. ON CONFLICT (key) DO NOTHING` —
существующие PG owner-значения не перетираются: идемпотентность доказана
тестом `test_seed_idempotent_owner_values_delta_zero` (2 сида, Δowner=0).
Чтение дефолта без дублей: `config_cache._synthetic_group_items` расширен на
Settings-backed ключи категории `temporal`, отсутствующие в bot_settings
(историческая БД) — честный Settings-дефолт деривацией на чтении,
строки БД не создаёт, `updated_at=None` (default-флаг) — тест
`test_missing_settings_backed_temporal_synthesized`. POST→hot→runtime→restart:
тест `test_post_hot_read_runtime_tool_gate` (set → gate off → reload →
новый кэш видит persistent False). RBAC: temporal.* — честный global control
(`per_chat=False`; edit local_admin+, view moderator+; user — deny, global
admin — allow; тест `test_rbac_global_control_role_deny`). API/REST-путь —
существующий `POST /api/config` (валидация `_coerce_value`/select-опции);
byte-freeze `pg_db.py` переутверждён константой `PG_DB_SHA256_B07`
(прецедент L-F11S-1, fixture не менялся) + инвариант DDL-сегмента в тесте.

**B07.3 — не карточка модуля.** `factcheck_temporal`: `visibility="hidden"`,
`registry_for_frontend()` фильтрует hidden → карточки в выдаче `GET /api/config`
НЕТ (ни top-level, ни subcard; тест `test_factcheck_temporal_absent_from_cards_output`).
Запись в `MODULE_REGISTRY` сохранена (инвентарь M2, env-оси, gate_snapshot,
analytics_anchor `temporal.factcheck` в реестре процессов) — backend-сервис
`temporal_factcheck` и events/inspector целы. Выключение Factcheck блокирует
его функцию: `flags.factcheck_enabled` OFF → tool `fact_check` скрыт из
`active_tools()` (и `/factcheck` гейтится мастером — source-тест) — тест
`test_factcheck_off_blocks_tool_not_direct`; обычный Direct не сломан:
`_is_direct_trigger` не содержит factcheck-осей (source-тест в том же тесте);
канон tool-набора при ON не изменился (`test_canon_twelve_tools` зелёный).
D11-тест обновлён под новый контракт (замена зафиксирована в тесте).

---

## 2. Acceptance-ledger

| Item | Статус | Доказательство |
|---|---|---|
| B04.1 | PASS (unit) | `test_full_story_and_summary_not_retransferred`, `test_edit_components_exclude_summary_context`, `test_pure_text_to_image_branch_untouched` |
| B04.2 | PASS (unit) | `TestSingleLanguage.*` (один язык, EN-дубли исключены, сцена 1 раз, логотип-референс, PERMsoc/выпуск 1 раз) |
| B04.3 | PASS (unit) | `TestNormalizer.*` (semantic dedupe, headroom, no invented limit, overflow no-paid-call, scene anchor policy, long RU summary) |
| B04.4 | PASS (unit) + API-handoff | `TestStyleEditPreviewReport.*`, parity-run тест; UI/API-панель — handoff W2 (патч готов, §4) |
| B04.5 | PASS (unit) + POLICY-DECISION | `TestDeliveryReplacement.*` + C03A case-2 delivery-поля; прод-замена Telegram — LIVE_UNVERIFIED (нужен реальный rich-выпуск; политика env-gated) |
| B04.6 | PASS (unit) | `TestSceneVerificationPolicy.*` (replaced→Base, pass, unknown, прод-бюджет, format≠scene); реальный vision-прогон — LIVE_UNVERIFIED (нужен настроенный vision-маршрут + env) |
| B06.1 | PASS (integration, реальные generate_and_send/_tick/cmd) | `TestMatrixRealGeneration.*`, `TestSchedulerFollowsResolver.*` (моки только LLM/bot/chat_params-store) |
| B06.2 | PASS (unit/matrix) | `TestCatalogRuntimeMatrix.*` (каталог-перечень, hot-чтение temporal, 422-гвард, global-only перечень) |
| B06.3 | PASS (unit) + существующие web-контракты | `TestTwoChatsAndRestart.*`; 409/role-deny — существующие тесты (перечислены выше) |
| B07.1 | PASS (unit/backend) | `test_select_modes_and_ttl_specs` + существующие mca-20 резолверы; UI-секция — handoff W2 |
| B07.2 | PASS (unit) | `TestSeedTemporal.*` + `test_post_hot_read_runtime_tool_gate`; прод-PG сид — постдеплой-проверка (идемпотентность доказана на fake-PG семантике DO NOTHING) |
| B07.3 | PASS (unit) | `TestNotAModuleCard.*` |
| REQ-B04/B06/B07 live (postdeploy) | PENDING OWNER | реальный Telegram-доставка styled, прод-сид, vision-канарейка — после deploy (live_required=true в карте) |

DoD-негативы B04: overflow ✅, long Russian summary ✅, logo reference ✅
(роль+protected-токен), ambiguous image model ✅, retry exhaustion ✅
(C03A `test_transient_recovery_is_bounded`), restart ✅
(`test_restart_mid_style_job_not_completed_then_recovered`), late recovery ✅
(case-2 + delivery-поля), two publications ✅
(`test_legacy_completed_styled_not_failed_by_sweep`, без дубля rich-отправки),
semantic mismatch ✅ (replaced→Base).

---

## 3. Изменённые файлы (владельческие)

- `services/cover_style_jobs.py` — EDIT-компилятор/нормализатор/preflight/scene-verification/delivery/preview-report/диагностика Inspector (`content_language`, `image_input_used`, `edit_*`, `semantic_verification`).
- `services/cover_prompt_assembly.py` — канон компактных EDIT-текстов (RU/EN), `edit_content_language`, авто-детект отправленных P0 в манифесте (аддитивные kwargs, default — прежний канон).
- `services/pg_db.py` — `SEED_CATEGORIES += temporal`; модульная `_seed_settings_into()` (Δ DDL = 0).
- `services/config_cache.py` — синтетика отсутствующих Settings-backed ключей категории temporal.
- `services/module_registry.py` — `factcheck_temporal` visibility=hidden + фильтр выдачи карточек (реестр/гейты/инвентарь сохранены).
- `services/summary_scheduler.py` — единый per-chat резолвер + cron-гейт.
- `services/summary_generator.py` — producer-гейт на входе `generate_and_send` (+UX).
- Новые тесты: 4 файла (60 тестов), маркеры TEST-LIFECYCLE внутри.
- Обновлённые тесты (замена контракта F3→B04 / D11→B07 / NOTE-allowlist): `test_asap8_f3_style_preservation.py`, `test_asap8_f4_prompt_truth.py`, `test_asap5_cover_prompt_manifest.py`, `test_asap44_cover_final_closure.py`, `test_asap8_v6_c03a_style_recovery.py`, `test_extra_cover_style_jobs.py`, `test_asap8_v6_p1_d11_registry.py`, `test_tool_coordinator_round1026.py` (allowlist NOTE), `test_round1025_f8_registry.py` (re-pin PG_DB_SHA256_B07 + DDL-инвариант).

## 4. Патчи вне WRITE_SCOPE (минимальные, согласованные с корнем причины)

1. **`bot.py`** (composition root; B06.1): условие старта Summary-контура расширено до `global ON AND not emergency OR (not emergency AND any_chat_opted_in)`; флаг `flags.summary_enabled` остаётся в If-выражении (AST-тест §18H(2) зелёный); импорт `summary_any_chat_opted_in`/`summary_emergency_disabled`.
2. **`handlers/summary.py`** (смежный summary-файл, в нём живёт enabled-резолв): `_summary_allowed_for_chat()` + гейт `cmd_summary` (emergency → chat override групп → global; ЛС — global; observer не тронут).
3. **`services/tool_schemas.py`** (gate fact_check; B06.2/B07.1/B07.3): `temporal.tool_enabled` через hot (было — только Settings), master `flags.factcheck_enabled` как AND-ось функции Фактчека.
4. **UI-handoff патч (НЕ применён — web/* запрещено)**: в `web/api/cover_styles.py::_style_preview_compile` заменить прямую сборку манифеста на отчёт production-маршрута:
```python
# compiled = jobs.compile_style_prompt(...) — уже есть; вместо dict выше:
report = jobs.style_edit_preview_report(
    profile, issue_display=issue_display, capabilities=caps,
    base_style_prompt=base_style, story_scene=story,
    image_input={"base": True, "references": 0},
    limit_source=str(limit_source or "unknown"), route="preview_compile",
    model="", provider="")
return {**resp, "edit_report": report,
        "limited_preview": True,
        "final_prompt": report["final_prompt"]}
```
   (аддитивный ключ `edit_report`; существующий ответ не ломает UI-волны).
5. `web/app.js::moduleRuntimeNotice` — handoff W2: для `runtimeGate==='per_chat'` читать фактический per-chat резолв (backend уже отдаёт `chat_source`/`global_value`/`per_chat`); global-only карточки — read-only тумблер + «Настроить глобально» (inert override backend уже не создаёт — 422).

## 5. UI-handoff (W2)

- **B04 preview-панель**: новый источник `edit_report` (см. §4.4): `original/deduped/final chars`, `dropped[]`+reason, `scene_anchor{included,chars,skip_reason}`, `language`, `headroom_chars`, `image_input_used`, `limit_source/value/unit`, `limited_preview:true`, точный `final_prompt` — рендер по U06 (одна строка `Style N · SceneAnchor M · Refs R · System S · Final F / Limit L`, моноширинный `pre` + copy).
- **B06**: тумблер Summary на chat-scope — активный (per_chat=true, runtime честный); read-only + «Настроить глобально» для global-only карточек (перечень — `TestCatalogRuntimeMatrix.test_runtime_reads_match_per_chat_contract`); `moduleRuntimeNotice` текст «не влияет; глобально» снять для Summary.
- **B07**: карточку «Временная проверка» из витрины убрать (backend уже не отдаёт); секцию «Фактчек → Настройки → Время/источники»: `Проверять дату и актуальность` (= `temporal.tool_enabled`, объяснение «включает инструмент fact_check в диалоге; датировку/режимы не выключает»), select режимов, TTL ×2; env-оси показывать как аварийные.

## 6. Прогон тестов

- Новые: **60 passed** (b04_edit 18, b04_scene 13, b06 17, b07 12).
- Смежные (cover/style/summary/recovery/modules/param/factcheck/temporal/scheduler/chat_params): **все зелёные**, в т.ч. 320 passed по 14 ключевым файлам, 253 passed по factcheck/temporal/param-блоку, 202 passed по API/contract блоку.
- Полный `tests/`: 13428 passed / 7 failed — все 7 вне моей полосы либо предсуществующие (проверено stash-методом):
  - `test_outgoing_guard_round1022.py` ×2 — `InputRichMessageMedia` отсутствует в aiogram 3.29.1 (env/предсуществующее, `services/telegram_send.py` не менялся);
  - `test_summary_asap2_failsoft_round1027`, `test_summary_publish_integration_round1026` — предсуществующие (воспроизводятся без моих изменений);
  - `test_mca01_tx_task_supervisor` (diff `chat_migration.py`/`database.py` — полоса B09/B03), `test_mca09_intents` (полоса B01), `test_mca16_experience` (полоса B02), `test_mca02_safe_fetch` (сетевой env).

## 7. Ограничения и реальные риски

- **B04.5 прод-доставка**: aiogram 3.29.1 не умеет редактировать RichMessage; замена изображения существующего выпуска возможна только если Telegram вернёт успех на `editMessageMedia` — иначе честный `rich_message_edit_unsupported`. Политика включения — env; требуется решение владельца (предложено в §1/B04.5). LIVE_UNVERIFIED.
- **B04.6 vision**: активация env'ом (осознанный бюджет); реальный verdict зависит от настроенного vision-маршрута. Отдельно: в этой среде `InputRichMessageMedia` недоступен — rich-публикация с media в этой сборке aiogram требует отдельного фикса (вне полосы; не трогал).
- **B07.2 прод-сид**: выполнится при следующем старте с PG (`init(seed_settings=True)`); на живой БД значения владельца защищены DO NOTHING (доказано unit-семантикой).
- **B06**: `flags.summary_enabled` в DM-дефолтах (`_DM_DISABLED_OVERRIDES`) влияет только на периодические сводки групп-логики; manual в ЛС сохранён (F-14 S4, тест).
- ПрогOwners-профиль «Графический роман Медведь Press» не менялся (данных владельца в фикстурах нет; только синтетика).

@Orchestrator — к строгому независимому ревью. UI-волна (W2): см. §5 handoff и §4.4 патч.
