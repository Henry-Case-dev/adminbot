# HC-TIME (slice B) — матрица временных metadata до Writer

- Контракт: `plans/features/p0-history-coverage-temporal-egress/arch-contract-2026-11-21.md` §3.
- Срез: B, ветка `p0/hc-b`, база A `658661710add58b88dfcb7a18a43bd7ad15d5f89`.
- Наблюдение: изолированный synthetic SQLite-фикстур + реальные функции линии; production trace/реальная переписка недоступны, поэтому строки ниже — проверенный код/фикстура, а не production evidence.
- Обозначения точности: `сек` — точное время источника (UTC), `мин` — рендер до минуты, `мес` — осознанная гранулярность месяца, `unknown` — проверяемого времени нет.

| Канал | Producer → consumer | Время/точность | Идентичность/связи | Фактически доставлено (после B) | Потеря/усечение | B-действие и проверка |
|---|---|---|---|---|---|---|
| `smart_messages` → Global/Thread/Reply/current | `get_smart_window`/`get_messages_around` → `_context_row_line` → `format_context_item(msg)` / `format_speech_item` | `timestamp` сек→мин (UTC), `sent_at` = исходная дата Telegram, `edited_at` = редакция | `user_id`+`author_name`, `tg_message_id`/`msg:id`, `reply_to_id`, `reply_to_author_id`, `forward_source`, `media_type` | ts/автор/ID/forward; **ответ на tg:… (uid …)**; **ред. … UTC** | Ранее reply/edit не выбирались и не рендерились; теперь выбираются тремя reader'ами | SELECT + аддитивные сегменты; тесты `test_window_row_renders_reply_and_edit`, `test_smart_window_selects_reply_edit_sent_at`, payload proof |
| `smart_messages` → history pages | `get_recent_messages` → `ToolRouter._history_lines` → canonical | то же; страницы целых сообщений | + `with_user_id` (`[uid]`) | ts/автор/uid/tg/forward; reply/edit сегменты | Ранее reply/edit не доезжали до страницы | SELECT + сегменты; тест `test_history_pages_show_reply_and_edit` |
| `get_recent_history` header | `tool_router._format_history_page` | range/count, `as_of`, UTC (`_format_timestamp`) | sample_id/anchor/has_next/coverage | count header не изменён; range-поля A | — | A header не трогали; UTC-guard тест `test_message_timestamp_renderers_are_utc` |
| `dig_into_lore` messages/facts | FTS/graph → `format_context_item`; факты через summary tuple | msg сек→мин; fact `rag_ts`→мес | автор/tg/fact id/forward | msg-точность сохранена; fact monthly + `дата записи`, если время только record | нет выдуманных часов | `time_origin` в RAG-tuple; mutation m5 |
| `mca_retrieval_context`: message (FTS/exact/recent/reply) | `_message_candidate` | `timestamp`/`sent_at` → `time_kind=source`; `ingested_at` → `recorded_at`; отсутствие → `unknown` | author/chat_id/item_id/revision | DTO теперь различает source/unknown; `sent_at` не переопределён | `ingested_at` приходит не из всех каналов → `recorded_at=0` (honest unknown) | конструкторы + фон; тесты `test_message_candidate_*` |
| `mca_retrieval_context`: graph fact (FTS/lexical/subject) | `_fact_candidate` | `message_timestamp` → `source`, `created_at` → `recorded`; `sent_at` остаётся COALESCE | subject/speaker/source_ref_id (не identity сообщения) | `time_kind`, `recorded_at`; `valid_from/valid_to` читаются, если строка их несёт; иначе 0 | SELECT graph_facts вне разрешённого B-скоупа (`database.py`: только три smart_messages reader'а) → valid_* в этой линии = 0 | тест `test_graph_fact_source_vs_recorded_not_mixed`; mutation m2 |
| `mca_retrieval_context`: vector fact | `_fact_meta_candidate` | берёт готовый `time_origin` строки, иначе message_timestamp/created_at | subject/speaker | `time_kind`, `recorded_at` | valid_* из vector-строки не приходят (та же граница SELECT) | тест `test_vector_meta_fact_uses_row_time_origin` |
| `mca_retrieval_context`: episode/story | `_episode_candidate` | `event_start/end` → `event`, `discovered_at`/`created_at` → `recorded`, `last_ts` → `source`; `sent_at` не переопределён | episode id | event/discovered различаются, если строка их несёт; facade `list_stories_for_retrieval` отдаёт `created_at`=discovered и теряет event_start/end | **ограничение линии:** `services/mca_episodes.py` вне write scope, facade по-прежнему не отдаёт event-колонки → в проде обычно `recorded`; это честный recorded, не выдуманное событие | конструктор + тесты `test_episode_*`; зафиксировано в limitations |
| Direct `<RAG_Memory>` | `_rag_rows_from_result`/`_search_graph_facts` → `build_rag_context(origin_labels=True)` → `_format_origin_labeled_line`/`_fact_prefix` | `rag_ts`→мес; `message_timestamp`→source, `created_at`→recorded; `created_at` не выдаётся за событие | origin label, author, `fact:`/`tg:`, forward | 8-й элемент tuple `time_origin` на Direct-RAG границе; `[ММ.ГГГГ \| дата записи \| …]` | `build_rag_context` структура/порядок не изменены; legacy search/factcheck не маркируются `дата записи` (не их Writer-линия) | `_fact_prefix`/`_format_origin_labeled_line`; тесты `TestRagFactOrigin`; payload proof |
| `EvidenceSource`/`EvidencePack` → L2 | `direct_execution.py` | текст как есть | tool/status/delivered/truncated | пакер не изменён (B его не касается) | `piece[:floor]` — существующее поведение | аудит; payload proof проверяет собранный `messages`, не bundle |
| `ContextPiece`/allocation | `direct_context_composer.py` | только текст/kind/priority | — | не владелец времени; изменений нет | — | audit-only (по контракту §3.6) |
| running/L2 summary | `get_running_summary`/`get_summary_level` | `window_end_ts`/created — время сводки, не события | — | сводка не рендерится как событие | — | не меняли; §2.7 A |
| прошлые ответы бота | `bot_replies`/ledger `sent_at` | время ответа бота | output id | не событие источника | — | не меняли |
| time injection | `chat_clock` → `render_chat_time_context`; `time_line` Writer | IANA чата + DST; `_fmt_ts` сообщений UTC | `as_of_utc` | одна легенда `Метки времени сообщений в контексте — UTC.`; Chat_Time_Context остаётся локальным | `chat_clock.py` вне B-скоупа; легенда добавлена в `_l2_write_answer`/legacy Writer payload, не в рендер блока | тесты `TestTimeLineLegend`, `test_chat_zone_and_dst_do_not_leak_into_utc_labels`; mutation m6 |
| голосовые/кружочки | handler → transcript в `smart_messages.text` | исходный `timestamp`/`user_id` | tg id | текст транскрипта | — | проверено кодом, не меняли |
| memory communities/associations | — | — | — | **не канал Writer**: отдельных строк/времени в этой линии нет | не изобретаем | зафиксировано как «не канал» |

## Что именно считается «честным unknown»

- `sent_at=0/None`/`legacy_unverified` → `RetrievalCandidate.time_kind=unknown`, `sent_at=0`; дата не подставляется из свежести/индексации/сводки.
- graph fact без `message_timestamp`, но с `created_at` → `time_kind=recorded`, `recorded_at=created_at`, `sent_at` остаётся COALESCE (прежний контракт), в Direct-RAG добавляется `дата записи`.
- graph fact без обоих → `time_kind=unknown`, `recorded_at=0`.
- episode без event-колонок → `recorded`/`unknown`, не `event`.
- `_fmt_ts`: `msg` — `ДД.ММ.ГГГГ ЧЧ:ММ UTC` (секунды теряются намеренно), `fact`/`archive` — `ММ.ГГГГ`; часы из месяца не выводятся.

## Где точность теряется намеренно

- `_fmt_ts(msg)` режет секунды — транспорт/читаемость; это зафиксированный канон.
- `_fmt_ts(fact/archive)` показывает только месяц — осознанная гранулярность производного факта; точное время цитируемого факта остаётся возможным backlog (архконтракт §3.3).
- `valid_from/valid_to` в B-линии не доставляются из graph_facts SELECT (граница write scope); поля DTO существуют с дефолтом 0, не выдумываются.
- Facade эпизодов не отдаёт `event_start/end` (вне write scope); B различает их только если строка их реально несёт.
