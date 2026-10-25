# P0 FINAL — L1 A fallback + meta E2 (Builder, 25.10.2026)

Родитель: `93169a4e` (код `879b1653`), ветка `task/speech-p0-hotfix`.
Закрывает два блокера `probes_final5.md`: **F1 (L1 A)** и **F2 (meta E2)**.
PROD/TG/LLM не задействованы; live-прогон остаётся за DevOps.

## 1. L1 A — дет. fallback смыслового акта (§1.1)

RED (final5): A «Бот проанализируй мои сообщения в чате и скажи, я злобный?»
→ план `action=reply, response_act=answer, extent=compact`, `mode=casual`,
payload analysis **0×0**, 515/546 симв.

Причина: план L1 валиден, но `response_act=answer` не даёт
`analysis_directive_needed` → в payload нет analysis/quote-директив, режим
`casual`. Детерминированная температура (0.0) уже была — маршрут не меняла.

Фикс (`services/direct_l1.apply_research_fallback`, вызов в
`DirectChatService._plan_direct_l1` после ladder, до `emit_l1_plan_event`):

* условие: `action=reply`, `needs_clarification is not True`,
  `response_act != research`, и **существующий**
  `response_extent.classify_request(query).task_kind == "research"`;
* повышается **только** `response_act` → `research`; `extent/structure/
  delivery_hint/tone` плана не меняются (глубина разбора не задаёт длину);
* новых списков слов/регулярок нет; casual/opinion не форсируются —
  классификатор там даёт `social_chat`/`explanation`;
* silent/react/clarification не трогаются; диагностика
  `research_fallback=response_extent` (Inspector) + self-check.

Итог для A: `research` + `serious`, extent `compact` сохраняется,
analysis/`QUOTE_FIDELITY` **1×1×1**, `NO_META` **1×** на payload (серьёзный
режим их не дублирует). B/E/forced уже на `research` — no-op.

## 2. Meta E2 — «Ладно, давай по фактам.» (§3)

RED: guard не снимал E2 — в `_L2_META_ANNOUNCE_RE` не было ветки
«ладно + давай» без глагола из списка.

Фикс: узкая ветка `ладно/ок/так/… + давай(те) + по фактам|факту|делу|
существу|порядку|к делу|к сути`. Границы прежние: удаляется ровно одно
предложение первого абзаца (≤90, без `:`/тире/кавычек), обязан остаться
текст ≥20 букв; остальной текст байт-в-байт. Содержательное «Ладно, давай в
субботу.» и «Ладно, давай по фактам: …» не режутся (тесты).

## 3. Проверки

| Проверка | Результат |
|---|---|
| `py_compile` 4 файла | EXIT 0 |
| `tests/test_p0_final_l1_guards.py` | **41 passed** |
| L1/clar/settings/d04/W1 набор | 149 passed, 2 failed (pre-existing) |
| speech-p0 набор (corrective/serious/texts/a2/simplify/extent/telemetry) | **107 passed** |
| composer/matrix/prompts набор | 55 passed, 5 failed (pre-existing) |
| harness `--self-check` | **PASS 21/21**, EXIT 0 (`l1_research_fallback_present`, `l2_meta_guard_present`, `l1_temperature_deterministic_zero`, Core 3294) |

Pre-existing (доказано на чистом `93169a4e` во временном worktree, без этих
правок — те же 7 падений): `test_asap7_direct_settings.py::test_migration_v35*`
(PRAGMA user_version = 37, тест ждёт 35), `test_soul1_composer_parity_off.py`
5× (записанный дамп канона `8ef75b632d12` vs действующий `cc020660ae03` +
слой `<Speech_Base>`). К этому лейну не относятся.

## 4. Осталось

* Live: тот же `probes_full/harness_probe_full.py` из нового коммита —
  A/B natural 2/2 research, A с analysis 1×1, forced 2/2, repeats 2,
  strict meta 0/16 (DevOps).
* Reviewer — независимый recheck нового SHA; PM — привязка карты.
