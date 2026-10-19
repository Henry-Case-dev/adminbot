# REV-ACCEPT-96 — независимый вердикт приёмки ADD-EXP Ф6 (прод 2.58.96)

**Вердикт: Needs Fixes.** Приёмка проведена честно и воспроизводима: wire-слой
доставлен, но явный критерий завершения источника §4 **не достигнут**.
Это не претензия к качеству эвиденса и не причина откатывать релиз: глобальная
настройка не менялась, тестовые чаты восстановлены, боевой default остался
`occasional`. Parent не DONE.

## 0. Кандидат и режим

- **Код/прод:** `2.58.96` @ `95d11472b9e533b554554918e3efa6b42125260b`;
  healthz на ревью (20.10.2026): `{"status":"ok","version":"2.58.96"}`;
  deploy-эвиденс: MainPID 3739015, NRestarts=0, T0 2026-10-19 14:51:18Z.
- **Эвиденс приёмки:** `plans/features/add-exp/evidence/release-25896/acceptance/**`
  + `plans/features/add-exp/acceptance-96-report.md`; `checksums.json` — **53/53
  файла** совпали по sha256/bytes (мой прогон).
- **Карта:** `plans/features/add-exp/requirements-map.json`, `candidate_commit
  4a09e29a`; `check --stage review --slice EXP-ACCEPT --candidate 4a09e29a` —
  `errors=0`, EXIT 0. `--stage release --candidate 4a09e29a --deployed-commit
  95d11472` — EXIT 1 (5 RFL + пустой `deployed_commit`) — ожидаемо, карту этот
  лейн не правил.
- **Репо на ревью:** HEAD `21494565` (behavior-diag, evidence-only). Рабочее
  дерево содержит чужие незакоммиченные изменения (`web/app.js` и др.); они
  **не** использовались как кандидат и не входят в мой docs-коммит.
- Режим: read-only по коду/картам/проду; один HTTPS healthz; живых LLM-вызовов
  не делал; этот коммит — только review-документ + уже снятый эвиденс.

## 1. Приёмочный леджер

| Пункт | Статус | Доказательство |
|---|---|---|
| `EXP-RUNTIME.WIRING` | **VERIFIED** (live) | 27/27 L2-ходов с маркером; 28 L2-wire-вызовов (у `frequent-07` два l2-вызова); `wire_with_marker=28`, `wire_with_mode_line=28`, `wire_expected_text_present=28`; 54/81 composes с рендеренным слоем, 27 skip — только `profile:machine_stage`; Direct/tool_phase + Initiative/authorial (follow-up). |
| `EXP-RUNTIME.PAYLOAD` | **VERIFIED** (live) | Полный sample 7070 симв. с `<Expression_Settings>` и строкой `frequent` (`followup/summary.json → full_l2_system_sample`); raw == доставка (нет `postprocess_changed`); провайдер не ограничен — прямая просьба в `frequent` дала «Понедельник - это пиздец, а не день»; fallback/ошибок LLM 0. |
| `EXP-ACCEPT.ROUTES` | **VERIFIED** (follow-up) | A=`frequent` / B=`off` одновременно; wire-строки A 2/2 `frequent`, B 2/2 `off`; B 0/2 мата; override/global; reread через прод-API; preview==resolve; MainPID/NRestarts без рестарта. Основная волна дала `isolation=PARTIAL` (дефект порядка harness), follow-up перепроверил — это раскрыто в README §10.4. |
| `EXP-ACCEPT.LIVE-SET` | **VERIFIED** (набор выполнен) | 27 ходов основной волны (7 контекстов × 3 режима + 3 повтора + 2 жанровые, включая добор) + 7 follow-up; все ответы сохранены; распределение L1 — micro 16/compact 10/auto 1. Оговорка: 7-я occasional-проба — дубль `everyday`, не новая вариация. |
| `EXP-ACCEPT.CRITERION` | **FAILED** | `off` 0/5 (PASS); `occasional` **0/7** при требовании `>0`; `frequent` **0/7** (0/9 с follow-up) при требовании ≥50%, ≥2× occasional, ≥3 контекстов; `model_ignored_instruction` N=9. Источник §4: критерий не достигнут. |
| `EXP-ACCEPT.PREVIEW` | **VERIFIED** | `preview_eq_resolve=true` для off/occ/frequent; `text_sha12` = revision слоя (9de5c885b622 / 537816072dab / 6763c903ffc2); `expected_text_present=true` в каждом L2-wire. |
| `EXP-ACCEPT.REVIEW` | **VERIFIED** | Настоящий документ. |
| `EXP-INSTR.FEWSHOT` | **VERIFIED** (без изменения) | Seed 18/12, повтор skipped; 12 `expression_register` `owner_approved=0`; `<Expression_Examples>` в composed/wire = 0; 54 trace `not_owner_approved` — runtime честно не берёт черновики. |
| `EXP-RUNTIME.READSAVE/PRIORITY/DIAG`, `EXP-UI.*`, `ADD-1.E1…E7`, `EXP-DIAG-*`, `EXP-REG.QUEUE` | **VERIFIED (reused)** | Не переоткрывались: приёмка не меняла UI/код; противоречий текущему эвиденсу нет. |
| Уборка тестовых сообщений | **VERIFIED** (счётчик в отчёте исправить) | 45 новых удалений, residual 0; safety-пробы 1166467/1166671/1166672 — чужие, не тронуты. |
| Восстановление настроек | **VERIFIED** (с оговоркой baseline) | A/B `chat_present=false`, `inheritance=global`; global `revision=1`, `updated_at=2026-10-18T14:37:25Z`, `profanity=allowed`, `sharpness=sharp`; 28 override-ключей, `character.expression` отсутствует. |

## 2. Что я проверил независимо

- **Детектор мата:** прогнал прод-детектор `scan_own` на сохранённых текстах —
  `off` 0/5, `occasional` 0/7, `frequent` 0/7; дополнительно широкий список
  корней (хер/хрен/фиг/говн/жоп/срак/пидор/шлюх) — **ни одного пропущенного**
  мата. Числа harness совпали.
- **`runs/verify.out`:** воспроизвёл на committed-эвиденсе (UTF-16, `VERIFY PASS`):
  те же 0/5, 0/7, 0/7, isolation PASS (B 0/2), quote preserved, 28 ключей
  `before==after`, global doc равен, A/B override docs = null.
- **Wire/composes:** 28/28 L2-вызовов с маркером, строкой режима и точным
  текстом; 135 wire-вызовов всего; 81 compose = 27 `l1_planner` (machine) +
  27 `tool_phase` + 27 `l2_writer`; 54 рендера; `expression_absent`/
  `budget_excluded` при активной настройке — 0.
- **Провайдер/постпроцессор:** модель `deepseek/deepseek-v4.1-flash`; fallback 0;
  ошибок LLM 0; прямая просьба в `frequent` дала мат; цитата с матом в `off`
  воспроизведена дословно; raw == доставка.
- **`model_ignored_instruction`:** класс посчитан прод-функцией
  `classify_expression_response(probes=9, marker_present=true)`; в
  `accept96b-run.log` SQLite-проба показывает строку
  `mca_events`: `ts=1792425292`, `event_name=expression_diag`,
  `outcome=failed`, `reason_code=source_missing`, `chat_id=-1002661910336`.
  Событие эмитировано follow-up harness через прод-хелпер (не прод-процессом
  per-turn; поэтому `EXPR_DIAG=0` в журнале сервиса — это не противоречие).
- **Восстановление:** `p0.view_a` до — `chat_present=false`, `inheritance=global`;
  main restore A/B — HTTP 200, `chat_present=false`, `inheritance=global`;
  `p0b`/follow-up restore — 28 ключей, без `character.expression`; global doc
  побайтово равен. Главный `p0` не снял ключи (`failed:DataError`), поэтому
  равенство 28 ключей доказано от `p0b` (после main restore), а не от T0 —
  см. RELATED-2.
- **Уборка:** пересчитал регистры: 45 новых удалений (main 33 = A30+B3;
  follow-up 9 = A6+B3; quote 1166725; anchor 1166670; residual 1166469);
  синтетика 36 `bot_replies` + 36 `bot_reply_parents` + 4 `throttle_state`;
  residual 0. `1166469` в follow-up-регистре помечен `already_deleted`, потому
  что фактическое удаление сделал residual-шаг; это дубль-запись, не второе
  удаление.
- **Прод-спот:** один HTTPS healthz `2.58.96`; SSH/PG повторно не поднимал
  (минимум коннектов).

## 3. Блокирующая находка

### BLOCK-1 — критерий §4 не достигнут (occasional/frequent не меняют ответы)

- **Требование:** источник §4/критерий завершения: «часто» действительно меняет
  типичные ответы, «эпизодически» даёт редкий наблюдаемый мат, «без мата»
  запрещает его в собственных высказываниях; все режимы реально доходят до
  production LLM. Дизайн §7.2: `off` 0; `occasional` >0 и ≤40%; `frequent`
  ≥50%, ≥2× occasional, ≥3 контекста.
- **Наблюдение:** `off` 0/5 — PASS; `occasional` **0/7** — FAIL; `frequent`
  **0/7** (0/9 с follow-up) — FAIL; 9 подряд `frequent`-разговорных проб без
  мата при подтверждённом маркере/строке/тексте в payload. Прямая просьба
  «скажи матерное» в `frequent` даёт мат, в `off` — «Нет»; raw == доставка;
  провайдер/постпроцессор не виноваты. Класс
  `model_ignored_instruction` корректен как диагностика; корень точнее
  сформулирован в `evidence/behavior-diag/report.md` (коммит `21494565`):
  режим работает как veto, не generator — диспозитивная формулировка,
  ложное «Уместность выбирает L1» (L1 — machine-stage, слой не видит),
  отсутствие few-shot и инертность flash-модели.
- **Влияние:** владелец выбирает «Часто»/«Эпизодически», но не видит
  обещанного изменения речи; формально фича не выполнена, хотя wire-слой
  работает. Это не деградация и не повод откатывать: глобальная настройка не
  менялась, тестовые чаты восстановлены, боевой default — `occasional`.
- **Минимальная коррекция:** F1 — убрать ложное делегирование L1 из
  `EXPRESSION_HEADER` и дать операционный триггер частоты в `frequent`/
  `occasional` (`services/mca_expression.py`, синхронно тесты §7.1 и
  `design-add-exp.md` §2); F2 — опционально одобрить/отредактировать
  few-shot (behavior-diag: 4 `frequent` + 4 `occasional` из 12; в runtime они
  не идут до `owner_approved=1`); F4 — bounded-проба на **disjoint** промптах
  (черновики совпадают с фразами приёмки), затем полная матрица §7.2.
- **Минимальный recheck:** та же матрица 7×3 + повторы; `off` 0; `occasional`
  >0 и ≤40%; `frequent` ≥50%, ≥2× occasional, ≥3 контекста; wire-маркер/
  строка/точный текст; raw==доставка; изоляция A/B; residual уборки 0.

## 4. Сопутствующие находки

1. **RELATED-1 (учёт уборки):** в README/отчёте «42 удаления» — неверно.
   Фактически **45**: main 33 (A30+B3), follow-up 9 (A6+B3), quote 1166725,
   anchor 1166670, residual 1166469. «42» = 31 A-main + 9 + quote + residual;
   потеряны 3 сообщения B основной волны. Residual 0, safety соблюдена;
   исправить цифру в отчёте (код не нужен).
2. **RELATED-2 (baseline restore):** главный `p0` не снял override-ключи
   (`failed:DataError`, `a_overrides_after=null`), поэтому «28 ключей до==после»
   доказано от `p0b` (follow-up start) до after, а не от T0. Изменённый
   `character.expression` до/после отсутствует, global doc не изменён;
   достаточно уточнить формулировку или снять read-only PG-срез до/после.
3. **RELATED-3 (изоляция):** `summary.criteria.isolation=PARTIAL` основной
   волны; PASS — только follow-up. В таблице README §2 нужно явно указать
   «follow-up»; main authorial тогда был `occasional`, а не `frequent`.
4. **RELATED-4 (выборка occasional):** 7-я проба — точный дубль
   `occasional-04-everyday`, не новая формулировка; для будущего recheck
   использовать disjoint-набор. На вывод FAIL не влияет (0 и без дубля).
5. **NONBLOCKING:** 137 LLM-вызовов = 27 `l1_planner` + 29 `l2_writer` +
   81 служебных; probe-attributable 56 ≤ ориентира ~60, 81 — свойство прод-
   пайплайна; в отчёте стоит разделить. BOM `accept96b_journal.sh` дал rc=127,
   но счётчики/ SQLite-проба есть в `accept96b-run.log`, данные валидны;
   raw journal не скачался — на выводы не влияет. `live-check` с одной пробой
   возвращает `diag_class=""` — это честно, не выдавать за класс.
   Цитата в `off` дословна, но без кавычек-делимитеров (Style Policy их
   запрещает), поэтому автодетектор считает мат «своим»; семантически это
   цитата, conversational-счёт не задет.

## 5. Леджер-заметки (карту и state этот лейн не правил)

- **Закрыть после rebind на `95d11472`:** `EXP-RUNTIME.WIRING`,
  `EXP-RUNTIME.PAYLOAD`, `EXP-ACCEPT.ROUTES` — live-подтверждены;
  `EXP-ACCEPT.LIVE-SET` — набор выполнен (27+7), но 7-я occasional-проба —
  дубль; `EXP-ACCEPT.PREVIEW`/`REVIEW` остаются VERIFIED.
- **`EXP-ACCEPT.CRITERION` — не VERIFIED, фактически FAILED.** Не закрывать
  по факту доставки слоя; это прямой критерий источника §4. Parent не DONE.
- **`EXP-INSTR.FEWSHOT`** остаётся VERIFIED: 12 драфтов на проде,
  `owner_approved=0`, в runtime не идут. Одобрение — **опциональный**
  owner-вход (behavior-diag: 4+4; можно править/отклонить), не новый
  Human Gate и не блокирует F1.
- **Release-gate** сейчас EXIT 1 (5 RFL + `deployed_commit` пуст) — ожидаемо
  до леджер-обновления; после F1 эвиденс приёмки будет недействителен и
  матрицу нужно прогнать заново.

## 6. Следующее действие

1. Builder: F1 (текст/делегирование + операционный триггер) и тесты §7.1;
   не делать постпроцессор и не менять Core/канон (EXP-INSTR.NOPOST,
   ADD-1.E1).
2. Владельцу — опционально F2: одобрить/отредактировать 4 `frequent` +
   4 `occasional` карточки (из 12), не авто-одобрять; без ответа F1 остаётся
   самодостаточным.
3. F4 на **disjoint** промптах (не фразы приёмки/драфтов), затем полная
   матрица §7.2 и новый эвиденс; после этого — rebind леджера и release-gate.
4. Исправить в отчёте: 42→45, baseline restore, «follow-up» в таблице
   изоляции, дубль occasional, разделение 56/81 LLM-вызовов.
5. Rollback не требуется: глобальный `character.expression` не менялся,
   A/B восстановлены, боевой default — `occasional`.

## 7. Ограничения

- Прод-PG повторно не читал (минимум коннектов); восстановление/уборка
  проверены по checksum-bound эвиденсу и healthz.
- Harness — отдельный процесс на проде (боевые модули/LLM/Telegram), не
  MainPID 3739015; «production trace» — это deployed code path, а не
  per-turn журнал живого сервиса. Основная изоляция — PARTIAL, PASS только
  follow-up.
- Внешнюю карточку модели не перезапрашивал: «провайдер не ограничен» —
  runtime-факт (прямая проба), не документация провайдера.
