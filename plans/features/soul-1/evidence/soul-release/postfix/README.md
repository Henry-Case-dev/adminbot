# SOUL-1 — postfix evidence (FIX-SOUL-F1F3, 18.10.2026)

Обновлённые выводы payload-стенда **после** мини-правки F1+F3 (решения
`review-payload-verify.md`, коммит `c640382e`). Отревьюенные артефакты
`../payload-verification/` **не перезаписывались** — это отдельный подкаталог
(`stand.py` здесь — копия стенда лейна с обновлённым блоком диагностики
`l2_voice` и агрегатом сегментов; реконструкция PG и fake-PG слой не менялись).

Кандидат: рабочее дерево с правкой F1/F3 поверх `c640382e`
(`stand-output.json → meta.services_vs_6094a2cf_diff` = `prompt_registry.py`
+`smartmodule_phrases.py`); после коммита лейна `git diff 6094a2cf HEAD --
services` показывает ровно эти два файла.

## Что изменено и почему

**F1 (блокер до включения).** Канон `summary.base.l2_writer`
(`prompts.summary_l2_writer_system_prompt`, живой = заводской `f832fb8cb5e4`,
`flags.summary_hybrid_l2_enabled=true`) содержал инструкцию сохранять старый
голос: «сохраняй характер бота и атмосферу конфы» + «двачерские обороты».
По решению ревьюера (два узких правила; одного недостаточно — симуляция):

1. гейт-маркер `_legacy_persona_marker_re` расширен `двач` (все остальные
   каноны с «двач» уже имели старые маркеры — их обработка не меняется);
2. два правила `LEGACY_PERSONA_RULES`:
   * `summary.l2_legacy_voice_reference`: «сохраняй характер бота и атмосферу
     конфы» → «держи голос Core» (характер задаёт только Core);
   * `summary.l2_dvach_vocabulary`: «Сарказм, интернет-сленг, двачерские
     обороты и мат разрешены» → «Сарказм, интернет-сленг и мат разрешены»
     (функциональная часть — разрешение сарказма/сленга/мата — сохранена).

Условие known-canon сохранено (кастом не трогается), вычистка на resolve
(`source=global`), байты PG/канона не мутируются (канон-бамп не выбран);
кодовый fallback (PG down, `source=default`) — байт-в-байт (OFF-паритет W2).

**F3 (мини-блокер).** `services/smartmodule_phrases.CHAT_PERSONA_PHRASE`
(ответ `/persona`, `handlers/direct_chat.py:253`): старая самоидентификация
(«я тот самый токсичный бот-абьюзер…») заменена на голос Core
(«я живой участник чата: остроумие, абсурд и язвительность, но не агрессия…»);
слот `{tone}` сохранён. Реестр: блок `message.smartmodule.chat_persona`
реклассифицирован (`legacy_persona` снят, метка `chat-persona-legacy` →
`chat-persona-core-voice`, note/purpose обновлены), `FACTORY_SET_SHA256_12`
бампнут `0fc99f73d646` → `7422c0385f7d`.

## Числа (postfix vs отревьюенный прогон)

| Метрика | Было | Стало | Источник |
|---|---|---|---|
| Сегментов вычищено (сумма `removed`, ключи `prompts.*`) | 37 / 12 ключей | **39 / 13 ключей** | `stand-output.txt` (`SEGMENTS_REMOVED_TOTAL`) |
| `prompts.summary_l2_writer_system_prompt`: removed / effective | 0 / `f832fb8cb5e4` | **2 / `cd3ecdfa7441`** | `keys_effective` диффом: изменён только этот ключ |
| `paths.summary.l2_writer`: маркеры / F1-обороты | `{двач:1}`; обороты на месте | **`{}`**; обороты отсутствуют, «держи голос Core» присутствует | `stand-output.json → paths.summary.l2_writer` |
| Маркер-скан 5 путей (Direct/Initiative/Factcheck/Summary/fallback) | чист (кроме F2-веток) | **чист** (F2-ветки `modes_off_prev_branch`/`code_default_path` без изменений — документированно-приемлемо) | тот же JSON |
| `sweep_registry` блоки с маркерами | 18 | **16** (`message.smartmodule.chat_persona` и `message.smartmodule.phrases` больше не несут старой личности) | тот же JSON |
| `sweep_python`: файлы с маркерами | 21 | **20** (`services/smartmodule_phrases.py` — код-строка удалена) | тот же JSON |
| Строка код-фразы в sweep | `smartmodule_phrases.py:161` `CHAT_PERSONA_PHRASE = "я тот самый…"` | **отсутствует** | тот же JSON |
| `withheld_values_view` | 11 строк | 11 строк (без изменений) | тот же JSON |
| `customs` / `humor` секции | эталон | **byte-equal** (json sort) | `stand-diff` прогон |
| factory_set | `0fc99f73d646` | **`7422c0385f7d`** | `meta` + `tests/test_soul1_registry_completeness.py` |

`summary.base.l2_writer` в `sweep_registry` остаётся строкой с маркером
`{двач:1}` — это **заводские байты канона** (backup; канон-бамп не выбран),
и у строки теперь видны `suppression_labels` обоих правил: вычистка
происходит на resolve. Заголовок раздела «СТИЛЬ (характер бота)» оставлен
как метка секции (решение ревьюера покрывает два оборота; третье правило —
расширение, если ревьюер сочтёт нужным).

## Прогоны (postfix)

* `focused-tests.txt` — 12 файлов (реестр обоих уровней, legacy-removal,
  completeness, legacy-custom, direct prompt reads, direct handlers,
  summary l2/asap21, parity off, core registry api, factory defaults,
  humor craft/feedback): **283 passed**;
* `tests/test_soul1_*.py` (30 файлов, весь SOUL-1 набор): **599 passed**;
* `tests/test_soul1_composer_parity_off.py` — **13/13** (parity OFF);
* `tools/gen_param_registry_round1025.py --check` — **575 == REGISTRY**, ok;
* node `tests/js` (86 tracked файлов кандидата) — **86 pass / 0 fail**
  (в рабочем дереве чужие правки P0-лейна в 2 glass-файлах; прогон по
  tracked-списку кандидата);
* смежные не-soul1 потребители реестра (`test_prompt_migrations.py`,
  `test_round1025_f8_registry.py`) — **70 passed**;
* новые тесты (3): `test_summary_hybrid_l2_canon_legacy_voice_is_stripped`
  (F1-регрессия), `test_code_path_persona_phrase_is_core_voice_and_registered`
  (F3 позитив), `test_persona_phrase_guard_catches_old_text_regression`
  (F3 негатив) — в `tests/test_soul1_registry_legacy_removal.py`;
  осознанно обновлён legacy-список в
  `tests/test_soul1_registry_completeness.py`.

## Файлы и повтор

| Файл | Содержание |
|---|---|
| `stand.py` | копия стенда лейна (обновлён блок `l2_voice` + агрегат) |
| `stand-output.json` / `stand-output.txt` / `stand-run.log` | полный/читаемый вывод и поток резолва |
| `probes.py` | unit-probe F1/F3-контракта (маркер/правила/реестр/fingerprint) |
| `probe-output-before.txt` | то же состояние ДО правки (RED: marker=False, removed=0, старая фраза) |
| `probe-output-after.txt` | после правки (GREEN: removed=2, обороты сняты, guard ловит старый текст) |
| `focused-tests.txt` | pytest 283 passed |

Повтор: `py -3 plans/features/soul-1/evidence/soul-release/postfix/stand.py`,
`py -3 plans/features/soul-1/evidence/soul-release/postfix/probes.py`.

Границы: стенд — офлайн, на восстановленном снапшоте прода 17.10 19:04 UTC
(SSH/прод не читались); F2-ветки (PG-деградация / `SMART_VERBALIZER_MODES=0`)
не затрагивались — их статус из отчёта лейна (документированно-приемлемо);
живой payload после релиза — постдеплойная проверка релизного прогона.
