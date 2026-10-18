# INIT-ARCH-GAP — gap-check архитектуры наблюдателя инициативы (P0B-INIT-ARCH, 11 пунктов)

Лейн: **INIT-ARCH-GAP-CHECK** · режим: read-only (код/карты не менялись; этот файл — единственная запись).
Дата/время: 2026-10-18 (локально вечер 18.10; UTC-время фактов ниже).
Код-база: HEAD `ce9d17ea`; `services/initiative_observer.py` чист в HEAD (sha256¹⁶ `eef7feec36aca94f`),
`services/initiative_diagnostics.py` (`0391fc582f602398`).
Прод: **2.58.90** (`3b02366e`), `/healthz` = ok. Прод-факты собраны **read-only GET** витрин
(`/api/memory/intel-funnels`, `/api/memory/initiative-vitality`); **SSH не использовался**.
Ссылка на источник в карте B: `requirements-map-followup.json` → slice `P0B-INIT-ARCH` (11 строк, все `PENDING`).

## 0. Свежие прод-факты (18.10.2026 15:40Z, чат −1002661910336 ≈ 2.2 млн строк)

```json
{"job_status":"completed","job_finished_at":"2026-10-18T15:40:01Z","passes":865,
 "scan_anchored":1,"observed":147081,"evals":8,"opportunities":5,"sent":2,
 "eval_skips":{"eval_not_due":774,"not_enough_messages":95,"min_gap":9,
               "direct_address_seen":1,"no_opportunity":2,"semantic_eval_unavailable":1},
 "events_24h(chat-scoped)":{"opportunity":6,"decided":5,"writer_generated":2,"sent":2,
                            "observer_diagnostic":0},
 "gates_state":{"cursor_lag_messages":2,"live_messages_24h":716,"pending":16,
                "eval_used_today":5,"last_initiative_output_age_seconds":9806},
 "vitality_state":"ok"}
```

Плюс уже сохранённые артефакты деплоя: `evidence/release-25890/acceptance/journal-25890.json`
(после T0: 16 сканов `success`, `stage=anchored` @13:40:06Z) и `acceptance-bc-25890-read.json`
(C1 `scan_anchored=1`, gate-диагностика: `cursor_lag_messages=0` на 13:55Z).
Честные оговорки: `events_24h.initiative_observer_scan=0` в chat-scoped выборке — **ожидаемая семантика**
(scan-события идут с `chat_id=null`, фильтр чата их исключает — `web/api/memory_overview.py` docstring);
пост-T0 решения: 1 шт. `l1_unavailable` (15:20:45Z) — см. §3.

## 1. Вердикты 11× (код ↔ прод)

| # | Пункт (L00019–L00029) | Вердикт | Код/тесты (refs) | Прод-факт |
|---|---|---|---|---|
| 1 | **NOARCHIVE** — не сканировать архив как основной способ | **covered** | `_scan_phase` L953-972: только `id > cursor ORDER BY id LIMIT 200` («назад — никогда»), bootstrap-курсор `0` в `enqueue_observe` L639-654 сразу подтягивается якорем L920-951; тест `test_stale_cursor_is_anchored_to_live_conversation` (1200 строк истории → `observed<300`, история цела 1206 строк) | `scan_anchored=1` (durable), `cursor_lag=2`; journal: `stage=anchored` 13:40:06Z, все 16 сканов success |
| 2 | **TAIL** — старт от актуального хвоста (6ч/≥200, `scan_anchored`) | **covered** | Константы L76-77 (`SCAN_FRESH_LOOKBACK_SECONDS=6ч`, `SCAN_FRESH_MIN_ROWS=200`), `_fresh_anchor_id` L920-951, счётчик `scan_anchored` L501, событие L966-967; тесты anchor + `test_live_cursor_is_not_rewound` | `cursor_lag=2` сообщения (на живом хвосте); `scan_anchored=1`; acceptance C1 |
| 3 | **CATCHUP** — новые с последнего наблюдения; при накоплении актуальное окно + **смысловое сжатие** пропущенного | **partial** | «актуальное окно» есть: watermark `last_eval_msg_id` L1233-1236, `_window_rows` L1067-1092 (самые свежие, `EVAL_WINDOW_MESSAGES*3` выборка → 14), тест `test_window_is_the_freshest_and_watermark_catches_up`; накопление: 200 строк/тик без LLM (L67, L969-972), оценки ограничены дедупом/бюджетами. **«Смыслового сжатия» нет**: пропущенный интервал нигде не сжимается и в промпт не попадает (L562-579 — только окно+hints); при 1000+ пропущенных актуальное окно оценивается, «середина» просто пропускается (без резюме/дайджеста) | `observed` растёт живыми окнами; `eval_not_due=774`/`not_enough=95` — окно не «жуёт» тысячи окон |
| 4 | **CONTEXT** — адаптивный объём (10 / 50–200+), не жёсткие 14 | **gap** | `EVAL_WINDOW_MESSAGES = 14` — жёсткая константа L78; используется без расширения: L569, L1084, L1091, диагностика `initiative_diagnostics.py` L875; параметра/hot-ключа объёма нет (grep по `window_messages`/`eval_window` — пусто) | окно оценки всегда ≤14 реплик (в т.ч. в dry-run «Проверить инициативу») |
| 5 | **SIGNALS** — темы/участники/адресаты/reply-связи/поводы сохраняются | **partial** | Участники+текст — в промпте L562-579 (`[user:id] author: text`); темы — `topic_key` L619 + счётчики тем L1335-1346; повод — `goal` → `build_opportunity_row` L699-730 → `handle_initiative` L1375-1382. **Потери**: `reply_to_id` выбирается L1078-1084, но в промпт оценки не попадает; `addressee_user_id` парсится L615-618 и **далее не используется** (grep: только определение); `rationale` не персистится; candidate L1352-1355 собирается без `source_refs` | — (структурная проверка; в проде полей не видно по R17) |
| 6 | **SMALL** — маленькие/новые чаты не требуют большой истории | **partial** | Барьера истории нет: floor `max(1, newest−199)` L939-951 на маленькой БД = вся она; тихий чат копит pending (тест `test_quiet_chat_accumulates_pending_until_threshold`); пороги профилей L126-148 (active 6 / normal 8 / rare 12), floor 4 при мягкой цели L162; B01/W5-тесты гоняются на малых объёмах (6–12 реплик, профиль active) | нет dedicated прогона сценария 2 (5–20 сообщений) ни в тестах, ни живьём (см. `P0B-LIVE-SCENARIOS` note). Нюанс: на заводском профиле `normal` порог 8 → чат из 5–7 сообщений сам не дойдёт до оценки |
| 7 | **BACKFILL** — отличать импорт от новых, не реагировать на многолетние события | **gap** | Платформа маркирует импорт `smart_messages.import_key` (миграция v7, `database.py` L6603; конвенция «живое = `import_key IS NULL`» L364/L7408-7420; загрузчик `tools/history_import/loader.py` L137-147 сохраняет **дату события** L143). Наблюдатель фильтр **не применяет**: anchor L920-951, scan L969-972, окно L1078-1085, rate L413-417, live L1497-1501, cursor-lag L1712-1715 | следствие: свежий импорт старых сообщений (новые id, старые ts) будет наблюдаться как «новые», окно `ORDER BY id DESC` покажет многолетнюю беседу → возможна реакция на древние события; теста на массовый импорт нет |
| 8 | **DURABLE** — состояние/дедуп переживают рестарты/деплои | **covered** | Payload durable-задачи: `enqueue` L639-654, `_load_payload` L753-781, `_inherit_state` L783-826 (курсор/чат-состояние/счётчики наследуются от терминального прогона), `_checkpoint` L828-839; дедуп-кольцо `recent_hashes` + TTL L1121-1128 (L85); тесты `test_b01_reboot_keeps_cursor_and_context_dedup`, `test_context_duplicate_still_blocks_repeat_evaluation` | `passes=865`, `scan_anchored=1` пережили все тики/перезапуски job после деплоя; `context_dedup=4` свежих окна (acceptance C3) |
| 9 | **DIRECT** — не отбрасывать весь контекст; Direct не подавляет бесконечно | **covered** | Per-reply классификация L1094-1115; окно отбрасывается только если обращения — ВСЕ реплики L1172-1174; антифлуд 300с после ЛЮБОГО вывода L99/L1188-1194; cooldown профиля — только по `initiative_reply` L100/L1179-1186; тесты `test_mixed_window_with_bot_mention_is_still_evaluated`, `test_window_with_only_bot_addresses_still_silent`, `test_direct_reply_does_not_block_initiative`, `test_anti_flood_blocks_right_after_any_output`, `test_pending_direct_request_stops_observer_initiative` | map A `P0A-INIT-DIRECT/COOLDOWN` = VERIFIED (prod C1/C3); живые пропуски: `min_gap=9`, `direct_address_seen=1`; обычный Direct (127 ответов/7д до фикса) больше не сбрасывает паузу инициативы |
| 10 | **DECISION** — SAY/REACT/SILENT по содержанию и личности, не по таймеру | **covered** | `_evaluate_window` L1284-1305 (один LLM-вызов на окно; промпт L543-559: SILENT легален, слухи/шутки/споры не обязаны становиться репликой, обращение к боту — не повод); `_act_on_opportunity` L1307+ → существующий единый вход `handle_initiative` (`direct_chat_service.py` L8696+, `decide_initiative` L8778, react/tool → честный silent `delivery_not_text` L8793-8802); «устарел ли повод» — `created_at` повода L726 + SendRecheck (тест `test_pending_direct_request_stops_observer_initiative`); тесты B01 `say/react/silent + durable intent`, W5 `silent never calls writer` | живые решения несут reason-коды (`default`, новый `l1_unavailable`) — правдивая причина стадии видна; таймеры управляют только расписанием проверок, не выбором |
| 11 | **CRITERION** — миллион сообщений: реакция на сегодняшнюю переписку, не ожидая обработки миллиона | **covered (live-эвиденс есть; строка карты ждёт привязки)** | Живой путь: anchor→`cursor_lag≈0`, окно = самые свежие реплики, watermark догоняет (тесты §2-3); архитектурного «ожидания обработки миллиона» нет (scan без LLM, eval bounded) | чат ≈2.2 млн строк: `cursor_lag=2`, `live_24h=716`; после T0: anchored + 16 сканов + 1 opportunity + decision 15:20:45Z (`l1_unavailable`) на живом окне; ledger: доставка 12:57:43Z (до T0), `counter sent=2` |

## 2. Минимальный список доработок (по приоритету)

1. **BACKFILL (gap, защита)** — применить платформенную конвенцию живой переписки во всех чтениях наблюдателя:
   `AND import_key IS NULL` в `_fresh_anchor_id`, `_scan_phase`, `_window_rows`, `recent_message_rate`,
   `live_messages`, `_cursor_lag` (как `get_smart_raw(exclude_imported=True)`). Тест: импорт пачки старых
   сообщений (`import_key` задан) не увеличивает `observed`/`pending` и не доходит до оценки.
2. **CONTEXT (gap, явный пункт ТЗ)** — адаптивный объём окна вместо жёстких 14: базовый 10, расширение
   до 50–200+ по ситуации (темп/накопление), с верхней границей и капом текста (`EVAL_MSG_TEXT_CAP`);
   тест на разных объёмах (10 / 50 / 200). Диагностика dry-run использует тот же резолвер окна.
3. **CATCHUP (partial)** — при большом разрыве watermark добавить в промпт оценки **bounded-дайджест
   пропущенного** (число сообщений/участников/период + ≤N примеров, без «последовательной оценки тысяч окон»);
   тест на 1000+ пропущенных. Если решено оставить «актуальное окно» единственной формой сжатия — зафиксировать это решением (PM/Architect), а не молчанием.
4. **SIGNALS (partial)** — донести до оценки `reply_to_id` (bounded-маркер в промпте) и не терять
   `addressee_user_id` вердикта (в candidate/`opportunity_row` или trace); тест: окно с reply-цепочкой
   доносит связь и адресата до промпта/кандидата.
5. **SMALL (partial)** — добавить прогон сценария 2 (новый чат, 5–20 сообщений, заводской профиль) в тесты;
   отдельно решить, допустимо ли «5–7 сообщений → ждать порога 8» (это осознанное поведение профиля).

Пункты 1–4 — изменение `services/initiative_observer.py` (+тесты); пункт 5 — тест/эвиденс без изменения архитектуры.

## 3. Сопутствующие находки (не блокеры P0B-INIT-ARCH)

* `semantic_eval_unavailable=1` в durable-счётчиках и живое решение `l1_unavailable` (15:20:45Z) —
  периодическая недоступность LLM/L1 в проде; воронка честно фиксирует причину (правки P0 работают).
  Классификация: `related-nonblocking` (наблюдать; не входит в 11 пунктов).
* Прежний `_BOTWORD_RE` в `_f6_chat_facts` (найден INIT-FIX, вне объёма) — `unrelated/pre-existing`.
* `events_24h.initiative_observer_scan=0` в chat-scoped выборке — семантика фильтра, не дефект.

## 4. Воспроизводимость

* Прод-проба (read-only GET, без SSH): scratch-скрипт `init_gap_probe.py`
  (шаблон — `evidence/release-25890/acceptance/probe_live_bc_25890.py`); сырой JSON пробы — рядом в scratch.
* In-repo источники прод-фактов: `evidence/release-25890/acceptance/journal-25890.json`,
  `acceptance-bc-25890-read.json` (sha256 в `acceptance/README.md`).
* Тесты-свидетели по пунктам: `tests/test_p0_initfix_initiative_observer.py`,
  `tests/test_asap8_v63_b01_initiative_observer.py`, `tests/test_soul1_w5_observer_gates.py`.
