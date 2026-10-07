# RCA — Summary Reliability (ASAP 5, T-5241, lane P1)

Read-only RCA на фактическом HEAD (worktree `C:\Code\Python\adminbot`) + production evidence.
Дата: 2026-10-07. Режим: код/прод-логи/метрики read-only; writer — только этот файл.

Прод-evidence собран за ОДИН SSH-батч (read-only: `journalctl`, SQLite `mode=ro`) + локальный
HTTP healthcheck. Сервис на проде: version **2.58.67**, жив.

Прод-источники:
- `mca_events` (SQLite, ro): `SUMMARY_RUN_DONE`, `SUMMARY_LEGACY_FALLBACK`, `SUMMARY_L1_STAGE`, `SUMMARY_L2_REVIEW`;
- `summary_runs` / `summary_run_stages` (durable state machine);
- `journalctl -u admin_bot` за 10 дней (маркеры `LEGACY_FALLBACK` / `L2_REVIEW_FINDING_DROPPED`).
Чаты маскированы (`***0336`), run id — допустимы (R17).

---

## 0. Верdict-сводка

| # | Пункт аудита / симптом | Вердикт |
|---|------------------------|---------|
| 1 | §1.1 L1 не обязан валить Summary (fallback → L2 от окна) | **confirmed** |
| 2 | §1.2A `unusable` слишком доверяет модели (raw status → Legacy) | **confirmed** |
| 3 | §1.2B unknown severity → blocking | **confirmed** (с усилением: anchor-mode делает blocking ВСЕ findings) |
| 4 | §1.2C progress-критерий сравнивает количество blockers | **confirmed** |
| 5 | §1.2D soft-quality findings уничтожают пригодный Hybrid | **confirmed** |
| 6 | Live: L1 рисуется как «не выполнено» без объяснения writer-продолжения | **confirmed** |
| 7 | Live: L2 UI «Writer не выполнено — Проверка отклонила статью после повторов» | **confirmed** |
| 8 | Live: не видно, какой finding blocking / почему revision не прогресс / почему весь Hybrid выброшен | **confirmed** (данные собираются server-side, но UI их не рендерит) |
| 9 | Live: Hybrid систематически уходит в Legacy | **confirmed** (8/8 последних fallbacks = `l2_unusable`) |

**Итого: 9 confirmed / 0 refuted / 0 adjusted.** Все пункты предварительного аудита раздела ASAP 5
подтвердились на HEAD; два пункта — с уточняющими деталями механики (№3, №8 ниже).

---

## 1. §1.1 — L1 уже не обязан валить Summary — **confirmed**

**Код (HEAD):**
- `services/summary_generator.py:1988-2004` — при `not l1_result.usable` (writer-source ON,
  default ON: `:188-195`, kill-switch `SUMMARY_WRITER_SOURCE_INPUT_ENABLED`) строится
  детерминированный `build_fallback_package(...)` и **L2 вызывается в любом случае** от Full
  SourceWindow; комментарий `:1992-1994`: «L1 failed ≠ Summary failed; переход на урезанный Legacy
  из-за L1 ЗАПРЕЩЁН». Аналогично для OFF-ветки `:2013-2026`. Не-терминальность L1 зафиксирована
  в докстринге `:1800-1805` (LEVEL-2: «L2 вызывается в любом случае»).
- При этом durable stage-статус L1 бинарный: `summary_generator.py:1971-1974` —
  `_durable_stage_result(ctx, "l1", "ok" if l1_result.usable else "failed", ...)`.
- Витрина: `services/pipeline_analytics.py:879-890` — узел L1: `state = STATE_FAILED if failed
  else STATE_SUCCESS`; `STATE_FAILED` → человекочитаемое **«не выполнено»** (`:300-309`); detail
  узла — только «Тем выделено». Никакого объяснения «Writer продолжил от full source» рядом нет.
- Частичное исключение: coverage-карточка `_coverage_breakdown` (`pipeline_analytics.py:756-784`)
  имеет флаги `map_degraded`/`map_reason`, и `web/app.js:3156-3170` печатает «· карта деградирована» —
  но это только для деградированной карты; при `usable=False` результат остаётся плоский
  `"result": "failed"` (`:760-764`). Трёхуровневой семантики OK / DEGRADED_MAP_FALLBACK /
  FAILED_TERMINAL нет нигде.

**Прод:** за 14 дней `SUMMARY_L1_STAGE`: 17 `success` / 7 `failed`. Владельческий live run
`9c742f0e973647768c465c50d99a044d` (2026-10-06 13:00–13:11 UTC, чат `***0336`): L1 по жалобе
владельца «failed», при этом run дошёл до L2 review-цикла (`calls_so_far=5` = L1+writer+review+
revision+review) и опубликован (`fallback=legacy`, `publication=rich`, coverage 874/874=100%).
То есть L1-fail реально не валит Summary — а витрина показывает красный крест.

**Root cause механики:** ось «статус этапа» (ok/failed) и ось «продолжение пайплайна» разделены в
коде, но в durable-статусе (`:1972`) и в узле витрины (`:882`) L1 схлопывается в binary
ok/failed; семантика «degraded, но Writer получил полное окно» не существует как значение.

**Направление фикса:** ввести трёхуровневый L1-статус (OK / DEGRADED_MAP_FALLBACK /
FAILED_TERMINAL) в durable stage result + узел витрины, с причиной и явной пометкой
«Writer продолжил от полного окна».

---

## 2. §1.2A — `unusable` слишком доверяет модели — **confirmed**

**Код (HEAD):**
- `services/summary_l2_review.py:279-283` — `status=unusable` из raw-ответа модели проходит валидацию
  как есть (status ∈ {approved, needs_fixes, unusable}).
- `:333-335` — единственная мягкая коррекция: `needs_fixes` без единой валидной находки →
  `approved`. Для `unusable` аналогичной защиты **нет**: unusable с **нулем** валидных findings
  остаётся unusable.
- `:1022-1031` — `verdict.status == VERDICT_UNUSABLE` → немедленно
  `invalid_result(REASON_L2_REVIEW_UNUSABLE)` → Legacy. Никакой server-side проверки «достаточно ли
  валидных hard findings» не существует. Raw LLM status = доказательство непригодности статьи.
- Далее `services/summary_generator.py:2271-2286` — `not l2_result.usable` → `_legacy_fallback("l2_unusable")`.

**Прод:** все 8 последних `SUMMARY_LEGACY_FALLBACK` (Oct 4–6, чат `***0336`):
`trigger=l2_unusable, fallback_from=l2`, 100% исходов. Run id — `c2e867f8…`, `9c742f0e…`, `91c30817…`,
`ac1789d6…`, `0abae91e…`, `994aec53…`, `48d28c7a…`, `9748/10562…` (ежедневные 07:00/13:00/19:00 прогоны).
Hybrid не «нестабилен» — он **систематически** отклоняется на L2 и конвертируется в Legacy.

**Root cause механики:** contract review-верdict'а доверяет модели финальное семантическое решение
(«статья непригодна») без server-side квоты доказательств; единственный путь «спасти» документ —
reviewer outage (`_degraded_or_legacy`, `:1278+`), который публикует degraded, но он не применяется
к осмысленному unusable.

**Направление фикса:** server-side gate для unusable (например: ≥N независимых валидных hard
findings, либо deterministic validator доказал непригодность), иначе трактовать как needs_fixes.

---

## 3. §1.2B — unknown severity → blocking — **confirmed** (с усилением)

**Код (HEAD):**
- `services/summary_l2_review.py:326-328` — `severity` вне {blocking, minor} → `SEVERITY_BLOCKING`
  («консервативно для progress criterion»). Форматная неточность Reviewer становится
  release-blocking дефектом.
- Усиление сверх аудита: в anchor-mode **все** findings принудительно blocking:
  `_verdict_from_anchor_result` `:353-367` — `severity=SEVERITY_BLOCKING` для каждого issue без
  исключений.
- Таксономии «код finding → класс/серверная severity» не существует: `FINDING_CODES`
  `:153-169` — плоский frozenset; severity решения — только поле модели (+ нормализация выше).

**Прод:** форматные проблемы Reviewer реально случаются: `journalctl` Oct 04 01:04:42 —
`L2_REVIEW_FINDING_DROPPED | code=unsupported_number | cause=missing_refs` (находка без
доказательств отброшена за 11 с до `LEGACY_FALLBACK` run `c1623880…`). Отдельного счётчика
«unknown severity» нет — нормализация silent, поэтому прямого прод-факта именно unknown→blocking
нет; механика в коде однозначна (см. выше).

**Root cause механики:** severity — произвольное поле модели, нормализуемое в самую жёсткую
сторону; серверная классификация по finding code отсутствует.

**Направление фикса:** server-owned taxonomy (finding code → default hard/soft, условия
promote/demote, `can_force_legacy`), модель не решает severity.

---

## 4. §1.2C — progress-критерий сравнивает количество blockers — **confirmed**

**Код (HEAD):**
- `services/summary_l2_review.py:1045-1057` — `blocking_now = verdict.blocking_count`;
  `if prev_blocking is not None and blocking_now >= prev_blocking and not last_revision_burned: break`.
  Сравнение голых счётчиков; fingerprint (code+paragraph+evidence) не вычисляется и в решении не
  участвует.
- После break: `:1197-1215` — verdict ≠ approved → `invalid_result(REASON_L2_REVIEW_REJECTED)` →
  Legacy. Т.е. «count не уменьшился» (даже при другом наборе findings) = выбросить Hybrid.
- Существующий механизм `seen_codes`/`l2_revision_new_findings` (`:1041-1043`) считает новые коды,
  но в break-решении не используется — только как метрика.

**Прод:** владельческий run `9c742f0e…` — `calls_so_far=5` (L1+writer+review+revision+review):
цикл оборвался по count-критерию после первой ревизии; run `c2e867f8…` — `calls_so_far=7` (полные
2 ревизии, всё равно rejection). «Почему следующая revision не считается прогрессом» владельцу
не объясняется нигде (см. п.8).

**Root cause механики:** identity находки сводится к количеству; исправление one finding + появление
другого выглядит как «ноль прогресса».

**Направление фикса:** stagnation по fingerprint hard findings (`code+paragraph+evidence refs`),
count — только как дополнительный сигнал.

---

## 5. §1.2D — soft-quality findings уничтожают пригодный Hybrid — **confirmed**

**Код (HEAD):**
- Разделения HARD vs QUALITY не существует: все 15 `FINDING_CODES` (`summary_l2_review.py:153-169`,
  включая soft `duplicate_event`, `major_topic_omitted`) равноправны; severity решает модель
  (unknown → blocking, п.3).
- После исчерпания bounded-цикла (`MAX_REVISIONS`/budget/break) `:1209-1215`: ЛЮБОЙ
  needs_fixes с оставшимися blocking → `invalid_result(REASON_L2_REVIEW_REJECTED)` → Legacy
  (`summary_generator.py:2271-2286`). Soft-only набор с severity=blocking уничтожает Hybrid так же,
  как доказанный factual corruption.
- Контраст: reviewer **outage** уже fail-soft — `_degraded_or_legacy` `:1278-1299` публикует
  `review_degraded` (draft прошёл deterministic-валидацию). Т.е. механика «опубликовать degraded
  пригодный документ» в коде есть — она просто не применяется к semantic soft-rejections.

**Прод:** все rejection-исходы уходят в Legacy (п.2); разделить hard/soft по прод-данным нельзя —
в `mca_events` finding-состав вердиктов не сохраняется (только в in-memory stage_events ≤24,
не рендерится; см. п.8). Это само по себе подтверждает невидимость hard/soft для владельца.

**Root cause механики:** отсутствие server-side классификации находок; единственный
пост-валидатор (deterministic §99) не различает factual corruption и completeness-замечания.

**Направление фикса:** soft-only результат → `hybrid_degraded` (публикация с пометкой) или
bounded repair, но не Legacy; hard — по server-taxonomy из п.3.

---

## 6. Live: «L1 отмечен как failed / not completed» — **confirmed**

Механика: `summary_generator.py:1972` (durable `l1: failed`) → `pipeline_analytics.py:881-882`
(узел STATE_FAILED) → `:305` label **«не выполнено»**; coverage-ось `web/app.js:3168-3170` —
`'не выполнено'` + красный state. Владелец видит красный крест на L1 при 100% coverage — при том,
что пайплайн продолжился и опубликовал текст (прод: run `9c742f0e…`).

## 7. Live: «L2 UI: Writer не выполнено — Проверка отклонила статью после повторов» — **confirmed**

Механика: при reviewer-rejection `l2_result.usable=False`, и durable-статус пишется на ВСЮ
L2-стадию: `summary_generator.py:2258-2262` — `("l2", "failed", reason="l2_review_rejected")`.
Витрина: `pipeline_analytics.py:892-901` — узел «L2 · Писатель» → STATE_FAILED → **«не выполнено»**;
`reason_code=l2_review_rejected` → `REASONS_RU` `:100-101` «Проверка отклонила статью после
повторов — отправлена в резервный контур». Writer при этом реально выполнился (документ прошёл
deterministic-валидацию); отказал Reviewer после ≤2 ревизий.
Дополнительная неточность витрины: `REASONS_RU["l2_review_unusable"]` (`:102-103`) — «Ответ
писателя не удалось разобрать», хотя фактически `l2_review_unusable` = Reviewer вернул semantic
unusable (`summary_l2_review.py:1022-1031`); parse-failure писателя — это другие reason-коды
(`summary_l2_writer.py:128-148`). Текст причины описывает другой механизм.

**Прод:** durable stages последнего run `c2e867f8…` (19:00): `l1=ok`, `l2=failed
(reason_code=l2_review_rejected)` — в точности владельческая формулировка UI.

**Направление фикса:** раздельные stage-исходы Writer vs Reviewer (Writer done + Reviewer rejected),
честные RU-тексты; «не выполнено» зарезервировать за transport/структурным провалом.

---

## 8. Live: не видно, какой finding blocking / почему revision не прогресс / почему весь Hybrid выброшен — **confirmed** (данные есть, UI не рендерит)

**Что собирается server-side (уже на HEAD):** per-attempt stage events с полным diagnosis-набором —
`summary_l2_review.py:727-761` (`_stage_event`): `stage, attempt, status, reason_code, verdict,
finding_codes, blocking_count, paragraph_ids, revision_target, revision_result,
revision_failure_reason, deterministic_validation_codes`. Они проектируются в snapshot
(R17-safe, последние ≤24: `services/execution_graph_source.py:291-314`) и отдаются в API в
developer-блоке (`services/pipeline_analytics.py:1162-1172`, `"developer": …` `:1067`).

**Что рендерит UI:** узел Review — только «Итераций исправления» / «Исправлено ревизией»
(`pipeline_analytics.py:910-922`); developer-details — только `stage · status · попытка N ·
reason_code` (`web/index.html:4230-4241`). `verdict`, `finding_codes`, `blocking_count`,
`paragraph_ids`, `revision_result` **не отображаются нигде** (в `web/app.js`/`index.html` нет ни
одного упоминания `finding_codes`/`blocking_count`/`stage_events`-полей кроме вышеприведённого
loop'а). Финальная причина для владельца — одна RU-строка без finding-деталей.

**Root cause механики:** decision-trace данные уже durable и R17-safe; отсутствует только витрина
(§3.1 плана — Hybrid Decision Trace) и финальный policy-статус
(HYBRID_PUBLISHED / HYBRID_DEGRADED_PUBLISHED / LEGACY_FALLBACK + точная причина).

**Направление фикса:** рендер Decision Trace из существующих stage_events (данных хватает:
attempt/verdict/finding_codes/blocking_count/paragraph_ids/revision-результаты) + отдельный
final-policy outcome; новых LLM-вызовов не требуется.

---

## 9. Live: Hybrid систематически уходит в Legacy — **confirmed**

**Прод-факты (10-дневный journal + mca_events):**
- 8/8 последних `SUMMARY_LEGACY_FALLBACK` — `trigger=l2_unusable, fallback_from=l2`; все
  завершились публикацией (`publication=rich`/`text`), `pipeline_health=degraded`. Legacy — не
  аварийный контур, а **штатный исход** ежедневных прогонов (07:00/13:00/19:00).
- Владельческий live run подтверждён: `9c742f0e973647768c465c50d99a044d` (2026-10-06 13:00–13:11,
  `***0336`): `source_total=874, source_considered=874, coverage=100%`, `fallback=legacy`,
  `publication=rich` (cover styled — ок, ось cover не задета), state=DEGRADED.
- Профиль вызовов: `calls_so_far` = 2 (writer-путь без review-вызова) / 5 / 7 (полный review-цикл).
  Т.е. `l2_unusable` в проде — **два класса**: (а) writer/deterministic-провал до review и
  (б) review-rejection. Витрина обе класса показывает одной строкой про «Проверку».

**Root cause механики:** матрица LEVEL-3 (`summary_generator.py:1805-1809`, `:2271-2286`) +
пункты 2–5 выше = цепочка «reviewer мягко придирался → count-стагнация → rejection → Legacy».

---

## 10. Incidental findings (вне скоупа фикса этого пункта, классифицированы)

1. **related-nonblocking:** ось «Final text coverage» на legacy-путях врёт: `SUMMARY_RUN_DONE`
   большинства legacy-runs содержит `coverage=0.0, source_considered=0` (например run
   `c2e867f8…`: source_total=293 → 0/293), хотя текст реально собран из того же окна; только
   отдельные runs (874/874) показывают честные 100%. Витрина покажет «0%» рядом с публикацией.
   Область: заполнение coverage в legacy-ветке (`summary_generator._run_legacy_pipeline` /
   `_coverage_breakdown`). В blurry-зоне корневых причин Summary-домена — не трогать в этом slice
   без отдельного пункта.
2. **related-nonblocking:** RU-текст `l2_review_unusable` («Ответ писателя не удалось разобрать»)
   описывает не тот механизм (см. п.7) — входит в B1-скоуп честных текстов.
3. **uncertain/наблюдение:** `trace_id` в строках `mca_events` для `SUMMARY_*` пуст — сшивание
   событий с run на витрине работает (владелец видел карту), но drill-down по trace из БД напрямую
   невозможен; телеметрия `SUMMARY_L2_REVIEW` за 14 дней — всего 2 строки при ~20 rejection-исходах
   (событие эмитится только при реально запущенном review-loop, `summary_generator.py:2233-2240`).
   Диагностическая полнота mca_events для review-исходов неполна — учесть при дизайне Decision
   Trace (источник — stage_events, не mca_events).
4. **unrelated/pre-existing:** `summary_runs.state=DEGRADED` при успешной публикации — согласовано
   с §50.53 (publication/health — раздельные оси), не дефект.

---

## 11. Ограничения evidence

- `unusable`-вердикты не сохраняют finding-состав в durable (только in-memory stage_events ≤24) —
  поэтому «какой именно finding блокировал прод-runs» реконструировать нельзя; это и есть симптом
  №8. Вердикты даны по механике кода (file:line) + агрегатам прод-логов.
- Прод-evidence: один SSH-батч (read-only), journalctl за 10 дней, SQLite ro-снапшот на момент
  2026-10-07 00:33 UTC (healthz 2.58.67). SSH-паттерн по AGENTS.md соблюдён (recon + 1 основной).

## 12. Сводка fix-направлений (детали — Step 2, не в этом slice)

1. Трёхуровневый L1-статус (OK / DEGRADED_MAP_FALLBACK / FAILED_TERMINAL) в durable + витрине.
2. Server-side gate для `unusable` (валидные hard findings / deterministic proof).
3. Server-owned severity-таксономия по finding code (hard/soft, can_force_legacy).
4. Stagnation по fingerprint hard findings вместо count.
5. Soft-only → `hybrid_degraded`/bounded repair, не Legacy; fail-soft mechanical уже есть —
   переиспользовать (`_degraded_or_legacy`).
6. Hybrid Decision Trace в Run Inspector из существующих stage_events + честные stage-исходы
   Writer vs Reviewer + final-policy outcome.
