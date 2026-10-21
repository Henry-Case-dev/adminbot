# PROBE-EXEC — исполняемые пробы RFL-хвоста (lane ASAP8-EXEC-TAILS)

Дата: **2026-10-21** (сервер UTC 09:00–09:16). Репо HEAD: `bf17a972`.
Прод: **2.58.105 @ `a6246e33fc8db237cc2f57232006d62ab885b50d`** (healthz 200
{"status":"ok","version":"2.58.105"}, service active, `git rev-parse` сверен
по SSH; tracked-модификаций продукта нет).

## Метод и дисциплина

- Read-only захваты с прод-сервера: **3 одиночных SSH-коннекта** (recon 09:00,
  захват №1 09:10, захват №2 09:15; между коннектами >1 мин, без ретраев
  логина — правило fail2ban). SQLite открывался строго `mode=ro`;
  journalctl — одним проходом во временный файл, удалён после речек.
- Ноль сообщений в реальные чаты, ноль LLM-вызовов; единственный внешний
  платноподобный вызов — **один** fetch транскрипта YouTube через боевой
  движок (проба R07, провайдер сконфигурирован — journal `proxy=set |
  cookies=set | resproxy=set`).
- R17: в артефактах только id/счётчики/тайминги/хэши; тексты сообщений и
  claim_text не печатались; proxy-эндпоинт замаскирован
  (`13…46:8000`, auth_configured=true).
- KNN-тайминг (R13): read-only реплика SQL `_vec_candidates` float-пути +
  `_staged_knn_scope` (services/summary_memory.py:4593-4604, 2883-2915) на
  реальной БД с синтетическим unit-вектором (без embed-вызова) — измеряются
  тайминг и chat-scope, не расстояния.

## Результаты по строкам

### B10-R01 — два реальных Summary L2 + diff источников → VERIFIED
Чистые L2-раны (стадия `l2` ok + `l2_review` ok) в `summary_runs`/`summary_run_stages`:
1. `5187dee4…` 17.10 13:00 UTC, chat -1002661910336 — **DONE, published rich
   `message_id=1164062`** (совпадает с incident-tail-25887: 9 абзацев);
2. `b61e74b5…` 19.10 19:00 UTC, тот же чат — **l2 ok + l2_review ok,
   SUMMARY_COMPLETE: paragraphs=10, fallback=none, health=ok** (публикация
   этого рана НЕ состоялась — publication_status=failed; честная оговорка);
3. + три чистых L2 на втором чате (-1004482340693): 14.10 13:00 (`53e54bd3…`,
   `1201`), 15.10 07:00 (`c8a7e040…`, `1427`), 15.10 13:00 (`b85fbbca…`, `1496`).
Diff источников двух L2-ранов одного чата (durably в summary_source_windows,
`capture2-l2-r07.json` §s1_source_diff_same_chat): 17.10-ран — 489 сообщений
(ids 1163555–1164053), 19.10-ран — 335 (ids 1166452–1166884), пересечение 0
(окно полностью продвинулось), sha12 id-списков зафиксированы.
Журнал: `SUMMARY_COMPLETE mode=hybrid_l2 … paragraphs=10 … fallback=none`
(19.10 19:13 UTC). Замечание: `chat_summary_levels` пуста (0 строк) — текущий
L2-контур живёт в summary-пайплайне, легаси-таблица не используется.

### B10-R13 — scoped vector/GraphRAG до top-K + прод-тайминг → VERIFIED
Реальная БД (`capture1-db-journal.json` §s2): graph_facts_vec **16005** строк
(dim=3072; главный чат 15747), graph_facts 19782 (expired 3970).
Staged-KNN на реальных данных: главный чат want=5 → k=20, own=15,
foreign отфильтрованы, **foreign_leak=0**, 2079.7 ms (холодный первый скан);
want=10 → k=40, own=28, 836.4 ms; малый чат (255 своих строк) — staged добор
20→80→320→512, own=0 → честный `partial=True` (чужие заняли K до cap) —
ровно документированное поведение D06, **чужие строки не возвращаются**.
Прод-тайминг стадии vec-кандидатов: 0.7–2.1 s на 16k векторов (полный
pipeline-тайминг не инструментирован — оговорка). FTS-eligibility
(`'а*'`, главный чат): fresh-only 3080 vs historical 3747 строк — **+667
истёкших/архивных видны только исторически** (eligibility ≠ retention,
B03.1) — 21.0 s / 25.1 s на ПОЛНЫЙ match-count (проба считала всё множество;
боевой retrieval ограничен LIMIT 10 — существенно дешевле).
Контроль displacement 9/9 — тесты; на реальных данных scope подтверждён.

### B10-R16 — live-примеры датирования Фактчека → VERIFIED
`mca_factcheck_runs`: 23 рана, **20 с original_published_at** (precision=day).
Живые примеры (`capture1-db-journal.json` §s3):
- `tfr-b900e314…` 21.10 08:36 — temporal unknown, insufficient_evidence,
  original 21.10 06:21, `date_source=telegram_origin`, repost_received 08:19;
- `tfr-b12dab00…` 07.10 — **temporal current**, supported,
  `date_source=telegram_origin`, repost через 12 мин после оригинала;
- `tfr-469b239a…`/`tfr-af523f2a…`/`tfr-38ab2b7f…` — **temporal
  old_but_valid**, supported (в т.ч. durable-пруф из AMD-проб 20.10);
- repost-детекция: `tfr-bb89255f…` — оригинал 15.10 17:46:59, репост 17:56:21;
  серия 16.10 — `date_source=telegram_message`.
date_source покрыты оба класса (telegram_message/telegram_origin), fallback_used=0,
кэш-хит 1. Machine key inventory 16/16 — уже закрыт (prep-rfl-binding).

### B10-R07 — реальный provider-проход транскрипта (407 + proxy health) → VERIFIED
Провайдер на проде сконфигурирован (journal 21.10 08:32: `[youtube engine]
config | proxy=set | cookies=set | resproxy=set`; `VideoDownloader enabled
(cobalt=http://localhost:9000)`). Выполнен **реальный проход** боевого каскада
(`YouTubeTranscriptEngine.fetch_transcript`, один публичный ролик, без LLM):
- proxy_profile: configured=true, auth_configured=true, endpoint masked;
- результат: yt-dlp → transient («extract_info returned None»), transcript-api
  → **реальный 407 Proxy Authentication Required от апстрим-прокси**;
- движок классифицировал `proxy_auth_failed (407)` → **permanent, no retry**,
  ровно один WARN (контракт F9/Y1) — `capture2-l2r07.json`
  §s5_r07_youtube_provider_pass.
Журнал сервиса за 17–21.10: real-транскрипт-запросов не было (только config-
строки) — 407-класс воспроизведён на живом конфиге агентской пробой.
Честная оговорка: success-путь (реальный текст транскрипта) сейчас заблокирован
состоянием апстрим-прокси (407) — внешнее состояние провайдера, не кода.

### B10-R09 — concurrent UI edit/refresh/409 (dossier/settings) → VERIFIED
Добавлен поведенческий тест гонки
`tests/test_asap8_v63_b10r09_settings_409_race.py`: два писателя с одним
optimistic-токеном → первый коммитится, второй получает ChatParamsConflict
(→ API 409 {code:'conflict', current_updated_at}) с АКТУАЛЬНЫМ токеном,
refresh+retry проходит. Реальный optimistic-протокол chat_params
(один токен на профиль, advisory+in-process лок). Живую мутацию настроек
владельца на проде пробы не делают (запись в чужой конфиг = вне read-only
дисциплины); 409-маппинг API-слоя уже покрыт существующими API-тестами
(test_budget_overrides_merge_round1024, test_chat_lore_api).

### B12.6 — три остатка → VERIFIED
`tests/test_asap8_v63_b126_residuals.py` (REGRESSION owner=B12.6):
1. **Ошибочный адресат** (2 теста): собственное сообщение-триггер исключается
   из исторической ступени резолвера (M-2 wiring) → sender не назначается
   автором (ambiguous → unresolved с исключением); ≥2 авторов → ambiguous,
   ни к кому не биндится; контроль: единственный чужой автор резолвится.
2. **GraphRAG hallucinated stats**: реальный `cs.measure()` по настоящей БД →
   `build_metric_result`/claims → numeric-гард: черновик с выдуманными числами
   в стат-контексте не публикуется (коррекция до verified_phrase измерения),
   честный ответ проходит байт-в-байт.
3. **Side effects измеримы**: перенос даёт полный измеримый след — per-table
   moved, backup 1:1 (стандартные таблицы), суммарные счётчики неизменны
   (0 DELETE), integrity ok, идемпотентность (повтор = 0 строк).
Замер: `b126-side-effects-measure.json` — синтетическая БД 5666 строк:
moved {5000/600/40/25/1}, backup 1:1 (кроме известного gap), totals
неизменны, move 0.314 s, повтор 0.002 s / 0 строк, integrity ok.

### Оставшиеся READY_FOR_LIVE (честно, не закрываемы агентом)
- **B10-R06 / REQ-B11-E2E** — квота эмбеддингов до сих пор не восстановлена:
  journal 21.10 07:03 `EmbeddingGroupCoolingDown, next_allowed_at=23:25 UTC`,
  7д: `EMBED_API_DEFERRED` ×357, «embedding generation not serviceable …
  FTS-only (A06)», 331 строка 429. Ждут восстановления квоты провайдера
  (WAITING_EXTERNAL) + backfill-проба (запись в БД + платные вызовы).
- **REQ-B09-BODY / B10-R10** — живого переноса supergroup не было:
  `chat_id_migrations` пуста на проде (21.10). WAITING_EXTERNAL: реальное
  событие Telegram migrate_to_chat_id.
- **B10-R11** — частичный journal-речек: direct_fresh_generation 335/7д,
  social_banter_intent 25, historical_evidence_intent 2, rate_limit skipped 3,
  quote_resolver_step 335 — реальные режимы/интенты видны; явных примеров
  «запрет без ключа»/бюджет-отказов в окне не найдено → остаётся RFL.
- **REQ-B03-DOD / V03** — read-only части закрыты пробой (см. R13: scope,
  eligibility, тайминг на реальных данных), но «архивный факт попал в
  relevant context» живого потока и confirm/refute-мутация не воспроизводились
  агентом → остаются RFL с суженным остатком.
- **PROBE-EXPERIENCE (REQ-B02-DOD, V02, B10-R12)** — ждут естественного
  боевого потока («доказанный lesson из боя»); не тронуты.
- **B10-R14, B10-R15, B10-R19** — вне этого лейна (UI-restart 2 чата, Dream
  gate off, видео-артефакт) — остаются RFL.

## ⚠ Инцидент-находка замера (требует отдельного фикса)

**backup-петля миграции не покрывает `chat_running_summary`** (и любую
таблицу, где chat_id = алиас rowid): PK(chat_id) = INTEGER PRIMARY KEY =
rowid; у суперчатов chat_id отрицательный, а backup читает
`WHERE chat_id = ? AND rowid > -1` → строка конспекта НЕ попадает в
`chat_migration_backup`, хотя UPDATE её переносит (нарушение контракта
«backup ДО записи» / REV-W1 F1 для этой таблицы; остальные таблицы покрыты).
Воспроизведено strict-xfail тестом
`test_backup_covers_running_summary_negative_pk` (сейчас xfailed; после
фикса services/chat_migration.py станет XPASS и потребует снятия маркера).
Прод-риск сейчас нулевой (реальных миграций не было — chat_id_migrations
пуст), но до реального переноса supergroup фикс обязателен. Код продукта в
этом лейне не менялся (WRITE_SCOPE) — фикс отдельным лейном.

## Гигиена артефактов

- `capture1-db-journal.json` — захват №1 (S1 L2/стадии/окна, S2 vec/FTS/
  тайминги, S3 фактчек, S4 события/алиасы).
- `capture2-l2-r07.json` — захват №2 (чистые L2-раны, diff источников, R07).
- `journal-extracts-2026-10-21.txt` — служебные строки журнала (SUMMARY_*/COVER_*/
  youtube engine/embed-429), без контента чатов и без секретов.
- `b126-side-effects-measure.json` — замер B12.6.
- Скрипты проб: `OPENCODE_WORKFLOW_SCRATCH/probe-exec-tails/` (не в репо).
