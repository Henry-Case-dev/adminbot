# ACCEPTANCE-96 — сводный отчёт: живая приёмка ADD-EXP Ф6 (прод 2.58.96)

- **Прод:** 2.58.96 @ `95d11472` (T0 2026-10-19 14:51:18Z, MainPID 3739015,
  NRestarts=0; healthz 2.58.96 loopback+HTTPS, `user_version=36`,
  `TRACKED_MOD=0` до/после; журнал волн: ERR/CRITICAL/Traceback=0, SKIPS=0,
  RuntimeWarning=0; 3 grep-совпадения «402» — фрагменты таймстампов, не
  HTTP 402).
- **Полный отчёт и эвиденс:** `plans/features/add-exp/evidence/release-25896/acceptance/README.md`
  (+ `harness/`, `runs/`, `followup/`, `checksums.json`).
- **Метод:** контролируемый harness на проде (ACCEPTANCE-91…95 bootstrap,
  реальная Bot API-доставка, реальные PG/SQLite/провайдеры); 6 SSH-сеансов,
  паузы ≥90 c; прод-код не менялся; временные настройки — только chat-scope
  тестовых чатов A/B с точным восстановлением.

## Что прогнано

- **27 ходов** основной волны: 7 контекстов × 3 режима (дружеский стёб, спор,
  короткий ответ, быт, шутка/ирония, нейтральная техзадача, фактчек) +
  3 повторяемости (стёб/короткий/шутка) + 2 жанровые пробы (цитата с матом,
  тех-сводка); переключение режимов через `POST /api/speech/expression`
  (chat-scope чата A; global не менялся — `allowed`→`occasional`).
- **Изоляция (follow-up):** A=frequent и B=off **одновременно**; B-L2-payload
  содержит строку `off` (2/2), A — `frequent` (2/2); B 0/2 мата.
- **Маршруты:** Direct (26 ходов), Initiative (`generate_initiative_reply` —
  payload с маркером+строкой frequent), авторский жанровый
  (`authorial_system`, nostalgia — маркер+строка frequent), фактчек/тех-сводка
  по жанровому контракту (факты целы, мат не форсируется).
- **«Проверить вживую»:** 2 пробы (occasional и frequent), HTTP 200,
  `expression_marker=true`, `profanity_roots=0`, без доставки.
- **not_owner_approved:** seed 18/12 → повтор skipped; 12 драфтов
  `owner_approved=0`; `<Expression_Examples>` в payload = 0 — в runtime не идут.

## Числа по критериям §7.2

| Критерий | Факт | Вердикт |
|---|---|---|
| `off` — 0 мата в собственных формулировках | 0/5 разговорных; цитата не искажена; `off`+«выругайся» → «Нет» | **PASS** |
| `occasional` — >0 и ≤40% разговорных | 0/6 (0/7 с добором — 7-я проба дубль контекста `everyday`) | **FAIL** |
| `frequent` — ≥50%, ≥2× occasional, ≥3 контекста | 0/7 (0/9 с follow-up) | **FAIL** |
| Изоляция frequent-чат vs off-чат | main — **PARTIAL** (дефект порядка harness: A осталась в occasional); корректно — follow-up: A frequent / B off, payload-строки режимов по чатам (B off 2/2, A frequent 2/2), B 0/2 мата | **PASS** (follow-up) |

## Восстановление настроек (честно)

«До == после» для **28 override-ключей** A+B доказано от `p0b` (срез после
main-restore) до финального restore follow-up; главный `p0` ключи не снял
(`failed:DataError` — запрос лейна). Изменённый ключ и global-документ
доказаны отдельно: `character.expression` (global) — `revision=1`,
`profanity=allowed`, `updated_at=2026-10-18T14:37:25Z` — идентично до/после;
в chat-overrides ключа нет ни до, ни после; API: `chat_present=false`,
`inheritance=global`. Рестартов не было (MainPID/NRestarts).

## Бюджет LLM

Основная волна: **137** = **56 пробных** (27 `l1_planner` + 29 `l2_writer`) +
**81 служебный** (machine-вызовы боевого пайплайна); probe-attributable —
**≤~60** (в ориентире), служебные — свойство прода, не дубли проб. Follow-up
≈37. `runs/verify.out` — UTF-16 (redirect PowerShell), содержит `VERIFY PASS`;
BOM/rc=127 follow-up-журнала — данные валидны (счётчики/SQLite-проба в
`accept96b-run.log`).

## Ключевая находка (честно)

Слой **реально доходит до модели**: `<Expression_Settings>` + строка режима +
точный текст preview — в **28/28** L2-wire-payload (Direct; плюс tool_phase —
54/81 composes с рендеренным слоем; Initiative/authorial — маркер есть),
preview == production trace, переключение без рестарта, reread подтверждён.
**Но модель не применяет частотную инструкцию**: 9 подряд контролируемых
разговорных `frequent`-проб без мата → класс **`model_ignored_instruction`**
(эмитирован **follow-up harness-ом через прод-хелпер**
`mca_expression.emit_expression_diag`; SQLite-проба `mca_events`:
`ts=1792425292`, `outcome=failed`, `reason_code=source_missing`, чат A;
поэтому `EXPR_DIAG=0` в журнале сервиса — **не противоречие**: эмиссия
сделана harness-процессом, durable-запись в общей SQLite, а не
прод-сервисом). Это не отказ провайдера: прямая
просьба «скажи матерное» в frequent дала «Понедельник — это пиздец, а не
день», а постпроцессор мат не режет (raw == доставка). Критерий завершения
ADD-EXP («часто меняет типичные ответы, эпизодически — редкий наблюдаемый
мат») на текущей живой модели **не достигнут**; решение (усиление инструкции
/ одобрение few-shot владельцем / смена модели) — следующий слот, карта и
леджер этим лейном не правились.

## Закрытие RFL-строк (предложение леджеру, не правка карты)

- `EXP-RUNTIME.WIRING` — **live-подтверждено** (Direct/tool_phase/Initiative/
  authorial; ревизия слоя; нет `expression_absent` при активной настройке;
  `budget_excluded` не наблюдался).
- `EXP-RUNTIME.PAYLOAD` — **live-подтверждено** (complete payload с маркером и
  строкой режима; доставленный текст == raw; подавления нет).
- `EXP-ACCEPT.ROUTES` — маршруты/override/GLOBAL/без-рестарта/reread/preview
  vs trace/изоляция — **подтверждено**.
- `EXP-ACCEPT.LIVE-SET` — набор выполнен (27+7 ходов, числа выше), но
  поведенческий критерий (`frequent` заметно чаще `occasional`) **не
  выполнен** → строка **не закрывается** как VERIFIED.
- `EXP-ACCEPT.CRITERION` — **не достигнут** (`model_ignored_instruction`).

## Уборка

**45 новых удалений**: основная волна 33 (`cleanup-register.json`: A — 30,
B — 3), follow-up 9 (A — 6, B — 3), ответ на цитату `1166725` (96d), anchor
добора `1166670` (96f), остаток «1 фото 95a» `1166469` (идентификация Bot API
по edit-пробе: `1166467` — чужое, не тронуто; `1166469` — сообщение бота →
удалено; в follow-up-регистре `already_deleted` — повторная проверка после
residual-шага). Синтетические строки: 36 `bot_replies`, 36
`bot_reply_parents`, 4 `throttle_state`; остаточных строк по нашим mid — 0;
safety: `1166467`/`1166671`/`1166672` — чужие, не тронуты.

