# UR-G / UR-B (остаток) — независимое ревью r2 (узкая дельта коррективы URGB-R1-F1)

Только дельта после `2837a719f`: кандидат `8929f04cb`, база `af8de2ac6`
(2.58.249). Artifact r1 не изменён (sha256 `9da4c9e8…`, проверено).

```json
{
  "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
  "candidate": "8929f04cbc91b02ba1b2b9557b24f92a5af5d304",
  "previous_r1_candidate": "6d10d35de968963495ca5a03c639d370cfbea359",
  "previous_r1_evidence_head": "2837a719f0456085cc4d08538fd2f0638f4822a0",
  "base": "af8de2ac6e59f4c0b899c0c839f02258a9e02236",
  "reviewer_session": "ses_deb8ae678ffenl0ElYbgKFje6D",
  "f1_status": "CLOSED",
  "rows": {
    "UR-RES-01": {"verdict": "PROVEN", "recommendation": "VERIFIED"},
    "UR-30.2": {"verdict": "PROVEN", "recommendation": "VERIFIED (остаток: композитный тест не утверждает явно число чанков и retry)"},
    "UR-07.3": {"verdict": "PROVEN", "recommendation": "VERIFIED"},
    "UR-17.7": {"verdict": "PROVEN_DETERMINISTIC", "recommendation": "VERIFIED (остаток: живая формулировка — агентская preprod-проверка)"},
    "UR-17.8": {"verdict": "PROVEN_DETERMINISTIC", "recommendation": "VERIFIED (остаток: живая формулировка — агентская preprod-проверка)"}
  },
  "findings": [
    {
      "id": "URGB-R1-F1",
      "severity": "major",
      "disposition": "IN_SCOPE",
      "blocking": false,
      "same_as_open": true,
      "state": "CLOSED",
      "closure_evidence": "sent -> delivery=true/tg=[id]; send fail -> context=error, delivery.outcome=error/reason=initiative_error; guard cancel -> cancelled; react -> reacted/channel=react; silent -> silent; подавленный _initiative_finish -> safety net error/unaccounted_exit, success не выдаётся"
    },
    {
      "id": "URGB-R2-F2",
      "severity": "minor",
      "disposition": "BACKLOG_ONLY",
      "blocking": false,
      "same_as_open": false,
      "title": "turn_trace.close(): digest_match/unexplained_text_change считаются ДО установки delivered_digest (предсуществующее, проявляется и на Direct)"
    }
  ],
  "tests": {
    "candidate": {"tests/test_ur_acceptance_trace.py": "6 passed", "tests/test_ur_search_first.py": "8 passed", "neighbours": "135 + 203 + 143 = 481 passed"},
    "base_2837a719f": {"tests/test_ur_acceptance_trace.py": "3 failed / 3 passed"},
    "pre_existing_sets": "25 failed / 78 passed и 20 failed / 85 passed — списки FAILED идентичны базе af8de2ac6"
  },
  "base_red": "2837a719f: TestUrRes01DeliveryStage — 3 failed (delivery None при context success; react -> context None), 3 passed",
  "mutations": [
    {"id": "MUT-1", "file": "services/direct_chat_service.py", "change": "успешный выход без delivery (note_delivery убран)", "killed": ["test_sent_initiative_turn_has_delivery_true"], "result": "1 failed / 5 passed"},
    {"id": "MUT-2", "file": "services/direct_chat_service.py", "change": "путь сбоя вызывает success-хелпер с delivery", "killed": ["test_failed_send_is_not_success_without_delivery"], "result": "1 failed / 5 passed"}
  ],
  "restored": "git checkout HEAD -- services/... после каждой мутации; git status --porcelain пуст; HEAD 8929f04cb",
  "probes": [
    "probe-A: реальный handle_initiative — sent/error/guard-cancel/react/silent проверены проекцией Inspector; все 5 терминальных путей имеют delivery stage и честный исход",
    "probe-B: порядок событий sent-хода — direct_turn_delivery до direct_turn_context (контекст больше не эмитится до отправки)",
    "probe-C: _initiative_finish подавлен -> finally фиксирует error/unaccounted_exit, context != success",
    "probe-D: turn_trace.close() на неизменённом 2837a719f и на кандидате даёт одинаковый digest_match=false при равных digest (предсуществующее)"
  ],
  "write_scope_violations": [],
  "ui_gate": "web/** в дельте отсутствует; Playwright/Browser Use не запускались (нет изменения разметки/JS). Наблюдаемый результат проверен проекцией web.api.routes._turn_chain_view — тем же кодом, что отдаёт Inspector.",
  "deploy_or_merge": "нет"
}
```

## Что именно проверено в дельте

Прочитано: `git diff 2837a719f 8929f04cb` по `services/direct_chat_service.py`
(+137/−22), `services/turn_trace.py` (+14), `tests/test_ur_acceptance_trace.py`
(+134/−3); весь `handle_initiative` (20895–21632), `_initiative_finish`,
`_initiative_trace_begin`, `plan_initiative_decision`,
`generate_initiative_reply`, `_execute_initiative_react`, `terminal_state`,
`turn_trace.close/emit_*`, `web/api/routes._turn_chain_view`.

1. **Терминальные пути.** Перечислены все `return` внутри `handle_initiative`:
   21 `return`, у 19 стоит `_initiative_finish` (или `close`) непосредственно
   перед выходом; два оставшихся — ранние `disabled`-выходы ДО старта трассы
   (закрывать нечего, `finally` видит пустое состояние). Пути: silent по
   решению, delivery_not_text, candidate_ready, intent_closed,
   already_answered, direct_pending, l1_unavailable, react (+recheck-react),
   l1_silent, writer_failed (оба), recheck-cancelled, publish_guard, недоступная
   цель reply, target_gone, sent, error.
2. **Независимый прогон терминальных путей** (свой probe, удалён):

```
P1 sent      context=success  delivery={success, initiative_reply, tg=[8801]}
P2 send fail context=error    delivery={error, initiative_error}, event=skipped
P3 guard     context=cancelled delivery={cancelled, publication_conflict}
P4 react     context=reacted  delivery={success, channel=react, l1_react}
P5 silent    context=silent   delivery={silent, l1_silent}
```

   Инвариант «success без доставки невозможен» проверен на каждом пути:
   `context.outcome == "success"` только вместе с `delivery.outcome == success`.
3. **Порядок.** У sent-хода события идут
   `['direct_turn_writer', 'direct_turn_delivery', 'direct_turn_context']` —
   контекст эмитится после фактической отправки; `emit_context` идемпотентен,
   дублей нет.
4. **Страховка `finally`.** При программно подавленном `_initiative_finish`
   ход всё равно закрывается честно: `delivery.outcome=error`,
   `reason=unaccounted_exit`, `context.outcome=skipped` (не success).
5. **`terminal_state()`** — read-only: читает `stop_outcome`/`stop_reason`/
   `_delivery_emitted`, ничего не пишет; используется только в
   `direct_chat_service` (нет второго стора/трассы).
6. **RED на старом tip.** `git checkout 2837a719f -- services/...` + новые
   тесты: `3 failed / 3 passed`; причины — `stages.delivery is False` при
   `context.outcome == success` (sent и failed-send) и отсутствие трассы у
   react. После проверки файлы восстановлены.

## Мутации (обе убиты, всё восстановлено)

| ID | Изменение | Результат |
|---|---|---|
| MUT-1 | успешный выход без `delivery` (убрана реальная доставка) | RED `test_sent_initiative_turn_has_delivery_true` (1 failed / 5 passed) |
| MUT-2 | путь сбоя вызывает success-хелпер с delivery | RED `test_failed_send_is_not_success_without_delivery` (1 failed / 5 passed) |

После каждой — `git checkout HEAD -- services/...`; `git status --porcelain`
пуст, HEAD `8929f04cb`.

## Регресс

- Кандидат: `test_ur_acceptance_trace.py` 6 passed, `test_ur_search_first.py`
  8 passed.
- Соседние наборы: `asap8_f6_initiative + ur_d_writer + ur_e_speech +
  ur_turn_engine + ur26_init_fc_payloads + ur_b_live_wiring +
  mod_acl_ux_01_m21_gates + nostalgia_proactive_recall` — 135 passed;
  `direct_chat + ur_ui_effective_config + rlr_observability` — 203 passed;
  `evol_social_frame + evol_evidence_routing + soul1_style_payload` —
  143 passed.
- Предсуществующие падения идентичны базе `af8de2ac6` (сравнение списков
  `FAILED` построчно, различий нет): `asap8_initreply_binding +
  initiative_coordination + mca09_intents_block_e + initiative_delivery_telemetry`
  = 25 failed / 78 passed; `nostalgia_worker + asap5_integration_w3` =
  20 failed / 85 passed.

## Строки (финально)

- **UR-RES-01 — PROVEN / VERIFIED.** Тот же шов `turn_trace`, одинаковый набор
  стадий direct/initiative, исход совпадает с фактом на всех терминальных
  путях, `react` имеет собственный канал, `finally` не даёт «успеха без
  доставки». Блокер r1 закрыт.
- **UR-30.2 — PROVEN / VERIFIED.** Композитный real-path тест зелёный на базе и
  кандидате (один ledger, chat-scope, реальные даты, ревизия, failed-строка,
  TTL, вчерашняя цитата, L2-payload). Остаток не блокирующий: явных
  утверждений о числе чанков и retry в композитном тесте нет (механизм
  покрыт связанными тестами UR-23.4).
- **UR-07.3 — PROVEN / VERIFIED.** Структурный источник + ограничения, запрет
  «я проверил» при пустой выдаче, отсутствие выдуманных URL; дата вынесена в
  `UR-SRC-DATE` авторитетной картой; adaptive no-growth — существующий
  зелёный `TestAdaptiveNoGrowth`. Независимый probe r1 подтвердил, что дата из
  выдачи доезжает до L2.
- **UR-17.7 / UR-17.8 — PROVEN (детерминированная часть) / VERIFIED.**
  Реальный вызов поиска, честный набор инструментов (гейт снимает вызов),
  честная граница при пустой выдаче, тема не отводится. Живая формулировка —
  свойство модели: агентская preprod-проверка, не критерий закрытия
  инженерной строки (bounded acceptance).

## Некритичные наблюдения (backlog, не блокируют)

- **URGB-R2-F2.** `turn_trace.close()` вызывает `_divergence()` ДО установки
  `delivered_digest`, поэтому на stop-путях (initiative silent/error/cancelled,
  а также Direct silent) карточка показывает `digest_match=false` и
  `divergence_reason=unexplained_text_change` при равных `raw_final_digest` и
  `delivered_digest`. Доказано unit-probe одинаково на `2837a719f` и
  кандидате — дефект предсуществующий, кандидатом не вызван; стоит исправить
  порядок в существующем `close()` отдельной мелкой правкой.
- Для silent/recheck-demote контекст может остаться с `outcome=skipped`
  (эмиссия внутри `plan_initiative_decision`), тогда как payload доставки
  называет `silent`; оба исхода не-success, ложного успеха нет.
- При сбое на втором чанке частичная отправка в трассе не отражается (общий
  исход `error` без первых id) — поведение не измерялось отдельно, отмечено
  как остаток.

## Границы и уборка

- UI-гейт (Playwright + Browser Use) не запускался: `web/**` не менялся,
  разметка/JS те же. Наблюдаемая сторона проверена той же проекцией
  `web.api.routes._turn_chain_view`, что использует Inspector.
- Живой/preprod прогон диалоговых формулировок UR-17.7/17.8 не выполнялся.
- Деплой/merge/push не выполнялись. Все временные probe-файлы и скрипты
  мутаций удалены; рабочее дерево чисто, HEAD `8929f04cb`.