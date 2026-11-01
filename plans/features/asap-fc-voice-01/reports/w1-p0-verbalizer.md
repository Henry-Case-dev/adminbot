# W1 / P0 — голос вербализатора фактчека (ASAP-FC-VOICE-01, часть A)

- Ветка: `feat/fc-voice-p0`, база `53f1b229`.
- Источники: `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md` (§1-4 владельца),
  `plans/features/asap-fc-voice-01/arch/verbalizer-contract.md` (§3-6 контракта).
- Прод-preflight (2.58.148, `6645ae8d`): `flags.factcheck_pipeline_v2 = true`,
  `flags.factcheck_wide_context = true`, `flags.factcheck_suitability_gate = false`,
  `SYSTEM2_FACTCHECK_ENABLED`/`MCA_TEMPORAL_FACTCHECK_ENABLED` — код-дефолты
  (true). Активный маршрут — v2-envelope.
- Тесты среза: `tests/test_asap_fc_voice01_verbalizer.py` (38 проверок) + обновлённые
  существующие контрактные наборы (см. §6).

## 1. Что сделано по пунктам контракта

### 1.1 Ревизия канона голоса (пункт 1 задания, §1-2 владельца)

`services/factcheck_prompts.py`: `prompts.factcheck_verbalizer_system_prompt`
переписан. Восстановлена манера исторического `FACTCHECK_SYSTEM_PROMPT`
(`995cf83a588b`, раздел «СУТЬ АНАЛИЗА / СУДЕЙСТВО СРАЧЕЙ»): речь от лица
участника спора, прямая полемика с автором, поиск настоящего логического
разрыва (подмена причинности, обобщение, выборочные данные), развитие
контраргументов, живые аналогии, позиция по имеющимся доказательствам,
короткий ответ на простой тезис и подробный на сложный.

Не перенесено (запрещено владельцем и контрактом): обход safety, безусловный
мат, запрет Markdown/списков/заголовков, обязательная небрежная орфография,
«уже проверял без инструмента», приоритет «своей логики» над первоисточником,
требование звать поиск на этапе Writer.

Решения по адаптации (нужны для ревью):

- **Язык канона — русский**, как у всех соседних блоков одного payload
  (`АНТИ-БОТ`, `АСИММЕТРИЯ`, `ТИПОГРАФИКА`, `<bot_knowledge>`). Смысл draft'а
  владельца сохранён поблочно: ROLE → `СИСТЕМНАЯ РОЛЬ`, GROUNDING AND INTEGRITY
  → `ОПОРА И ЧЕСТНОСТЬ`, HOW TO ARGUE → `КАК СПОРИТЬ`, OWNER-CONTROLLED VOICE →
  `ГОЛОС ВЛАДЕЛЬЦА`, ADAPTIVE PRESENTATION → `ПОДАЧА ПО СМЫСЛУ, БЕЗ ШАБЛОНА`,
  CASE INPUT → `ВХОДНОЙ РАЗБОР`, OUTPUT → `ВЫХОД`. Требования не ослаблены.
- **`{max_symbols}` — единственный placeholder** (`.replace`, как и раньше);
  подпись «потолок генерации, а не целевая длина».
- **Входной контракт назван честно**: `claim`, `findings` (assertion/status/
  evidence/author/human_time), `verdict`, `inference_gap`, `counterpoint`,
  оговорки, части со статусами, свежесть. Старое «опирайся исключительно на
  claim/findings/verdict» было ложным для временного маршрута и снято.
- **Канал**: обычное сообщение Telegram с экранированием; Markdown/HTML/таблицы
  запрещены, подзаголовок — отдельная короткая строка, перечисление — `- `.
- **Стилевой суффикс** — новый вариант `STYLE_BLOCKS_SUFFIX_NO_LISTS`
  (`services/prompt_style_blocks.py`): тот же блок A без пункта «Списки с
  буллитами…». Пункты блока вынесены в `ANTI_BOT_ITEMS`, `ANTI_BOT_BLOCK`
  собирается из них **байт-в-байт** (печать `style.anti_bot` `52dced8da19b` не
  менялась), вариант без списков получается тем же материалом.
- `TYPOGRAPHY_BLOCK` в каноне сохранён (типографика — не шаблон подачи).

Идентичность ревизии:

| Блок | Метка | Печать (sha12 байтов) | Прежние байты (откат) |
|---|---|---|---|
| `factcheck.base.verbalizer` | `factcheck-voice-historic-01` | `45361c23221c` | `PREV_FACTCHECK_VERBALIZER_VOICE01` = `42442333d77d` (= прод 2.58.148) |
| `factcheck.base.analyst` | `factcheck-analyst-voice01-semantics` | `ed4c7a642804` | `PREV_FACTCHECK_ANALYST_VOICE01` = `806d6cc6af77` (= прод 2.58.148) |
| `temporal.analyst` | `temporal-analyst-voice01-semantics` | `506f9787af4e` | `temporal-analyst-fc08` / `cd212371aa22` |
| Набор фабрики | — | **`FACTORY_SET_SHA256_12 = 033670411c73`** (было `f84baaf69559`) | — |

Лестница: `PROMPT_MIGRATIONS` получил ступени
`PREV_FACTCHECK_VERBALIZER_VOICE01 → активный` и
`PREV_FACTCHECK_ANALYST_VOICE01 → активный` **первыми** (старые ступени W1 /
ER-54 сохранены), `ROLLBACK_MIGRATIONS` — обратные ступени. Пользовательские
PG-редакции не перезаписываются: ступень узнаёт только точное совпадение байт.
Канон аналитика расширен детерминированной заменой двух якорей
(`_ANALYST_SCHEMA_ANCHOR`, `_ANALYST_RULES_ANCHOR`); якоря проверяются тестом,
поэтому тихая потеря полей при будущей правке базы невозможна.

### 1.2 Одна точка сборки речи (пункт 2 задания, §3 контракта)

- Тело боевого метода Direct вынесено в
  `services/prompt_composer.py::compose_speech_system` (`prompt_composer.py:965`);
  `DirectChatService._compose_speech_system` (`direct_chat_service.py:6719`) —
  тонкий делегат, байт-паритет проверен тестом (`manifest_id` совпадает).
- В композер добавлены три аддитивных элемента (default → прежнее поведение):
  `PromptPlan.humor_skip_reason`, `PromptPlan.include_speech_base`,
  `compose_speech_system(plan_skip=…)`; закрытый набор `SKIP_REASONS` расширен
  кодами `no_l1_plan_in_genre`, `duplicate_of_persona`,
  `genre_argued_analysis` (+ человеческие подписи).
- Все четыре точки сборки фактчека сведены к одному владельцу через
  `factcheck_service._compose_genre_speech` (`factcheck_service.py:138`):

| Точка | Где | Writer | Как унифицировано |
|---|---|---|---|
| одиночный (legacy/fallback) 10.21 | `factcheck_service.py:1536` | `factcheck_single` | канон `prompts.factcheck_system_prompt` + директива критики → `compose_speech_system` |
| двухвызовный Stage-2 | `factcheck_service.py:1604` | `factcheck_verbalizer` | канон вербализатора + директива; `compose_verbalizer_system(character_block=…)` удалён |
| временной вербализатор (v2-envelope) | `factcheck_service.py:2334` | `factcheck_temporal_verbalizer` | тот же ключ вербализатора + директива |
| короткая персона-реплика | `factcheck_orchestrator.py:339` | `factcheck_short_reply` | инструкция + те же слои владельца |

Один набор параметров на всех: `profile="speech_plain"`, `channel="plain"`,
`html_safe=False`, `include_mode_block=False`, `identity_skipped=
"duplicate_of_persona"`, `plan_skip="no_l1_plan_in_genre"`,
`humor_skip="genre_argued_analysis"`, `include_speech_base=True`.

Что доказывает отсутствие двойной инъекции: `speech_owner_block` в
`services/factcheck_service.py` больше не импортируется и не вызывается
(структурная проверка тестом), `<Expression_Settings>` и Core встречаются в
эффективном system ровно один раз на каждом из четырёх маршрутов.

Слои, которые фактчек получает (из манифеста): `channel_contract` (канон +
`speech_base`), `core`, `expression` (+ финальный контракт Expression
последним), `few_shot` (`<Expression_Examples>`), `style_policy_hint`.
Пропуски названы кодами: `identity → duplicate_of_persona`,
`response_plan → no_l1_plan_in_genre`, `humor_craft → genre_argued_analysis`,
`channel_output → channel_output_not_required`, `mode_block → не подключён`.
Эквивалентности Direct и фактчека по этим слоям **не заявляется**: у Direct
есть identity/lessons/plan/humor/samples, у жанра их нет.

### 1.3 Снятие противоречащих инструкций (пункт 3 задания)

- `ANTI_BOT_BLOCK` п.4 («Списки с буллитами… запрещены») больше не попадает в
  канон вербализатора (вариант `_NO_LISTS`); общие каноны и их байт-пины не
  тронуты.
- Режимный блок (`MODE_CASUAL`: «запрещены заголовки, списки…») в публичном
  тракте фактчека больше не подключается (`include_mode_block=False`) — он
  задавал чужую длину и запрещал структуру.
- В каноне нет собственного правила про мат (проверяется регуляркой в тесте):
  регистр задаёт только `<Expression_Settings>`.
- В машинные стадии (Аналитик, temporal-аналитик, L1-планер) стиль не
  переносится — проверяется тестом.

### 1.4 Поля Аналитика (пункт 4 задания, §4 контракта)

Та же JSON-стадия, третьего LLM-вызова нет, обратная совместимость:

- `services/temporal_factcheck.py`: `TEMPORAL_ANALYST_SYSTEM` (реальная стадия
  v2-envelope) — схема + правила (11)/(12); `TemporalVerdict` получил
  `inference_gap`/`counterpoint`; `verdict_from_payload` читает их через
  `_optional_semantic_text` (пустое/нестроковое/с системными ID → поля нет);
  `apply_validator` переносит поля через перепроверку.
- `services/system2_handoff.py::parse_factcheck_analysis`: те же два поля
  принимаются в System2, **`tone_hint` больше не принимается** (мёртвый
  стилевой канал из payload убран).
- `services/factcheck_service.py::_temporal_verbalize`: ключи добавляются в
  payload Writer'а только при непустом значении.
- `stage2_payload` доносит поля до Stage-2 автоматически (служебный
  `response_mode` по-прежнему вырезается).

### 1.5 Граница Writer ↔ renderer (пункт 5 задания, §5 контракта)

`services/factcheck_renderer.py`:

| Было | Стало |
|---|---|
| «По утверждениям:» выводился всегда | только FALLBACK при пустом/вырожденном теле Writer'а |
| `_trim(text)` = 110 символов на каждом тезисе | обрезка тезисов убрана (`_trim(text, None)`); 120 символов остались только для служебного `gap_note` |
| `_MAX_BOUND_PARTS = 8` + «…и ещё N: не показаны» | предел снят; в fallback публикуются все проверенные тезисы, молчаливой потери нет |
| секция «Критический разнос» отдельным `<b>`-блоком (`split_critique_section` в `_serialize`) | формат снят: текст проходит как написан; при `allow_critique=False` (настройка OFF) прежний формат распознаётся и вычищается |
| вердикт по enum, ссылки только из `EvidenceMap` прогона, `split_entity_safe` + `send_chunked_reply` | **без изменений** |

Данные покрытия не потеряны: `_emit_claim_coverage` (аналитика) не менялся,
а fallback-публикация сохраняет все части с их конкретной причиной пробела.

### 1.6 Директива критики (реальный механизм)

Изменён не только канон:

- `factcheck_prompts.build_critique_section_block` больше не требует «раздела»
  и фиксированного заголовка: директива владельца (`prompts.factcheck_critique_directive`,
  PG-ключ, дословный текст) остаётся дословно, но действует внутри
  рассуждения. Смысловые границы (критиковать только установленную ошибку,
  без новых фактов/ссылок, разбирать высказывание, а не человека) сохранены.
- `FACTCHECK_CRITIQUE_HEADING` остался как маркер узнавания прежнего формата
  (нужен `resolve_critique_section` OFF и `_apply_critique_setting`), новых
  требований Writer'у не задаёт (docstring обновлён).
- `resolve_critique_section` / `flags.factcheck_critique_section_enabled`:
  семантика прежняя (chat → global, default ON), действует как гейт промпта;
  политика `critique_policy_for_findings/for_verdict` остаётся
  детерминированной серверной проверкой («разгрома без установленной ошибки
  нет»).
- Байты самой директивы и её печать `cfcd9009df17` **не менялись** — это
  редактируемый текст владельца, а не формат.

## 2. Preflight alignment: какой ключ/константа чем управляет

| Требование | Где реально исполняется | Почему здесь |
|---|---|---|
| Голос публичной речи | `prompts.factcheck_verbalizer_system_prompt` → `factcheck_service.py:1585` (System2) и `:2250` (v2-envelope, `_temporal_verbalize`) | единственный ключ, общий для обоих активных маршрутов |
| Смысловые поля аналитика (v2) | `temporal_factcheck.TEMPORAL_ANALYST_SYSTEM` (код-константа стадии envelope) + `TemporalVerdict` + payload `_temporal_verbalize` | на v2 стадию-1 вызывает не PG-ключ, а эта константа; без правки здесь поля не появились бы в проде |
| Смысловые поля аналитика (System2) | `prompts.factcheck_analyst_system_prompt` → `factcheck_service.py:1555` + `parse_factcheck_analysis` | fallback-маршрут двухвызовной схемы |
| Одиночный (legacy/fallback) | `prompts.factcheck_system_prompt` → `factcheck_service.py:1490` | включается только при kill-switch или невалидном JSON стадии-1 |
| Директива критики | `prompts.factcheck_critique_directive` + `resolve_critique_section` → `_critique_section_block` на всех трёх публичных маршрутах | отдельный ключ, не часть речевого канона |
| Слои владельца (Core/Expression/Style/примеры) | `prompt_composer.compose_speech_system` | одна точка сборки; Direct делегирует туда же |
| Публикация | `factcheck_renderer` | достижим только внутри v2 (`factcheck_orchestrator.py:1115`) |

Честные границы этого среза:

1. **Renderer работает только на v2.** Активный прод-маршрут — v2
   (`flags.factcheck_pipeline_v2 = true`), поэтому изменения публикации
   действуют в бою; legacy-сервис renderer не импортирует.
2. **Одиночный (legacy) канон `prompts.factcheck_system_prompt` не переписан.**
   Это отдельный ключ со своим байт-пином (`plans/docs/canon/architecture.md`,
   Section 72) и своей историей; его жанровый текст содержит прежние
   формулировки подачи. Срез унифицирует **слои владельца** на этом маршруте
   (Core/Expression/Style/примеры), но не переписывает его жанровый текст.
   Приёмка §8.11 контракта («один и тот же речевой контракт на одиночном и
   двухвызовном») выполнена в части owner-слоёв; полное совпадение жанровых
   текстов требует отдельной правки этого ключа + эталона + пина.
3. **`flags.factcheck_suitability_gate = false`**: часть сообщений вообще не
   доходит до речевого канона фактчека (нет тезиса / путь уточнения). Такие
   ответы идут через короткую персона-реплику или готовые фразы — смена голоса
   их не затрагивает.
4. **Публикация потеряла построчную привязку ссылки к каждому тезису** в
   непустом ответе Writer'а: по §5 контракта список стал fallback'ом, ссылки
   остаются в «Источники:» с ролью источника. Это осознанный размен против
   троекратного дублирования; данные покрытия живут в аналитике
   (`_emit_claim_coverage`) и в fallback-публикации.
5. **Серверное вырезание «разноса» из готового текста снято** (кроме случая
   настройки OFF, где прежний формат узнаётся и удаляется). Гарантия «нет
   выдуманного опровержения» теперь обеспечивается промптом (директивы нет при
   `supported`/`insufficient_evidence`/техсбое) и детерминированной политикой
   `critique_policy_for_*`, а не постобработкой текста.

## 3. Renderer: поведение до/после

| Вход | До | После |
|---|---|---|
| короткое тело «Да, подтверждается.» | тело + список «По утверждениям» | тело как есть, без списка и заголовков |
| сложное тело с подзаголовком и `- ` пунктами | тело + принудительный список | тело байт-в-байт (с экранированием), авторская структура сохранена |
| пустое/вырожденное тело + части прогона | список (≤8, тезисы обрезаны до 110) | полный список всех частей, формулировки целиком, причины пробела конкретные |
| текст с legacy-заголовком «Критический разнос» | отдельный `<b>`-блок | строка остаётся в тексте автора; при `allow_critique=False` — вычищается |
| `<b>`, `&`, `#` в авторском тексте | экранирование | экранирование (без изменений) |
| длинный ответ | чанки `split_entity_safe` + `send_chunked_reply` | без изменений (проверено на списке из 59 пунктов) |

## 4. Красное → зелёное (доказательство, что тесты ловят регресс)

Скрипт `check_red.py` (scratch, вне репозитория) применяет утверждения нового
набора к **выложенному** коду (`git show HEAD:…`, байты без перекодирования) и
ожидает падения. Результат — 8/8 «красных» на старом коде:

| Проверка | На выложенном коде |
|---|---|
| в каноне нет запрета списков и ложного входного контракта | RED (`Списки с буллитами…` и «Опирайся исключительно…» присутствуют) |
| в каноне есть прямая полемика | RED (нет «Вступай в спор») |
| у аналитика есть `inference_gap`/`counterpoint` | RED (нет) |
| в сервисе нет ручной склейки owner-блока | RED (`speech_owner_block(` встречается 3×) |
| в оркестраторе нет второй сборки owner-блока | RED (`speech_owner_block(` есть) |
| renderer не выводит обязательный «По утверждениям» | RED (выводит) |
| renderer не обрезает тезис до 110 символов | RED (обрезает) |
| renderer публикует все тезисы без «…и ещё N» | RED (предел 8) |

На текущем коде те же проверки зелёные (см. §5), то есть RED→GREEN получен на
одном и том же наборе утверждений.

## 5. Тесты и счётчики

Новый контрактный набор: `tests/test_asap_fc_voice01_verbalizer.py` —
**38 проверок, все зелёные** (`pytest -q`):

- ревизия канона: печать/метка/`FACTORY_SET`, откат = байты прода
  (`42442333d77d`), ступени миграции и обратные ступени, единственный
  placeholder, ревизия аналитика и temporal-аналитика;
- содержание канона: голос жанра, отсутствие навязанного формата, отсутствие
  собственного правила про мат, директива критики без раздела;
- единая точка сборки на четырёх маршрутах: ровно один Core и один
  `<Expression_Settings>`, Expression-контракт последним, `<Speech_Base>`
  сохранён, манифест называет каждый пропуск, `modes=OFF` отдаёт прежнюю
  заводскую редакцию;
- поля аналитика: приём/совместимость/изоляция системных ID/`tone_hint` не
  принимается/доходят до payload Writer'а/переживают validator;
- renderer: короткий тезис остаётся коротким, сложный сохраняет подзаголовки и
  `- `, экранирование, отсутствие обрезки, fallback со всеми тезисами,
  вердикт и валидированные ссылки, plain-канал, чанкинг длинного списка;
- Expression как единственный регулятор: off/occasional/frequent → ровно один
  слой и соответствующий финальный контракт;
- Direct: делегат байт-в-байт равен модульной функции, owner-слои идентичны,
  стиль не утёк в Аналитика и L1.

Обновлённые существующие наборы (счётчики после правки):

| Файл | Тестов | Что изменено |
|---|---|---|
| `tests/test_factcheck_renderer_cfg06.py` | 36 | «По утверждениям» → fallback; шов owner-слоёв = `compose_speech_system` |
| `tests/test_evol_factcheck_critical.py` | 11 | формат раздела снят, директива и гейт политики сохранены |
| `tests/test_evol_fc_evidence_style.py` | 24 | конкретные причины пробела проверяются в fallback-публикации |
| `tests/test_factcheck_fc_r1_fix.py` | 22 | replay без обязательного списка, owner-слои через единую точку |
| `tests/test_factcheck_p0_fc.py` | 33 | FC-07: части видны в fallback, заголовок не скрывает частичный вердикт |
| `tests/test_prompt_migrations.py` | 40 | новые ступени аналитика/вербализатора |
| `tests/test_evol_w17_small_canon_reqs.py` | 15 | ER-54 сохранён, добавлена ступень 2.58.148 |
| `tests/test_evol018_prompt_audit.py` | 10 | печати целы (зелёный) |
| `tests/test_asap_w1_semantics.py` | 21 | жанровые маркеры нового канона, ступени W1+voice01 |
| `tests/test_cfg07_guard_07d5.py` | 41 | guard-контракт через единую точку |
| `tests/test_factcheck_orchestrator_cfg06.py` | 16 | персона-реплика через единую точку |
| `tests/test_factcheck_w7_acceptance_cfg06.py` | 8 | то же |
| `tests/test_prompts_round1024.py` | 21 | у фактчека нет режимного блока (и на сбойном пути) |
| `tests/test_verbilizer_response_modes_round1023.py` | 72 | `TestFactcheckTwoCallMode::test_casual_mode_selected` переписан |
| `tests/test_factcheck_deep_context_round1023.py` | 53 | обратная ступень аналитика |
| `tests/test_expression_isolation_followup.py` | 4 | пин `FACTORY_SET` → `033670411c73` |
| `tests/test_p0_prompts_core.py` | 9 | то же |
| `tests/test_er65_sent_segment_snapshot.py` | 17 | снимок перегенерирован (`--write`), `--check` → OK |

Снимок сегментов: `plans/features/evol/evidence/er65/sent-segments.{json,md}`
перегенерированы штатным инструментом
(`python tools/er65_prompt_segment_snapshot.py --write`, затем `--check` → OK,
stages=27 segments=58). В снимке видно, что `factcheck.stage2_verbalizer` и
`factcheck.single` теперь собираются слоями
`channel_contract → core → speech_base → expression` (было: канон + режимный
блок + склейка owner-блока).

Фоновые прогоны, которые остаются красными: пакет `test_direct_fallback_recompose_asap32`
(5), `test_hotfix_round1025_logging`, `test_history_cli`, `test_chat_keys`,
`test_verbilizer_response_modes_round1023::test_summary_kill_switch_off_prev_narrator`,
`test_mca08_style_form`, `test_mca17a_observability_core_round1027`,
`test_factcheck_post_release_w1::TestAggregatorFailureTaxonomy` (2),
`test_samples_fewshot` (2), `test_asap2_clar_contract` (2),
`test_asap5_paradigms_diagnostics::test_bootstrap_cooldown_bypass_then_cap`,
`test_cfg02c_image_isolation::TestSharedCeilingHonesty::test_usage_breakdown_separates_user_and_cover` —
все воспроизводятся на базе `53f1b229` (общий корень — `_post_fallback(sent=…)`
в `llm_client` и флаки, зависящие от порядка/времени), к этому срезу не
относятся.

Полный набор `tests/` (порядок фиксирован, `-p no:randomly`):

| Дерево | failed | passed | errors |
|---|---|---|---|
| база `53f1b229` | 60 | 17408 | 23 |
| этот срез (`f7319638`) | 61 | 17445 | 23 |

Разница наборов: в срезе добавлено 38 новых проверок; «лишние» падения
относятся к трём файлам, каждый из которых проверен отдельно:
`test_asap5_paradigms_diagnostics` и `test_cfg02c_image_isolation` падают и на
базе при том же изолированном наборе, а
`test_mca09_intents_block_e_round1040::test_handle_initiative_sent_single_transport_chunks`
— плавающий: на базе в паре с `test_factcheck_orchestrator_cfg06` падает 2 из 6
прогонов, в срезе — 1 из 5. Это флаки общих синглтонов (`mi.get_service`), не
регресс среза; отдельно: `test_factcheck_fc_r1_fix` на базе падал в полном
прогоне, а в срезе зелёный (после добавления изоляции hot-кеша).

Отдельно отмечу найденный при этом дефект тестовой изоляции: публичная
Writer-фаза фактчека теперь реально резолвит оси (Core/Expression/Style) и
заполняет процессный hot-слой. Без сброса это протекало в следующие файлы
(каскад релевантности поиска падал на порядке файлов). Добавлена autouse-фикстура
сброса hot-кеша в `tests/test_evol_fc_evidence_style.py` и в новом наборе.

## 6. Что остаётся Reviewer'у (22 сценария владельца)

| # | Сценарий | Статус в этом срезе |
|---|---|---|
| 1 | официальная статистика не превращается в отрицание | **не доказывается здесь**: нужен прогон модели (P1/фикстура A) |
| 2 | реальный логический скачок разобран конкретно | **частично**: `inference_gap` доезжает до Writer'а (тест), качество разбора — за моделью |
| 3 | нет первоисточника → «не удалось подтвердить» | **доказуемо на уровне канона** (маркер есть) + сценарии `test_evol_fc_evidence_style` |
| 4 | `EvidenceMap` дошёл до Writer'а и пережил renderer | **да** (существующие + наши тесты) |
| 5 | одно- и двухстадийный маршруты не дают несовместимых настроек | **да** для owner-слоёв; жанровый текст одиночного канона — отдельный ключ (см. §2 п.2) |
| 6 | при сбое Writer'а честные fallback и причина | **да** (fallback-публикация + технические заголовки) |
| 7 | пустые/ошибочные источники не вставляются | **да** (ссылки только из `EvidenceMap` прогона) |
| 8 | `prompt_registry` показывает обе стадии и историю | **да** (печати/метки/ступени) |
| 9 | короткий факт → короткий ответ без 4 пунктов | **да** (renderer-тест на реальном поведении) |
| 10 | сложная тема → структура по смыслу | **да** (renderer пропускает авторскую структуру; выбор — за моделью) |
| 11 | резкий исторический эталон без шаблонного раздела | **да** на уровне канона/формата; живой текст — P1 |
| 12 | profanity off/occasional/frequent | **да**: effective-слой и финальный контракт по режиму |
| 13 | Style Policy и примеры применяются либо назван пропуск | **да** (слои в манифесте) |
| 14 | нет тройного повтора тезиса | **да** (список стал fallback'ом) |
| 15 | произвольные абзацы + безопасная отправка | **да** (экранирование, чанкинг, plain-канал) |
| 16 | сложный частичный вердикт не сливается | **частично**: заголовок и fallback различают части; текстовый синтез — за моделью |
| 17-21 | общесистемный L1 (Direct/Initiative/Summary) | **вне среза** — часть B (`arch/l1-decision-profile-contract.md`) |
| 22 | тестируются фактические собранные промпты и провенанс | **да** (эффективный system + манифест + снимок сегментов) |

Фикстуры A/B/C владельца в репозитории отсутствуют; фактическая репродукция
исторического спора (B) требует отдельного набора входных данных.

## 7. Инциденты и замечания

- В ходе работы дважды использован `git checkout --` на **собственных**
  правках двух файлов тестов после порчи кодировки при массовой замене
  (`tests/test_expression_isolation_followup.py`,
  `tests/test_p0_prompts_core.py`). Чужие изменения не затрагивались: оба файла
  были изменены только этим срезом, работа переписана и повторена.
- В рабочем дереве остаются изменёнными файлы чужого лейна
  (`plans/features/evol/audit/evidence/*`), они в коммит не включены.
- `services/direct_l1.py` и `web/**` не тронуты (как требует задание).
