# ADD-EXP — независимое ревью (REV-ADD-EXP)

- **Кандидат:** рабочее дерево поверх `35b8b455` (release-25895, pins-only; ADD-EXP-файлы byte-equal базе `b20fe4f7`). sha256_12 всех 15 файлов пересчитаны ревьюером и **совпали** с заявленными.
- **Дата:** 20.10.2026. Прод/деплой не трогались; только чтение + локальные прогоны. RELEASE-PKG-95 (worktree `release-25895/wt`) не смешивался.
- **Вердикт: Needs Fixes** — 1 блокер (EXP-INSTR.FEWSHOT: сиды few-shot недостижимы в production); остальные пункты пройдены независимыми прогонами/осмотром.

## Связка кандидата (sha256_12, пересчитано ревьюером)

| Файл | sha12 |
|---|---|
| services/mca_expression.py | d1c70075e1c1 |
| services/mca_gates.py | 1f6c28841d8a |
| services/prompt_composer.py | 3682774c28fd |
| services/mca_sample_library.py | d3041729af1a |
| services/direct_chat_service.py | 0faaa6034f71 |
| services/mca_authorial_speech.py | 55e8fd72ccff |
| web/api/speech.py | 96d1fab6a0a0 |
| web/app.js | ba456f742c3f |
| web/index.html | f9909c2e1061 |
| tests/test_add_exp_expression.py | 7e96fcc51d04 |
| tests/test_soul1_w6_speech_ui.py | a83f72cd13dc |
| tests/test_p0_persistfix_speech_chat_scope.py | 323af71b4f96 |
| tests/test_soul1_flags_composition.py | 94d9467b9a4f |
| tests/ui_p0a_ux_speech_compact_e2e.py | 07c8a7c9bcff |
| .gitignore | +1 узкое исключение `!plans/features/add-exp/evidence/build/` |

Дисциплина дельты: 15 заявленных файлов + `plans/features/add-exp/evidence/build/**`. Vision (`b20fe4f7`) и CFG-файлы (`param_catalog`, TSV/meta, f8) не тронуты. Прочие modified-файлы дерева (`plans/workflow_state.md`, `plans/progress_scope.json`, asap8/архив) — чужие лейны, в вердикт-коммит не входят. `.gitignore`-исключение проверено: каталог evidence не ignored, чужие `build/` (fonts) остаются ignored.

## Проверено ревьюером (свои прогоны/осмотры)

1. **Канонические тексты** §2.1/§2.2/§1.1/UI — программная сверка с `design-add-exp.md`: header, 3 инструкции, 3 UI-эффекта, вопрос, `EXPRESSION_NOTES`, метки — **байт-в-байт** (14/14). Запрещённые обороты не являются единственным правилом; off упоминает цитаты; frequent — «регулярно… в собственных живых ответах».
2. **Значения/нормализация**: closed-set; alias `allowed`→`occasional`; неизвестное→`inherit`; `inherit` — не 4-я степень (код + t1).
3. **Effective**: per-control chat→global→factory (factory `occasional`); источники chat/global/factory_default; в global scope `inherit` не предлагается (код + t2/t8 + Browser Use).
4. **Миграция**: read-alias без фоновых записей; revision/history/note/override/reset/Core не потеряны; ни один чат не `frequent` (t3, persist-тест, w6).
5. **Wiring**: `_compose_speech_system` (tool_phase/L2/system2_stage2/initiative_writer) и `authorial_system` передают `expression=`; machine-writers — профильная причина; `budget_excluded` честен; манифест LAYER_EXPRESSION с ревизией (t5/t7; мой прогон 27/27).
6. **Диагностика §6**: точки эмиссии совпадают с дизайном (`composer_excluded` — composer emit; `policy_not_injected` — L2/authorial/fallback-адаптер; `postprocess_changed` — style-pass + egress до early-return; `provider_limitation` — `_generate`; `model_ignored_instruction` — только live-check/harness); дедуп 1×процесс; R17 (только коды/числа).
7. **Few-shot**: отбор ≤4 своего режима + `owner_approved=1` + `status=active` + изоляция scope; humor-путь жёстко исключает `expression_register`; ось env-only default ON (паттерн `_env_flag`); 12 сидов — **байт-в-байт** §3.1; бюджет ≤140 токенов; пересечения с humor-сидами = 0 (и inputs, и replies).
8. **UI**: payload без сырых кодов; effective+источник у слоя и у контролов; «Проверить вживую» (rate-limit 30 c, одна проба в полёте, без доставки); `runtime_wired=true` + честный `runtime_note`; предупреждение убрано; тач-цели ≥44px.
9. **Запреты §8**: второго параметра/storage нет (единственный документ `character.expression`); второго Inspector/редактора нет; постпроцессора вставки мата нет (`RULE_KINDS` без profanity, `EXTRA_PATTERNS=()`, egress не режет); legacy-промпты не тронуты.
10. **Прогоны (мои)**: `test_add_exp_expression.py` **27 passed**; §5.4-кластер (w6+persistfix+flags) **49 passed**; composer/authorial/sample-кластер **131 passed**; direct/speech/initiative-кластер **304 passed**; capability/registry-кластер **302 passed**. **RED-2 воспроизведён точечно** в отдельном worktree (`b20fe4f7` + только `services/mca_expression.py`): **19 failed / 8 passed**, список падений совпал с `red-baseline-module-only.txt`. JS-свип: **105 файлов, 0 ошибок**. UI e2e (мой прогон): **failures=0, POST=22** (вкл. `expression/live-check`) — совпало с `ui-e2e.json` (пост-распределение идентично).
11. **UI-осмотр**: мои Playwright-скрины (моб. 390 и desktop 1280, chat/global) + независимый Browser Use по реальному DOM (локальный стаб-API): global — «Действует: Эпизодически — источник: заводское», опции мата ровно «Без мата/Эпизодически/Часто», `runtime_note` честный; «Проверить вживую» — результат с текстом/маркером/классом, без доставки; скрин лейна (`shots/expression_390.png`) совпадает с моим прогоном.
12. **Девиации №1–9**: №1 (merge в `mca_expression`) — эквивалентно дизайну; №2 (`values`=effective в global) — соответствует §1.2/§1.5; №3 (новый skip-reason `expression_examples_disabled`) — обоснован; №4 (`llm_stats` delta) — приемлемо для диагностики (см. N2); №5 (live-check = тот же L2-путь с его bounded-ретраями ≤2) — безопасно/bounded (см. N1); №6 (LRU 64) — bounded; №7 (дроп строк ≤140 токенов) — честно; №8/№9 — соответствуют; №10 (.gitignore) — узко и обосновано.

## Findings

### BLOCK-1 — EXP-INSTR.FEWSHOT: сиды few-shot недостижимы в production (блокер)

- **Требование:** «Добавлен небольшой **редактируемый owner-approved набор** коротких разговорных few-shot-примеров…; примеры используются по бюджетному контролю в целевых speech-путях» + дизайн §3.3 (сиды в `humor_samples`; одобрение — существующим механизмом).
- **Наблюдение:** `seed_expression_samples` (`services/mca_sample_library.py:854`) **не вызывается ни из одного прод-пути** (grep по репо: только тест `tests/test_add_exp_expression.py:737`). Эндпоинт `POST /speech/examples/seed` (`web/api/speech.py:2988`) сидит только `seed_starter_samples` (humor). `resolve_expression_examples` требует `owner_approved=1` → в проде всегда `()` → композер всегда даёт `expression_examples_absent` (блок не рендерится никогда).
- **Последствия:** владелец не видит и не может одобрить 12 черновиков «существующим механизмом»; заявленный набор примеров фактически отсутствует в продукте (есть только константа + функция, вызываемая тестами). Утверждение evidence-README «12 сидов-черновиков… до одобрения в runtime не идут» верно только на уровне тестов.
- **Мелкий довесок той же причины:** дизайн §3.3 называет честную причину `not_owner_approved`; реализация отдаёт только `expression_examples_absent` (не отличает «нет одобренных» от «нет строк вовсе»).
- **Смежное (в том же фиксе, минимально):** в разделе «Примеры» техника `expression_register` не представлена в UI-перечне (`HUMOR_TECHNIQUES`, `web/index.html:8351/8410/8522`) — карточки показывали бы сырой код без подписи и без фильтра; решить одной строкой (человеческая метка) или явно задокументировать границу.
- **Минимальная правка (1–2 строки + 1 честная причина):** в `post_examples_seed` вызвать и `samples_lib.seed_expression_samples(...)`, сложить `seeded/skipped` в ответ (идемпотентно, как humor-сид); при наличии неодобренных строк отдавать `not_owner_approved` (или явно задокументировать замену причины в девиациях/README).
- **Минимальный recheck:** HTTP-прогон seed-эндпоинта на temp-DB: 12 строк `owner_approved=0`, повтор — no-op; `resolve_expression_examples`=() до одобрения, после `set_approval` — блок рендерится; 1 точечный тест через эндпоинт.

### Замечания (nonblocking)

- **N1.** Текст «Проверить вживую» говорит «один реальный L2-вызов», фактически это один прогон того же пути с его bounded-ретраями (≤2 при провале валидации; девиация №5). Стоит уточнить формулировку («один прогон, bounded-ретраи — часть боевого пути»).
- **N2.** `provider_limitation` по дельте процесс-глобального `llm_stats()["fallbacks"]` может приписать пробе чужой параллельный fallback (диагностика, дедуп; влияние — только на класс события).
- **N3.** `postprocess_changed` со `stage="style_policy"` может фактически отражать numeric-guard (проверка идёт после него) — `detail` неточен, класс честен.
- **N4.** В chat-scope предпросмотр показывает «слой пуст», пока выше строка «Действует: …» — соответствует дизайну §5.2 (предпросмотр = слой scope), но стоит держать в уме при UX-волне.

## Леджер-заметки (после закрытия BLOCK-1; карта read-only — правки отдельным шагом)

- `EXP-UI.MODES/OFF/OCC/FREQ/INHERIT/MIGRATION` → **V**
- `EXP-INSTR.POSITIVE/NOPOST` → **V**; `EXP-INSTR.FEWSHOT` → **V после закрытия BLOCK-1**
- `EXP-RUNTIME.READSAVE/PRIORITY/DIAG` → **V**; `EXP-RUNTIME.WIRING` → **RFL** (postdeploy), `EXP-RUNTIME.PAYLOAD` → **RFL**
- `EXP-DIAG-PROD/DIAG-PAYLOAD` → **V** (Ф0, `evidence/f0/**`)
- `ADD-1.E1–E7` → **V**
- `EXP-ACCEPT.PREVIEW` → **V**; `EXP-ACCEPT.REVIEW` → **V** (этот файл)
- `EXP-ACCEPT.LIVE-SET/ROUTES/CRITERION` → **RFL**: Ф6-набор 20–30 проб (матрица §7.2), изоляция `frequent`/`off`-чатов, переключение без рестарта, reread после сохранения, preview vs production trace
- `EXP-REG.QUEUE` → **V**
- Проекция реестрового `CFG-07B.profanity_use` (ON ⇔ effective ∈ {occasional, frequent}) — **отдельный слот CFG-07B**; ADD-EXP второй параметр не создаёт.

## Гейты/статус процесса

- `requirements_gate check --stage plan`: **errors=0, EXIT 0**.
- `--stage review --slice EXP-RUNTIME --candidate b20fe4f7`: **EXIT 1** — пред-биндинговое состояние: `candidate_commit` в карте пуст, строки `PENDING` (леджер ещё не проходил). Это ожидаемая точка конвейера (прецедент CFG-01: EXIT 0 достигается на шаге биндинга после проставления candidate/статусов). **Не считать пройденным:** на биндинге проставить фактический sha кандидата и статусы (V/RFL) и перезапустить review-стадию до EXIT 0.

## Следующее действие

1. `FIX-ADD-EXP-FEWSHOT` (Builder): BLOCK-1 минимальной правкой + тест через эндпоинт.
2. Узкий `REV-RECHECK` (только BLOCK-1 + соседние швы seed/отбор/манифест).
3. Затем биндинг/леджер (candidate=фактический sha, статусы, RFL для live) → release-гейт → деплой → Ф6.

Reviewer не редактировал код приложения; вердикт — этот файл (1 docs-коммит `--only`).