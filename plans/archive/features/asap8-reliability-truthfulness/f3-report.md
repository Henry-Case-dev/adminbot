# ASAP 8 F3 — Style Edit scene preservation (отчёт Builder-лейны F3)

Базовый HEAD на старте: `cbda23b` (в процессе работы параллельные лейны закоммитили F2 `fcbbf12`,
F6, F9, bump `c3f182e` — фокус-прогон перевыполнен на финальном дереве). Кандидат в рабочем
дереве, НЕ закоммичен (после Reviewer).

## 1. Новый порядок приоритетов `compile_style_prompt` (cover_style_jobs.py)

Строка промпта (нормальный путь), порядок из architecture §3.1 соблюдён:

```text
P0 CONTENT_PRESERVATION_INVARIANTS  (НОВЫЙ, первый в строке, label content_preservation)
P0 ISSUE/TEXT INVARIANTS            (runtime_invariants_text, как было)
P1 STORY_IDENTITY                   (story_scene + brief.render(), label cover_brief)
P1 STYLE_IDENTITY minimum           (profile.instruction)
P2 REFERENCE_DESCRIPTIONS           (refs)
P2 base_style_prompt                (ПОНИЖЕН с P1, НЕ удалён)
P3 decorative extras
```

* STORY_IDENTITY поднят из `budget_component` в P1-компоненту обязательного ядра:
  сюжет едет **целиком** или даёт честный `prompt_limit_exceeded` (compact/floor-механика
  на сюжет в нормальном пути больше не применяется). Story floor 160 сохраняется в
  retry_core-ядре (`cpa.story_floor_text`), как и было.
* `base_style_prompt` P1→P2: эффект уже запечён в input image; текст остался (нужен
  preview-ветке `cover_style_preview.py:440` через `run_style_job` и честному предпросмотру),
  при давлении падает. В retry_core-ядро больше не входит (раньше ехал) — drop фиксируется
  как `dropped=["base_style_prompt"]`.
* Механика `image_prompt_compiler.compile_prompt` НЕ менялась (P-уровни как данные,
  required=P0+P1, EXTRA-контракты целы — tests/test_asap42_step2c_image_capacity.py и
  tests/test_extra_image_capabilities_compiler.py зелёные).
* STORY_IDENTITY-текст нормализуется по whitespace (`_story_identity_text`) —
  детерминированный floor-containment для fail-soft и манифеста.
* `_prompt_breakdown`: system_chars = runtime_invariants + content_preservation
  (4-lens контракт Style/Context/Refs/System сохранён).
* prompt_diagnostics: добавлен `story_identity_present` (bool, containment-чек факта).

## 2. Preservation-компонент (cover_prompt_assembly.py)

`CONTENT_PRESERVATION_TEXT` / `content_preservation_text()` — формулировка §5.3 ТЗ дословно
(«Preserve the exact depicted event, people, actions, object relationships, composition and
framing from the input image. Do not replace the scene with a generic portrait or generic city
scene. Apply the requested visual style without changing the story content.»). Единый источник
для compile и манифеста. Входит в required-ядро и в retry_core-ядро — никогда не режется.

Манифест (`build_style_manifest`): новый первый компонент `CONTENT_PRESERVATION`
(source=code, P0, kept/omitted по факту в final_prompt); приоритеты отражают новую карту
(`STORY_SCENE` P2→P1, `BASE_STYLE` P1→P2). Попутный фикс честности: полный сюжет в промпте
раньше помечался `compacted/story_minimum` (пинился floor) — теперь `kept`; floor-ветка
(compacted/story_minimum) осталась для squeeze-путей. `MANIFEST_KEYS` дополнен.

## 3. Fail-soft (§5.4) — `style_publish_skip_reason` + гейт в `run_style_job`

Детекция детерминированная, из результата компиляции (НЕ LLM):

* `prompt_limit_exceeded` — `compiled.exceeded` (P0-ядро, включая story identity, не влезло);
* `story_identity_dropped` — story floor не вошёл в фактический промпт ИЛИ `cover_brief`
  в `dropped[]` (legacy byte-контур `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED=false`,
  срез короче floor и т.п.); пустой story — терять нечего, skip нет.

Исход: styled НЕ публикуется (платный edit-call не вызывается), публикуется Base
(`_style_failed` → `outcome=RESULT_BASE`, `reason=style_failed`, `fail_reason=<skip_reason>`);
манифест строится и для skip-исхода (прежде overflow возвращался вовсе без манифеста) и
помечается `style_publish_skipped{reason}` (+ `attempts[0].outcome=failed`); маркер дублируется
в `meta["style_publish_skipped"]`; персист в `state.prompt_manifest` (Inspector/F4 читает).
Событие `COVER_STYLE_FAILED` несёт reason/reason_code=<skip_reason>; `story_identity_dropped`
добавлен в `STYLE_REASON_CODES` (без generic-схлопывания при snapshot ON) и в
`REASON_DETAILS_RU`. Точка хука — прежний overflow-фолбэк (бывш. :1794-1809), порядок выпуска
не изменён; в нормальном пути story теперь в required-ядре, поэтому потеря сюжета выражается
честным overflow → Base, а `story_identity_dropped` остаётся живым сигналом для
non-semantic-контура и защитой от любых будущих compiler-регрессий (проверено тестом).

## 4. Тесты

Новый `tests/test_asap8_f3_style_preservation.py` — 13 тестов
(TEST-LIFECYCLE: REGRESSION owner=ASAP8/F3; CONTRACT owner=ASAP8/F3):
порядок строки, смысл preservation-текста, story в required-ядре без сжатия,
base_style понижен-но-не-удалён, retry_core (preservation+floor, base_style в dropped),
unit `style_publish_skip_reason` (exceeded/lost-floor/cover_brief-dropped/empty/healthy),
overflow→Base (0 paid calls, манифест-маркер, event reason_code),
story_identity_dropped→Base (legacy-контур, 0 paid calls, STORY_SCENE omitted),
happy path (preservation+story+base_style в отправленном промпте, parity манифеста,
CONTENT_PRESERVATION kept, STORY_SCENE kept P1, BASE_STYLE P2, маркер отсутствует),
C1-канон Base (story→ctx→style не тронут), манифест full-story kept vs floor.

Фокус-прогон на финальном дереве (после коммитов F2/F6/F9/bump):

```
pytest tests/test_asap8_f3_style_preservation.py tests/test_asap44_cover_final_closure.py
  tests/test_asap5_cover_prompt_manifest.py tests/test_asap5_cover_manifest_web.py
  tests/test_extra_cover_style_jobs.py tests/test_cover_style_wave_b_asap4.py
  tests/test_asap7_cover_readpath.py tests/test_asap7_cover_fix.py
  tests/test_asap7_cover_preview.py tests/test_asap43_cover_style_surgical.py
  tests/test_cover_styles_contract_asap32.py tests/test_summary_cover_style_wave_f_asap41.py
  tests/test_asap42_step3_style_integration.py
→ 247 passed
```

Расширенный прогон (плюс asap42_step2c/2c2, extra_image_capabilities_compiler,
extra_cover_styles_api, asap44_graphrag, asap7_module_completeness): 315 + 53 passed.
JS-контракты: `node tests/js/asap5_cover_manifest_test.js`, `asap7_f7_cover_compile_test.js` — OK.
Summary-сторона (F2-зона, только прогон): test_summary_test_run + test_asap8_f2 — 113 passed.

### Intended pin replacements (2 смысловые замены, 3 файла)

1. **Манифест-компонент lens + CONTENT_PRESERVATION** (прямое следствие нового P0-компонента):
   `test_asap5_cover_prompt_manifest.py::test_style_manifest_runtime_profile_story_refs`
   (set-equality 6→7 + priority/status сохранены) и
   `test_asap5_cover_manifest_web.py::test_admin_gets_full_manifest` (len 6→7, key-set,
   fixture-FINAL_PROMPT без preservation → честный omitted).
2. **cover12e probe-лимит** (`test_asap44_cover_final_closure.py`): лимит считался по probe без
   brief, при новом P1-сюжете реальный required > limit → честный overflow до первого paid
   call (это и есть C4-семантика). Probe дополнен тем же brief — исходный смысл теста
   (known-retry → unknown-failure → ровно 2 paid call, третьего нет) сохранён и зелёный.

Изменения тестов вне этих двух пунктов: нет. `tests/test_cover_style_wave_b_asap4.py`
не редактировался (зона F2 на момент брифинга) — diagnostics-тест проходит как есть
(overflow-ветка и до, и после фикса даёт те же observable-поля).

## 5. Файлы

* `services/cover_prompt_assembly.py` — preservation-константа/функция, манифест (компонент,
  приоритеты, full-story kept), MANIFEST_KEYS;
* `services/cover_style_jobs.py` — compile_style_prompt (новая карта), `_story_identity_text`,
  `style_publish_skip_reason`, fail-soft гейт в run_style_job, diagnostics
  story_identity_present, reason-code/детали, `_prompt_breakdown`, `__all__`;
* `tests/test_asap8_f3_style_preservation.py` — НОВЫЙ (13);
* обновлённые пины: tests/test_asap5_cover_prompt_manifest.py,
  tests/test_asap5_cover_manifest_web.py, tests/test_asap44_cover_final_closure.py.

Механика compile_prompt, image_capabilities, Base-сборка (cpa.base_prompt_plan), web/* —
не тронуты. Секретов нет; в манифесте preservation — кодовая константа (не chat data), R17
не задет.

## 6. Инцидентальные находки

* `unrelated/pre-existing` (F2-зона): `tests/test_summary_publish_integration_round1026.py::
  TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` — красный на дереве БЕЗ
  изменений F3 (проверено stash-прогоном): пин `llm.generate.await_count == 1` (L2 на
  fallback-пакете) vs закоммиченный fcbbf12. Тот же семантический узел, что F2 перепинил
  в wave_b TestDryRunBudget; в этот файл правка F2 не попала. Оркестратору — в зону F2.
* `related-nonblocking` (UI-подпись): web/app.js `coverManifestSourceLabel` не знает ключ
  `CONTENT_PRESERVATION` → UI покажет fallback по source ('code'). Контракт не ломается
  (JS-тесты зелёные, web/* — зона F8/F4); добавить RU-подпись («Сохранение сюжета») в их
  слайс.
* Неопределённость нет; release-bump/version-пины — зона релизной волны (конвенция bump+пины),
  для F3-кандидата не выполнялись.
