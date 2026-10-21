# Review REV-CFG07D5 — волна 07D.5 (bounded retry метаречи + FA/MB-детекторы)

- **Вердикт: Needs Fixes** (4 блокирующих, все малые/локальные — один цикл ремонта).
- **Кандидат:** uncommitted worktree поверх HEAD `ce77b2c4` (прод 2.58.103).
  Коммитов/пушей/деплоя/чатов нет; биндинг за оркестратором после фиксов.
- **Скоуп диффа подтверждён:** 4 services (public_speech_guard +240, negative_constraints +86,
  factcheck_service +25, prompt_style_blocks +14) + новый тест `test_cfg07_guard_07d5.py` +
  evidence (07d5-summary/tests) + карта (только строка CFG-07D.5, PENDING сохранён).
  Остальные грязные файлы в `git status` — чужие лейны (совпадает с 07cg-tail).
- **W3-фриз:** `factcheck_prompts.py`/`prompt_migrations.py` вне диффа;
  prompt_style_blocks — только новый `METATEXT_RETRY_SYSTEM_PROMPT`, старые блоки не тронуты.

## Что верифицировано (независимо)

| Пункт | Результат |
|---|---|
| Reuse retry: ≤1 metatext в общем бюджете ≤2, приоритет metatext→form→numeric→cliché | OK (код + тесты) |
| metatext_reason только для инверсных/вариативных; дословные/машины/честные → None | OK (тест), НО см. F3 (негация) |
| Honest degradation: metatext_fallback=True + strip_guard_findings, идемпотентен | OK (тест + проба) |
| OFF-паритет: `_metatext_retry_reason()`=None при FACTCHECK_PIPELINE_V2_ENABLED off; default-контракт → stats без новых ключей | OK (6 wiring-тестов) |
| FA-06/07/08, FA-01/02, SF-16, MB-10/11/12 — ровно записи 07a1-corpus.json (id в findings) | OK (corpus-parity тест + сверка JSON) |
| Границы токенов `_`: host_not_actively / myunchanged / host_tool_not_actively не ловятся | OK (тест + пробы) |
| Bracket-фикс `_bracket_block_re` работает: `[1]`, `[прим. автора]` целы; FA-08 режется, соседний `[5]` цел | OK (проба), НО см. F2 (нет теста) |
| 0 ложных: 202 текста пулов smartmodule_phrases (число подтверждено пробой), PC-01..12, renderer/checkup-каноны — 0 находок, байт-в-байт | OK |
| Тесты: новый 39 passed; guard+factcheck-семья (супермножество 232) 293/0; валидаторная семья 331 (в отдельной сессии); add_exp 36; mca20 temporal-семья 80/0 | OK, НО см. F1 (комбинированный прогон) |
| sha256 07d5-summary.md = artifact_sha256 в карте | OK (f11bd30e…) |
| Карта: только строка CFG-07D.5 (L00380), статус PENDING, evidence добавлен | OK |

## Блокирующие находки

**F1 (BLOCKER, small) — тест-файл ломает чужой тест в комбинированном прогоне (загрязнение settings-синглтона).**
`test_kill_switch_bypasses_metatext` (tests/test_cfg07_guard_07d5.py) патчит
`SYSTEM2_VALIDATOR_LOOP_ENABLED` через `object.__setattr__(settings, …)`; это ClassVar
(config/settings.py:553), поэтому после restore в инстансе НАВСЕГДА остаётся
инстанс-атрибут (проба: `in vars(settings)` False→True), который затеняет класс-патч
`monkeypatch.setattr(Settings, …)` из старого теста.
Репро: `py -3 -m pytest tests/test_cfg07_guard_07d5.py tests/test_negative_constraints_round1022.py`
→ `test_kill_switch_off_single_call` FAILED (assert 3 == 1). Валидаторная семья 331 зелёная
только при раздельных сессиях — сводный релизный прогон упадёт.
Фикс: в этом тесте патчить класс (`monkeypatch.setattr(type(settings), "SYSTEM2_VALIDATOR_LOOP_ENABLED", False)`),
не инстанс. Речек: та же двухфайловая комбинация → EXIT 0.

**F2 (BLOCKER, tiny) — фикс `_bracket_block_re` не закреплён тестом (бриф: «по коду+тесту»).**
Код верен (тело экранируется без ведущей `[`; проба подтверждает), но в
test_cfg07_guard_07d5.py нет ни одного теста на «чужие скобки не режутся» — регрессия
в дефектную char-class-форму прошла бы суиту незаметно. Фикс: один тест
(`"[СИСТЕМНОЕ УВЕДОМЛЕНИЕ: x] см. [1] и [прим. автора]"` → срез только FA-08-блока,
`[1]`/`[прим. автора]` целы), TEST-LIFECYCLE: REGRESSION owner=CFG-07D5.

**F3 (BLOCKER, small) — смысловой слой ловит честное отрицание (ложный триггер bounded retry).**
Проба: `metatext_retry_reason('Тезис не подтверждён — весь интернет я не проверил.')`
→ `'metatext_semantic:total_verification_variant'` (закрытый сет инверсию не покрывает,
негации перед глаголом нет). Это класс PC-01/честных ограничений — сам retry-канон волны
требует «честные ограничения сохрани», а контракт гласит «retry только для нарушений».
Эффект при v2 ON: лишний трат ≤1 повтора + переписывание честного текста; strip не режет
(«не» вне межслова) → fallback-текст цел, но метка/бюджет ложные.
Фикс: negative lookbehind «не» перед глаголом в `_SEM_VERIFY_VERB_RE` + тест
(честная негация → retry_reason None). Речек: проба + тест.

**F4 (BLOCKING, small) — evidence описывает поведение шва вопреки коду.**
`_INVERSE_STRIP_RE` включён в `_strip_matches`, который `guard_public_text` применяет:
проба `guard_public_text('Тезис подтверждается. Весь интернет я проверил.')` →
findings + changed=True, text='Тезис подтверждается. .' — инверсия НА шве РЕЖЕТСЯ.
При этом утверждают обратное: 07d5-summary.md §2.2 («delivery-шов инверсию не режет»),
комментарий в guard_public_text («текст не режется… только телеметрия»), докстринг теста
(:589). Поведение (срез как defense-in-depth) разумно и согласуется с докстрингом самой
_INVERSE_STRIP_RE («и на delivery-шве») — править надо документацию/тест, не код.
Фикс: синхронизировать 2 комментария + буллет summary + ассерт на фактический text.
Прим.: остаток « .» после среза — существующий класс уборки _strip_matches (так же режет
закрытые формулы на HEAD) — вне скоупа.

## Попутные (nonblocking)

- Прецедентный дефект того же класса на HEAD: закрытый сет 07D.2 игнорирует негацию —
  `claims_total_verification('Я не проверил весь интернет') == True` → срез честной
  негации на шве. Существовал до волны; чинить корпусно (07A.7), отдельным микрослайсом.
- FA-06/MB-10 англ. слова (UNCHANGED, precision, uncertainty) в легитимной речи будут
  флаггаться — санкционировано корпусом (word_ci, решение 07A-2); принять как есть.

## Источники

- Код/дифф: git diff (4 services), tests/test_cfg07_guard_07d5.py; corpus 07a1-corpus.json;
  план cfg-07-build-plan.md §3 (07D.5-acceptance), 07cg-reuse-audit.md §3, 07cg-tail.md §6.
- Прогоны: независимые pytest-сессии (все числа выше воспроизведены), пробы python на
  реальном guard/verbalize. Внешние источники не требовались (все факты репо-локальные).

## Биндинг для ledger (оркестратор)

- Кандидат: uncommitted worktree @ HEAD ce77b2c4 — фиксы F1–F4 в тех же 5 файлах;
  коммитит оркестратор, затем re-check: (a) комбо new+nc1022 EXIT 0, (b) сводный фокус
  (как в 07d5-tests.txt) EXIT 0, (c) пробы F3/F4.
- Evidence: plans/features/cfg/evidence/cfg-07a/07d5-summary.md (sha256 f11bd30eecd21081b27de59a5c9346f0f8e46764e93455fb97dc4a5ae77cc29f;
  после F4-фикса буллета — обновить sha в карте), 07d5-tests.txt, этот файл.
