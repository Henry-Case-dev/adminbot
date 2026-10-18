# REV-INIT-FIX — вердикт (P0 «Инициатива»: фикс реальных блокеров)

Независимое read-only ревью кандидата (перепрогоны RED/GREEN, чтение кода, хеши UI).
Этот коммит — только данный документ. Ветку/дерево не менял.

Биндинг:
* Кандидат: незакоммиченные правки поверх `185cff1c` (в дереве есть и чужие
  незакоммиченные правки другого лейна — исключены: 0 пересечений по смыслу,
  см. §6). HEAD продвинулся чужими docs-коммитами (`097e3653`, `ebe10806` — планы/стейт); кандидат не менялся.
* SHA256 6 продуктовых файлов == `candidate-fingerprint.txt` (снял повторно):
  `AD98B5B7…` initiative_observer.py, `A3776DF9…` direct_chat_service.py,
  `B3C62581…` mca_intents.py, `C5952BBB…` status_service.py,
  `5A4AEA37…` web/app.js, `856C89C9…` web/index.html.
* ПРИМЕЧАНИЕ к evidence: fingerprint не пиннит тестовые файлы — фиксирую их
  SHA256 здесь: P0-набор `6DA2FCC4EE79E8B2…`, W5 `A058C5FB58F88B99…`,
  B01 `6F52FB257F3A34B3…`, module-registry `519772DB0A1A3DB7…`,
  mca09-e `CDB56DBA5F2CDE73…`.
* UI PNG (SHA256): before `01==03` (`66a419b307d0939b…`), after `01`
  (`888c073f82278493…`) `!=` `03` (`c7a2cb8862e955ca…`), `02` побитово
  идентичен before==after (`50aaa00927879b1e…`).

## 1. Факты прода — подтверждены (сам читал дампы)

* Курсор: job `cursor=155734` (= `last_seen_msg_id`) при `MAX(id)=2350637`,
  778 passes, `observed=135869`, `evals=2`, `sent=0`, `eval_skips.min_gap=4`.
* `BOT_OUTPUTS_7D`: `direct_reply` ×127 при `initiative.min_gap_seconds=7200`
  (PG_BOT_SETTINGS); мастер-гейты все `true`.
* `DECIDED_FULL`: 2× `initiative_decided` `status="reply"`, `outcome=silent`,
  `reason_code="default"`, без writer/recheck/sent-событий; `INTENTS []`.
* `intent_snapshot` при `chat_id=None` отдавал `restricted` — подтверждено
  кодом базы (`185cff1c`: `if chat_id is None or not chat_scope_allowed:
  return restricted`) и пробой `ui-before` (в дампах не снималось — источник
  код+UI, это отмечено как есть).
* `initiative_observer_diagnostic` failed ×3 — ложное «24ч ноль поводов» на
  исторических счётчиках.

## 2. Фиксы в коде — прочитаны фактически

1. Подтяжка курсора: `SCAN_FRESH_LOOKBACK_SECONDS=6ч`, `SCAN_FRESH_MIN_ROWS=200`;
   `anchor = min(старт 6ч-окна, newest-199)`; перенос **только вперёд**
   (`if anchor > cursor_pos`), `cursor = anchor-1` (строка-якорь читается);
   ошибка чтения → 0 (не двигаем); счётчик `scan_anchored` + событие
   `initiative_observer_scan stage=anchored`; ничего не удаляется.
2. По-репличная классификация: `addressed_to_bot` (падежные формы «бот…»,
   «ботик/ботяра», `@username`; «ботаник/ботва/робот» не матчатся);
   окно отбрасывается **только если обращения — все реплики**; смешанное
   доходит до оценки.
3. Антифлуд/cooldown: `ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS=300` после ЛЮБОГО
   `delivered`-вывода; `min_gap` профиля — только по `output_kind=
   'initiative_reply'` (фильтр `kinds` существовал в database.py уже на базе
   `185cff1c` — новых деп-зависимостей нет). Порядок ворот: min_gap → anti_flood.
   `chat_block_state` показывает оба возраста (`anti_flood` +
   `last_initiative_output_age_seconds`).
4. `no_chat` ≠ `restricted`: ранний `no_chat` при `chat_id=None` (данные
   по-прежнему 0/[]), `restricted` — только RBAC-запрет; route `/api/status`
   прокидывает `chat_id=None`/`X-Chat-Id` корректно; UI: label (app.js 8714-15),
   тексты состояний (index.html 9067-9077), гейт воронки (app.js 4912).
5. Эфемерный повод: `opportunity_row` (goal/kind/origin/created_at/source_refs)
   из наблюдателя → `_ephemeral_intent_row` → L1/L2 получают реальные поля
   (реальный writer читает именно `goal/kind/origin` — проверено по
   `plan_initiative_decision`/`generate_initiative_reply`); pre-send
   `SendRecheck` получает реальный контекст (`created_at`=момент повода;
   `direct_pending` = обращение, пришедшее во время генерации); `note_decision`
   несёт истинный `reason_code`, и **все** новые коды есть в allowlist
   `mca_events.REASON_CODES` (l1_silent/l1_unavailable/recheck_demoted/
   delivery_not_text/already_answered/direct_pending/intent_closed/writer_failed)
   → причина в событии не теряется.

## 3. RED → GREEN (перепрогоны ≥3)

* RED (мой прогон): worktree `185cff1c` + кандидатный тест → **7 failed,
  3 passed**, ровно тот же список 7 падений, что в `red-before-fix.txt`.
* GREEN на кандидате: P0+W5+B01 — 40 passed (×3 прогона); 5 файлов — 69 passed;
  супернаборы 227 / 286 / 630 passed — падений 0; сам P0-набор — 10/10 во всех прогонах, включая 8 подряд (не флак).
* Число «405 passed» из evidence буквально не воспроизвёл: точный состав
  команды в логе не зафиксирован (приведён только хвост), а мой супернабор
  шире. Все файлы, перечисленные в README §3, перепрогнаны отдельно и в
  супернаборах — 0 падений.

## 4. Цепочка до отправки — валидна

`test_opportunity_carries_context_into_writer_and_sends`: fake writer — тот же
duck-typed контракт (2 метода), что реальный DirectChatService (прод-тик
`memory_maintenance.py:443` передаёт именно его); тест утверждает содержимое
строки повода (goal/origin/created_at), `sent==1`, ledger
`output_kind='initiative_reply'` — это и есть основа cooldown/антифлуда.
Не подмена реального Writer, а проверка переданных ему данных.
`test_pending_direct_request_stops_observer_initiative`: monkeypatch на границе
`build_fresh_recheck_context` (wiring-проверка: для эфемерной строки recheck
вызывается и `direct_pending` отменяет отправку). Реальная функция прочитана:
её окно `direct_pending` — «после created_at» (=во время подготовки), что
соответствует объявленной безопасности. Остаток: реальная функция для
эфемерного повода отдельным тестом не покрыта (общая логика с durable).

## 5. UI — проверено

Хеши before/after (см. биндинг): до фикса «чат не выбран» и «нет доступа»
рисовались побитово одинаково (=дефект), после — различаются; «доступный чат»
побитово не изменился (регрессии нет). Тексты состояний и их источник в коде
сверены. Дополнительно я повторно прогнал after-пробу сам (копия пробы,
вывод в scratch; evidence не менял): `global_state=no_chat`,
`global_honest_no_chat=true`, `global_no_false_restricted=true`,
`global_funnel_hidden=true`, `denied_state_label=true`, `chat_funnel_visible=true`,
`no_h_overflow=true`, `console_errors=[]` — совпадает с evidence.

## 6. Дисциплина дерева

6/6 продуктовых хешей == fingerprint. Чужой лейн (`mca_authorial_speech`,
`nostalgia_*`, `param_catalog`, 3 чужих теста + 1 new) — 0 вхождений
`initiative_observer/handle_initiative/intent_snapshot/no_chat/anti_flood/
opportunity_row` в его диффе; мои GREEN-прогоны шли на комбинированном дереве
— конфликтов нет. Обновлённые тесты **не ослаблены**: W5 — monkeypatch заменён
реальной записью ledger (строже); B01 — добавлен `_age_outputs` (сдвиг времени
после реального антифлуда; ассерты сохранены); mca09/module-registry — к
`no_chat` добавлен настоящий `restricted`-кейс. Обоснование «дефектный
контракт» принимаю (владелец явно потребовал разделения состояний).

## Находки

* RELATED (не блокер; рекомендую в это же релизное окно): owner-facing
  «Проверить инициативу» (`services/initiative_diagnostics.py:950`) вызывает
  `handle_initiative` **без** `opportunity_row` → L1/L2 снова видят «цель не
  указана», а pre-send recheck работает с пустым `RecheckContext(intent_row=
  None)`. Dry-run не отражает исправленную цепочку. Мини-фикс: собрать
  `opportunity_row` из `verdict`+`rows` (как в наблюдателе) и передать;
  1 ассерт в W5 dry-run тесте. Проверка: тот же тест + trace.
* INCIDENTAL (pre-existing, не блокер): флейк
  `test_mca09_intents_block_e_round1040::test_candidate_ready_defers_intent_backoff`
  (defer не долетел при «мёртвом» aiosqlite-соединении/розыгрыше exploration).
  Interleaved A/B: база `185cff1c` 1/10, кандидат 1/10 → фиксом не внесён.
  При желании — изоляция теста (fixture `_no_exploration_draw` как в B01).

## 7. Решения леджеру

| Пункт | Решение | Остаток |
|---|---|---|
| §1.1 курсор (актуальная переписка) | готово к VERIFIED (код+тесты) | live: `scan_anchored>=1`/`stage=anchored`, снижение lag |
| §1.2 mixed-окно | готово к VERIFIED | нет |
| §1.3 антифлуд/cooldown | готово к VERIFIED | live: пропуски `min_gap` от Direct исчезают в живом ритме |
| §1.4 no_chat/restricted | готово к VERIFIED (код+UI+пробы) | live: блок на реальном `/api/status` |
| «Эфемерный повод» (observer path) | готово к VERIFIED | live: writer/recheck/sent-события реального повода |
| P0A-INIT-DIAG/PROOF (live_required) | **READY_FOR_LIVE** — не закрывать | postdeploy-воронка прода |
| dry-run «Проверить инициативу» | related, рекомендовано до/вместе с деплоем | см. находку |

## Вердикт

**Approved** (код-фикс кандидата; parent не DONE). Live-строки §1.1/§1.4 и
P0A-INIT-PROOF остаются `READY_FOR_LIVE` до postdeploy-проверки воронки
(scan_anchored≥1, writer/recheck/sent-события, anti-flood в живом ритме).
Блокирующих находок нет.