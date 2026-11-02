# MEME-JOKE-SPEECH — этап B мемов как авторская речь одного композера

Полоса: сервисная часть пакета `MEME-JOKE-SPEECH` (отчёт Builder).
Основание: `plans/owner_inputs/2026-11-03-meme-joke-speech-layers.md` (дословно,
intake `936340f4`), замороженная архитектура
`plans/features/meme-pipeline-refactor-01/arch/joke-speech-layers.md`.
Ветка `feat/meme-joke-speech`, база `b8d96a06`, кандидат `a1f0f9a0`.

## 1. Точка сборки (что и с какими аргументами)

`services/meme_initiative.py::_joke_system_prompt` (новый шов) → модульная
функция-владелец речи `services.prompt_composer.compose_speech_system`
(инстанс Direct-сервиса не нужен, второй композер не создавался):

```python
pc.compose_speech_system(
    chat_id=chat_id, writer="meme_joke", run_id=jid,
    channel="plain", html_safe=False,
    base_prompt=joke_instruction(editable_joke_prompt, budget.joke_budget),
    base_source="chat"|"global"|"default",      # из effective_meme_prompt
    include_mode_block=False, profile=pc.PROFILE_SPEECH_PLAIN,
    gates=await pc.resolve_gates(chat_id),
    include_speech_base=True, extent_block="",
    plan_skip="no_l1_plan_in_genre",
    response_plan=JokeAdvice(comic_strategy=<приём ротации>),
    identity_text=<bot_persona.resolve_character_block(chat_id)>,
    identity_source="chat",
    identity_skipped=""|"persona_disabled"|"identity_absent",
    style_skip="style_requests_absent", lessons_skip="lessons_absent",
    speech_skip="speech_absent",
    context_text=<выжимка>, user_parts=(<выжимка>,))
```

`messages = [{"role":"system","content":system},{"role":"user","content":summary}]` —
выжимка только user-частью; этапы A и C композер не вызывают.

`bot_persona.resolve_character_block(chat_id) -> (block, ctx)` — новая функция
(тело перенесено из `DirectChatService._initiative_character` без изменения
логики), `_initiative_character` стал делегатом в 1 строку (байт-паритет).

## 2. Наблюдаемый манифест (фактический прогон боевого пути)

Пробник: `consider_chat(... llm=<счётчик>, job_id="meme:probe-1")`, чат с
документами Core `r21`, Expression, Style Policy `g5`, Humor Craft (deadpan
выключен владельцем).

```
system 2826 симв., начинается с задания «Придумай короткий абсурдный прикол из этой выжимки.»
system_sha12 = f0c2695c31ca     manifest_id = 62aaae1adf259de9
versions:
  core           r21.848ba4c426b8   (core_detail = compact:document_default)
  identity       a227bfbefc8732fb
  expression     386f4ac001c1
  style_policy   g5.6aff783e44a7
  channel        speech_plain/plain/text/cd3e44a70856
  composer       w2
  (lessons/samples_library/response_plan/expression_examples = "")
слои (rendered / skip):
  channel_contract:channel_canon    cd3e44a70856  rendered
  core:core                          r21.848ba4c426b8 rendered
  identity:identity                  a227bfbefc8732fb rendered
  self_model_traits                  skip self_model_folded_into_identity
  context_lessons (style_requests / verified_lessons / speech_understanding)
                                     skip style_requests_absent|lessons_absent|speech_absent
  response_plan                      skip no_l1_plan_in_genre
  channel_contract:speech_base       9b33f0f3f15f  rendered   (BASE_SPEECH+HUMOR_TEXT+…)
  expression:expression              386f4ac001c1  rendered
  humor_craft:humor_craft            402b6636e025  rendered
  few_shot:expression_examples       skip expression_examples_absent
  few_shot:few_shot                  skip samples_disabled
  style_policy_hint                  g5.f85eb22d138f rendered
  channel_output                     skip channel_output_not_required
flags: unified_composer/character_core/humor_craft/persona/…=true,
       humor_library=false, humor_feedback=false
```

## 3. «Ровно один вызов» (счётчик `llm.generate`)

Фейковый клиент считает все вызовы: на попытку `steps ==
["meme_summary","meme_joke"]`, `len(calls) == 2`, `meme_joke` встречается один
раз. Композер LLM не вызывает: прямой повторный вызов
`compose_speech_system` с тем же входом не увеличивает счётчик
(`test_joke_step_is_one_call_and_composer_calls_no_llm`), и
`mca_humor_craft.layer_calls(<приём>) == 0`. Второго агента, отдельного
композера, дубля Core и хардкода юмористических текстов в сервисе нет.

## 4. Humor Craft: ротация по включённым владельцем техникам

`joke_technique(chat_id, job_id, gates)`:
`enabled = [t for t in TECHNIQUES if resolve_config(chat_id).technique_enabled(t)]`,
индекс `sha256(job_id) % len(enabled)`. Пусто/ось выключена/`enabled=False` →
`""` → слоя нет, причина в манифесте.

Наблюдаемое (deadpan выключен): `meme:probe-0…5 → bureaucratic_logic,
literalism, absurd_escalation, literalism, absurd_escalation,
unexpected_analogy` — 4 разные техники, ни одной выключенной; тот же `job_id`
даёт тот же приём (детерминизм). Если владелец оставил одну технику — ротация
даёт только её. Приём едет объектом `JokeAdvice.comic_strategy`, композер
читает его до подмены PlanRef, поэтому текст плана в payload не попадает.

## 5. Диагностика (аддитивно, без миграций)

`facts.joke.speech` в существующем поле `detail`:

```
composer          "on" | "failed"            (failed = манифеста нет, payload legacy)
system_sha12      sha12(system)              (совпадает с реальным payload)
manifest          manifest_id (16 hex)
core, core_detail, identity, expression, style_policy   из manifest.versions
humor             ревизия слоя humor_craft (versions["humor"] НЕ добавлялся)
technique         применённый приём | ""
humor_status      "rendered" | "skip:<причина>"
layers            [{layer, block, revision, chars, rendered, skip}]
skipped           {слой: причина[|причина]}
off_axes          ["humor_library_enabled", …]
```

`analytics_snapshot` получил аддитивный `last_joke` — факты свежего `joke`-ряда
через единственный `parse_attempt_facts`. `web/api/routes.py` отдаёт
`analytics` целиком, поэтому API не менялся. `prompt_composer.py` не тронут
(`git diff --stat` — только `meme_initiative`, `bot_persona`,
`direct_chat_service`, три теста). Текст прикола и тексты слоёв в журнал не
попадают.

## 6. Обычная текстовая инициатива (сервисная проверка, без переделки Writer)

`generate_initiative_reply` → `_initiative_persona_block` (теперь
`bot_persona.resolve_character_block`) → `_l2_write_answer(writer=
"initiative_writer")` → `_compose_speech_system` → `resolve_gates`, Core/Style
— через `turn_snapshot` с чатовым оверрайдом.

Новый `tests/test_initiative_speech_layers_chat_overrides.py` (3 теста):
глобальные документы ≠ чатовые оверрайды (Core `r11`, Style Policy `rev 9`,
Expression с чатовым пожеланием и контролом). Проверено в РЕАЛЬНОМ payload
Writer'а: чатовый Core/стиль/выражение присутствуют, глобальные — нет;
`manifest.versions` совпадают с ревизиями резолверов; выключенная ось
(`character_core_enabled`, `speech_style_policy_enabled`) снимает слой с
причиной `core_disabled` / `style_policy_disabled`, остальные слои живы.
`test_soul1_w5_observer_gates.py` не правился и зелёный.

## 7. Тесты и прогоны (кандидат `a1f0f9a0`)

Новые: `tests/test_meme_joke_speech_layers.py` — 9 тестов (CONTRACT):
слои/ревизии в реальном payload и совпадение `system_sha12` с журналом;
`last_joke`; один вызов + ноль вызовов внутри композера; ротация только по
включённым и разные приёмы на разных `job_id`; выключенные Core/Expression/
Humor → слоя нет, причина в `speech.skipped`; редактируемый промпт — задание,
не вытесняющее личность.
`tests/test_initiative_speech_layers_chat_overrides.py` — 3 теста (CONTRACT).
Обновлён осознанно по контракту: `tests/test_evol014_meme_initiative.py::
test_default_joke_matches_real_client_contract` (system теперь начинается с
задания, а не равен ему; возврат `(текст, диагностика)`).

Прогоны:
* два новых файла — **12 passed**;
* `test_meme_pipeline_stages`, `test_meme_pipeline_api`,
  `test_meme_command_autodelete`, `test_p0_meme_image_only`,
  `test_soul1_w5_observer_gates`, `test_soul1_w4_humor_craft`,
  `test_soul1_composer_layers`, `test_quota_removal_composer`,
  `test_evol014_meme_initiative` — **160 passed**;
* широкий `pytest tests -k "meme or initiative or prompt or composer or persona"`
  — **1243 passed, 2 skipped**.

Мутации (файлы восстановлены, финальный `git diff --stat` совпал):
* отключить сборку (вернуть базу канала) — падают 8 из 9 тестов этапа B;
* захардкодить один приём (`deadpan`) — падают оба теста ротации;
* выключить композер на пути Writer'а (`_c_on = False`) — падают все 3 теста
  инициативы.

## 8. Риск R2 (подтверждён и закрыт тестом)

Доставка совета Humor Craft без L1-плана хрупкая: `_strategy` читается из
переданного объекта до подмены PlanRef. «Чистка» композера тихо снимет слой
(`humor_no_strategy`) — это поймает
`test_joke_payload_inherits_speech_layers` (assert `craft.technique_text(tech)
in system` и `humor_status == "rendered"`).

## 9. Что осталось за этой полосой (P4 — показ в админке)

`web/**` не менялся. P4 обязан показать в карточке «Инициатива → Мемы»
(`web/index.html:1737-1750`, `web/app.js:6878`) аддитивный блок по
`analytics.last_joke.speech` из `GET /api/initiative/meme-settings`:

1. `composer`: «собран композером» / «композер недоступен — legacy payload».
2. `system_sha12` и `manifest` — идентификаторы фактического payload/манифеста.
3. Ревизии: `core` (+ `core_detail`), `identity`, `expression`, `style_policy`;
   пустая строка → «нет».
4. `humor` (ревизия приёма), `technique`, `humor_status`: `rendered` →
   «приём применён: <technique>»; `skip:<причина>` → «приём не применён:
   <причина>».
5. `off_axes` — выключенные оси (или «все оси включены»).
6. `layers` — таблица «слой/блок/ревизия/символы» с пометкой rendered/skip;
   `skipped` — причины по слоям (код причины рядом с человеческим ярлыком).
7. Никогда не показывать текст прикола, тексты слоёв, персону и выжимку —
   только ревизии и коды (R17-safe).
8. Нет `last_joke`/`speech` → честное «приколов ещё не было», без выдуманных
   значений; блок не должен обнуляться/переписываться между перезагрузками
   (рендер строго из ответа API, без локального кеша).
9. Человеческие ярлыки для новых кодов причин, которые теперь видны в
   `skipped`: `no_l1_plan_in_genre`, `self_model_folded_into_identity`,
   `expression_examples_absent`, `channel_output_not_required`
   (карта ярлыков живёт в `web/app.js`, не в этом пакете).

## 10. Файлы кандидата

`services/meme_initiative.py` — шов сборки, ротация приёма, диагностика,
`last_joke`; `services/bot_persona.py` — `resolve_character_block`;
`services/direct_chat_service.py` — `_initiative_character` делегат;
`tests/test_meme_joke_speech_layers.py`,
`tests/test_initiative_speech_layers_chat_overrides.py`,
`tests/test_evol014_meme_initiative.py`. Миграций, веб-правок, деплоя и
живых отправок нет.
