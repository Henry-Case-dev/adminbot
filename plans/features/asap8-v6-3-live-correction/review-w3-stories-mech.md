# REV-W3PRE — независимый ревью backend-части B08 (Stories) + B11 (механизмы-отчёт)

Лейн: REV-W3PRE (leaf, read-only) · Кандидат: HEAD `ccdd0a7` = 4b64b38 (B08+B11) + хвост mca_episode_jobs · Дата: 15.10.2026
Прогон: tests/test_asap8_v63_b08_stories.py + test_asap8_v63_b11_report.py → **39 passed**; смежные mca05/mca12/f7 → **94 passed**; скрипт B11 жив (JSON 10 секций, честный разброс диагнозов на реальной history-БД).

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| B08.1 детерминированная сборка без выдуманных имён/финалов | VERIFIED | `deterministic_episode_card` (заголовок из ключевого сообщения, claims=сами сообщения+refs, `_SUBSTANTIVE_TEXT_MIN`, EPISODE_UNKNOWN_OUTCOME); тесты `test_deterministic_card_no_invention`, `test_unknown_outcome_is_honest` |
| B08.1 три даты раздельно + 1970-фикс | VERIFIED | `event_start_ts/event_end_ts/discovered_at/rebuilt_at` раздельно во всех DTO; `_norm_ts`: 0/мусор/отрицательные→None, ms→sec; тесты `test_event_vs_discovery_vs_rebuild_separate`, `test_norm_ts_no_fake_1970`, `test_episode_without_ts_not_1970` |
| B08.2 пустые эпизоды ≠ готовые истории; content_status | VERIFIED | derived `episode_content_status/story_content_status` (ready только при непустом summary/claim); `insufficient_sources` → «Не удалось восстановить сюжет»; тесты TestInsufficientSourcesAndBackfill (5) |
| B08.2 участники ≤5+others, порядок по вовлечённости, полный список сохранён | VERIFIED | `participants_by_involvement` (-count,id), `PRIMARY_PARTICIPANTS_MAX=5`, read-side primary+others_count, `participants` полный; тесты TestParticipants (3) |
| B08.2 backfill bounded + kill-switch + идемпотентность | VERIFIED (с NB-1) | `episodes_needing_backfill` (cap 20, только insufficient с ключами, recheck_pending-скип), `CONTENT_BACKFILL_MAX=20`, gate `episodes_enabled` OFF→no-op (тест `test_backfill_disabled_gate`); повторный вызов по готовому эпизоду не candidato |
| B08.3 честный no_sources, оригиналы не удаляются | VERIFIED | тесты `test_no_sources_message`, `test_backfill_without_sources_keeps_honest`, `test_backfill_sources_deleted_honest_skip` (счётчик smart_messages не меняется в `test_bounded_backfill_restores_content`) |
| B08.4 10 эпизодов / 2 темы / merged / архив / unknown / ссылки / provenance | VERIFIED (fixtures) | `test_ten_episodes_deterministic_ready`, TestIndependentTopics (без LLM не склеиваются, с LLM-подтверждением merged — fail-closed), `test_timeline_refs_supergroup_links` (t.me/c для супергруппы, null для ЛС), `test_provenance_not_lost` (SourceRef+EvidenceLink) |
| B08 RBAC t.me/c только по правам | VERIFIED | `_parse_tg_key` (chat_id ключа == чат карточки, изоляция), `_tg_link` только chat_id<0; роутер `_require_chat_access` (A25), TH-1 отказ без раскрытия |
| B11 SCOPE 10 механизмов | VERIFIED | `_mechanism_specs` порядок = ТЗ; тест `test_ten_mechanisms_full_chain` |
| B11 CHAIN полная | VERIFIED | gate(env+settings+PG global+PG chat, именованный источник)→last_attempt→real_input→producer(реестр)→job/24h/7d→write_result→used_in_response(честный tracked)→counters_24h/7d; поля во всех 10 секциях (прогон на history-БД) |
| B11 диагнозы различаются | VERIFIED | unit-матрица 10 кодов + сиды реальных состояний БД: producer_off/no_input/cursor_stalled/worker_crashed(heartbeat+failed)/ttl_due/never_run/attention/ok — не фиктивная матрица; «включено, но не запускалось» ≠ зелёное (`test_never_run_not_painted_green`) |
| B11 read-only + fail-soft | VERIFIED | SQLite `mode=ro` (INSERT отклонён — тест), PG только `fetchrow` SELECT (bot_settings/chat_profiles); builder в try/except → `unavailable`; пустая БД → 10×unavailable без краша |
| B11 счётчики из persisted данных | VERIFIED | все SQL по реальным таблицам (memory_dream_log, mca_belief_reviews, mca_trait_observations, summary_runs, task_jobs, mca_events, graph_facts...); dummy-счётчиков нет; схемы колонок сверены с DDL |
| **B08 honest-display на ленте** | **FAILED** | `_feed_item` (web_stories.py:131-153) отдаёт сырой `title` из `stories_titles` без `content_status/display_title/primary_participants/others_count/rebuilt_at` — легаси-заглушка «Эпизод 1780000000» пройдёт в ленту как есть; противоречит собственному handoff отчёта §6 («Лента/таблица: те же поля») и anti-fake принципу B08 (блокер N1) |
| **B11 запуск задокументированной командой** | **FAILED** | `py -3 tools/v63_b11_mechanisms_report.py --db ...` из корня падает `ModuleNotFoundError: No module named 'config'` (sys.path[0]=tools/; импорты config.settings/services внутри функций; sys.path-бутстрапа нет, в отличие от config_snapshot_diff.py:45 и ещё 7 tools). Работает только с PYTHONPATH=. — задокументированная прод-команда (docstring + отчёт §5) сломана (блокер N2) |
| B08/B11 live (UI-карточки, prod-прогон, E2E на живых механизмах) | LIVE_UNVERIFIED | вне лейна (Wave 4/frontend) — по брифу не блокер |

## Блокеры (оба — маленькие точечные фиксы)

**N1 [блокер, RELATED_SMALL] Лента показывает цифровые заглушки историй.**
- Требование: B08 — техзаглушка «Эпизод 1780…» не показывается как история; handoff отчёта лейна §6 сам обещает ленте те же content_status/display_*.
- Локация: `services/web_stories.py::_feed_item` (+`stories_titles`) — лента единственный surface без read-side подмены.
- Фикс: в `_feed_item` добавить `content_status/display_title/display_summary` (через `_display_fields` по story-строке) + `primary_participants/others_count/rebuilt_at`; либо честно сузить handoff §6 и подменять title на display-вариант.
- Речек: один тест — story со stub-title в ленте → display_title без «Эпизод N».

**N2 [блокер, RELATED_SMALL] B11-скрипт не запускается задокументированной командой.**
- Требование: B11 — отчёт готов к прод-прогону (Wave 4); «скрипт жив».
- Локация: `tools/v63_b11_mechanisms_report.py` — нет sys.path-бутстрапа (репо-прецедент: `config_snapshot_diff.py:45`).
- Фикс: 2 строки в шапке (ROOT→sys.path) как в соседних tools.
- Речек: `py -3 tools/v63_b11_mechanisms_report.py --db <любая .db>` из корня без PYTHONPATH → JSON собирается.

## Nonblocking
- NB-1: эпизод с ключами, но только короткими (<12 симв.) сообщениями — вечный кандидат backfill: каждый прогон считает его «reextracted» без контента, extraction_version растёт «+recheck+recheck». Честность карточки не страдает (insufficient_sources отображается честно). Точечный фикс по желанию: пустой детерминированный card → honest skip (не «reextracted»).
- NB-2: `reextract_episode` пишет updated_at=now — при двух прогонах в одну секунду rebuilt_at не двигается (косметика семантики «пересборка»).

## Вердикт
**Needs Fixes** — 2 конкретных блокера (N1, N2), оба одно-файловые; после точечного речека лейн-кандидат соответствует B08 backend + B11 backend. UI-карточки и live E2E — вне зоны (Wave 4), не блокер.

---

## Fix-note (Orchestrator, пост-ревью)

**N1 (блокер)** — исправлено: лента stories_feed использует те же честные
display-правила (новый _stories_display + EpisodeRepository.stories_rows;
_feed_item отдаёт display_title/content_status/display_summary/
primary_participants/others_count/rebuilt_at; легаси-заглушки не проходят).
Регресс-тесты: test_feed_sanitizes_stub_title_and_carries_display,
test_feed_ready_title_passes_through (24 passed по файлу).
**N2 (блокер)** — sys.path-бутстрап в шапке скрипта (прецедент
config_snapshot_diff.py); речек: py -3 tools/v63_b11_mechanisms_report.py
--db local_database.db из корня → exit 0, отчёт собран (fail-soft секции
честны). NB-1/NB-2 — в backlog. Итог B08/B11: IMPLEMENTED+TESTED (fix
applied); live — Wave 4.
