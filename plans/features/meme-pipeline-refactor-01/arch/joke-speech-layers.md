# Этап прикола на едином речевом композере (Architect, 03.11.2026)

Основание: `plans/owner_inputs/2026-11-03-meme-joke-speech-layers.md` (дословно; intake 936340f4). Дополняет `arch/integration-decisions.md` §1 (этап B) и §5 (диагностика); §2–§4, §6–§10 не меняются.

## 1. Точка сборки этапа B (заморожено)

`services/meme_initiative.py:1617 _default_joke` собирает system через единственный владелец речи `prompt_composer.py:965 compose_speech_system` — модульную функцию (`DirectChatService._compose_speech_system`, `direct_chat_service.py:6901`, тонкий делегат в неё; инстанс сервиса мему не нужен).

```python
system, manifest = await pc.compose_speech_system(
    chat_id=chat_id, writer="meme_joke", run_id=jid, channel="plain", html_safe=False,
    base_prompt=joke_instruction(effective_joke_text, budget.joke_budget),   # ЗАДАНИЕ
    base_source=<provenance effective_meme_prompt>, include_mode_block=False,
    profile=pc.PROFILE_SPEECH_PLAIN, gates=await pc.resolve_gates(chat_id),
    include_speech_base=True, extent_block="", plan_skip="no_l1_plan_in_genre",
    response_plan=<advice: .comic_strategy/.extent/.structure/.tone>,         # только совет юмора
    identity_text=<блок bot_persona>, identity_source="chat",
    identity_skipped=("" if persona_enabled else "persona_disabled"),
    style_skip="style_requests_absent", lessons_skip="lessons_absent",
    speech_skip="speech_absent", context_text=summary, user_parts=(summary,))
# messages = [{"role":"system","content":system},{"role":"user","content":summary}]
```

- Задание, не личность: `prompts.meme_joke` (`:57`; чат→глобал→заводской, `:588`) + `JOKE_LENGTH_DIRECTIVE` (`:74`) идут слоем `channel_contract` (`prompt_composer.py:1555-1562`) первым; речевые слои дописываются после и не вытесняются (аддитивного бюджета инструкций нет, `:1530-1532`) — правка промпта в админке не может отключить Core/Expression/Humor, они из резолверов.
- Выжимка аналитическая: только user-часть (как сейчас `:1631`); этапы A (`:1390-1414`) и C (`:1449`) композер не вызывают — инвариант: вне `_default_joke` ноль обращений.
- `include_mode_block=False` (режимные блоки — часть диалогового хода); `plan_skip="no_l1_plan_in_genre"` — код из закрытого `SKIP_REASONS:103`: плана ответа нет честно, но `.comic_strategy` доходит до юмора (§4).
- `base_source`: `chat→chat`, `global→global`, `factory|registry|explicit_override→default` (значения `SOURCES:77`, новых не вводим).

## 2. Слои (только действующие оси владельца, новых осей нет)

| Слой | Источник | Условие |
|---|---|---|
| `channel_contract` | `prompts.meme_joke` + J-директива | всегда |
| `core` | `character.core` (чат→глобал), редакция `prompt_registry.core_selection` | ось `character_core_enabled` |
| `identity` (+ SelfModel внутри) | `bot_persona` (персона/черты/кадр, `flags.persona_enabled` чата) | `persona_enabled` |
| `expression` («Речь и характер») | `resolve_expression_settings(chat_id)` | режим выражения |
| `speech_base` | `speech_base_block()` = базовая речь + `mca_expression.HUMOR_TEXT` | `include_speech_base=True` |
| `humor_craft` | `mca_humor_craft.resolve_ref` (один приём) | ось `humor_craft_enabled` + `humor.craft` |
| `few_shot`, `style_policy_hint` | библиотека примеров / `resolve_style_policy_ref` | соответствующие оси |
| `context_lessons`, `response_plan` | — | пропуск: `lessons_absent` / `no_l1_plan_in_genre` |

Гейты — `resolve_gates(chat_id)` (`:671`), те же чатовые оси, что у Direct; `manifest.flags` фиксирует факт. Мастер-ось `unified_composer_enabled` этап B не гейтит: legacy-пути, который надо сохранять, у мема нет (в проде мастер ON — `plans/features/cfg/evidence/release-25897/`). Отвергнуто: ветка «мастер OFF → без личности».

## 3. Чего не строим и как доказан «ровно один вызов»

Не строим: второй композер или `speech_owner_block`-склейку (дубль Core = двойная личность), нового агента, доп. LLM-вызов, хардкод юмористических текстов в `meme_initiative`. Фейковый клиент считает `llm.generate`: на попытку ровно 2 вызова, шаги ровно `{meme_summary, meme_joke}` в этом порядке, `meme_joke` = 1; композер LLM не вызывает (только резолверы, `mca_humor_craft.layer_calls()`=0) — рост числа вызовов невозможен.

## 4. Humor Craft: приём из существующих, а не один захардкоженный

`select_technique` (`mca_humor_craft.py:248`) ждёт совет `comic_strategy`; у мема L1-плана нет. Решение — детерминированная ротация по имеющемуся `job_id` среди включённых владельцем техник: `enabled=[t for t in TECHNIQUES if cfg.technique_enabled(t)]` из `resolve_config(chat_id)` (`:199`), индекс `sha256(job_id) % len(enabled)`; пусто → `comic_strategy=""` (слой пропущен `humor_no_strategy`).

Совет едет объектом с `.comic_strategy`; композер читает его до подмены PlanRef (`:1020`), поэтому текст плана в payload не попадает. Наблюдаемость: `facts.joke.speech.humor_technique` + `humor_status` + ревизия слоя. Отвергнуто: один приём (прямой запрет владельца); все приёмы одним слоем (5 текстов ≈1000 симв. против `MAX_LAYER_CHARS=800` — обрезка и вторая сборка юмора); отдельный LLM-выбор приёма (запрещённый вызов). Слой остаётся подсказкой (`HUMOR_CRAFT_GUARD` не обязывает) — уместность решает сам персонаж.

## 5. Диагностика: точные поля, новых таблиц нет

В существующее поле `detail` строки журнала (компактный JSON, `:1143 compact_facts`) у stage `joke` добавляется подобъект `speech`; прочие ключи этапа (`:1438-1446`) не меняются:

```
speech = {composer: "on"|"failed",      # failed = манифеста нет, payload legacy
          system_sha12, manifest,      # sha12(system), manifest_id (16 hex)
          core, core_detail, identity, expression, style_policy,    # manifest.versions
          humor, technique, humor_status,   # ревизия humor_craft / приём / rendered|skip:<причина>
          layers: [...], skipped: {слой: причина}, off_axes: [оси с False]}
```

`versions["humor"]` не добавляем: в `_versions` (`prompt_composer.py:2085`) такого ключа нет, добавление меняет `manifest_id` всех Writer'ов и ломает пинованные хеши — ревизия берётся из `LayerTrace` слоя `humor_craft`. `prompt_composer.py` этой задачей не правится вообще.

Витрина: `analytics_snapshot` (`:1727`) получает аддитивный `last_joke` (факты свежего `joke`-ряда через единственный `parse_attempt_facts:1154`); `web/api/routes.py:3994` уже отдаёт `analytics` целиком — правок API и миграций нет. Показ — additive в карточке «Инициатива → Мемы» (`web/index.html:1737-1750`, `web/app.js:6878`).

## 6. Контракт Reviewer: что такое «реальный payload»

Реальный payload = сообщения, которые `_default_joke` отдал в `llm.generate` боевым путём (композер, без инъекции `joke_generator`). Захват — фейковый клиент `generate(messages, ...)`, без вызова модели:

1. system начинается с текста задания и содержит J-директиву (задание не вытеснено);
2. system содержит фактические строки Core (чат-редакция), Expression, `HUMOR_TEXT`, hint стиля;
3. при включённом Humor Craft system содержит `technique_text(chosen)`, при выключенном — нет;
4. user == ровно выжимка (личности/юмора в user нет, выжимка не переписана);
5. `system_sha12` == `facts.joke.speech.system_sha12` в журнале (доказательство связано с журналом);
6. `manifest.layers` (rendered/skip+ревизии) == `speech.layers/skipped`, причины ∈ `SKIP_REASONS`.

Живая приёмка (PET_PROJECT, без новых гейтов): `/meme` → в журнале `speech.*` непусты; Inspector `provider_calls(module="initiative", step="meme_joke")` показывает тот же system (`llm_client.py:103`).

## 7. Обычная текстовая инициатива: доказать, не меняя

Швы: `generate_initiative_reply` (`direct_chat_service.py:12068`) → `_l2_write_answer(writer="initiative_writer")` (`:12254-12260`) → `_compose_speech_system` с чатовыми осями (`:7001-7002`, `:916`) → `resolve_gates`; личность — `_initiative_persona_block/_initiative_character` (`:11847-11888`, учитывает `flags.persona_enabled`); Core/Policy — `turn_snapshot` → `resolve_core_ref/resolve_style_policy_ref` с чат-оверрайдом (`prompt_composer.py:748-780`).

Уже доказано «Direct == Initiative»: `tests/test_soul1_w5_observer_gates.py:606` (+`get_manifest(..., writer="initiative_writer")`, `:644`). Не хватает чатового слоя: новый `tests/test_initiative_speech_layers_chat_overrides.py` — глобальный документ ≠ чатовый оверрайд (`character.core`, style_policy, expression); проверить в захваченных сообщениях текст чатового Core/hint и `manifest.versions`, плюс выключенная ось → слой пропущен с причиной. Writer не переделывается: `_l2_write_answer` и OFF-ветка (`:7010-7033`) не меняются.

## 8. Сериализация и владение файлами

`PARALLEL_SAFE`: `services/meme_initiative.py`; `tests/test_meme_joke_speech_layers.py`; `tests/test_initiative_speech_layers_chat_overrides.py`; этот документ.

`SERIALIZE` (мелкие хунки, rebase перед коммитом): `services/bot_persona.py` — новая `resolve_character_block(chat_id) -> (block, ctx)` (перенос тела `_initiative_character`, логика та же); `services/direct_chat_service.py` — `_initiative_character` становится делегатом (3 строки, байт-паритет); `web/index.html`, `web/app.js` — аддитивный блок диагностики (владение MEME-UI-FIELDS, файлы чистые).

`READ-ONLY`: `prompt_composer.py`, `mca_humor_craft.py`, `prompt_style_blocks.py`, `mca_expression.py`, `web/api/routes.py`. Нарезка: новый сервисный пакет `MEME-JOKE-VOICE-LAYERS` (depends `MEME-PIPE-CORE`, читает P2-слой промптов) + расширение acceptance `MEME-UI-FIELDS` строкой слоёв.

## 9. Отказы, откат, риск

- Композер fail-open (`:1118-1121`): возвращается база канала → payload байт-в-байт сегодняшний, `speech.composer="failed"`; прикол не подменяется выжимкой. Сбой резолвера слоя его не валит — слой пропускается с причиной в манифесте. Ретраев нет: один вызов, `JOKE_TIMEOUT_SECONDS=30`.
- `trim_joke` — страховка; рост доли `trimmed` виден в аналитике (`_joke_stats:1702`). Откат: `git revert` коммита (новых флагов-гейтов не вводим); оси `character_core_enabled`, `humor_craft_enabled`, `speech_style_policy_enabled` действуют и на мем.
- Риск **R2**. Хрупкий шов — доставка совета Humor Craft без L1-плана: `_strategy` читается из переданного объекта (`:1020`) до подмены PlanRef; «чистка» композера тихо снимает слой (`humor_no_strategy`), и это заметит только тест §6.3.
- Решение владельца не требуется: выбор (авторская речь через один композер, приём из существующих по настройкам) дан дословно; ротация — механическое следствие «не привязывать к одному приёму».

## 10. Приёмка

1. Тест §6 (6 проверок) на боевом пути `_default_joke` + совпадение `system_sha12` с журналом; счётчик: ровно `summary`+`joke`, `meme_joke` = 1, ноль LLM-вызовов в композере.
2. Выжимка аналитическая: system этапа A == эффективный промпт выжимки без `<Speech_Base>/<Humor_Craft>`/Core; этап C LLM не вызывает.
3. Humor Craft: выключенные техники не выбираются; на разных `job_id` — больше одной техники; выключенная ось → слоя нет с причиной `humor_disabled`.
4. Витрина: `GET /api/initiative/meme-settings` отдаёт `analytics.last_joke` с ревизиями; строка видна в карточке мемов и не меняется самовольно после перезагрузки.
5. Инициатива: новый чат-оверрайд-тест §7 зелёный; `test_soul1_w5_observer_gates` не правится; регрессия P1–P3 (`test_meme_pipeline_stages`, `test_meme_pipeline_api`, `test_meme_command_autodelete`, `test_p0_meme_image_only`) зелёная без правок.
