# ASAP-FC-VOICE-01 / A — контракт голоса и подачи FactCheck

- База: ветка `evol/impl`, HEAD `613fae5d` (EVR2/ER-08 влиты). Дата: 2026-11-02.
- Приоритет: P0. Источник: `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md`.
- Область: эффективный речевой путь фактчека, слои владельца, входной case record, граница Writer↔renderer.
- Исключения: поиск/provenance (`ASAP-FC-EVIDENCE-STYLE-02`), evidence-routing v3, UI-каталог, L1 (документ B), релиз 2.58.148 / ER-08-RC.

## 1. Какие каноны реально существуют (проверено по коду)

| Ключ реестра | Блок | Код | Маршрут | Факт |
|---|---|---|---|---|
| `prompts.factcheck_system_prompt` | `factcheck.base.single` | `factcheck_prompts.py:185-190`, база `:100-128`, CoVe `:170-175` | одиночный (legacy 10.21) + фолбэк двухвызовного | активен; `{max_symbols}`×1; **содержит** «торопливое письмо», запрет Markdown/списков/эмодзи, «сплошной текст», «2-4 предложения», «ОБЯЗАТЕЛЬНО дерни `dig_into_lore`» |
| `prompts.factcheck_analyst_system_prompt` | `factcheck.base.analyst` | `factcheck_prompts.py:308-313` + фазы `:334-360` | Stage-1 в `_check_claim_two_call` | активен; только JSON, стиля нет ✅ |
| `prompts.factcheck_verbalizer_system_prompt` | `factcheck.base.verbalizer` | `factcheck_prompts.py:433-447` (W1 base + `TYPOGRAPHY_BLOCK`) | Stage-2 + `_temporal_verbalize` | активен; текст 10.23 «Опирайся исключительно на поля JSON: claim, findings, verdict» + «Вынеси дерзкий вердикт» |
| `prompts.factcheck_critique_directive` | `factcheck.critique.directive` | `factcheck_prompts.py:484-534` | все три публичных маршрута | активен, гейт `resolve_critique_section` |

Каталог/UI: оба слота объявлены (`prompt_registry.py:889-902`, `param_catalog.py:622-629`, группа `prompts_factcheck`). «Вербализатора нет в UI» — фильтрация каталога в in-flight релизе, не архитектурный вопрос: параллельное меню редакторов не создаётся.

Требование владельца про `_points`/`_MAX_POINTS=4` **устарело по коду**: принудительный список 2–4 пунктов уже снят (`factcheck_renderer.py:411-414`); остались `_MAX_BOUND_PARTS = 8` и `_PART_TEXT_MAX_CHARS = 110` (`:132-136`).

## 2. Что фактически уходит в модель (четыре точки сборки, не одна)

| Шов | Сборка system | Вход | Режимный блок | Слои владельца |
|---|---|---|---|---|
| single `factcheck_service.py:1478-1534` | `resolve_prompt` + критика + `speech_owner_block` + `speech_style_hint` склейкой `\n\n` | `build_user_content` (сырьё + выдача поиска) | нет | `:1521-1526` |
| two-call `:1536-1646` | `compose_verbalizer_system(base, mode, "plain", character_block=…, style_directives=…)` | `stage2_payload(data)` | **есть** (`MODE_*`, `FORMAT_PLAIN_TEXT` для deep_research) | `:1589-1601` |
| temporal `:2224-2334` | `resolve_prompt` + критика + `speech_owner_block` + style склейкой | свой payload: `verdict/freshness/period/caveats/parts/claims/situation/fallback_note/limit_note` | нет | `:2307-2311` |
| short reply `factcheck_orchestrator.py:315-335` | инструкция + `speech_owner_block` | ситуация | нет | `:331` |

Следствия: (1) заявленный контракт «только `claim/findings/verdict`» **ложен** для temporal и short-reply; (2) `speech_owner_block` молча возвращает `""` при пропуске (`prompt_composer.py:864-914`, `except: pass`) — причина пропуска нигде не видна; (3) режимные блоки дают фактчеку запрет списков/заголовков (`prompt_style_blocks.py:191-196`) и запрет буллитов 4-м пунктом `ANTI_BOT_BLOCK` (`:28-35`), вшитым в базу канона через `STYLE_BLOCKS_SUFFIX` (`:61`) — это прямое противоречие адаптивной подаче владельца.

`speech_owner_block` = `<Speech_Base>` + компактный Core (`simplify_core_for_prompt`) + `<Expression_Settings>` (`:889-914`). Style Policy — отдельно (`:917-942`). Этого **недостаточно** для эквивалентности Direct: у Direct сборка идёт полным `PromptPlan` c `LAYER_ORDER` (`:62-67`) и манифестом причин по каждому слою.

## 3. Решение: одна точка сборки — существующий композер

Эталон уже есть: `DirectChatService._compose_speech_system` (`direct_chat_service.py:6719-6851`) собирает `PromptPlan` (core, identity, response_plan, expression, expression_examples, humor, samples, style_policy, scoped_requests, lessons, speech) → `compose_prompt` → `(system, manifest)`. Он же даёт `rendered/skip_reason/revision/source` по каждому слою (`prompt_composer.py:1395-1439` и далее) — это и есть требуемое «явное объяснение пропуска».

**Действие:** вынести тело метода в модульную функцию `compose_speech_system(...)` в `services/prompt_composer.py` (владелец сборки), `DirectChatService` — тонкий делегат (байт-паритет). Все три фактчек-маршрута вызывают её с `profile="speech_plain"`, `writer="factcheck_verbalizer"`, `channel="plain"`, `include_mode_block=False`, `extent_block=""`. Склейка `system + "\n\n" + owner_block` в `factcheck_service.py` **удаляется**: иначе Core/Expression попадут дважды.

Карта слоёв фактчек-публикации:

| Слой | Решение | Причина (попадает в манифест) |
|---|---|---|
| `core` | ВКЛ (компактный Core) | владелец задаёт личность; квот нет |
| `expression` | ВКЛ (`enabled`, GLOBAL/chat) | регистр мата/резкости — только владелец |
| `few_shot` = `<Expression_Examples mode=…>` | ВКЛ (существующий `mca_expression.build_expression_examples_refs`) | п.13 задания: примеры — часть owner-voice |
| `style_policy_hint` | ВКЛ | активные правила владельца |
| `channel_contract` | ВКЛ — секция «формат публикации» внутри канона (plain, без Markdown) | реальный канал = escape-HTML, разметка не рендерится |
| `identity` | ПРОПУСК `duplicate_of_persona` | `identity_text == character_block` (персона) — иначе двойник Core |
| `response_plan` | ПРОПУСК `no_l1_plan_in_genre` | план принадлежит Direct L1; у фактчека свой `response_mode` |
| `humor_craft` | ПРОПУСК (ось `humor_craft_enabled` OFF по умолчанию) причина `genre_argued_analysis` | юмор-приёмы поверх `<Speech_Base>` дублируют HUMOR_TEXT |
| `context_lessons` | ПРОПУСК `direct_turn_lessons_only` | уроки опыта Direct-хода |
| `mode_block` | ВЫКЛ (`include_mode_block=False`) | ломает длину и запрещает структуру |
| `channel_output` | встроен в канон (plain-текст) | — |

**Direct ≠ FactCheck:** отсутствуют 6 слоёв (identity, self_model_traits как отдельный слой, lessons, response_plan, humor_craft, samples). Наличие Core/Expression эквивалентности не даёт; эквивалентность заявляется только по реально доставленным слоям из манифеста.

Замена `STYLE_BLOCKS_SUFFIX` в каноне вербализатора: `ANTI_BOT_BLOCK` разложить на пункты (единый источник), собрать `ANTI_BOT_BLOCK` (байт-в-байт как сейчас) и `ANTI_BOT_BLOCK_NO_LISTS` (без п.4) — вариант без списков использует **только** фактчек-канон. `PREV_*`-слепки и `_BYTES`-пины не меняются.

## 4. Входной контракт case record

Сегодня (two-call, allowlist `system2_handoff.py:150-202`; `stage2_payload` убирает только `response_mode`/`cover_prompt`, `:56-66`): `claim`, `findings[{assertion,status(true|false|misleading|unverifiable),evidence,author,human_time}]`, `verdict`, мёртвый `tone_hint`, `response_mode`.
Temporal (`factcheck_service.py:2253-2290`): `verdict/freshness/period/caveats/parts[{text,factual_verdict,status_detail,gap_note,evidence_refs}]/claims[{claim_id,text,outcome,status,gap,sources}]/situation/fallback_note/limit_note`.

Из 8 предложенных владельцем полей **6 уже покрыты**, дублировать нельзя:

| Поле владельца | Реальность |
|---|---|
| `atomic_claims` | `findings[].assertion` |
| `what_is_supported` | `findings[].status == true` + `parts[].factual_verdict` |
| `source_refs` | НЕ в промпт: URL владеет renderer (`links ⊆ EvidenceMap`, `factcheck_renderer.py:251-266`). В промпт — только `claims[].sources` (счётчик, зона EVIDENCE-STYLE-02) |
| `attribution` | `findings[].author/human_time` + `EvidenceMap` роль `chat` |
| `uncertainties` | `caveats[]` (temporal) + статус `unverifiable` (two-call) |
| `reasoning_links` | работа Writer'а, не вход |

**Добавляется ровно два необязательных поля Аналитика** (та же JSON, тот же вызов — третьей стадии нет):
- `inference_gap` — что **не** следует из подтверждённых данных (подмена причинности/обобщение). Это ядро старого канона и единственное, чего в машине сегодня нет.
- `counterpoint` — сильнейшее честное контрпрочтение (для «признай, если база»).

Правила: отсутствует → ключ в payload не появляется (пустые поля запрещены); строка, прошедшая `contains_system_ids`; `counterpoint` не может противоречить `findings` (только формулировка вывода); `tone_hint` из payload **удаляется** (`system2_handoff.py:192-199`) — стилевой канал в машине не остаётся. Persisted-каноны Аналитика без новых полей валидны; парсер толерантен в обе стороны.

Границы: число запросов/провенанс источников — `ASAP-FC-EVIDENCE-STYLE-02`; доставка evidence, claim keys, `external_claims` — EVOL routing v3; здесь только семантика, нужная для аргумента Stage-2.

## 5. Граница Writer ↔ renderer (`factcheck_renderer.py`)

| Элемент | Решение | Обоснование |
|---|---|---|
| `_esc`/`_esc_attr`, escape всего тела (`:392-477`) | ОСТАВИТЬ | безопасность Telegram HTML |
| `_safe_links` (http/https, dedupe) + ссылки только из `EvidenceMap` прогона (`:174-181,251-266`) | ОСТАВИТЬ | нельзя выдумать/подменить источник |
| `split_entity_safe` + `send_chunked_reply` + plain-деградация сломанного чанка (`:534-566,571-591`) | ОСТАВИТЬ | предел 4096, безопасная доставка |
| Заголовок по enum вердикта (`:63-68,242-249`) | ОСТАВИТЬ | это проверенный вердикт, а не канцелярский титул; один короткий `<b>` |
| Технические заголовки/уведомления по `reason_code` (`:73-93,267-278`) | ОСТАВИТЬ | честность сбоя, без «данных недостаточно» |
| `verbalize_validated` (клише/form/numeric/metatext), `public_speech_guard`, `strip_phantom_tags`, `cleanup_llm_text` | ОСТАВИТЬ | детерминированные guard'ы, форму не диктуют |
| **`"По утверждениям:"` блок (`:421-474`)** | ИЗМЕНИТЬ: только fallback при пустом/вырожденном теле Writer'а | сейчас обязательно дублирует уже сказанное: текст части + `_trim(...,110)` + подпись + пробел + ссылки |
| `_trim` 110 символов на утверждении (`:282-286,443`) | УБРАТЬ для утверждений (оставить только для `gap_note`, лимит 120) | обрезка `…` калечит авторскую формулировку |
| `_MAX_BOUND_PARTS = 8` + «…и ещё N: не показаны» (`:463-468`) | УБРАТЬ в fallback-режиме | молчаливая/служебная потеря тезисов при том, что данных о покрытии достаточно |
| **Секция «Критический разнос» (`split_critique_section:184-208`, блок `:417-420`, `FACTCHECK_CRITIQUE_HEADING`)** | УБРАТЬ как формат | п.11 задания: без шаблонной секции. Директива (`factcheck_prompts.py:484`) переносится в текст канона, а `critique_policy_for_findings/for_verdict` решает, **включать ли абзац в промпт** — гейт остаётся детерминированным, но перестаёт резать готовый текст |
| `"Источники:"` с ролью источника (`:365-390,470-474`) | ОСТАВИТЬ | п.37/§4: подтверждённые ссылки обязательны; дублей с телом нет (модель URL не получает) |
| `_VERDICT_HEADLINE`-подмена вердикта, автодобавление ссылок из `presentation.links` вне прогона | ЗАПРЕЩЕНО | п.7: пустые/ошибочные источники не превращаются во вставленные ссылки |

Контракт подачи для модели (в каноне, а не в renderer): структура — только plain-текст: пустые строки между абзацами, короткие отдельные строки-подписи, при необходимости `- ` перечисления; **никакого Markdown/HTML/таблиц/нумерации-как-шаблона**; заголовки не обязательны и не имеют фиксированных имён; одно и то же содержание не повторяется в вердикте, теле и списке; URL/Source-ID не выдумывать и не печатать. `{max_symbols}` — потолок генерации (разрешённый лимит), не целевая длина.

## 6. Инварианты
1. Один `compose_prompt` на маршрут; Core/Expression в payload ровно один раз.
2. Analyst не получает ни стиля, ни Core, ни профиля; Writer не получает тулов и не ищет.
3. Ни один URL/цифра не появляется вне `EvidenceMap`/валидированных данных.
4. Отсутствующие данные не превращаются в уверенность; сбой Writer'а — честный текст с причиной.
5. Пропуск слоя всегда назван кодом причины в манифесте (`rendered=false` + `skip_reason`).
6. `SMART_VERBALIZER_MODES_ENABLED=OFF` → предыдущая заводская редакция вербализатора + без mode-блока.

## 7. Отвергнутые варианты
1. **Оставить `speech_owner_block` и дописать в него few-shot/Style** — тихие пропуски, нет манифеста, прямой путь к двойной инъекции в `compose_verbalizer_system`.
2. **Свой новый сборщик фактчек-промпта** — второй владелец речи; запрещено §5 задания и ломает единый Core.
3. **Держать `MODE_CASUAL/SERIOUS` и добавить «списки разрешены»** — взаимоисключающие инструкции в одном prompt; поведение станет лотереей.
4. **Правка `ANTI_BOT_BLOCK`/`MODE_*` глобально** — меняет Direct и ломает байт-пины; поэтому только аддитивный вариант `_NO_LISTS` для фактчека.
5. **Отдавать Writer'у URL/ID источников** — риск выдуманных ссылок и утечки служебных меток.
6. **Третий LLM-вызов «аргументатор»** — запрещено §8.4 задания.
7. **Оставить «По утверждениям» как есть «для аудита»** — аудит уже есть в `_emit_claim_coverage` (`factcheck_orchestrator.py:1131-1139`); в Telegram это повтор.
8. **Переписать `factcheck_renderer` целиком** — ломает доставку/escape/деградацию; правится ровно три места.

## 8. Приёмка, параллельность, риск

Проверки (обязательные, на реальных сборках):
1. Короткий факт → тело без принудительного списка; блока «По утверждениям» в публикации нет.
2. Сложная тема → авторские абзацы/строки-подписи, `- ` допустимы, Markdown в тексте отсутствует.
3. Частичный вердикт: подтверждение/ошибка/неопределённость не сливаются в красивый финал; `inference_gap` из JSON Аналитика виден в аргументе.
4. Первоисточник не найден → «не удалось подтвердить», не «ложь».
5. `profanity off/occasional/frequent` при одинаковом входе: `<Expression_Settings>` присутствует один раз; `off` без мата (детерминированная проверка), остальные не сваливаются в стерильный заводской голос.
6. Style Policy и `<Expression_Examples>` присутствуют в эффективном system либо имеют `skip_reason` в манифесте.
7. На всех трёх маршрутах `system.count("<Expression_Settings>") == 1` и одинаковые байты owner-блока.
8. Сбой Writer'а → честный текст с причиной, без имитации разбора.
9. `EvidenceMap` доходит до Writer'а и не теряется renderer'ом: `links ⊆ run_urls`, нет выдуманных URL.
10. Эффективные байты снимаются `tools/er65_prompt_segment_snapshot.py` (offline, `--check`) **и** `prompt_composer.provider_calls`/`record_provider_call` (`prompt_composer.py:2078-2133`) для живого прогона; ограничение инструмента «PG не читается» не выдаётся за боевые байты.
11. Одиночный и двухвызовный/временной маршруты дают один и тот же речевой контракт (сравнение сегментов снимка).

Параллельная безопасность: `SERIALIZE` по `prompt_registry.py`, `prompt_migrations.py`, `factcheck_service.py` (в полёте 2.58.148 + ER-08-RC). Файлы A: `factcheck_prompts.py`, `factcheck_service.py`, `prompt_style_blocks.py`, `prompt_composer.py`, `system2_handoff.py`, `factcheck_renderer.py`, тесты. Миграция: новая заводская ревизия обоих блоков + ступень `prompt_migrations` + цель откатa (ADR-1013-3); пользовательские PG-редакции не перезаписываются. Риск R2 (речевой контракт + публикация; откат — возврат ревизии).
