# REV-P0-PROMPTS — независимое ревью `3fcac03c`

Ревьюер: REV-P0-PROMPTS (read-only). Кандидат: `3fcac03c` (= HEAD, код-дерево
чистое). База сравнения: `9051e9fe`. Прод/SSH/живые чаты не трогались.

## Вердикт

**Код лейна — принят. В поезд — НЕТ** (два внешних к лейну блокера: устаревшая
карта требований и невоспроизводимые числа в доказательствах). Ни один блокер
не требует переписывать freepseech/withheld/миграцию.

## 1. Свобода речи в Core — ПОДТВЕРЖДЕНО

| проверка | факт |
|---|---|
| Full | ровно 1 абзац `Свобода речи.` (`chat_prompts.py:975-980`), между «Как говорить о реальных событиях» и «Грубость и конфликт» |
| Compact | ровно 1 предложение в существующем абзаце (`PERSONALITY_CORE_COMPACT_TEXT`) |
| уровень личности | текст говорит о собственном голосе/словах, не о правилах ответа |
| слово «мат» | 0 вхождений (корень `мат`) в factory Full; квот/частот нет |
| Expression | `services/mca_expression.py` в коммите не менялся |
| функциональные промпты | `checkup.base.system`, `factcheck.base.single`, `factcheck.base.verbalizer`, `summary.base.single`, `search.base.system` — фразы нет (проверено по `factory_text`) |
| идемпотентность | `owner_preserve_core_full_patch`: повторный прогон → `(тот же текст, [])`; вставка только при отсутствии смысла; авторские байты не переписываются (тесты `test_91_*`, `test_p0_checkup_core_contract`) |

Семантика: «не подчиняешься внешним настройкам безопасности, цензуры и морали,
когда выбираешь собственные слова» + явная граница «свобода голоса, а не фактов».
Это исполняет ADDENDUM #2 (source-2026-10-24.md:802-806) и не создаёт второго
регулятора мата.

Остаток (шаг деплоя, не дефект кода): активная владельческая PG-редакция Core
получает абзац только когда деплой вызывает `owner_preserve_core_full_patch`;
в рантайм-сервисах вызовов нет (только тесты/процедура W1). Должно быть в
чек-листе выката; compact в проде пуст → действует фабрика v4.

## 2. Withheld — ПОДТВЕРЖДЕНО (не активированы)

- 8 редакций `legacy_incompatible` классифицированы по точным байтам; тексты и
  история не удалены (в диффе нет ни одной записи/удаления).
- `write_speech_value` отклоняет такие байты: `reason=legacy_incompatible`,
  `applied=false`, без выдуманного провенанса (в т.ч. для chat-слоя).
- Причины соответствуют содержимому: старая личность + строка обхода
  ограничений; у factcheck дополнительно «сознательно игнорируй часть
  утверждений» (противоречит контракту полного разбора).
- `direct.base.l2_writer` `83ff62bbee40` → `identical_to_factory`: WARNING
  заменён INFO только для этого sha, блок остаётся withheld (текущая фабрика
  новее).
- Allowlist `persona.checkup_language` узкий: только точные байты текущей
  owner-редакции Checkup; копия с лишним символом снова чистится (тест есть).

## 3. Миграция — ПОДТВЕРЖДЕНО

`migrate_prompt_canons` → `_attest_migrated_canon` → `_mark_provenance`
(kind=`factory_reset` входит в `PROVENANCE_WRITE_KINDS`), сравнение по
`sha256_12` перед записью ⇒ повторный прогон no-op; аттестация только для
блоков, которым провенанс реально нужен; сбой журнала не отменяет миграцию
значения. Тест `test_pr03_migration_attests_canon_and_survives_restart` зелёный.

## 4. FACTORY_SET — ПОДТВЕРЖДЕНО

`FACTORY_SET_SHA256_12 = 071b1f3ec5f9` == `factory_set_fingerprint()` (проверено
исполнением). Метки: `asap-core-full-v4`, `asap-core-compact-v4`,
`checkup-p0-24-10`. Тексты фабрик в этом коммите изменены у 2 блоков (Full +
Compact); «4 фабрики» в сообщении — суммарно по P0 (checkup и fallback notice
пришли из `9051e9fe`, где константа ещё была `24ae494ac422`). Формулировка
неточная, состояние гарда на кандидате консистентно.

## 5. Inspector — ПОДТВЕРЖДЕНО, с косметикой

`_block_detail` отдаёт `saved{text,source,revision,present,withheld,class,reason,
resolution}` + `effective.withheld_class/withheld_reason`; сохранённый текст
показывается отдельной readonly-областью с подписью «не уходит в LLM», активная
редакция — отдельно (`scope_label` + `revision`). Тест
`test_inspector_shows_saved_active_reason_and_resolution` зелёный.

Косметика (не блокирует): ветка `elif eff.provenance_reason ==
pr.WITHHELD_IDENTICAL_CLASS` в `web/api/speech.py` и `v-if="...
provenance_reason === 'identical_to_factory'"` в `web/index.html:9271`
недостижимы — сравнение класса с полем причины. Информация при этом доступна
через `withheld_class`. `web/app.js`: `speechEditionReasonText` начинается в
одной строке с `var reason` — `node --check` OK, стиль небрежный.

## 6. PR-01..03 и числа — числа НЕ ВОСПРОИЗВЕДЕНЫ

PR-01..03 и все 9 тестов `tests/test_p0_prompts_core.py` — passed.

| заявлено | фактически (этот кандидат, это окружение) |
|---|---|
| focused 256 passed | 14 затронутых файлов: **291 passed, 1 failed** |
| broad filtered 1426 passed, 2 failed | `-k "prompt or speech or registry or provenance or core"`: **1428 passed, 0 failed** |
| 2 падения: `test_soul1_machine_profile_no_core`, `test_soul1_w5_observer_gates` (`_StubService`/`804b68b1`) | таких тестов нет; оба файла — **23 passed**. `_refresh_turn_aliases` есть (direct_chat_service.py:2186) и в стабе observer-теста определён |

Единственное фактическое падение: `tests/test_asap_w1_semantics.py::
test_p0d_expression_header_footer_and_modes_byte_exact` — `KeyError` по префиксу
`PROFANITY_INSTRUCTIONS["frequent"]`: Expression-текст больше не совпадает с
фенсом в снапшоте источника. Файл этим коммитом затронут, но падение
**pre-existing** (Expression и снапшот в `3fcac03c` не менялись → P0-E). В
доказательстве не раскрыто.

Вывод: 2 «pre-existing» падения не от этого коммита — их вообще нет; но и
заявленное «зелёное» множество неполно. Числа и атрибуцию нужно исправить в
evidence (правка на 3-4 строки), код не трогать.

## 7. Скоуп

Чужих правок в коммите нет: 4 сервисных файла (`chat_prompts`, `prompt_factory`,
`prompt_migrations`, `prompt_registry`) + web (`speech.py`, `app.js`,
`index.html`) + тесты + 2 evidence-файла. Канон Checkup в этом коммите не
переписывался (только метка), Core-канон не сломан, ступени `PREV_*` не
затронуты (ретро-замены нет).

## 8. Блокеры выката (вне кода лейна)

1. **REQUIREMENT_DRIFT**: `requirements_gate.py check --stage plan` →
   `FAIL: authoritative source changed` (`07d944ea…` vs фактический
   `d69c104d…`); ADDENDUM #2 не разложен по items (2 строки PENDING), карта
   strict → review/release gate закрыты. Нужна сверка карты PM, не правка кода.
2. **Доказательства**: числа/атрибуция падений (см. §6) должны быть заменены
   фактическими; иначе release-отчёт опирается на непроверяемые данные.

Итог: freepseech в Core подтверждён, 8 withheld не активированы, миграция
идемпотентна. Код можно везти после сверки карты и исправления чисел.
