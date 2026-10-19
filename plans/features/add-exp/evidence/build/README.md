# ADD-EXP — evidence сборки (лейн ADD-EXP-BUILD, без коммита)

База: master `df078406` + параллельный коммит vision-лейна `b20fe4f7` (во время
работы лейна; мои файлы — только uncommitted рабочее дерево ADD-EXP).
Кандидат = HEAD `b20fe4f7` + рабочее дерево (список файлов и sha256_12 — в
`green-focused.txt`).

## Файлы лейна (uncommitted)

| Файл | Роль |
|---|---|
| `services/mca_expression.py` (новый) | единственный владелец логики §1.6/§2/§3/§6 |
| `services/mca_gates.py` | ось `EXPRESSION_EXAMPLES_ENABLED` (env kill-switch, default ON) |
| `services/prompt_composer.py` | `ExpressionSettings.mode`, `expression_examples` (слой few_shot, owner core), skip-причины, `composer_excluded`-diag, `resolve_expression_settings` |
| `services/mca_sample_library.py` | техника `expression_register`, 12 сидов-черновиков, `resolve_expression_examples`, жёсткое исключение из humor-отбора |
| `services/direct_chat_service.py` | wiring Direct L2/tool_phase/system2_stage2, диагностика §6, postprocess-сравнение, live-check-совместимый `diag_out` |
| `services/mca_authorial_speech.py` | wiring жанровых авторских текстов + `policy_not_injected` после compose |
| `web/api/speech.py` | режимы/метки/инструкции, per-control merge в payload, `migration`, `runtime_wired=true`, live-check endpoint, preview через тот же builder |
| `web/app.js`, `web/index.html` | рендер меток/инструкций/effective из payload, миграционный баннер, «Проверить вживую», честные примечания |
| `tests/test_add_exp_expression.py` (новый) | §7.1: 27 тестов, 10 групп |
| `tests/test_soul1_w6_speech_ui.py`, `tests/test_p0_persistfix_speech_chat_scope.py`, `tests/test_soul1_flags_composition.py`, `tests/ui_p0a_ux_speech_compact_e2e.py` | обновление §5.4-тестов по контракту |

## BLOCK-1: фикс + прогоны (REV-ADD-EXP Needs Fixes `981e9902`)

**Симптом (ревью):** `seed_expression_samples` не вызывался из прод-путей →
12 черновиков не появлялись в `humor_samples`, владелец не мог их одобрить,
`resolve_expression_examples` всегда `()`, блок примеров не рендерился никогда.

**Фикс (минимальный):**
1. `web/api/speech.py::post_examples_seed` — сидятся ОБЕ подборки
   (`seed_starter_samples` + `seed_expression_samples`, идемпотентно, без
   дублей); в ответе честные `expression_seeded`/`expression_skipped` и
   примечание про `not_owner_approved`.
2. Причина `not_owner_approved` реализована:
   `mca_sample_library.resolve_expression_examples_ex` → `(строки, причина)`
   (`""` | `expression_examples_disabled` | `expression_examples_absent` |
   `not_owner_approved`); `mca_expression.build_expression_examples_refs`
   отдаёт `SampleRef(enabled=False, skip_reason="not_owner_approved")`, и
   причина видна в манифесте/событии (`SKIP_REASONS` расширен), текст в
   систему не попадает.
3. `expression_register` виден владельцу в разделе «Примеры»: техника в
   перечне/фильтре/схеме сущности (`SAMPLE_TECHNIQUES_UI`), человеческая
   метка в карточке (`sampleTechniqueTitle`), отдельные счётчики подборок
   (`expression_expected`/`expression_seeded` в payload, меню «Заводская
   подборка (18 + 12 регистра речи)», тост сида называет обе подборки).
   Ось юмора (`HUMOR_TECHNIQUES`, humor-фильтр) НЕ расширена.

**RED → GREEN (BLOCK-1):**

- RED (`red-block1.txt`): worktree `981e9902` + кандидат БЕЗ фикса
  (sha совпали с таблицей ревью) + новые тесты →
  **4 failed** (`test_seed_endpoint_creates_expression_drafts_idempotently`,
  `test_not_owner_approved_then_block_renders_after_approval`,
  `test_examples_payload_exposes_expression_register_technique`,
  `test_ui_shows_expression_register_label_not_raw_code`).
- GREEN (`green-block1.txt`): тот же кластер в рабочем дереве —
  **407 passed / 0 failed**; полный focused-набор (`green-focused.txt`) —
  **642 passed / 0 failed** (было 638 + 4 новых теста BLOCK-1).
- UI e2e (`ui-e2e.json`): **failures=0, POST=22**; в `run_examples_crud`
  добавлены проверки BLOCK-1 (человеческая метка техники в карточке, счётчик
  «регистр речи: 0 из 12», меню «…12 регистра речи», тост сида) — зелёные;
  скрин `shots/examples_block1_390.png`.
- Browser Use (реальный DOM, локальный стаб-API): карточка «№12 · Регистр речи
  (мат: без / эпизодически / часто)» без сырого кода; «черновиков заведено:
  3 из 18 · регистр речи: 0 из 12»; фильтр приёмов содержит
  `expression_register|Регистр речи (…)`; меню «Заводская подборка
  (18 + 12 регистра речи)».
- JS-свип: **105 файлов, 0 ошибок**.

**HTTP-подтверждение сид-флоу (temp-DB, через прод-эндпоинт):**
`POST /speech/examples/seed` → `seeded=18`, `expression_seeded=12`; 12 строк
`technique='expression_register'`, `owner_approved=0`, `scope='global'`,
`source_kind='bot_suggested'`, теги `mode:*`; повтор → `seeded=0`/`expression_seeded=0`,
`skipped=18`/`expression_skipped=12`, всего 30 строк (без дублей);
`resolve_expression_examples_ex` → `not_owner_approved`; после
`set_approval` одной карточки `off` → `build_expression_examples_refs` рендерит
`<Expression_Examples mode="off">` и блок попадает в систему; другие режимы
остаются `not_owner_approved`.

**Новые sha256_12 (BLOCK-1-дельта):** `mca_expression.py 2b0d09888243`,
`mca_sample_library.py a7f81b4f62c0`, `prompt_composer.py 721773eada65`,
`web/api/speech.py 85741bcacdbf`, `web/app.js 1d68fede513e`,
`web/index.html b80dad12a482`, `tests/test_add_exp_expression.py 49227ae3a9c7`,
`tests/ui_p0a_ux_speech_compact_e2e.py 039821b199d4`
(остальные файлы кандидата не менялись). N1–N4 из ревью — nonblocking, не
трогались (бэклог).

## RED → GREEN (исходный лейн)

- RED-1 (`red-baseline-no-module.txt`): baseline `df078406` без модуля —
  `ERROR tests/test_add_exp_expression.py` (ImportError `mca_expression`), rc=2.
- RED-2 (`red-baseline-module-only.txt`): baseline + только новый модуль
  (логика без интеграции) — **19 failed / 8 passed**: падают effective-merge в
  payload, режимы/метки UI, миграция, wiring Direct/authorial, diagnostics,
  few-shot сиды/отбор/бюджет, live-check, no-postprocessor-контракт.
  8 зелёных — чистые функции самого модуля (нормализация/резолв/тексты).
- GREEN (`green-focused.txt`): **638 passed / 0 failed** (26 файлов: новый тест,
  обновлённые §5.4, затронутые кластеры speech/composer/direct/authorial/
  soul1-w4/w5, capability-контур (ADD-1.E2), CFG-registry sanity; там же
  sha256_12 всех файлов лейна).

## Бласт

- JS-синтаксис-свип (`js-sweep.txt`): `node --check` по `web/**/*.js` +
  `tests/js/**/*.js` — **105 файлов, 0 ошибок**.
- UI e2e (`ui-e2e.json`): `tests/ui_p0a_ux_speech_compact_e2e.py` —
  **failures=0**, POST=22 (включая `expression/live-check`), 9 вьюпортов +
  stress + save/scope/humor/examples + новый `run_expression_flow`
  (скриншот `shots/expression_390.png`, `shots/store_390.png`).
- Browser Use (реальный отрендеренный осмотр, живой DOM):
  - глобальный scope: «Действует: Эпизодически — источник: заводское»;
    опции мата ровно «Без мата / Эпизодически / Часто» (наследования нет);
    у каждого контрола своя строка effective+источник; `runtime_note` — честный
    (без предупреждения `runtime_wired=false`);
  - chat scope: опция «Как в глобальных настройках (наследование)» вернулась,
    предпросмотр для чата честно пуст («все контролы „как настроено“»);
  - «Проверить вживую»: клик → блок результата «Режим: occasional; корней
    мата: 1; маркер слоя в payload: есть; 812 мс» + текст + честное «класс не
    присвоен: явных промахов в одной пробе нет»;
  - desktop 1280: две колонки, overflow=0; mobile 390: одна колонка,
    тач-цели ≥44px (проверено PROBE в e2e).

## Покрытие требований (карта READ-ONLY, леджер — отдельным шагом)

| req_id | Тесты/доказательство |
|---|---|
| EXP-UI.MODES/OFF/OCC/FREQ | t1 (closed-set, alias), t4 (тексты §2.2 байт-в-байт), t8 (метки/вопрос/эффект в payload), e2e flow |
| EXP-UI.INHERIT | t2 (inherit=нет явного выбора), t8 (chat-метка наследования; global без inherit), e2e |
| EXP-UI.MIGRATION | t3 (alias, migrated, «ни один чат не frequent»), t8 (баннер до сохранения, каноническая запись + revision/history), persist-тест (canonical write) |
| EXP-INSTR.POSITIVE | t4 (три разные инструкции, запрещённые обороты отсутствуют, off/цитаты, frequent/регулярность), payload `notes` |
| EXP-INSTR.FEWSHOT | t10 (12 сидов-черновиков, отбор ≤4 только своего режима/owner_approved, бюджет/`budget_excluded`, изоляция от humor, отсутствие дублей текста, нет метакомментариев) |
| EXP-INSTR.NOPOST | t9 (RULE_KINDS без profanity, `EXTRA_PATTERNS=()`, egress не вырезает), t6 (style-pass сохраняет мат) |
| EXP-RUNTIME.READSAVE | persist-кластер + t8/t3 (read-after-write, alias→canonical, revision/history) |
| EXP-RUNTIME.WIRING | t5 (Direct L2 manifest с ревизией; authorial; machine-writers профильная причина; budget_excluded честен), t7 (`_l2_write_answer`: маркер в system + `diag_out`) |
| EXP-RUNTIME.PRIORITY | t6 (Core/канон байт-в-байт при off; factcheck-профиль без слоя/примеров; style ортогонален) |
| EXP-RUNTIME.PAYLOAD (live) | Ф6 postdeploy (payload/ответ прода) |
| EXP-RUNTIME.DIAG | t7 (все классы, дедуп, R17; точки: composer/emit, маркер, adapter-repack, provider, postprocess) |
| EXP-ACCEPT.PREVIEW | t8 (effective+источник, честный preview-текст), live-check-тесты (503/422/429/результат+класс), e2e/Browser Use |
| EXP-ACCEPT.LIVE-SET/ROUTES/CRITERION (live) | Ф6 postdeploy (20–30 проб, изоляция чатов, reread/hot-reload) |
| EXP-ACCEPT.REVIEW | этот отчёт + независимое ревью |
| EXP-REG.QUEUE | лейн в очереди, без прерываний; `requirements-map.json` не менялся |
| EXP-DIAG-PROD/DIAG-PAYLOAD | Ф0 (preprod, `evidence/f0/README.md`) |
| ADD-1.E1 | один storage (`character.expression`) и один рендер; второй параметр/Inspector не созданы; t1 (единый владелец значений) |
| ADD-1.E2 | capability-контур не тронут (150 тестов зелёные) |
| ADD-1.E3 | тот же редактор «Выражение» (e2e P0A-UX 0 failures) |
| ADD-1.E4 | t6 + authorial wiring (один Core, Expression=интенсивность) |
| ADD-1.E5 | e2e P0A-UX полностью зелёный (grid/save/scope) |
| ADD-1.E6 | P0A-PERSIST путь переиспользован (persist-тесты + новый alias-тест) |
| ADD-1.E7 | few-shot — библиотека (не хардкод), второй Writer/личность не созданы |

## Девиации (минимальные, честно)

1. **Точка merge**: per-control merge живёт в единственном владельце
   (`mca_expression.resolve_effective`), а `_expression_document` остался
   читателем документов (отдаёт `global_document`/`chat_document`). Дизайн
   §5.1.5 называл местом `_expression_document`; функционально merge тот же и
   вызывается из payload/preview.
2. **`values` в глобальном scope** = явные effective-значения (для формы),
   `document` = нормализованный слой. Дизайн §5.1.6 не фиксировал `values`;
   это минимальный способ дать «явное разрешение эффективного режима» при
   «форме без изменений».
3. **Новая skip-причина `expression_examples_disabled`** (плюс
   `expression_examples_absent`) — в §3.3 дизайна перечислены только
   `absent`/`budget_excluded`; при выключенной оси честнее «disabled», чем
   «absent» (добавлена в `SKIP_REASONS`/`_OFF_REASONS`).
4. **`provider_limitation`** определяется снимком существующего счётчика
   `llm_client.llm_stats()["fallbacks"]` до/после L2-вызова; `policy_not_injected`
   для fallback-репака — обёртка адаптера (точка ~4532), сам адаптер не изменён.
5. **live-check** — один вызов через `_l2_write_answer` (тот же L2-путь; его
   собственные bounded-ретраи ≤2 при провале валидации — часть пути), rate-limit
   30 с и одна проба в полёте; текста ответа владельцу отдаются (owner-facing UI),
   в события — только коды/числа.
6. **postprocess-сравнение** (`raw`-флаги хода, bounded LRU 64 по
   `correlation_id`): точка style-pass — после `apply_style_policy`, точка
   egress — внутри `_verify_style_payload` ДО early-return (egress-гард
   действует и без style-прохода); `_send_direct_answer` получил
   `correlation_id`.
7. **Бюджет примеров ≤140 токенов** реализован отбрасыванием строк в
   `render_expression_examples_block` + честный `budget_excluded` композера.
8. **`_gate_state()`** показывает ось `expression_examples_enabled` (витрина
   осей); `GateState.expression_examples_enabled` — env-only (без каталога).
9. Payload-строки §2.2/§5.1.6 (`EXPRESSION_NOTES`, `runtime_note`,
   `preview_note`) живут в `web/api/speech.py` (UI-слой), инструкции слоя — в
   `mca_expression` (единый владелец текста, дрейф ловится тестом t1).
10. **`.gitignore` +1 узкое исключение** `!plans/features/add-exp/evidence/build/`:
    generic-паттерн `build/` (артефакты шрифтов T-1146) делал каталог evidence
    лейна некоммитабельным; без исключения durable доказательства были бы
    потеряны при коммите. Другие `build/`-каталоги не затронуты.

## Остаётся на живой путь (Ф6 / postdeploy — не в этом лейне)

- EXP-RUNTIME.WIRING/PAYLOAD (live): реальный complete LLM payload и ответ
  прода на трёх режимах; жанровые пробы (цитата с матом, тех-сводка).
- EXP-ACCEPT.LIVE-SET/ROUTES/CRITERION: живой набор 20–30 проб, изоляция
  `frequent`/`off`-чатов, переключение без рестарта, reread после сохранения,
  preview vs production trace.
- Владельческая проба «Проверить вживую» на проде (реальный L2-вызов) — после
  деплоя; endpoint готов (тест + UI).
- Одобрение 12 черновиков набора регистра речи владельцем в разделе «Примеры»
  (BLOCK-1: черновики теперь реально заведены прод-эндпоинтом сида; до
  одобрения — честная причина `not_owner_approved`) — OPTIONAL_FEEDBACK,
  существующим механизмом `owner_approved`.
- Проекция реестрового параметра CFG-07B (`profanity_use`) — отдельный слот
  CFG-07B (ADD-EXP второй параметр не создаёт).
- `model_ignored_instruction` (N≥5) — только в harness Ф6/«Проверить вживую»
  (одиночная проба честно НЕ приговор).

## Санитария окружения

- Прод/SSH/деплой/пуш не использовались. Ничего не закоммичено.
- CFG-файлы (`services/param_catalog.py`, TSV/meta, f8-тест) не тронуты —
  re-pin не потребовался (registry/F8-тесты зелёные: 59 passed).
- Vision-файлы чужого лейна не тронуты.
- Одноразовые сервер/скрипты — в `OPENCODE_WORKFLOW_SCRATCH/add-exp-build/`
  (не в репозитории); в репозиторий промотированы только логи/скриншоты выше.
