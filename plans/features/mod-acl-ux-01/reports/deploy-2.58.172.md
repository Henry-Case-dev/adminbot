# Deploy 2.58.172 — MOD-ACL-UX-01 семантический контракт уроков, schema v46

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`), 09.11.2026 06:18–06:19Z.

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.172` = `bee14188f5d554021813db332ab35abea2ecbff5` |
| Кандидат на ревью | `c51933d0` (Reviewer APPROVED, изолированный checkout) |
| Bump-коммит | `bee14188` — только `APP_VERSION`, README, F8-мета, version-пины (27 файлов / 28 строк) |
| Предыдущий прод | `4f7428e6` @ `release/2.58.171`, healthz 2.58.171, schema 45 |
| MUTABLE_WORKTREE_REQUIRED | **no** — immutable checkout по SHA, `dirty_after=1` (только untracked `.cache/`, было и до выкладки) |
| Repo write scope | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 25 test-файлов |
| Δ DDL | **+1 шаг**: `user_version` 45 → 46, `schema_migrations` 34 → 35 |

### Сверка дельты

Ветка кандидата ответвлена от `2779059b`, поэтому `4f7428e6` (bump 2.58.171) в неё не входит.
Проверено, что это безопасно:

- `git diff 4f7428e6..c51933d0 -- services/` **побайтово равно** `git diff 2779059b..c51933d0 -- services/`
  (139 451 символов, идентичность подтверждена) — то есть прод-код 2.58.171 (STALE-DEADLOCK, `2779059b`) присутствует;
  `4f7428e6` не содержит кода: README, `APP_VERSION`, F8-мета, 24 version-пина.
- Посторонних продуктовых правок в кандидате нет: services — 6 файлов (mca_experience, mca_experience_jobs,
  database, experience_diagnostics, param_catalog, retrieval_context), плюс тесты, README, settings.
- Каталог: `595 → 606` ключей (категоризованных `569 → 580`), F8 `--check` = `CHECK OK: реестр 606 == REGISTRY`.

## 2. Предрелизные прогоны (на точном кандидате `bee14188`)

| Набор | Результат |
|---|---|
| experience (`lesson_strategy_contract` + mca16 a–f + stale-recheck hotfix + asap8 d05/b02 + evol020 + mca17c oversight) | **177 passed** |
| maintenance (memory_maintenance, communities_maintenance, mca17c invariants, mca18 lifecycle, mca17 sleep workers) | **109 passed** |
| analytics + каталог (param_catalog, F8 registry, ia_inventory, scope_selector, summary catalog, webapp_analytics, pipeline_analytics, analytics_viz, token_analytics) | **242 passed** |
| memory-подсистема (`-k "memory or param_catalog"`, 1263 кейса) | **1262 passed**, 1 failed, 1 error — оба **предсуществующие** |
| version-пины + webapp-пины + mod-acl checkpoint (25 файлов) | **879 passed** |
| F8-каталог `gen_param_registry_round1025.py --check` | `CHECK OK: реестр 606 == REGISTRY, RTS/map идемпотентны, R17-чисто` |

Предсуществующие падения (воспроизведены на прод-базе `4f7428e6`, к дельте не относятся):

- `test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::test_style_anchors_not_broken` —
  `AttributeError: 'AnchorsDB' object has no attribute 'get_active_participants'` (неполный тест-дубль).
- `test_youtube_multimodal_download_round1024.py` — 18 errors setup:
  `module 'handlers.youtube' has no attribute 'get_smart_cache'` (дрейф тест-дубля).

Локальный предпрогон миграции на синтетической v45-БД с 3 реальными строками:
`user_version 45 → 46`, `schema_migrations +1`, 10 аддитивных колонок, 19 шаблонов,
строки сохранены (`origin_kind NULL`, `temporal_rank 1.0`, `confirmation_count 0`),
повторный `initialize()` — no-op 0.004 s. Миграция шага — 0.093 s.

## 3. Выкладка

- Снапшот `/tmp/predeploy-258172.db`: SQLite backup API с read-only источника,
  `user_version 45`, `quick_check ok`, 6 уроков, 1 839 075 328 B,
  sha256 `c5ccd69fdd9b38d5995cf99be68633a41b37632e3ef28fd8ff4ce708285901f6` (read-back на снапшоте).
- `git fetch origin release/2.58.172` → `git checkout -B release/2.58.172 bee14188`, HEAD совпал.
- `systemctl restart admin_bot` (06:18:14Z), затем повторный рестарт для проверки идемпотентности
  (06:19:30Z). Итоговый процесс `MainPID 3337241`, `NRestarts=0`.
- Диск после снапшота: 34G/99G (36 %).

## 4. Миграция v45 → v46 (факты с прода)

| Проверка | До | После |
|---|---|---|
| `user_version` | 45 | **46** |
| `schema_migrations` | 34 | **35** (`46 / lesson_semantic_v46`) |
| `quick_check` | ok | **ok** |
| `mca_lessons` строк | 6 | **6** (до тика), затем 7 (новый урок тика) |
| Колонки v46 | — | все 10: `confirmation_count`, `independent_sources`, `origin_kind`, `semantic_rule_key`, `semantic_scope_key`, `temporal_rank`, `superseded_at`, `semantic_confidence`, `contradiction_count`, `applicability_version` |
| `mca_lessons_semantic_templates` | — | **19** строк, 19 уникальных `rule_key` (context 2, failure_pattern 2, retrieval 1, social_preference 11, tool_usage 3) |
| Существующие уроки | 5 active + 1 suspended | те же 6 строк: `origin_kind NULL`, `temporal_rank 1.0`, `confirmation_count 0`, `semantic_confidence 0.0`; сверка со снапшотом: **изменённых строк 0** |
| Повторный init | — | `migrations: start | current user_version=46 | pending=[] | total 0.0s` — строгий no-op |

Журнал: `pending=[46]`; backup-guard `done in 55.0s`; `migration v46: … templates_seeded=19`;
`migration v46 applied in 0.0s`; `migrations: complete | user_version=46 | total 55.0s`.
Повторный запуск: `pending=[]`, `total 0.0s`.

## 5. Пост-деплой

| Проверка | Факт |
|---|---|
| Unit | `active (running)`, **NRestarts=0**, MainPID 3337241, старт 06:19:30Z |
| `/healthz` локально (127.0.0.1:8000) | `{"status":"ok","version":"2.58.172"}` |
| `/healthz` публично (`admin-bot.duckdns.org`) | 200, `2.58.172` |
| Served asset | `web/app.js` sha256 `e6fdef1f…2291` = отданный по `https://admin-bot.duckdns.org/web/app.js` (2 082 497 B) |
| Журнал | `Traceback` **0** с 06:17Z |
| Планировщик | job `MemoryMaintenanceService._tick_experience_review`, interval 15 мин; тик 06:34:33Z выполнен успешно, следующий 06:49:33Z |
| Схема | `user_version 46`, `schema_migrations 35`, `quick_check ok` |

Примечание: одно чтение схемы, сделанное в окне самой миграции, показало промежуточное состояние
(`user_version 45` при уже закоммиченном DDL). Шаг пишет DDL-коммит и штамп версии разными коммитами;
следующий старт зафиксировал `user_version=46`, `pending=[]`, данные целы.

## 6. Живая проверка (read-only)

Тик опыта 06:34:33–06:34:39Z, `[mca16] experience review tick | status=completed`.

| Пункт | Реальный результат |
|---|---|
| `origin_kind` / статусы | `active` 6 (5 × `origin NULL` legacy + 1 × `explicit` новый), `suspended` 1; **`llm_hypothesis` в active/validated = 0** |
| Пороги в конфиге | фактические: чатов/проход **6**, строк/чат **50**, архив/прогон **200**, свежий хвост **5000**, лаг-порог **500**; пороги классов **2 / 1 / 1 / 3**; hot-override’ов нет (действуют заводские). `llm_hypothesis` ∉ `LESSON_AUTO_CONFIRMABLE` |
| Лимиты дренажа в тике | прочитано **100** строк = 2 чата × 50 (≤6 чатов, ≤50 на чат); `semantic_selected 47`, `eligible 47`, `throughput 100` |
| `temporal_rank` | min 1.0 / max 1.0, строк 7; вне `[0, 2.0]` — **0** |
| Рендер блока уроков | канонический серверный шаблон: `<Verified_Lessons>` + фиксированный заголовок + строки `- [type] <канонический текст>`; 6 active → в блок попало 5 (существующий bounded-кап `block_max_items`); все тексты ∈ закрытый каталог/`mca_lessons_semantic_templates` (`non_canonical = []`) |
| 8 событий аналитики | **наблюдены 3**: `experience.lesson_candidate` 1, `experience.lesson_activated` 1 (`origin_kind=explicit`, `confirmation_count=2`, `temporal_rank=1.0`), `experience.fresh_stream_lag` 2. **Пока не наблюдались 5**: `lesson_rejected`, `lesson_contradiction`, `archive_direction_selected`, `archive_coverage`, `stale_belief_flagged` |
| Архивный курсор | **ещё не создан**: `archive_rows_scanned 0`, `archive_skipped_fresh_backlog 1`, `archive_watermark None`. Механизм работает (честный skip при непустом свежем бэклоге); курсор появится после дренажа свежего потока |
| `_forbidden_effects` | ложных срабатываний **0** |
| Применения уроков | `mca_lesson_applications` = 0 строк (применение ждёт реального хода в чате) |
| Прочее | `recheck_resolved 5`, `stale_marked 5`, `errors 0`, `semantic_write_failures 0`, `semantic_read_errors 0`, `semantic_parse_invalid 0` |

Новый урок `da7931b3…` — `failure_pattern`, scope `chat`, `origin_kind=explicit`, `confirmation_count=2`,
`temporal_rank=1.0`, текст канонический (из серверных шаблонов), пользовательский текст не скопирован.

## 7. Успевает ли свежий поток

- Приток (реальные сообщения): 2 265 / 2 218 в среднем за сутки (03–08.11: 1486–3356/сутки).
- Пропускная способность дренажа: 100 строк за проход (2 чата × 50) × 96 проходов/сутки ≈ **9 600 строк/сутки**;
  верхняя граница при 6 чатах — **28 800 строк/сутки**.
- Текущий бэклог свежего потока: **15 628** строк в 1 чате (`lag_seconds` ≈ 7 377 013 ≈ 85 сут),
  `actionable_rows 15 628`, `deferred_chats 0`.
- Вывод: мощность дренажа (≈9.6k/сут) выше притока (≈2.2k/сут), чистый слив ≈ +7.4k строк/сутки →
  бэклог ~15.6k закрывается примерно за **2 суток** штатной работой, без вмешательства.
  Узкое место — не число чатов (2), а кэп 50 строк на чат за проход.

## 8. Откат

- **Код:** `git checkout release/2.58.171` (`4f7428e6`) + `systemctl restart admin_bot`.
- **Данные:** `/tmp/predeploy-258172.db` (v45, `quick_check ok`, sha256 `c5ccd69f…01f6`) —
  состояние до миграции; дневная копия `backups/local_database_20261109.db`.
- Схема v46 старым кодом не читается (аддитивные колонки + новая таблица инертны), `DROP` не требуется.
  Тик после отката добавил 1 урок (`da7931b3…`) — откат кода его не удалит; точное прежнее состояние — только из снапшота.
- Диск 34G/99G — место под снапшот есть.

## 9. Что осталось наблюдать

- Качество уроков во времени (формулировки, полезность, отсутствие дублей канонических текстов в блоке).
- Первое реальное противоречие: `contradiction_count > 0` и `temporal_rank × 0.5` (событие `lesson_contradiction`).
- Первое повторное подтверждение: `+0.1` к рангу (событие `reconfirmations`).
- Применения уроков в живых ответах (`mca_lesson_applications`) — появятся на первом ходе, где отбор даёт урок.
- Архивный курсор и покрытие по чату/году — после дренажа свежего бэклога (~2 суток).
- `experience.lesson_rejected` — при первом отклонённом предложении урока.

## 10. Находки (не блокеры)

- `experience.fresh_stream_lag` пишется с `reason_code=unmapped:18d14796` и даёт WARN
  `mca_event unmapped reason_code` — событие доходит, но код не в карте маппера (как существующий
  `detector_scan unmapped:4f8aced7`). Косметика наблюдаемости, кандидат в бэклог.
- В отрендеренном блоке два разных урока (`9c97344e…` и новый `da7931b3…`, оба `failure_pattern`,
  разные чаты) дают одинаковый канонический текст — контент-наблюдение, не дефект контракта.
- `requirements_gate.py check --stage release --slice EP-E-LESSON` = **FAIL (46 ошибок)**: карта эпика
  не сведена (все 176 строк `PENDING`, `candidate_commit` пуст) — это работа PM/Orchestrator по привязке
  доказательств, а не технический сбой выкладки. Статусы в карте не менялись.
