# Deploy 2.58.139 — release/p0-2026-10-26 (DEPLOY-258139)

**Дата:** 28.10.2026 (server UTC 04:59:52 рестарт). **Ветка:** `release/p0-2026-10-26`.
**DEPLOY_SOURCE:** commit `95e6c7c9f4b6bdf18c27af51079c2878f801f2ac` (detached checkout на сервере; mutable worktree НЕ требуется).
**Кандидат (final review Approved):** `820d443f` (merge `ad239f73`/`97800ad1`: nostalgia rework + FCPOST factcheck resilience W1/W2 + hygiene; registry regeneration `820d443f`).
**Bump-коммит = deployed SHA:** `95e6c7c9f4b6bdf18c27af51079c2878f801f2ac`
(`chore(release-258139): bump 2.58.138 -> 2.58.139 (31-file/33-pin proc set SET EQUAL proc-258138, F8-meta HEAD=820d443f, deltaDDL=0 verified vs 1e438e3a; …) [P0-NOSTALGIA-REWORK+FCPOST,REL-258139]`).
**Pre-state:** `1e438e3a` (2.58.138, healthz 200 внешний 2.58.138, active, NRestarts 0, dirty 13).

## PART 1 — bump

31 файл / 33 пина (SET EQUAL proc-258138): README `v2.58.139`, APP_VERSION
(config/settings.py), F8-meta (APP_VERSION 2.58.139 + HEAD `820d443f`), 24 py-пина
(polygon — 2 строки), 4 JS escaped-regex. Push `f4ce0df6..95e6c7c9 -> origin`
(fast-forward). Evidence-файлы (release-258138/deploy.md,
p0-nostalgia-rework/requirements-map.json) не тронуты — исторические.

| Guard | Результат |
|---|---|
| `python tools/gen_param_registry_round1025.py --check` | **OK**: реестр 586 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны (rc=0) |
| `python -m compileall services handlers` | **OK** (rc=0) |
| deltaDDL | **0** vs `1e438e3a`: 54 файла — factcheck_*-код (W1/W2), smart_cache (снятие slug), mca_gates/module_registry/mca_process_registry (удаление гейта/env/TTL/слага), param_catalog (586) + fixtures/TSV/meta + tests + docs; `services/database.py`/`pg_db.py` не тронуты, ни одного добавленного/удалённого CREATE/ALTER/user_version |
| Версионные пин-тесты | **PASS** на 2.58.139 (в т.ч. `test_version_and_catalog`: `assert APP_VERSION == "2.58.139"` — green) |

Предсуществующие красные (НЕ регрессия бампа; наследуют известный класс
задокументированных в release-258138 пинов): **43 test-файла** с устаревшим
пином `assert len(pc.REGISTRY) == 587` против фактического каталога 586
(fcpost W2: 588→586, fixtures/пины обновлены в 5 файлах, 43 пропущены; часть
красных с 2.58.137 ещё с пином против 588). Version-pin-ассерты тех же файлов
— зелёные. `registry --check` (авторитетный гвард) — OK. → Builder/backlog:
механическая замена 587→586 в 43 файлах, тот же one-line класс.

## PART 2 — deploy (SSH, fail2ban-safe)

`nik@198.46.175.136` (ключ ed25519), `/var/www/admin_bot`, unit `admin_bot`
(venv python 3.12), healthz loopback :8000 + внешний
`https://admin-bot.duckdns.org/healthz`.

| Шаг | Результат |
|---|---|
| Pre-state (recon) | HEAD `1e438e3a`, dirty 13, active, NRestarts 0; внешний healthz **200 2.58.138** (до любого SSH) |
| `git fetch origin release/p0-2026-10-26` | rc 0, `1e438e3a..95e6c7c9`, FETCHED == bump SHA |
| `git checkout --detach 95e6c7c9f4b6…` | rc 0, HEAD = `95e6c7c9f4b6bdf18c27af51079c2878f801f2ac`, dirty 13 сохранено |
| Контент-сверка deployed vs кандидат | **9/9 sha256-12 OK** (settings `6fcac661eb7a`, factcheck_service `5a1b9e59bc50`, factcheck_orchestrator `0e380c79a236`, factcheck_planner `8904f54080dc`, factcheck_renderer `a24fb3f55fa4`, temporal_factcheck `5e761c3b0d0e`, search_aggregator `b918258fe5d7`, smart_cache `20e38c393a49`, handlers/factcheck `6327b8da4ff7`) |
| `sudo systemctl restart admin_bot` | RESTART_RC=0, новый MainPID 753933, ActiveEnter 04:59:52 UTC |
| healthz после рестарта | loopback **200 `{"status":"ok","version":"2.58.139"}`** (try 6); внешний duckdns **200, 2.58.139** |
| Unit | `active`, **NRestarts = 0** |
| Журнал (6 мин после рестарта) | **0** ERROR/CRITICAL/Traceback |

### Миграция prompt-канонов — НЕТ (честно проверено; НЕ красный флаг)

Журнал старта: «канон обновлён» **0**; «уже новый канон» ×6
(`direct_chat_system`, `direct_chat_verbalizer`, `direct_l1_planner`,
`compress`, `factcheck_analyst`, `summary_l1_clusterizer`); «кастом юзера —
НЕ трогаем» ×11; core-патч владельца цел (`character.core` sha
`ead77b2ab509`).

Ожидание lane («L1 planner canon changed in 2.58.136→139 line, migration
expected») **не подтвердилось и не должно было**: PA5W2-канон L1-планировщика
мигрировал ещё на деплое 2.58.136 (задокументировано в
post-asap5-corrective/evidence/live-reprobe-258136.md — «канон обновлён» ×3,
direct_l1_planner → sha12 `14743d288ea3`; прод 2.58.138 унаследовал его —
журнал деплоя 2.58.138 фиксировал тот же no-op набор ×6). В дельте этого
релиза (`1e438e3a..95e6c7c9`) канон-носители не менялись — только
tests/test_p0_prompts_core.py (тест). Ноль миграций == точное соответствие
нулевой канон-дельте и предыдущему постдеплой-журналу. «Pre-migration
state» из брифа относится к пробе 2.58.135 (до PA5W2), а не к текущему
проду.

## PART 3 — postdeploy

### Fact-check resilience live spot-check — **PASS** (read-only, без Telegram)

Метод — паттерн live_pa5_s10/reprobe: стейджинг `/tmp/fcp139` из
`git archive HEAD` (deployed байты, 7202 файлов), `.env` symlink прод,
SQLite — свежий schema-клон (прод-БД не тронута), PostgreSQL RO через
asyncpg server_settings (`ro_ok:ReadOnlySQLTransactionError`), реальный LLM
`deepseek/deepseek-v4.1-flash` (nano-gpt), FakeBot (0 отправок в Telegram).
Сценарий: claim «В 2026 году 366 дней, потому что 2026 - високосный год.
Проверь, это точно так?» + staged empty search results на границе
агрегатора (реальный planner отработал таксономию empty_results; 5
query-попыток за прогон, все → пустая выдача).

| Проверка | Результат |
|---|---|
| Analyst продолжается на пустом evidence | **PASS**: step `temporal_verdict` выполнен в ОБОИХ прогонах (LLM 200, in≈7.8k chars), payload содержит `<analysis_context>`, `<evidence>` отсутствует |
| FC-08 директива | **Ровно 1×** в analyst system (байт-идентичность с deployed `tf.ANALYST_DIRECTIVE`), 0 в других слоях |
| Ответ не «поисковики недоступны» | **PASS**: содержательный разбор «Не подтверждается»: 2026 mod 4 = 2 → невисокосный → 365 дней; basis=`внутренняя проверка: арифметика григорианского календаря`; technical-заголовок «проверка не завершена» не появился |
| Таксономия поиска (W1 §5) | **PASS**: `retrieval_state`=«поиск ответил, но подходящих для проверки материалов не дал — другие подходящие источники могли просто не попасть в выдачу» (no_usable_results, НЕ search-failed) |
| Выдуманные источники | **PASS**: 0 URL, 0 ev-N ссылок в ответе (EvidenceMap пуст → allowlist пуст) |
| Повтор = свежая проверка (кеш вердиктов удалён) | **PASS**: run2 — новый `temporal_verdict` LLM-вызов, 2 отдельных run_id (`tfr-b6e676652c3b444c`, `tfr-aafa21f137c8422c`), `cache_hit=0` в обоих записях, ответы перефразированы (не копия) |
| Delivery | 1 прогон = 1 отправка (FakeBot, egress-гвард) |

Авто-вердикт 8/8 true (`results/verdict.json`). `factual_verdict=refuted`,
`temporal_status=current`, `fallback_used=false`.

### Nostalgia W1 behavior

Deployed байты == reviewed candidate (9/9 pins + git-archive staging).
Incident-shape decline — unit-tested (офлайн T17-T23 зелёные на кандидате);
live-проверка естественными тиками остаётся в установленном статусе
NOST-15/16 (honest PENDING в карте, natural prod ticks) — релиз не блокирует.
Provenance labels — deployed-код кандидата (blob-bound, 95e6c7c9).

### Диск и миграции

`/dev/vda2` 24G: **94% используется, 1.6G свободно** (258138: 96%/1.1G).
Рост-тренд диска — открытый красный флаг из release-258138 (disk-full
инцидент 2.58.136; retention-ревизия — решение владельца, docs/ops анализ
`69ca601d`). Не блокирует. deltaDDL=0 — неожиданных миграций нет; PG
стейджинга только read-only (usage-events INSERT честно отклонены —
fail-open шум, известный контур).

## Инциденты процедуры (не продуктовые)

1. **SSH-бюджет**: деплой = 2 коннекта (recon + основной прогон, ≤3 ✓);
   live-проба = 2 коннекта (первый прогон упал на boot стенда: забыт
   `.env` symlink → пустой `Bearer` ключ → LLM-ретраи → честный
   fallback-вердикт `temporal_fallback_mode`; стенд пересобран, второй
   прогон полный PASS). Итого 4 одиночных сессии, интервалы ≥65 с,
   BatchMode, 0 аутентификационных отказов — fail2ban-дисциплина соблюдена.
   Первый (упавший) прогон сохранён как побочное доказательство
   fallback-поведения: LLM-down → честный insufficient_evidence, доставка
   жива, прод не затронут.
2. Драйвер пробы v1: `settings.APP_VERSION` — переменная модуля, не атрибут
   `Settings` (лечено `getattr(config.settings, ...)`).

## Откат

```
cd /var/www/admin_bot && git checkout 1e438e3a9d4f072d3eed6441e5514af8cad249f9 && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.138, healthz 200. untracked 13 переживают
checkout. deltaDDL=0 → схемных откатов не требуется. Каноны не мигрировали →
откат без канонных последствий.

## Итог

- **Deployed:** `95e6c7c9` (= кандидат `820d443f` + release-bump),
  healthz **2.58.139/200** (loopback + внешний), unit active, **NRestarts 0**,
  журнал чист (0 ошибок), deltaDDL=0, контент 9/9, rollback готов
  (checkout `1e438e3a` + restart).
- **Канон-миграция: НЕТ** — корректно (нулевая дельта; PA5W2 уже на проде
  с 2.58.136).
- **FCPOST live-проба: PASS** (8/8 авто-вердиктов; analyst продолжает на
  пустом поиске, таксономия честная, источников не выдумывает, повторы
  свежие).
- Сырые артефакты пробы: opencode scratch `rel258139/results/`
  (boot/run1/run2/verdict.json, sha-лист); консоль сессий — scratch
  `deploy_main.sh`/`probe_out*.txt` (не коммитятся).
