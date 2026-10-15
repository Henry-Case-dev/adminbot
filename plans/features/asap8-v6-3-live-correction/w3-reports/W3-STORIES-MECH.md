# W3-STORIES-MECH — B08 (Stories backend) + B11 (генератор отчёта механизмов)

Lane: W3-STORIES-MECH · Базовый HEAD: db8dae5 (свежее f1418d7 + fix b09) · Коммиты не делались (по брифу).
Дата: 15.10.2026

## 1. Что реализовано

### B08 — Stories: истории с содержанием, временем и участниками (backend)

**Root cause baseline**: `services/mca_episodes.py::_process_segment` при
отсутствии LLM нормализует сегмент (текст отбрасывается) и сохранял
`title="Эпизод 1780…"`, `summary=""` → в карточке «Краткое содержание:
неизвестно» и «история №17800000» — техзапись выдавалась за готовую
историю. Даты могли отрисовываться как 1970 (0/None → epoch), участники
шли плоским списком без ключевых.

Изменения (без DDL — Δ database.py = 0, все статусы derived):

1. **Детерминированная сборка из фактов (B08.1/B08.5)** —
   `mca_episodes.deterministic_episode_card`: заголовок из самого
   содержательного сообщения (не цифро-заглушка), утверждения = сами
   исходные сообщения с refs на стабильные ключи, честная выжимка.
   Ничего не выдумывается (имён/итогов/дат). Пайплайн теперь передаёт
   исходные строки сообщений (`sources` map) в `_process_segment` —
   раньше текст терялся при нормализации сегмента.
2. **Честный статус контента** — `CONTENT_READY`/`CONTENT_INSUFFICIENT`
   (`episode_content_status`/`story_content_status`, derived): пустая
   техзапись (pending/unresolved) не считается готовой историей.
3. **Safe bounded backfill/re-extract (B08.2)** —
   `episodes_needing_backfill` (кандидаты: пустые эпизоды с живыми
   исходными ключами, cap 20) + `EpisodesBackfillRunner.process_content_backfill`:
   re-extract по источникам (LLM или детерминированная пересборка пустых),
   после успеха — пересборка историй; источников нет → честный `no_sources`
   (записи не удаляются, не выдумываются). Kill-switch OFF → no-op.
4. **Три РАЗНЫЕ даты + U03.2-принцип** — DTO карточки/ленты/таблицы:
   `event_start_ts`/`event_end_ts` (оригинальные события), `discovered_at`
   (обнаружение), `rebuilt_at` (пересборка). `_norm_ts`: 0/отрицательные/
   мусор → None (не фальшивый 1970), ms → sec.
5. **Участники 3–5 + остальные (B08.2)** — `participants_by_involvement`
   (порядок по вовлечённости, детерминированный); read-side:
   `primary_participants` (≤5) + `others_count`; полный список остаётся в
   `participants` (раскрытие без потери).
6. **Честное отображение (B08.3)** — `display_title`/`display_summary`:
   insufficient_sources → «Не удалось восстановить сюжет» +
   «Не удалось восстановить сюжет: нет источников» (нет ключей) либо
   «Сюжет ещё не восстановлен по источникам — ожидает повторной сборки»;
   авто-цифровые заглушки («Эпизод 1780000000»/«История 1650…») и пустые
   заголовки подменяются первым фактом/нейтральной меткой.
7. **Раскрываемая хронология с источниками (B08.1)** —
   `web_stories.story_timeline`: хронология утверждений карточки
   (`{ts, episode_id, text, refs:[{message_key, tg_message_id, url}]}`);
   ссылки — по правам: только валидированные t.me/c-ключи супергрупп
   (`_tg_link`, chat-scope изоляция сохранена), ЛС/archive_only — честный
   `url: null` (ссылка не выдумывается).
8. Вне скоупа лейна (не тронуто): UI-карточки (web/**), БД, каталог
   параметров, settings. Override-контракт A13 и CAS не затронуты.

### B11 — генератор отчёта скрытых фоновых механизмов (backend-часть)

Новый read-only инструмент `tools/v63_b11_mechanisms_report.py`:

* **Перечень (REQ-B11-SCOPE)** — все 10 механизмов: сон, глубокий сон,
  пересмотр убеждений, парадигмы, self-model/traits, graph memory,
  инкрементальный embedding/backfill, Experience, Initiative, Summary
  scheduler.
* **Цепочка (REQ-B11-CHAIN)** — по каждому: `gate` (env-мастер + settings-
  default + PG global `bot_settings` + PG chat `chat_profiles.chat_params`,
  effective с именованным источником слоя) → `last_attempt` (время/статус/
  skip reason/ошибка из memory_dream_log, mca_belief_reviews,
  mca_trait_observations, summary_runs, task_jobs, mca_events) →
  `real_input` (реальные счётчики входов: graph_facts, smart_messages,
  mca_experience_episodes, mca_trait_observations) → `producer` (зарегистрирован
  ли — из code-реестра `mca_process_registry`, с enabled_gate) →
  `last_job`/`job_24h`/`job_7d` (task_jobs: kind/coalesce, heartbeat, attempt,
  reason) → `write_result` (парадигмы/watermark/reviews/lessons/intents/
  generations/quota/backlog) → `used_in_response` (честный tracked флаг) →
  `counters_24h`/`counters_7d` (реальные таблицы, chat-scope фильтр).
* **Диагнозы (REQ-B11-E2E)** — фиксированный словарь: `ok`, `producer_off`,
  `no_input`, `cursor_stalled` (backlog embedding-векторов растёт, job
  завершён без прогресса), `worker_crashed` (stale heartbeat/failed job),
  `ttl_due` (просрочен интервал), `never_run` («включено, но не
  запускалось» — НЕ зелёное), `attention` (последняя попытка ошибочна),
  `unavailable`. Никаких dummy-счётчиков.
* **Надёжность** — SQLite открывается `mode=ro` (не мигрирует, не пишет);
  PG (опционально `--pg-dsn`/`POSTGRES_DSN`) — только SELECT; каждая
  секция fail-soft → `unavailable` с причиной; отсутствие отдельных
  таблиц (например vec0 `graph_facts_vec` на части инсталляций) не роняет
  отчёт. Вывод: JSON (--json PATH или stdout) + человекочитаемый хвост.
* UI/прод-прогон (Wave 4) — вне лейна: отчёт готов к запуску на проде,
  E2E-кейсы на живых механизмах (REQ-B11-E2E live_required) —
  `LIVE_UNVERIFIED` до деплоя.

## 2. Acceptance ledger

| Требование | Статус | Доказательство |
|---|---|---|
| REQ-B08 (B08.1): заголовок/завязка/факты/лица/финал-или-честный вопрос; synopsis+хронология с refs; 3 даты | IMPLEMENTED+TESTED | `tests/test_asap8_v63_b08_stories.py::TestTenReadyStories`, `::TestArchiveDates`, `::TestRefsAndProvenance::test_timeline_chronological_order` |
| B08.1: нет неоснованных имён/финалов | IMPLEMENTED+TESTED | `test_deterministic_card_no_invention`, `test_unknown_outcome_is_honest` (outcome=«исход неизвестен», state=uncertain) |
| B08.2: пустые эпизоды ≠ готовые истории; bounded backfill; 1970-fix; ключевые 3–5+остальные; независимые темы не склеены | IMPLEMENTED+TESTED | `TestInsufficientSourcesAndBackfill` (5 тестов), `test_norm_ts_no_fake_1970`, `test_episode_without_ts_not_1970`, `TestParticipants` (3 теста), `TestIndependentTopics` (2 теста) |
| B08.3: «Не удалось восстановить сюжет: нет источников» вместо «история №…»; оригиналы не удаляются | IMPLEMENTED+TESTED | `test_no_sources_message`, `test_backfill_without_sources_keeps_honest`, `test_backfill_sources_deleted_honest_skip`, `test_bounded_backfill_restores_content` (счётчик сообщений не изменился) |
| B08.4: 10 настоящих эпизодов; merged/continuation; архив; unknown outcome; ссылки; provenance не теряется | IMPLEMENTED+TESTED (fixtures) | `test_ten_episodes_deterministic_ready` (10 тем → 10 готовых историй), `test_merged_continuation_confirmed` (+ `test_continuation_requires_llm_confirmation` fail-closed), `test_event_vs_discovery_vs_rebuild_separate`, `test_timeline_refs_supergroup_links`, `test_provenance_not_lost` |
| REQ-B08 live (карточки в UI, мобильная карточка) | LIVE_UNVERIFIED | UI-часть — W2/поздние волны; данные для рендера готовы (см. §4) |
| REQ-B11-SCOPE: 10 механизмов без пропусков | IMPLEMENTED+TESTED | `test_ten_mechanisms_full_chain` |
| REQ-B11-CHAIN: полная цепочка в отчёте; «включено, но не запускалось» не зелёное | IMPLEMENTED+TESTED | `test_ten_mechanisms_full_chain`, `test_never_run_not_painted_green` |
| REQ-B11-E2E: различаются no_input / producer_off / cursor_stalled / worker_crashed / TTL | IMPLEMENTED+TESTED (фикс. БД) | `TestKnownStatesDiagnosed` (8 тестов) + `test_diagnose_unit_matrix` (все 9 кодов); live E2E на проде — LIVE_UNVERIFIED |
| REQ-B11: fail-soft, read-only | IMPLEMENTED+TESTED | `test_missing_tables_honest_unavailable`, `test_readonly_no_writes` |

## 3. Изменённые файлы / тесты

* `services/mca_episodes.py` — детерминированная сборка, статусы контента,
  вовлечённость участников, `episodes_needing_backfill`, sources-map в
  пайплайне, честный re-extract пустых эпизодов.
* `services/mca_episode_jobs.py` — `CONTENT_BACKFILL_MAX`,
  `EpisodesBackfillRunner.process_content_backfill` (bounded, честный
  no_sources, пересборка историй после успеха).
* `services/web_stories.py` — `_norm_ts` (U03.2), `_primary_participants`,
  `_display_fields`, timeline, нормализация дат ленты/таблицы/карточки,
  новые поля DTO.
* `tools/v63_b11_mechanisms_report.py` — NEW, read-only отчёт B11.
* `tests/test_asap8_v63_b08_stories.py` — NEW, 22 теста
  (TEST-LIFECYCLE: REGRESSION owner=REQ-B08/B08.1–B08.4).
* `tests/test_asap8_v63_b11_report.py` — NEW, 17 тестов
  (REGRESSION owner=REQ-B11-E2E; CONTRACT owner=REQ-B11-SCOPE/CHAIN).

Запрещённые файлы не тронуты (database.py, summary_memory.py, web/**,
param-каталог, settings, initiative_observer, mca_experience_jobs и др.);
git commit не выполнялся. Чужие незакоммиченные изменения
(disk_retention.py, tests/js/**, tools/_*) — не мои, не трогал.

## 4. UI-handoff B08 — структура данных для карточек историй

Карточка `GET /api/stories/{id}` (web/api/stories.py не менялся — новые
поля приходят автоматически из `services/web_stories.py`):

```jsonc
{
  "state": "ok",
  "story": {
    "story_id": "...", "chat_id": -100500,
    "title": "...", "summary": "...",             // сырые поля (как раньше)
    "content_status": "ready | insufficient_sources",
    "display_title": "человеческий заголовок | «Не удалось восстановить сюжет»",
    "display_summary": "выжимка | честное сообщение о недостаче",
    "primary_participants": ["7", "9", "3", "4", "5"],   // ключевые ≤5
    "others_count": 2,                             // остальные (раскрытие)
    "participants": ["7", "9", "3", "4", "5", "6", "8"], // полный список
    "event_start_ts": 1650000000,                  // даты ОРИГИНАЛЬНЫХ событий
    "event_end_ts": 1650003600,
    "discovered_at": 1790000000,                   // обнаружение
    "rebuilt_at": 1790000500,                      // пересборка (≈updated_at)
    "outcome": "исход неизвестен | <факт>",
    "state": "open|closed|uncertain",
    "verification": "unknown|tentative|...",
    "claims": [{"text": "...", "refs": ["<chat>:tg:<id>", ...]}],
    "open_questions": ["нерешённый вопрос", ...]   // честный «вопрос» вместо финала
  },
  "timeline": [                                    // раскрываемая хронология
    {"ts": 1650000000, "episode_id": "...",
     "text": "факт по исходному сообщению",
     "refs": [{"message_key": "-100500:tg:10", "tg_message_id": 10,
               "url": "https://t.me/c/.../10" | null}]}   // null = archive_only
  ],
  "episodes": [ /* каждый эпизод: те же content_status/display_*/],
  "original": {"state": "available|archive_only|unavailable", "links": [...]}
}
```

Правила рендера для W2/поздних волн:
1. `content_status == "insufficient_sources"` → карточка НЕ «успешно
   составленная история»: `display_title` + `display_summary` (честный
   текст), без success-раскраски (V05: unknown ≠ success).
2. Даты: `null` = «нет данных» — НИКОГДА не рендерить как 1970;
   `rebuilt_at` показывать отдельно от `event_*`/`discovered_at`.
3. Участники: показывать `primary_participants`; при
   `others_count > 0` — экспандер «+N остальных» из `participants`.
4. `timeline` — раскрываемая хронология; ref с `url` → clickable
   (по правам, ссылки валидированы сервером); `url: null` →
   «только в архиве».
5. `outcome == "исход неизвестен"` / `open_questions` — блок «Нерешённый
   вопрос», финал не выдумывать.
6. Лента/таблица: те же `content_status`/`display_*`/`primary_participants`/
   `others_count`/`rebuilt_at` на строке.

## 5. Как запускать b11-скрипт (Wave 4, прод)

```bash
# JSON в файл + человекочитаемый вывод в stdout (per-chat гейты/счётчики):
py -3 tools/v63_b11_mechanisms_report.py --db local_database.db \
    --chat-id -100XXXXXXX --json b11_report.json

# Без --json: полный JSON в stdout + human-хвост.
# PG-слой гейтов (global bot_settings + per-chat chat_profiles):
#   --pg-dsn "$POSTGRES_DSN" (или env POSTGRES_DSN; недоступен → честный pg_reason).
# Порог "worker crashed" по stale heartbeat:
#   --stale-seconds 1800 (default)
```

Выход: JSON со `summary.diagnoses` (агрегат по кодам) + 10 секций;
человекочитаемый хвост «== механизм — диагноз» с цепочкой. Код выхода 0,
если отчёт собран. Скрипт только читает (SQLite mode=ro, PG SELECT).

## 6. pytest-числа

* Новые: `tests/test_asap8_v63_b08_stories.py` — **22 passed**;
  `tests/test_asap8_v63_b11_report.py` — **17 passed**.
* Регрессия затронутых швов: mca05 (63) + mca12 (24) + F7 stories (7) +
  mca07 retrieval + mca10b A/B/C + mca01 supervisor + b09 migration —
  все passed (сводный прогон 137 + 83 + 6, exit 0).
* RED-фаза: до фикса sources-map детерминированный путь давал пустые
  карточки (воспроизведено, затем исправлено в этом же лейне).

## 7. Остаточный риск / примечания

* `process_content_backfill` — bounded API (как `process_rechecks`);
  автоматического планировщика для него нет (не создавали новый scheduler
  по брифу «не вводить новую очередь»). Для прод-обкатки можно вызывать
  из существующего цикла backfill-обслуживания Wave 4 — отдельного
  producer'а не требуется.
* B11 per-chat гейты по PG best-effort (nested-walk
  `chat_profiles.chat_params`); при недоступном PG — честный
  `pg_reason`, effective по env/default (не выдумывается).
* E2E REQ-B11-E2E на живых механизмах и Stories narrative в UI
  (V05/B08 live) — postdeploy, вне лейна.
