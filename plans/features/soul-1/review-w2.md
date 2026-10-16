# SOUL-1 / W2 — REVIEW-W2: независимое адверсариальное ревью композера

**Вердикт: Needs Fixes.** Паритет OFF доказан, но (F1) поставка конфликтует с
обязательным уточнением владельца, (F2) ON-путь L2 дублирует `context_lessons`
в system+user, (F3) тесты не покрывают реальный ON-вызов, (F4) review-гейт не
пройден. Правки — минимальные, кода почти не требуют.

**Кандидат (binding):** base `50a7e689` + рабочее дерево 2026-10-16 20:40.
`prompt_composer.py` sha256_12=`44D2780B04E7`, `direct_chat_service.py`=`701B6C8C2B70`,
`mca_gates.py`=`2DA5986D8CCD`, `prompt_style_blocks.py`=`A62AB337A2D6` — совпадают
с отчётом Builder'а и не менялись в ходе ревью.
Планировочные артефакты менялись ВО ВРЕМЯ ревью (PM-1): `plan.md`
`73a190b1f74c9fb9` (20:33), `requirements-map.json` `1f9ab535d1396cd4` (20:29),
`requirements-map-amendment.json` `4be62c82e3655ff7` (20:28). Вердикт вынесен по
этим ревизиям. Уточнение владельца: `338fd9c6…4a35c` (SHA256 сверен).

## 1. Паритет OFF — воспроизведено независимо (VERIFIED)

1. Мои прогоны: W2-сьюты **52 passed**; [B] **432 passed**; [C] **200 passed**
   (те же списки, что в `evidence/w2/focused-suites.txt`). Падения на счётчиках
   каталога больше не воспроизводятся (сосед обновил фикстуры) — регрессий нет.
2. **Саботаж-проверка чувствительности** (без правок репо, pytest-плагин из
   TEMP подменял `direct_chat_service.compose_verbalizer_system`):
   4 failed / 7 passed — P1, P2, P5b и OFF-guard падают. Тест реально сравнивает
   байты легаси-сборки, а не тавтологичен.
3. **Дифференциальный прогон old-vs-new** (мой скрипт, стубы = как в тесте):
   до-W2 копия `OPENCODE_WORKFLOW_SCRATCH/w2-before-f1418d7` (hash-object =
   pre-image `6816727f/a7c2df97/07fdd734` → это ровно дерево до W2) и текущее
   дерево OFF дают **побайтово одинаковые** P1/P2/P3/P4/P5a/P5b; значения
   совпали с артефактом `evidence/direct-runtime-assembly.txt`:
   P1 2088/6dc4aafa6167 (user 277/5bbb2c1c44e7), P2 1936/abd6cc49be6c,
   P3 1289/18af54a36e67, P4 2423/99a207313889, P5a 1107/6bae7eb26bc3,
   P5b 2088/6dc4aafa6167. Новая I/O на OFF-пути нет: `resolve_gates` при
   env-OFF выходит до `chat_params` (`prompt_composer.py:494-496`).
4. Core инъектируется ровно один раз на system (тесты слоёв + мой разбор
   `_compose`); одна ревизия identity на ход — подтверждается дампом
   (`44d962217014a041` в tool_phase и l2_writer) и `run_id` в рантайме.
5. Zero extra LLM: в `prompt_composer.py` нет `.generate(`/HTTP/send (grep пуст);
   тесты счётчиков вызовов осмысленны. Машинные профили (`machine_json`) не
   рендерят Core/юмор; события `manifest_for_events` — только ревизии/размеры.

## 2. Amendment conflict (критичный) — BLOCKING

Уточнение владельца и **текущая** карта (`requirements-map-amendment.json`)
закрепляют за W2: `SOUL-AMD.1.2` («legacy custom-промпты не сохранены активным
слоем», backup, без спец-UI-миграции) и `SOUL-AMD.8.4` («старые PG речевые
overrides не оказываются в effective prompt»). План W2 (20:33) добавляет в exit
«старые каноны вне runtime и вне legacy-редактора».

Факт: при флаге ON композер берёт `base_prompt`, который рантайм резолвит из
`prompts.direct_chat_verbalizer_system_prompt` / `prompts.direct_chat_system_prompt`
(включая PG-кастом, см. `direct_chat_service.py:2360-2363`, `4077-4080`) и
рендерит его **слоем №1 `channel_contract`** — до Core (`prompt_composer.py:936-963`).
`personas.system_prompt_overrides` идёт слоем `identity` и снимается только при
дословном дубле Core (`_duplicate_character_segment`). Мой пробник с ON:
custom-база присутствует в effective prompt; тест
`tests/test_soul1_legacy_custom_preserved.py:106-119` (`test_custom_base_goes_to_prompt_byte_for_byte`)
прямо утверждает `manifest.system.startswith(CUSTOM_BASE)` и защищает «эффект
сохранён». Это противоречит уточнению (оно отменяет SOUL-03/04 о сохранении
кастомов), при этом шапка файла ссылается именно на SOUL-04.4/15.3. Отчёт
Builder'а конфликт нигде не назван.

Минимальная коррекция (не «удалять кастомы в композере» — backup/migration
принадлежат W1/JB-3):
1) переанкорить `test_soul1_legacy_custom_preserved` на data-safety (нет записи,
   нет мутации, идемпотентное чтение) и убрать/помечить transitional ассерт
   «эффект сохранён»;
2) внести в отчёт явный блокер: `UNIFIED_COMPOSER_ENABLED` не включать в проде
   до выполнения SOUL-AMD.1.2/8.4 (W1 backup+миграция + registry), затем
   перепроверить;
3) PM/Orchestrator: не переводить SOUL-AMD.1.2/8.4 в VERIFIED по этой поставке;
   W2-выход в текущей редакции плана эти пункты требует.

## 3. Findings

**F2 (blocker, ON-путь): дубль `context_lessons` в system+user на L2 Writer.**
`direct_chat_service.py:4090-4093` кладёт `speech_block`/`lessons_block` в user-часть,
а `4124-4129` передаёт те же блоки композеру, который рендерит их в system
(`prompt_composer.py:1097-1126`). Пробник (ON, реальный `_l2_write_answer`):
SYSTEM содержит `<Speech_Understanding>`×1 и `<Verified_Lessons>`×1, USER — ещё
по ×1 (итого ×2 в одном payload; OFF — ×1). Нарушает «отсутствие повторов»
(source L281, контракт §3 «дублирование текста слоя запрещено»); затронуты
`l2_writer` и `initiative_writer` при непустых блоках. Исправление: при ON не
добавлять speech/lessons в `parts` (оставить слоями композера) + тест на
payload-уровне (сумма вхождений == 1), повторить parity OFF.

**F3 (related small): тесты не покрывают реальный ON-вызов и слабые ассерты.**
`test_l2_on_keeps_block_set_and_applies_designed_order` вызывает
`_compose_speech_system` без lessons/speech — поэтому F2 не пойман.
`test_known_legacy_scrub_stays_with_response_extent_owner`: `assert count >= 0`
(тавтология) и `strip_cap_phrases not in source.split("def _compose")[0]`
(проверяет лишь префикс модуля); содержателен только `scrub_for_plan( not in source`.
`test_p3_modes_off_parity_when_stage2_scrub_unified`: `if removed:` (при
`removed==0` проходит) и `assert psb.compose_verbalizer_system` (тавтология);
Stage-2 modes-off скраб не проверен через `_synthesize_direct_answer`.
Исправление: усилить 2-3 ассерта, добавить интеграционный кейс Stage-2
modes-off и L2 ON с lessons/speech; per-chat override новых осей (заявлен в §5.4
отчёта) отдельным тестом не подтверждён.

**F4 (bookkeeping/gate): review-гейт W2 не пройден.** Мои прогоны:
`check --stage review --slice W2 --candidate 50a7e689` → 34 error (candidate
mismatch: `candidate_commit` карты пуст; все 33 строки W2 = PENDING); для
amendment-карты slice W2 — 24 обязательных PENDING. Гейт — метаданные, но
«Approved» без него не выставляется. Исправление: PM привязывает кандидата и
обновляет статусы после F1/F2 (часть W2-строк можно VERIFIED уже сейчас).

**F5 (риск до включения флага, принять явно):** Core входит в аддитивный бюджет
и может быть исключён `budget_excluded` (`prompt_composer.py:1010-1016`,
`mca_gates.py:2210-2230`, дефолт 1200 токенов) — при `detail_level=full` Core
может исчезнуть из речи. До включения флага: вынести Core из бюджета либо
гарантировать размер редакций. Также принять явно: ON меняет порядок блоков
L2/Stage-2 (extent после личности/lessons) — по контракту §3/§5, недостижимо
до включения флага (env+catalog, оба OFF по умолчанию — проверено).

## 4. Четыре сознательно не сделанных пункта — оценка

1. **mca_self_model-хеши (шов 1)** — файл не тронут, в `persona_version_hash`/
   `_snapshot_version` Core-ревизии нет (`mca_self_model.py:378-411`). Заявление
   отчёта честное: закрыто на manifest/hot-apply/in-flight уровне, для
   snapshot/провайдер-трассы нужен отдельный мини-слайс. SOUL-15.5 остаётся
   UNVERIFIED в части snapshot/rollback; решение — за Orchestrator.
2. **Пять независимых семейств** — не подключены, это заявлено. Но текущая
   редакция плана (20:33) и AMD-карта (AMD.2.2/2.8/8.1) делают Core/Composer
   обязательными для публичных Factcheck/Summary → W2 в текущем виде этот
   выход не выполняет; нужен re-slice или расширение W2.
3. **W2_GATES вместо KILL_SWITCHES** — подтверждено: `KILL_SWITCHES` 1:1 связан
   с `MODULE_ENV_GATES` (M2-тесты), файлы реестра вне scope. Следствие: оси пока
   не регистрируются в каталоге/UI; включение только env + hot. Совместимо.
4. **SOUL-15.2 (per-chat у 4 «тихих» рубильников)** — не тронуто, заявлено;
   новые оси W2 читаются per-chat (`get_chat_param`), но теста per-chat нет.

## 5. Acceptance-ledger (W2, моё ревью)

- Байт-паритет OFF (шов 2): **VERIFIED** (мой дифференциальный прогон old-vs-new + артефакт).
- Один Core/одна identity-ревизия на ход: **VERIFIED** для system; **FAILED** для
  payload L2 (F2 — дубль lessons/speech).
- 0 доп. LLM: **VERIFIED**. Машинные стадии без Core/юмора: **VERIFIED**.
- События без текста/PII: **VERIFIED**. Бюджет не вытесняет вопрос/evidence: **VERIFIED**.
- Уточнение владельца (AMD.1.2/8.4): **FAILED** (F1). AMD.1.1/4.x/3.2/3.4: UNVERIFIED
  (не входят в поставку).
- SOUL-15.5 (snapshot/rollback-часть): **UNVERIFIED** (заявлено). SOUL-15.7: VERIFIED (причины/события).
- Гейт review W2: **FAILED** (F4). Итог: Approved невозможен.

## 6. Следующий шаг (минимальный)

1. Builder: F2 (2 строки + тест), F3 (усилить ассерты, добавить интеграционные кейсы),
   переанкорить legacy-custom-тест (F1.1), добавить в отчёт явный блокер F1.2.
2. Пока F1 не закрыт в полном объёме — флаг остаётся OFF; W2 не может быть
   Approved как выполнение текущего exit-критерия (старые каноны вне runtime).
3. PM: связать кандидата в обеих картах, обновить статусы W2; после правок —
   повторный review-гейт и точечная перепроверка: F1 (тест+отчёт), F2 (payload
   L2 ON ×1), F3 (новые кейсы), паритет OFF (52+432+200) без изменений.

*Ревью выполнено read-only: правок кода/карт/планов нет; создан только этот файл.*

## Verdict — RECHECK-W2 (2026-10-16, после fix-pass): **Approved за F1–F3 + Core-budget**

**Кандидат (binding):** master `50a7e689` + рабочее дерево, без коммита. sha256_12
совпали с заявлением fix-pass: `prompt_composer.py=426D93014FC9` (в ревью был
`44D2780B04E7` — смещение объявлено), `direct_chat_service.py=D603E00DB241` (был
`701B6C8C2B70` — объявлено), `mca_gates.py=2DA5986D8CCD` (не менялся),
`prompt_style_blocks.py=A62AB337A2D6` (не менялся); тесты `parity_off=33C0D128B3A4`,
`layers=296BE6D5F300`, `legacy_custom=13801A5FCB88` — совпадают.

### F2 — закрыт (воспроизведено независимо)
Мой пробник (scratch-only, реальный `_l2_write_answer`, ON): system 2229/`4d12389e8505`,
user 158/`aaf972648703` — байт-в-байт как `evidence/w2/on-payload-single-copy.txt`
(и маркеры, и полные блоки ×1 в system, ×0 в user, ×1 в payload); защищённые
`<Plan>`/`<Context>`/время/`<Tool_Evidence>` — ×1; edge без прочих user-блоков →
`user == query`. Аудит вызовов: speech/lessons передаёт только L2 (3281), initiative
(7846) их не передаёт, `user_blocks` дублей не содержит. OFF-паритет: мои прогоны
[A] 55 / [B] 432 / [C] 200 passed; 13/13 parity читают хеши из дампа (P1/P2/P3/P5a/P5b
байт-идентичны).

### F1 — закрыт в редакции уточнения владельца
`tests/test_soul1_legacy_custom_preserved.py`: ассертов «кастом активен» больше нет —
только байт-retrieval/read-only/идемпотентность; шапка цитирует SOUL-AMD.1.2/8.4 + §1.2/§4.6
(сверено с `source-architectural-clarification.md`: строки 3/10/58; в AMD-карте оба пункта
slice=W2, disposition=required, status=PENDING). Блокер есть в отчёте (:220, маркер
`composer_flag_release_gate`), в `prompt_composer.py:524–533` (`composer_enabled_now` —
ровно та функция, через которую композер включается) и в шапке теста (:18–21).
Включение код-дефолта в `mca_gates.W2_GATES` ломает parity/flags-тесты — мутация MutD:
FAILED (`assert True is False`). Env/каталоговое включение рантаймом не блокируется
(by design: флаг — рубильник владельца), гейт процессный, продублирован в трёх местах.
Нюанс (не блокирующий): литеральная строка маркера есть только в отчёте; в коде и шапке —
тождественный BLOCKER-текст со ссылкой, сканеру нужно включать отчёт.

### F3 — усилено, фальсифицируемо (мутации в scratch, репо не тронут)
- `test_known_legacy_scrub...`: точные счётчики (1 под longform-планом, 0 без плана,
  идемпотентно), `inspect.getsource(pc)` по всему модулю; `count >= 0` / `if removed:` /
  тавтологий не осталось (grep).
- `test_p3_modes_off_parity_when_stage2_scrub_unified`: реальный `_synthesize_direct_answer`,
  `removed == 1`, байт-сверка stage2-сообщения, manifest None.
- Новый `test_stage2_modes_off_with_composer_on_single_scrub_pass` реально проходит цепочку:
  `_synthesize_direct_answer` → Stage-2 ON-ветка (4282/4323) → `_compose_speech_system(
  writer="system2_stage2")` → один проход `scrub_for_plan`; ассерты: manifest≠None,
  source=legacy_mode, flags modes=False, Core в system.
- Мутации (pytest-плагин + копии модулей в `OPENCODE_WORKFLOW_SCRATCH/w2-recheck`):
  MutA (Core снова под бюджетом) → FAILED `budget_excluded`; MutB (возврат F2) → FAILED
  «в payload 2 копий»; MutC (снят Stage-2-скраб) → FAILED; MutD → FAILED.

### Core-budget — защита реальна
`prompt_composer.py:1021–1045`: Core рендерится всегда; перерасход виден конфликтом
`core_protected_from_budget`/`exempted_protected` с провенансом; `budget_excluded` остаётся
только добавке (expression/humor/few_shot/hint). Тест с бюджетом 20 tokens падает при снятии
защиты (MutA).

### Целостность кандидата
После 20:40 менялись только объявленные файлы (mtime 20:48–20:58) + evidence
(`dump_on_single_copy_payload.py`, `on-payload-single-copy.txt` sha256_16=`D05D0CB5AE2A3CCC` ✓,
`focused-suites.txt`, `parity-off.txt`); `core_version/flags/machine`-тесты, `mca_gates`,
`prompt_style_blocks` не менялись. Вне W2: `web/app.js` (20:57) — соседняя UI-полоса,
в W2-путях не участвует, на приёмку W2 не влияет. Замечание к отчёту: аннотация
«+8 после 4074» неточна (по сверенным якорям 4090→4102, 4124→4136, 7767→7779 сдвиг ≈ +12);
это только документация, поведение проверено тестами.

### Что НЕ включать до amendment-слайса
`UNIFIED_COMPOSER_ENABLED` (env + `flags.unified_composer_enabled`) и регистрацию `flags.*`/UI —
не включать; `SOUL-AMD.1.2/8.4` остаются PENDING (по этой поставке не VERIFIED); legacy-каноны
(`prompts.direct_chat_verbalizer_system_prompt`/`prompts.direct_chat_system_prompt`) уходят из
effective-слоя только после W1 backup+миграции; затем повторная проверка F1 и только потом включение.
F4 (статусы в картах) — за PM, вне этого recheck. Прочие пункты §4 исходного ревью —
без изменений, решения Orchestrator'а.

*Recheck выполнен read-only: правок кода/карт/планов нет; изменён только этот файл.*
