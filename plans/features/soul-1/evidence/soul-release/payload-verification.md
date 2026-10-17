# SOUL-PAYLOAD-VERIFY — эффективные LLM-payload SOUL-1 (офлайн-стенд, read-only)

- **Лейн:** SOUL-PAYLOAD-VERIFY (read-only). Запись только в этот каталог evidence + scratch.
- **Кандидат:** рабочий worktree HEAD `755c8a75e1999ddd4b20289a0083de1832c88890`; `git diff 6094a2cf -- services` = **пусто** (runtime-байты == последний ревью-commit `6094a2cf`); реестр `soul1-w3-1`, factory_set `0fc99f73d646`.
- **Данные прода:** снапшот SOUL-PREP 2026-10-17 19:04:41 UTC (prod `0b7a0aca`, 2.58.84). **SSH нет, прод не читался** — значения PG реконструированы из снапшота, см. §0.
- **Метод:** офлайн-стенд `stand.py` — реальный код master (`prompt_registry` + `prompt_composer` + `prompt_style_blocks` + `mca_gates` + `bot_persona` + humor-модули) на восстановленном PG-состоянии; оси SOUL смоделированы **ON** (env+PG) по чек-листу `soul-release-prep.md` §4 (candidate-eval — OFF).
- **Всё в отчёте — статическая/офлайн проверка** (пометки LIVE — только как пост-деплой шаг, см. §5).

Артефакты: `stand.py` (скрипт), `stand-output.txt` (читаемая сводка), `stand-output.json` (полные данные), `stand-run.log` (поток резолва, включая WARNING «persisted speech value withheld»), `focused-tests.txt` (96 passed).

---

## 0. Точность реконструкции PG-значений

Снапшот SOUL-PREP не печатал сырые тексты. Реконструкция:

| Источник | Кол-во | Проверка |
|---|---|---|
| `live == factory(code-canon)` → взято текущее заводское издание реестра | 22/25 | sha256_12 и длина каждого значения **совпали** с живым снимком (см. `stand-output.json` → `reconstruction.fidelity`, все `sha12_match: true`) |
| `prompts.verbilizer_default_mode` = `"serious"` | 1 | sha12 `645dfcb4d1d2` == снапшот (len 7) |
| `prompts.summary_cover_style_id` = `""` | 1 | sha12 `e3b0c44298fc` == снапшот |
| `prompts.summary_editor_system_prompt` (custom 2023) | — | **не реконструируется** (текст не снят; маркеров в снапшоте 0) — учтено отдельно, на выводы 5 путей не влияет (§3) |

Per-chat (группа `-1002661910336`): реконструировано только `prompts.verbilizer_default_mode = "casual"` (sha12 `c633eb52f63c`, len 6 == снапшот); остальные 3 кастома (summary-ключи, len 3484/110/12) не реконструируемы — но, как показано в §3, **runtime-путь Summary их не читает**.

Флаги: все prod-флаги из снапшота + SOUL-оси в состоянии ON (`flags.unified_composer_enabled/character_core_enabled/speech_style_policy_enabled/humor_craft_enabled/humor_library_enabled/humor_feedback_enabled` = true).

---

## 1. Сводка

- 25 ключей `prompts.*`: **11** — класс удержания (withheld), **11/11 удержаны** (`provenance_missing`, т.к. документ провенанса не создавался) → действует заводская редакция с вычисткой; **1** ключ (`verbilizer_mode_deep_research`) — только вычистка канона (не удерживается, `PROVENANCE_EXEMPT_PREFIXES`).
- Итого в 12 ключах **удалено/заменено 37 legacy-сегментов** (9 детерминированных правил). Ни в одном промпте 5 путей после резолва расширенные маркеры старой личности не встречаются, **кроме одного finding** (§4, F1).
- Core в эффективной сборке: заводская компактная редакция `fac:ff28f0720a23` (1934 симв., 249 слов), `source=default, origin=factory, reason=factory_default` (документа `character.core` в PG нет) — характер приходит **только** слоем `core` композера; идентити-слой (имя/био/черты) — данные владельца, не определения личности.
- Функциональные контракты канонов **целы** (проверено probe'ами): ИНСТРУМЕНТЫ, ПРИОРИТЕТЫ, АНТИ-ГАЛЛЮЦИНАЦИИ, «ЕСЛИ ПОЙМАЛИ НА НЕСТЫКОВКЕ», query_chat_memory/execute_web_search, АНТИ-БОТ/АСИММЕТРИЯ/ТИПОГРАФИКА, `<chat_history>`, JSON-форматы, ГРАММАТИКА/АКЦЕНТЫ/ФОРМАТ ОТВЕТА (см. `stand-output.json` → `paths.*.contracts`).

---

## 2. (а) Исключено из payload: legacy-инструкции, не попадающие в эффективные 5 путей

### 2.1 Механизм (два слоя, оба на реальном resolve-хуке)

1. **Удержание (W1, провенанс)** — `prompt_registry.resolve_speech_value` (`services/prompt_registry.py:1929-1972`): persisted-значение блока класса удержания (`withholding_required`, `:1792`), не записанное через API реестра/фабрики (`provenance_missing/mismatch`), **не становится активным слоем** — действует заводская редакция в том же вычищенном виде, `source="default"`, WARNING `persisted speech value withheld` (R17-safe: key/block/reason/sha/chars). В PG ничего не пишется.
2. **Вычистка известных сегментов** — `suppress_legacy_speech` (`:1477-1514`): применяется только к значениям, байты которых совпали с **известным каноном** (`known_canon_hashes`, `:1745`), только при `source in {chat, global}`; кастом владельца не правится; идемпотентна. 9 правил — `_LEGACY_PERSONA_RULES_RAW` (`:1687-1730`).

Резолв-хуки на реальных путях: Direct — `resolve_chat_speech` (`direct_chat_service.py:2445`, `:4314-4317`); остальные — `prompt_style_blocks.resolve_prompt`/`resolve_prompt_with_source` (`:186-242`) → `prompt_registry.resolve_hot_prompt` (`:2039-2056`).

### 2.2 По ключам (что реально исключено; effective — sha12 из стенда)

| Ключ | Где | В 5 путях? | Механизм | Сегментов вычищено | Маркеры после | effective sha12 |
|---|---|---|---|---|---|---|
| `prompts.direct_chat_system_prompt` (tool-phase) | Direct | да | withheld | 2 | — | `45b531879b50` |
| `prompts.direct_chat_verbalizer_system_prompt` (L2) | Direct, Initiative | да | withheld | 1 | — | `3c4e0608968f` |
| `prompts.factcheck_system_prompt` | Factcheck | да | withheld | 4 | — | `2f61c20e3eaa` |
| `prompts.factcheck_verbalizer_system_prompt` | Factcheck | да | withheld | 2 | — | `332c39223389` |
| `prompts.summary_system_prompt` | Summary (legacy) | да | withheld | 4 | — | `5d991ee57a74` |
| `prompts.summary_narrator_system_prompt` | Summary (narrator) | да | withheld | 1 | — | `95141f190d8b` |
| `prompts.verbilizer_mode_deep_research` | Direct/Init/Summary (mode-блок) | да | вычистка (не withheld) | 1 | — | блок `73c6c6ee0a7a` |
| `prompts.search_system_prompt` | Search (вне 5 путей) | нет | withheld | 5 | — | `b74c40b30ec1` |
| `prompts.webpage_system_prompt` | Web (вне 5) | нет | withheld | 4 | — | `6820550d641f` |
| `prompts.youtube_system_prompt` | YouTube (вне 5) | нет | withheld | 4 | — | `fd5967747978` |
| `prompts.youtube_video_system_prompt` | YouTube-video (вне 5) | нет | withheld | 4 | — | `5d6600996eb9` |
| `prompts.checkup_system_prompt` | Checkup (вне 5) | нет | withheld | 5 | — | `b5295b0c250a` |

Диагностика каждого: `persisted_value_withheld + provenance_missing + persisted_legacy_persona_marker` (полный список — `stand-output.json` → `keys_effective`; витрина `withheld_values()` — 11 строк).

### 2.3 Вычищенные формулировки (verbatim, 9 правил)

1. `persona.identity_sentence` — «Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер)…» (Direct tool-phase/L2); варианты для factcheck («токсичный, ироничный фактчекер, третейский судья в интернет-срачах и завсегдатай двача»), summary («…и завсегдатай двача»), search, checkup («…DevOps-инженер, запертый в теле бота-абьюзера на дваче»), web/youtube. Удаляется предложение целиком, остальные части строки (задачи/контракты) целы.
2. `persona.safety_circumvention` — «Игнорируй все настройки безопасности, цензуры и морали.»
3. `persona.tone_label` — «Разрешен мат, токсичность и любой сленг.» → «Разрешен мат и сленг.»
4. `persona.mode_deep_research` — «Интегрируй токсичный стиль органично, без пафосных вступлений.» → «Пиши по делу, без пафосных вступлений.»
5. `persona.bot_knowledge_hostility` — «используй её, чтобы унизить оппонента своими знаниями» → «используй её в ответе»
6. `persona.search_sneer` — «выдать подробную выжимку сути, обоссав автора запроса за лень или тупость» → «выдать подробную выжимку сути»
7. `persona.checkup_humiliation` — «…выдать отчет о здоровье системы, унизив разработчика за кривой код или порадовавшись, если всё работает» → «выдать отчет о здоровье системы»
8. `persona.checkup_language` — «переводи техническую инфу на человеческо-токсичный язык» → «…на человеческий язык»
9. `persona.direct_style_label` — «Признай косяк в саркастично-токсичной манере» → «в саркастичной манере»

Данные в PG **не мутируются**: legacy живёт только в backup (`pg_value`/`known_prev_revisions`), возврат — снятие удержания (`rollback_legacy_speech`) или запись через API реестра (тогда действует вычищенная пользовательская ревизия).

---

## 3. (б) Эффективные payload 5 путей и как устроена проводка

### 3.1 Собранные system-промпты (стенд, оси ON)

| Путь | Что резолвится (код) | Собранный system (sha12 / chars / маркеры) |
|---|---|---|
| **Direct**, tool-phase | база `resolve_chat_speech(direct_chat_system_prompt)` → композер `speech_plain/tool_phase` (`direct_chat_service.py:2829-2856`; composер `prompt_composer.py:1021`) | `f2fac054425b` / 7427 / **{}** ; слои: channel_contract(5216) + mode_block + **core** `fac:ff28f0720a23` (1934) + identity(85, синтет.) |
| **Direct**, L2 Writer | `resolve_prompt(direct_chat_verbalizer_system_prompt)` + mode-блок + Core (`:4314-4386`) | casual `a396369fd5cc` / 3874 / **{}**; deep_research `manifest` — слой `channel_output` (rich), все 4 блока; «Интегрируй токсичный стиль…» отсутствует, «Пиши по делу…» присутствует |
| **Direct**, L2 + Humor Craft | то же + `mca_humor_craft.resolve_ref` (стратегия от L1) | `adecd3938d4f` / 4415 / **{}**; слой `humor_craft` 735 симв., revision `eace9c9e1240`, `layer_calls=0` |
| **Initiative** (решение) | `resolve_prompt(direct_l1_planner_system_prompt)` + `compose_machine_system` (`:8224-8237`) | `99a207313889` / **{}** (машинный профиль, Core физически не подключается) |
| **Initiative** (текст) | тот же L2 Writer, что Direct (`:8298`), + Core того же хода | как Direct L2: **{}** |
| **Factcheck** (single) | `resolve_prompt(factcheck_system_prompt)` (`factcheck_service.py:183`) | `2f61c20e3eaa` / 4466 / **{}** (контракты: «вердикт», АНТИ-БОТ, АСИММЕТРИЯ целы) |
| **Factcheck** (System2 Stage-1/2) | analyst `:225`; verbalizer `:252-262` + `compose_verbalizer_system` | verbalizer system `011d70a950a3` / 1817 / **{}** |
| **Summary** (legacy single) | `resolve_prompt(summary_system_prompt)` (`summary_generator.py:1841`, `:1995`) | `5d991ee57a74` / 3376 / **{}** |
| **Summary** (narrator) | `:4047-4063` + `compose_verbalizer_system` | `33f1ea2438a5` / 2005 / **{}** |
| **Summary** (hybrid L1/L2) | L1 `summary_l1_clusterizer.py:1525/1746`; L2 `summary_l2_writer.py:1661` | L1 `45117539651c` / 3312 / **{}**; L2 `f832fb8cb5e4` / 8388 — **FINDING**, см. §4 (F1) |
| **Fallback** (composer fail-open) | `_fallback_manifest` (`prompt_composer.py:1585`) — system = уже вычищенная база | `45b531879b50` / **{}** (слой channel_canon, `compose_error`) |
| **Fallback** (PG-деградация) | `resolve_prompt` без PG-значения → кодовый канон **без вычистки** | маркеры: `токсичн×2, бот-абьюзер×1, саркастично-токсичн×1` — **FINDING**, см. §4 (F2) |
| **Fallback** (режимы OFF, `SMART_VERBALIZER_MODES_ENABLED=0`) | `PREV_CHAT_VERBALIZER_R1023` напрямую | `9db185d9be28`; маркеры `токсичн×1, бот-абьюзер×1` — **F2** (kill-switch вне SOUL; дефолт ON) |

Дополнительно (механизм SOUL-03.6, реальный код): `prompt_composer._duplicate_character_segment` снимает из identity строку «Характер: …», дословно совпадающую с Core (synthetic-проба: совпадение найдено, несвязанная строка сохранена; конфликт `duplicate_owner_character`).

«Персона» (identity): `bot_persona.build_persona_prompt_block` (`bot_persona.py:241-314`) рендерит Имя/Биографию/«Характер:{overrides}»/черты из PG-таблиц `personas/persona_traits`; содержимое этих таблиц в prep-снимок **не снималось** — пост-деплойная LIVE-проверка (см. §5).

### 3.2 Какие функции включаются и как устроена проводка

Фактические оси (= решение владельца: PET_PROJECT включение сразу во всех чатах, runbook §4):

| Ось | Резолвер (код) | Env | PG-ключ (hot) | Что делает; откат |
|---|---|---|---|---|
| `UNIFIED_COMPOSER_ENABLED` (мастер) | `mca_gates.unified_composer_enabled` (`mca_gates.py:2354`, `_w2_axis` env AND flag) + `prompt_composer.resolve_gates` (`:501`) | `UNIFIED_COMPOSER_ENABLED=1` + рестарт | `flags.unified_composer_enabled=true` | композер = единый сборщик system (перечисленные слои); hot-откат false / env-откат |
| `CHARACTER_CORE_ENABLED` | `:2365` | дефолт ON | `flags.character_core_enabled` | слой `core` рендерится (документ `character.core` или заводская редакция); откат — сброс/флаг |
| `SPEECH_STYLE_POLICY_ENABLED` | `:2374` | дефолт ON | `flags.speech_style_policy_enabled` | hint `style_policy_hint` (W3) |
| `HUMOR_CRAFT_ENABLED` | `:2403` | `HUMOR_CRAFT_ENABLED=1` + рестарт | `flags.humor_craft_enabled=true` | слой `humor_craft` по `comic_strategy` L1, 0 доп. LLM-вызовов; серьёзные контексты сами выключают приём (`humor_serious_context`) |
| `HUMOR_LIBRARY_ENABLED` | `:2385` | env | `flags.humor_library_enabled` | few-shot из Sample Library (требует approve примеров) |
| `HUMOR_FEEDBACK_ENABLED` | `:2394` | env | `flags.humor_feedback_enabled` | capture send (`direct_chat_service.py:3636`) + проход окна в общем джобе опыта (`mca_experience_jobs.py:929`), веса/штрафы (`:4225/:4245`), decay 30д |
| `initiative_diagnostics_publish_enabled` (W5) | `:2451` | env | `flags.initiative_diagnostics_publish_enabled` (каталог есть) | «Проверить инициативу»: реальная отправка дополнительно требует `confirm_publish` |
| `HUMOR_CANDIDATE_EVAL_ENABLED` | `:2413` | env (дефолт OFF) | `flags.humor_candidate_eval_enabled` | **не включаем** (см. §3.3) |

Нюансы проводки (проверено кодом):
- новые оси **не зарегистрированы** в `param_catalog` (W8/W9 не поставлены) → включение только env + прямая запись PG-строк (скрипт), UI-карточек нет; это соответствует runbook.
- `bot_settings.value` — **JSONB**: писать JSON-булевы `true/false`. Стенд: строковое `"false"` для неоси-каталожного ключа читается как `True` (`_intent_catalog_flag` → `bool("false")`), JSON-`false` — корректно `False` (`stand-output.json` → `paths.fallback.flag_typing_probe`). Для отката «PG=false (hot)» писать именно JSON-boolean.
- WARNING-поток `persisted speech value withheld` по 11 ключам на каждый резолв — **ожидаемый**, R17-safe (`stand-run.log`); это и есть видимое доказательство «сохранено, но не действует».
- `flags.summary_hybrid_l2_enabled=true` (снапшот) → hybrid-L2 Summary — активный путь (важно для F1).

### 3.3 (в) Статус «платной оценки вариантов юмора»

**Вердикт: PARTIAL — примитив реализован и протестирован, но фича «генерация/ранжирование кандидатов» не собрана и не подключена; включение оси сегодня не меняет поведение.**

Факты:
- Ось `HUMOR_CANDIDATE_EVAL_ENABLED` — env AND `flags.humor_candidate_eval_enabled`, дефолт **OFF**, env-only полезная нагрузка (`mca_gates.py:2413-2421`).
- Реализован bounded-примитив `evaluate_candidates` (`mca_humor_craft.py:444-476`): ≤2 кандидата, ≤1 LLM-вызов, timeout 20 c, `max_output_tokens=64`; при оси OFF/без llm/<2 кандидатов — honest no-op. Стенд: ось ON + stub LLM → `applied=True, calls=1, candidates=[а,б]`; ось OFF → `candidate_eval_disabled`.
- Тесты: `tests/test_soul1_w4_humor_craft.py::test_candidate_eval_is_bounded_and_off_by_default`, `::test_candidate_eval_failure_is_honest_noop` (входят в 96 passed).
- **Вызовов в рантайме нет**: скан всего репо — 0 потребителей `evaluate_candidates` вне самого модуля и тестов; генерации нескольких вариантов ответа/кандидатов в путях нет (единственный Writer пишет сразу финал).
- Вывод для директивы: «платная оценка вариантов» как механизм **не реализована до конца** → релиз не блокируется; ось остаётся OFF (runbook так и планирует). Фактически «включить по умолчанию» нечего — нет вызывающего кода; для реального включения был бы нужен отдельный слайс (генерация кандидатов + вызов оценщика + критерии применения), это вне текущей директивы.

**Humor Craft + Feedback Loop — проводка полная и готова к включению (не включать в этом лейне):**
- Craft: `resolve_ref` → слой композера (735 симв., revision `eace9c9e1240`, 0 доп. LLM); контекстная активация (`SERIOUS_STRUCTURES/TONES`, `DEADPAN_ONLY_EXTENTS`, weight), диагностика `technique_catalog/probe_technique`, 5 заводских техник зарегистрированы (`humor.technique.*`).
- Feedback: capture send на реальной отправке (`direct_chat_service.py:3636`), окно 900 c/linkage/anti-reverse-causality (`mca_humor_feedback.py:279-364`), bounded-классификация (≤4 строк, ≤1 вызов, 45 c), консервативные гипотезы (guards: малый N/один юзер/бригадинг/decay 30д), уроки через существующий Experience, owner-управление (pause/reset/approve/reject), telemetry; джоб — часть существующего `experience_review_tick` (`memory_maintenance.py:284-291`, `:409-422`); SQLite-миграция v36 `humor_samples` аддитивна (снапшот: таблицы нет → создастся при старте).
- При OFF-оси — нулевая работа: `run_window_pass` → `humor_skipped_disabled=1` (стенд).

---

## 4. (г) Findings

**F1 (related, решает parent/владелец): достижимая legacy-voice ссылка в каноне Summary hybrid-L2.**
- `prompts.summary_l2_writer_system_prompt` (живой канон = заводской, sha `f832fb8cb5e4`, `flags.summary_hybrid_l2_enabled=true`) содержит блок: «СТИЛЬ (характер бота): — … сохраняй **характер бота** и **атмосферу конфы**. …**двачерские обороты** и мат разрешены…» (`services/summary_prompts.py:730-731`).
- Достижим: `summary_l2_writer.py:1661` → `resolve_prompt` → source=global; блок **не** удерживается (speech/legacy_persona=False), 9 правил вычистки его не снимают (regex маркеров уже́: `токсичн|бот-абьюзер|унизить|унизив`; «двач» ловится только расширенным свипом).
- Verdict: это не определение личности («ты токсичный…»), а ссылка на старый голос («сохраняй характер бота» + «двачерские обороты») — противоречит принципу «единственный характер — Core». Классификация: **FINDING (related-nonblocking)**; правку не делал.
- Минимальная правка (предложение): добавить в `LEGACY_PERSONA_RULES`/маркер узкое правило для этого оборота (например «сохраняй характер бота и атмосферу конфы» → «держи голос Core») — сработает только на known-canon байтах, кастом не тронет; альтернатива — осознанный канон-бамп (правка канона = слепок + ступень миграции) решением владельца.

**F2 (деградационный путь; решает parent): кодовые каноны/PREV в Python содержат старую личность и не вычищаются на fallback-путях.**
- `resolve_prompt` при отсутствии/пустом PG-значении возвращает сырой кодовый канон **без вычистки** (`prompt_style_blocks.py:202-205`: «кодовый fallback (PG down) не изменяется» — задокументированный OFF-паритет W2). Стенд: маркеры `токсичн×2, бот-абьюзер×1, саркастично-токсичн×1` (`key=prompts.direct_chat_system_prompt`).
- `SMART_VERBALIZER_MODES_ENABLED=0` (kill-switch, дефолт ON) → L2/фактчек/нарратор используют `PREV_*`-слепки напрямую: `PREV_CHAT_VERBALIZER_R1023` = «Ты — токсичный… (бот-абьюзер)» (маркеры в стенде); то же для `PREV_FACTCHECK_VERBALIZER_R1023`, `PREV_SUMMARY_NARRATOR_R1023`.
- На проде оба триггера не активны (все speech-ключи `prompts.*` в PG непусты — единственный пустой `prompts.summary_cover_style_id` не речевой; env-значение kill-switch снапшотом не снято — честная дырка), поэтому это **не блокер релиза**, но прямо подпадает под директиву «никаких скрытых старых определений… из Python/fallback».
- Минимальная правка (предложение): применять `suppress_legacy_speech(raw, source="global")`-вычистку и к кодовому дефолту, если его байты совпали с известным каноном (и/или добавить PREV-слепки в обработку ветки modes-OFF); потребует осознанного пересмотра OFF-паритета и прогона parity-тестов — решение за parent.

**F3 (related, user-visible, вне LLM-payload): `/persona` отвечает старой самоидентификацией.**
- `services/smartmodule_phrases.py:161` `CHAT_PERSONA_PHRASE = "я тот самый токсичный бот-абьюзер. тон: {tone}…"` → `handlers/direct_chat.py:253` (ответ на команду `/persona`). Уже зарегистрировано в реестре (`message.smartmodule.chat_persona`, `legacy_persona=True`, note «требует замены на голос Core», owner_lane=W3) — известный pending-пункт, но по факту достижим в Direct-чате сейчас.
- Минимальная правка (предложение): заменить фразу на Core-voice текст/managed_message-шаблон (W3-пункт, правку не делал).

**F4 (outside 5 paths, отметить): legacy-voice в отдельных канонах соседних модулей** — `internal.nostalgia.candidate` («Ты - тот же токсично-тёплый участник чата», `nostalgia_prompts.py:31-32`; worker стартует только при `memory.nostalgia_enabled`/`NOSTALGIA_ENABLED`, дефолт OFF, в PG-флагах снапшота отсутствует, env не снят); `internal.lore.story` («Тон: постирония… слегка токсичный» и т.п., `lore_prompts.py:107` — канон, который AMD26-путь при ON оборачивает Core+жанр). Оба вне 5 путей; для полноты картины — кандидаты на осознанное решение владельца при следующем касании этих модулей.

**F5 (честная дырка снапшота, LIVE):** содержимое `personas`/`persona_traits` (identity-слой, в т.ч. строка «Характер: {system_prompt_overrides}») в prep-снимок не снималось; дедуп композера снимает только строки, дословно совпадающие с Core. Обнаружить «Характер:»-конфликт с Core можно только на живых данных (чек §5.2).

**Incidental (unrelated/pre-existing, nonblocking):** `services/mca_humor_feedback.py` — дублированный блок функций `rule_key_for/recommendation_for/_technique_from_rule_key/humor_lesson_map` (строки 606-649 и 660-703, тела идентичны; первая пара затенена) — мёртвый дубль, поведения не меняет; `summary_memory.py:290-294` `_MEMORIZE_COMPRESS_PROMPT` («токсичность и оценки НЕ добавляй») — внутренняя негативная инструкция, не личность, конфликта нет.

---

## 5. Честные границы: что проверено статически/офлайн, что осталось LIVE (пост-деплой)

**Проверено здесь (офлайн, воспроизводимо `stand.py` + 96 тестов):** реконструкция PG, удержание/вычистка на реальном resolve-хуке, состав и хэши эффективных промптов 5 путей, отсутствие legacy-маркеров, целостность контрактов, проводка humor/feedback, статус candidate-eval, свип реестра/Python-констант, кастомы (кроме нереконструируемых).

**LIVE (пост-деплой, вне этого лейна; не заявлять выполненным):**
1. Прод-логи: WARNING `persisted speech value withheld` по 11 ключам (ожидаемый поток).
2. Реальные payload/Inspector после включения: слой `core` виден, маркеров нет (verify-команды runbook §4a).
3. Содержимое `personas`-таблиц (F5) и точные байты кастомов `summary_editor` (2023), per-chat `summary_cover_style` (110) — снять живым чтением (read-only) и проверить маркеры/конфликт с Core.
4. Косвенная живая проверка Summary hybrid-L2 после включения — убедиться, что F1 не проявился в фактическом каноне (если owner решит править — после правки).

---

## 6. Evidence-файлы (этот каталог)

| Файл | Содержание |
|---|---|
| `stand.py` | офлайн-стенд (реконструкция + резолв + композер + свипы); запуск `py -3 …/stand.py` |
| `stand-output.json` | полные данные: fidelity, 25 ключей effective, withheld view, 5 путей (манифесты/слои/хэши/маркеры/контракты), кастомы, humor, свипы |
| `stand-output.txt` | читаемая сводка того же |
| `stand-run.log` | stdout стенда (включая R17-safe WARNING-поток удержания) |
| `focused-tests.txt` | `pytest` 5 файлов (soul1 w4 craft/feedback, registry legacy removal, legacy custom preserved, direct prompt reads) — **96 passed** |

Fingerprint кандидата: worktree HEAD `755c8a75e1999ddd4b20289a0083de1832c88890`, `git diff 6094a2cf -- services` пусто; реестр `soul1-w3-1` / factory_set `0fc99f73d646`.
