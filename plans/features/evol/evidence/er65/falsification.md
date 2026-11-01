# ER-65 — проверка «на разрыв» (falsification) снимка сегментов

Снимок считается доказательством только если он **падает** при изменении
канона, при исчезновении боевых слоёв композера и при исчезновении
tool-раундов. Ниже — три опыта, каждый выполнен на рабочем дереве локально
(без сети, без прода), с побайтным восстановлением источника после опыта.

Общая процедура: сохранить файл в копию → внести ровно одну правку → прогнать
`py -3 tools/er65_prompt_segment_snapshot.py --check` и
`py -3 -m pytest tests/test_er65_sent_segment_snapshot.py -q` → вернуть файл из
копии → сверить `sha256` → повторить `--check` (снова `OK`).

## Опыт 1. Правка канона канала

Правка ровно одна: в конец `services/chat_prompts.py` дописана строка
`CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT + "\nФАЛЬСИФИКАЦИЯ-КАНОНА"`
(добавка — 21 символ контента, `addition_chars=21`).

`services/chat_prompts.py`: `sha256` до правки
`4942cdb1da53961dcb87b0fca4b4c7bcecc06b13ea2172bd6a661e31a2e640f8`,
после правки `29ea4f9f46439a15f7da298b652070b11ecc14b2ea1a71d96128e4a43fa74a73`.

Фактический вывод `--check` (дословно, ведущие обрезанные строки с
`direct.single.legacy_no_tools` — тоже в дельте):

```
FAIL: снимок разошёлся с закоммиченным артефактом
  direct.single.legacy_no_tools[0] system: chars 8490 → 8511, sha a77bf0e36ce8 → b36fa6ff62f0
  direct.tool_phase.model_driven[0] system: chars 5961 → 5982, sha fa18451557a4 → 9dab2c3556c0
  direct.tool_phase.model_driven[0] system: chars 8490 → 8511, sha a77bf0e36ce8 → b36fa6ff62f0
  direct.tool_phase.tool_round[0] system: chars 5961 → 5982, sha fa18451557a4 → 9dab2c3556c0
  direct.tool_phase.tool_round[0] system: chars 8490 → 8511, sha a77bf0e36ce8 → b36fa6ff62f0
```

Дельта `5961 → 5982` (ровно 21 символ) и `8490 → 8511` — то есть правка
канона видна и на боевом (ON), и на вторичном (OFF) контуре.

Тест: `1 failed, 16 passed` —
`FAILED test_snapshot_regenerates_byte_stable_from_code`.

## Опыт 2. Исчезновение боевых слоёв композера (B1)

Правка: в конец `services/prompt_composer.py` дописано перекрытие
`def composer_enabled_now(gates): return False` — композер выключается ровно
тем же способом, каким его выключает прод-флаг.

`--check` (дословно):

```
FAIL: снимок разошёлся с закоммиченным артефактом
  direct.l2_writer.deterministic_fallback_plan[0] system: chars 7721 → 5192, sha f54eac49d24c → 3777cd74c36a
  direct.l2_writer.direct[0] system: chars 7718 → 5189, sha 9d767f32a789 → 0f778962e071
  direct.l2_writer.fallback_model_capacity[0] system: chars 8037 → 5374, sha c79a1ddacf75 → 4e4ed6b8babf
  direct.l2_writer.fallback_model_repack[0] system: chars 8037 → 5374, sha c79a1ddacf75 → 4e4ed6b8babf
  direct.l2_writer.fallback_model_repack[1] user: chars 1016 → 1150, sha bd815c5825c7 → 1068de784d23
  direct.l2_writer.layered[0] system: chars 8037 → 5374, sha c79a1ddacf75 → 4e4ed6b8babf
```

То есть при выключении композера из system исчезают Core / identity /
Expression / speech_base (8037 → 5374 у слоистого Writer'а), а speech/lessons
возвращаются в user (1016 → 1150) — ровно та структурная разница, из-за
которой снимок нельзя было снимать в OFF.

Затем артефакт пересобран этой же (сломанной) сборкой
(`--write`, `roles=assistant,system,tool,user`, без слоёв) и прогнан тест:
`5 failed, 12 passed`, падают именно «слоевые» проверки:

```
FAILED test_primary_mode_is_production_gate_configuration
FAILED test_production_stages_carry_core_identity_and_expression
FAILED test_lessons_and_speech_live_in_system_on_production_path
FAILED test_layered_writer_keeps_declared_block_order
FAILED test_fallback_model_repack_and_capacity_are_distinct
```

## Опыт 3. Исчезновение tool-раундов (B2)

Правка: в `services/tool_loop.py` три вхождения `{"role": "tool",` заменены на
`{"role": "user",` — сообщение с результатом инструмента перестаёт быть
tool-сегментом (`file_sha256` до `87cbfa92…`, после `fba54cd6…`).

`--check` (дословно):

```
FAIL: снимок разошёлся с закоммиченным артефактом
  direct.tool_phase.tool_round[3] tool → user: chars 57 → 57, sha 580242f6cf5f → 580242f6cf5f
  direct.tool_phase.tool_round[3] tool → user: chars 57 → 57, sha 580242f6cf5f → 580242f6cf5f
```

Обратите внимание: текст сообщения не менялся, поэтому диагностика обязана
показывать смену РОЛИ — она её показывает.

После `--write` этой же сборкой тест падает:
`1 failed, 16 passed` —
`FAILED test_model_driven_tool_loop_captures_assistant_and_tool_segments`.

## Восстановление после опытов

Все правки внесены в копию и возвращены из неё; `git status` не содержит
изменений в `services/`. Сверенные `sha256`:

```
services/chat_prompts.py     4942cdb1da53961d…   (исходный)
services/prompt_composer.py  15f5705cc91ede08…   (исходный)
services/mca_gates.py        a8323d62b5e70d89…   (исходный)
services/tool_loop.py        87cbfa92e6499529…   (исходный)
sent-segments.json           51e4b26bf3312b56…   (закоммиченный)
```

Финальная проверка после восстановления:

```
OK: снимок воспроизводится байт-в-байт (stages=27, segments=58, two isolated processes identical)
```
