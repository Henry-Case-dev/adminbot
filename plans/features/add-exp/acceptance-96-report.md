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
| `occasional` — >0 и ≤40% разговорных | 0/6 (0/7 с добором) | **FAIL** |
| `frequent` — ≥50%, ≥2× occasional, ≥3 контекста | 0/7 (0/9 с follow-up) | **FAIL** |
| Изоляция frequent-чат vs off-чат | A frequent / B off, payload-строки режимов по чатам | **PASS** |

## Ключевая находка (честно)

Слой **реально доходит до модели**: `<Expression_Settings>` + строка режима +
точный текст preview — в **28/28** L2-wire-payload (Direct; плюс tool_phase —
54/81 composes с рендеренным слоем; Initiative/authorial — маркер есть),
preview == production trace, переключение без рестарта, reread подтверждён.
**Но модель не применяет частотную инструкцию**: 9 подряд контролируемых
разговорных `frequent`-проб без мата → класс **`model_ignored_instruction`**
(эмитирован в `mca_events.expression_diag`). Это не отказ провайдера: прямая
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

Удалено **42** тестовых сообщения (осн. 31/31 — включая anchor добора,
добитый после безопасной идентификации; follow-up 9/9; пропущенный ответ на
цитату 1; остаток «1 фото 95a» — 1). Остаток 95a закрыт безопасной
идентификацией Bot API (edit: 1166467 — чужое, не тронуто; 1166469 —
сообщение бота → удалено). Синтетические строки: 36 `bot_replies`,
36 `bot_reply_parents`, 4 `throttle_state`; остаточных строк по нашим mid — 0.

