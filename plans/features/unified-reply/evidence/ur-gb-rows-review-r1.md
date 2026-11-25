# UR-G / UR-B (остаток) — независимое ревью r1

Ревьюер: независимая проверка контракта строк `UR-RES-01`, `UR-30.2` (UR-G),
`UR-07.3`, `UR-17.7`, `UR-17.8` (UR-B). Пишущий код/тесты не менялись;
изменения рабочего дерева после проверки отсутствуют.

```json
{
  "verdict": "NEEDS_FIXES",
  "candidate": "6d10d35de968963495ca5a03c639d370cfbea359",
  "evidence_head": "2837a719f0456085cc4d08538fd2f0638f4822a0",
  "base": "af8de2ac6e59f4c0b899c0c839f02258a9e02236",
  "base_version": "2.58.249",
  "reviewer_session": "ses_deb8ae678ffenl0ElYbgKFje6D",
  "rows": {
    "UR-RES-01": {"verdict": "NEEDS_FIXES", "recommendation": "PENDING до исправления F1"},
    "UR-30.2": {"verdict": "PROVEN", "recommendation": "VERIFIED (остаток: явные утверждения про несколько чанков и retry в композитном тесте отсутствуют)"},
    "UR-07.3": {"verdict": "PROVEN", "recommendation": "VERIFIED (дата веб-источника действительно вынесена в UR-SRC-DATE авторитетной картой; adaptive no-growth — существующий зелёный тест)"},
    "UR-17.7": {"verdict": "PROVEN_DETERMINISTIC", "recommendation": "VERIFIED с остатком: живая формулировка — агентская preprod-проверка, не гейт закрытия"},
    "UR-17.8": {"verdict": "PROVEN_DETERMINISTIC", "recommendation": "VERIFIED с остатком: живая формулировка — агентская preprod-проверка, не гейт закрытия"}
  },
  "findings": [
    {
      "id": "URGB-R1-F1",
      "severity": "major",
      "disposition": "IN_SCOPE",
      "blocking": true,
      "same_as_open": false,
      "title": "Инициативный ход не пишет стадию доставки, а контекст объявляет success ДО отправки"
    }
  ],
  "tests": {
    "candidate": {"tests/test_ur_acceptance_trace.py": "3 passed", "tests/test_ur_search_first.py": "8 passed"},
    "base": {"tests/test_ur_acceptance_trace.py": "2 failed / 1 passed", "tests/test_ur_search_first.py": "8 passed"},
    "neighbours_candidate": {"ur_turn_engine+ur_d_writer+asap8_f6_initiative+ur_b_live_wiring+ur26_init_fc_payloads": "92 passed"}
  },
  "base_red": "tests/test_ur_acceptance_trace.py::TestUrRes01* — 2 failed (assert [] на direct_turn_context инициативы), TestUr302 — 1 passed",
  "mutations": [
    {"id": "MUT-A", "file": "services/direct_execution.py", "change": "статус источника {src.status} -> ok", "killed": ["test_empty_search_payload_forbids_claiming_checked"], "result": "1 failed / 7 passed"},
    {"id": "MUT-B", "file": "services/direct_chat_service.py", "change": "ветка decision.required_unmet отключена (guard-строки не попадают в payload)", "killed": ["test_empty_search_payload_forbids_claiming_checked", "test_no_evidence_means_no_fabricated_research"], "result": "2 failed / 6 passed"},
    {"id": "MUT-C", "file": "services/direct_chat_service.py", "change": "модульный гейт flags.search_enabled игнорируется", "killed": ["test_l1_sees_only_tools_that_are_really_available"], "result": "1 failed / 7 passed"}
  ],
  "restored": "services/direct_chat_service.py и services/direct_execution.py восстановлены (git checkout --); git status --porcelain пуст, HEAD 2837a719f",
  "probes": [
    "probe-1: реальный handle_initiative, отправка успешна -> direct_turn_writer=1, direct_turn_context(outcome=success)=1, direct_turn_delivery=0",
    "probe-2: send_text бросает -> handle_initiative вернул status=error, direct_turn_context(outcome=success)=1, delivery=0",
    "probe-3: живой handle() с датой в выдаче -> '[ИСТОЧНИК 1 | execute_web_search | ok | дата публикации: 2025-03-11]' в L2-payload",
    "probe-4: пустая выдача -> '[ИСТОЧНИК 1 | execute_web_search | error | дата публикации не сообщается источником]'"
  ],
  "write_scope_violations": [],
  "ui_gate": "web/** в диффе отсутствует; Playwright + Browser Use не запускались (нет изменения разметки/JS). Видимый эффект — существующая карточка инспектора для нового вида хода; дефект F1 доказан на уровне контракта события, карточка читает те же stages.",
  "deploy_or_merge": "нет"
}
```

## Что проверялось и на чём

Кандидат: worktree `feat/ur-gb-rows`, HEAD `2837a719f`, продуктовый диф
`6d10d35de`. База: существующий worktree `release/ur-f-2.58.249` на
`af8de2ac6` (те же тестовые файлы копировались туда и удалены после прогона).
Тесты запускались интерпретатором основного checkout
(`C:\Code\Python\adminbot\.venv\Scripts\python.exe`) с cwd соответствующего
worktree (`sys.path[0]` = cwd, `services.turn_trace.__file__` из нужного
дерева проверен).

Прочитано (не только дифф):

- `services/direct_chat_service.py`: `plan_initiative_decision` (19481+),
  `generate_initiative_reply` (19759+), `handle_initiative` (20866+),
  `_execute_initiative_react` (20796+), `_l1_tool_subset` (9656+),
  `_l2_write_answer`/`note_l2_*`, `_send_direct_answer`/`_send_traced`
  (2404+, 11540+), `_evidence_writer_note` (9560+);
- `services/turn_trace.py` целиком (begin/get/note_l1/note_tools/emit_*/
  note_delivery/close, `_pack`/`_scrub`, `_context_emitted`-идемпотентность);
- `services/direct_execution.py`: `build_evidence_pack`, `_publication_label`,
  `_split_publication_date`, `resolve_search_axis`-потребители;
- `web/api/routes.py` (2580–2659: `stages`, `_TURN_DELIVERY_SCHEMA`),
  `web/app.js` (`turnMissing`, 21001–21005);
- карта `plans/features/unified-reply/requirements-map.json` **авторитетного
  planning-checkout** (`294c04627`), а не только копия ветки: там приёмка
  UR-07.3 уже содержит вынос даты в `UR-SRC-DATE` (владелец 11.11.2026),
  подтверждено также `plans/backlog.md:584` и
  `plans/features/unified-reply/evidence/release-2.58.184-ur-src-date.md`;
- `chat_prompts.py` (1438–1461): ось `knowledge_origin`/`search_intent`
  реально спрашивается у модели (устаревшая оговорка в докстринге
  `resolve_search_axis` — только текст, не поведение).

Шов трассы переиспользован: новая система не вводилась. `begin` вызывается
только при отсутствии трассы по тому же `correlation_id`; `note_l1`/
`note_tools` пишут в существующий `TurnTrace`; `emit_context` идемпотентен
(`_context_emitted`), повторная эмиссия на recheck — no-op; `L2`/проверка —
существующие `note_l2_request`/`note_l2_completion` из `_l2_write_answer`.
Текстов/URL в событиях нет (`note_l1`/`note_tools` — только коды/числа).
Новых флагов/DDL/промптов нет. `flow="initiative"` проходит `_code`.

## RED на базе (независимо подтверждён)

`af8de2ac6`, те же два файла:

```
FAILED TestUrRes01SameStagesOnBothTraces::test_direct_and_initiative_expose_same_stage_sequence
E  AssertionError: инициативный ход не дал трассы хода: этапы L1 -> tools ->
   evidence на нём не наблюдаемы
E  assert []
FAILED TestUrRes01SameStagesOnBothTraces::test_initiative_silent_still_visible_without_tools
E  AssertionError: молчаливый инициативный ход не оставил трассы
E  assert []
2 failed, 9 passed
```

Кандидат: `11 passed`. RED именно на отсутствии события, а не на форме
утверждения (проверено чтением трейса падения).

## F1 (IN_SCOPE, blocking) — доставка инициативы не попадает в трассу, а контекст врёт об исходе

**Факт 1.** Успешно отправленный инициативный ход пишет `direct_turn_writer` и
`direct_turn_context`, но **никогда** `direct_turn_delivery`:
`handle_initiative` отправляет текст через `_tg_send.send_text` (21345–21383) и
не вызывает `_ttrace.note_delivery`/`close`; `note_delivery` существует только
в Direct-доставке (`_send_direct_answer`/`_send_traced`). Следствие:
`web/api/routes.py` отдаёт `stages.delivery=false`, а карточка инспектора
(`turnMissing`, `web/app.js:21001`) печатает «нет данных (трасса старше
версии)» для свежей трассы — прямо неверное утверждение.

**Факт 2.** `direct_turn_context` для инициативы эмитится внутри
`generate_initiative_reply` (20293) **до** фактической отправки и с
фиксированным `outcome="success"`. Если отправка падает (`send_text` бросает)
или отменяется (`publish_guard`, привязка reply, recheck-demote), трасса
остаётся с `outcome=success` и без стадии доставки: ход, ничего не
доставивший, выглядит успешным.

**Факт 3.** Ветка `react` (`_execute_initiative_react`) реально ставит реакцию
и пишет `initiative_delivery_manifest`, но трасса хода уже закрыта
`outcome="skipped"` из `plan_initiative_decision` (19748): форма доставки
«реакция» в трассе отсутствует и заменена «пропуском».

Независимый прогон (временный probe, удалён после; создан и закрыт
ревьюером):

```
PROBE1 result: sent
PROBE1 events: [... 'direct_turn_writer', 'direct_turn_context',
              'initiative_writer_generated', 'speech_extent',
              'initiative_recheck_passed', 'initiative_recheck',
              'recheck_deferred', 'initiative_sent',
              'initiative_delivery_manifest', 'initiative_decided']
PROBE1 ctx_outcome: ['success']   writer: 1   delivery: 0
PROBE2 result: error              ctx_outcome: ['success']   delivery: 0
```

Ожидаемо по приёмке строки: «на фактической трассе direct и initiative видны
одинаковые этапы … -> отправка». Сейчас у инициативы нет этапа отправки вовсе,
а исход объявляется до неё. Это дефект самой строки, которую срез объявляет
реализованной, а не независимая мелочь.

Тест кандидата этого не ловит: он утверждает только набор полей
`direct_turn_context`, `tools` и `coverage`, и не проверяет ни наличие стадии
доставки, ни исход проваленной/отменённой отправки.

Направление исправления (без новой системы/гейта): эмитить доставку в
`handle_initiative` на всех терминальных путях (sent / reacted / cancelled /
writer_failed / error) существующими `_ttrace.note_delivery`/`note_stop` +
`close`, а `direct_turn_context` эмитить в конце хода (он идемпотентен), чтобы
`outcome` соответствовал факту. Тест строки расширить: sent -> `stages.delivery`
и реальные tg id; send-сбой -> `failed`/`skipped` без success; react -> форма
`react`.

## Остальные строки

- **UR-30.2 — PROVEN.** Композитный тест на frozen UTC clock с реальными
  путями записи (`record_bot_output`, `_factcheck_temporal`,
  `SummaryGenerator._record_published_output`, `collect_thread_chain`) зелёный
  и на базе, и на кандидате; проверяет один ledger, chat-scope, реальные даты
  отправки, ревизию, исключение failed-строки, вчерашнюю цитату при истёкшем
  TTL и реальный L2-payload (своя дата, чужие слова отсутствуют, нет
  `<Style_Anchors>`/«имитируй»). Остаток (не блокирующий): композитный тест не
  утверждает явно число чанков многочанкового вердикта и отдельный retry —
  механизм чанкования и ledger покрыты связанными тестами UR-23.4 из карты.
- **UR-07.3 — PROVEN.** Структурный `[ИСТОЧНИК N | tool | status | дата]`,
  выдержка, запрет приписывать проверку при пустой выдаче, отсутствие
  выдуманных URL — доказаны живым `handle()`; дата веб-источника действительно
  вынесена владельцем в `UR-SRC-DATE` (авторитетная карта + backlog +
  evidence 2.58.184), поэтому в приёмке строки не предъявляется; «остановка
  adaptive-добора» доказана существующим
  `TestAdaptiveNoGrowth::test_empty_tool_result_stops_adaptive_instead_of_looping`
  (3 passed на кандидате). Независимый probe: дата из выдачи реально доезжает
  до L2 (`дата публикации: 2025-03-11`), пустая выдача даёт честную пометку.
- **UR-17.7 — PROVEN (детерминированная часть).** Гейт
  `feature_gates.module_enabled` реально снимает `execute_web_search`
  (мутация MUT-C делает тест RED: ровно один вызов провайдера при выключенном
  модуле), актуальный внешний запрос даёт ровно один реальный вызов до L2,
  разговорный вопрос не подменяется выдуманной проверкой. Остаток: «честно
  описывает инструменты» — свойство живой модели (агентская preprod-проверка,
  не критерий закрытия инженерной строки); видимость набора доказана на уровне
  анонсера, не текстом L1-payload.
- **UR-17.8 — PROVEN (детерминированная часть).** Научное утверждение
  проверяется поиском (источник в payload, вызов Writer'а, текст доставлен),
  пустая выдача даёт границу знания без выдуманных ссылок/исследований
  (мутация MUT-B делает тест RED). Остаток тот же: формулировка — живая модель.

## Регресс и предсуществующие падения

Кандидат и база, одинаковый набор:

```
25 failed, 78 passed
tests/test_asap8_initreply_binding.py       14 failed
tests/test_initiative_coordination.py        4 failed / 56 passed
tests/test_mca09_intents_block_e_round1040.py 5 failed / 11 passed
tests/test_initiative_delivery_telemetry.py  2 failed / 11 passed
```

Списки имён `FAILED` на базе и кандидате совпадают построчно
(`Compare-Object` — без различий). Причина группы — локально недоступный
QRNG/random-провайдер, изменением не вызвана. Соседние наборы вокруг
затронутых путей на кандидате: `test_ur_turn_engine`, `test_ur_d_writer`,
`test_asap8_f6_initiative`, `test_ur_b_live_wiring`,
`test_ur26_init_fc_payloads` — 92 passed.

## Мутации (все убиты, всё восстановлено)

| ID | Файл | Изменение | Результат |
|---|---|---|---|
| MUT-A | `services/direct_execution.py` | статус источника `{src.status}` → `ok` | RED: `test_empty_search_payload_forbids_claiming_checked` (1 failed / 7 passed) |
| MUT-B | `services/direct_chat_service.py` | ветка `decision.required_unmet` отключена | RED: `test_empty_search_payload_forbids_claiming_checked`, `test_no_evidence_means_no_fabricated_research` (2 failed / 6 passed) |
| MUT-C | `services/direct_chat_service.py` | модульный гейт `flags.search_enabled` игнорируется | RED: `test_l1_sees_only_tools_that_are_really_available` (1 failed / 7 passed) |

После каждой мутации файл восстанавливался `git checkout --`;
`git status --porcelain` пуст, HEAD `2837a719f`. Тестовые файлы,
скопированные на базу, удалены; временный probe-файл и вспомогательный
скрипт мутации удалены.

## Границы ревью

- UI-гейт (Playwright + Browser Use) не запускался: в кандидате нет диффа
  `web/**`, разметка/стили/JS не менялись. Видимый эффект — существующая
  карточка инспектора для нового вида хода; F1 доказан на уровне контракта
  события, который карточка и читает (`stages`/`outcome`). Если Orchestrator
  считает появление нового вида хода визуальным изменением, визуальная
  проверка карточки остаётся невыполненной.
- Живой/preprod прогон диалоговых формулировок UR-17.7/17.8 не выполнялся
  (нет доступа к живой модели в этом ревью) и не выдаётся за выполненный.
- Деплой/merge/push не выполнялись.

## Уборка

Все временные артефакты ревьюера (probe-тест, скрипт мутации, копии тестов на
базе, файлы сравнения в `%TEMP%\opencode`) удалены; рабочий worktree полосы
сохранён намеренно для коррективы F1.