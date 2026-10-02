# review.md — post-asap4-corrective-pass (Corrective gate T-4504 @Reviewer)

Feature-ID: `post-asap4-corrective-pass` · Risk-Level: R3 (постановка gate; design-fix декларировал R2, фактический бласт-радиус — онлайн P0-путь embedding + инструмент удаления файлов → проверено по R3-глубине)
Status: **Approved** (release-blocking: 0) · **Round 2 re-gate (corrective micro-fix): Approved for delivery — подтверждён, см. секцию в конце**
Дата: 03.10.2026 · Режим: независимый ревью, код не правлен, коммитов нет

## Binding

- **Reviewed-Commit:** `34ba7d886d6e99a44bc803a91fa197a3030b6e36` (HEAD; по постановке коммитов НЕТ — оба трека в worktree)
- **Working-Tree-Hash:** `4d2c7b04cbef6e77082f69dbd2d7e18aee51a42d3eb16c6ce6b24c41231d6484` — SHA-256 от конкатенации строк «путь SHA256» по 15 файлам review-скоупа (см. манифест ниже). Чужой WIP (`plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, untracked `node_modules/`, `package*.json`, `.playwright-mcp/`, `extra_images/`) в биндинг не входит и не рецензировался (задокументирован в evidence обоих треков).
- **Spec-Hash:** spec.md отсутствует намеренно (corrective pass, указание владельца). Действующий контракт — `design-fix.md`, SHA-256 `7e53d8046194a52f23fb39051aafcbab15c9ba1fc8716f855a95baa5fd44bc67`.

Манифест WTH (per-file SHA-256, порядок фиксирован):

```
config\settings.py 109dd213316ffd58bab94356627c17382e339b6f600f54e38a509b3bfbc16e57
services\embedding_control_plane.py 395d24fc811915be0a2dc9fffe97dbac3969770c23488e83c3cd546043209ac2
services\graphrag_rebuild.py 3bcdc5233b9f1b963d950f3e8befbad22632a90476b9026e13ca9bc0136d4467
tests\test_embedding_control_plane_asap4.py cc58f822674fb82d83ba870e5939900b1e261a416263b3e7a0b07a4e71f6989a
tools\disk_retention.py 1e3c7aff997699c69b3f95a6371ed84d609a6d012f2b476829e192f88faaad98
tests\test_disk_retention_server_t4506.py 0ecff3dfa43b1f7093c8469a8b77dce894154f896160bd1e6e8b2411558d73fb
docs\deploy-disk-retention-t4506.md 9aee78d794e10d6c1e60d7e889277beb6206a43d8213e5c1169b1e5bc0203251
plans\archive\asap-4-...adr-1028-7-asap4-embedding-control-plane.md d221ab82a6dde6a4a672e00f81d69cf0629981f37ff09e5035ee6aa5ffc793f5
plans\archive\requests\post-asap4-corrective-pass.md 464dff02a31dbb698d9268aec6fb71284e2299145e3aa780b10d86f4a89c5720
plans\features\post-asap4-corrective-pass\design-fix.md 7e53d8046194a52f23fb39051aafcbab15c9ba1fc8716f855a95baa5fd44bc67
plans\features\post-asap4-corrective-pass\disk-audit.md 59ae094b3f27d00da072a4dadabfa35f83d428e771dc9734908c3f3a1fb45753
plans\features\post-asap4-corrective-pass\evidence.md e2c75640fc36c57490d22921a13c1642100144fa6f8d65bb92f3eb960fb07737
plans\features\post-asap4-corrective-pass\rca-graphrag.md 01011ce4227a823c0e9b53fa7b3e9ee47e5b87cde1fb1993bb3c8fdee95eda97
plans\features\post-asap4-corrective-pass\requirements-map.md fc306af9e66c1a35fce1f856e332ec469ae5b5b2d135a88476ffe493a38b03a2
plans\features\post-asap4-corrective-pass\tasks.md c44c5567c593f6ff899950101263852fbc19f270bfeb93e5d1afb58d7b8360da
```

## Git base и inspected change scope

База: HEAD `34ba7d8` (= база evidence; прод-состояние 2.58.45 = `b5eaecd` в терминах задач). Проверены: `git status`, полный unstaged-дифф 9 файлов, untracked-вклад трека 2 (`tools/disk_retention.py`, тест, deploy-doc). Review-скоуп: `services/embedding_control_plane.py`, `services/graphrag_rebuild.py`, `config/settings.py`, `tests/test_embedding_control_plane_asap4.py` (трек 1); `tools/disk_retention.py`, `tests/test_disk_retention_server_t4506.py`, `docs/deploy-disk-retention-t4506.md` (трек 2); ADR AMEND (docs-only, T-4502). Критичные неизменённые зависимости: resume-гейты §68 (`_ensure_job` :1644–1695, `_resume_later` :448–484), `_pick_credential` :1204–1215, `retry_after_seconds` :431–440 — в диффе hunk'ов нет (подтверждено).

## Checks performed (независимо, не из evidence Builder'а)

1. Полный pytest: **10837 passed / 2 failed / 1 skipped** (328s) — оба failed = known pre-existing round1026 `forbidden_paths_out_of_diff`/`_vs_baseline` (падают от факта некоммитнутого диффа, вне скоупа). Ожидание задачи выполнено.
2. Целевые: `test_embedding_control_plane_asap4.py` **69/69**; retention **45 passed / 1 skipped**; соседи (graphrag asap32 + memory + rerank + summary hotfix + wave B/C/D + pipeline analytics) **407 passed**.
3. F8 каталог: `CHECK OK: реестр 488`, **EXIT=0**; py_compile 6 .py — EXIT=0.
4. EOL/BOM: 5 новых/правленых файлов pass'а — LF, без BOM; `config/settings.py` — CRLF и в индексе, и в worktree (смешения нет, `git ls-files --eol` сверён).
5. R17-скан полного диффа (4 код-файла + tools + тесты + ADR AMEND): регекс-скан (sk-/AIza/api_key=/Bearer/password) — 0 совпадений; мануальный разбор новых логов/панели/нот — только alias/group-id/счётчики; тестовый «secret-key-material» — фейк, ассерт на отсутствие в панели есть.
6. Код-аудит по контракту design-fix D1–D6 (см. ниже) + adversarial-пробы retention (symlink-эскейп, TOCTOU-подмена файла каталогом, подделанные планы — 3 теста + мои пробы).
7. Прямой probe веток `_quota_parking_seconds`, не покрытых тестами: horizon-оверрайд 7200→`(7200, True, 'horizon')`; кап 200000→`86400`; формула utc_day_end сверена `(int(now)//86400+1)*86400+300−now` ±2s — корректно.

## Трек 1 — GraphRAG механизм-фикс (D1–D6)

- **D1 parking** (`embedding_control_plane.py:449–488`, применение в `_on_error` :1277): spend/daily без RA → `next_allowed_at = utc_day_end + margin(300s)`, cap 86400, оверрайд `EMBED_QUOTA_RESET_HORIZON_SECONDS>0`; с RA → `min(RA,300)` (AM-1); rpm/tpm/rate/unknown — прежняя `retry_after_seconds` (20s). Честность: note `parked kind=X est=Y` vs `429 ... ra=...` (:1294–1299), лог `parked=1|0` (:1308–1314), панель различает. ✓
- **D1 интеграция (0 HTTP до срока):** executor после 429 ставит group-state на длинный horizon; `_pick_credential` (не менялся) пропускает blocked-группу, `PriorityScheduler.acquire` :812–818 поднимает `EmbeddingGroupCoolingDown` без HTTP; после `max_defers` — исключение наверх с parking-horizon. Гейты §68 не менялись и работают: `_ensure_job` :1667–1677 (не истёк → None, generation не сброшен), `_resume_later` :452–475 (sleep-кап 6ч + перепланирование на остаток). Тесты: ровно 1 HTTP при парковке; рестарт не будит, attempts заморожены; resume после срока — та же generation, checkpoint продолжен (processed 2→6, last_id сохранён). ✓
- **D2 backoff** (`graphrag_rebuild.py:252–264`): `min(20×2^streak,3600)×jitter(1.00–1.25)`; применяется ТОЛЬКО к паузам без provider-горизонта (CoolingDown `exc_next<=now` :1430–1436; легаси-ветка исключает RA и spend-kinds :1493–1497) — поверх парковки не наслаивается. Персистентность ΔDDL=0: `quota_exhaust_streak`/`quota_kind_last` в `result_ref` через `_pause_bookkeeping` :378–411, толерантное чтение :267–283 (битый JSON → 0), сброс первым успешным батчем `run_job` :1178–1180 (один раз, только если стрик был). Горизонт 24h не тронут: `pause_started_at` ставится однократно, парковка его расходует, терминал `retry_horizon_exhausted` — существующий путь. ✓
- **D3 диагностика:** `pool_rotation_diagnosis` :318–324 (degenerate = не known ИЛИ |groups|≤1), WARN ≤1/10мин под мастер-флагом :326–347, панель-блок `rotation: none|grouped`+hint :349–359/:1581–1602. `_pick_credential` НЕ менялся — фейковой ротации нет. ✓
- **D4 дедуп 429:** точки инкремента ровно две и взаимоисключающие: `_on_error` :1281 (исключения через executor) и легаси-ветка graphrag :1489 (исключения мимо executor'а); дубль из CoolingDown-конверсии удалён (:1418–1420 комментарий). ✓
- **D5 kill-switches:** `EMBED_QUOTA_KIND_PARKING_ENABLED`/`EMBED_RESUME_BACKOFF_ENABLED` — env-only, default ON (`_flag`/`_env_bool`), читаются зоновыми функциями :97–107. OFF-паритет: parking OFF → старая формула `retry_after_seconds` + старая note (тест: 18–22s + байт-формат note); backoff OFF → ровно 20.0 без джиттера; матрица 4 сочетаний параметризована. ✓
- **D6 ΔDDL=0:** в диффе 0 CREATE/ALTER/ADD/DROP; новые данные только в `result_ref` JSON и значениях `embedding_quota_state`; миграций нет. ✓
- **Смысловой E2E:** «spend-исчерпание (реальный executor-429, фейк-транспорт считает) → парковка до конца суток → 0 запросов (планировщик + рестарт-гейт) → horizon расходуется → resume с checkpoint той же generation» — покрыт связкой `test_parking_spend_until_utc_day_end` + `test_resume_waits_until_next_allowed` + `test_restart_parked_not_woken` + `test_parking_consumes_horizon`. Механизм, не заглушка: цикл «wake→429→20s→wake» устранён структурно (group-gate), а не маскированием. ✓
- **Вторых контуров нет:** фикс внутри control plane ADR-1028-7; AMEND — docs-only, согласован с реализацией. ✓

## Трек 2 — retention tool (`tools/disk_retention.py`)

- **Whitelist-only:** 7 декларативных правил `default_rules()` :125–194, CLI корни не расширяет; соответствие disk-audit §9 сверено построчно (bak.2026-09-15, pre_mca_v19-класс, pytest-of-nik, proxy.log.N, migrate_history+7д/owner-confirm; «НЕ включать» = denylist). ✓
- **Denylist неприкосновенен даже внутри whitelist** (:53–90, `deny_reason` :257–277): рабочая БД+WAL/shm (точные имена, case-insensitive), `local_database_2*.db` (суточный+именованные), ВСЕ `pre_migration_*.db`, маркер `pre_v`, `.env*`, `*history*`, `*cookie*`, сегменты media/uploads/graphrag/chroma/lancedb/embeddings/memory/venv/.git/chrome-profile. Юнит-тесты + adversarial: protected-файлы в whitelist-каталоге не попадают в план и не удаляются из подделанного плана (`test_apply_never_deletes_denied_even_in_forged_plan`). Over-block сознательно безопасный. ✓
- **Dry-run default / --apply:** удаление только по-файлу `os.unlink` с ПЕРЕпроверкой каждого пути (realpath-контейнмент в корнях СВОЕГО правила + denylist + паттерн + islink/isfile) :433–487; rmtree/широких rm нет; каталоги не удаляются. Мои пробы: symlink-файл внутри whitelist-корня → в плане, но apply BLOCKED (outside-whitelist), жертва цела; подмена файла каталогом между plan и apply (TOCTOU) → BLOCKED not-regular-file. Подделанный план (чужой путь/чужое правило/паттерн-мисматч) — блокируется (3 теста). ✓
- **Kill-switch** `ADMINBOT_DISK_RETENTION_ENABLED=0` — проверен живым прогоном CLI: «disabled … no-op», EXIT=0; default ON. ✓
- **--with-owner-confirm** — двойной гейт (флаг правила + независимый сегмент-guard), свежие <7д не удаляются даже с флагом; на default-правила флаг влияет только на migrate_history. **apt** — argv-список без shell, timeout, только `--apply --with-apt`, dry-run не зовёт, отсутствие бинарника не фатально. ✓
- **CLI-smoke (dev):** dry-run default, `--json` парсится, план пуст (прод-корни отсутствуют), EXIT=0. Идемпотентность — тест «повтор — no-op». ✓

## Counterexamples checked (контрпримеры)

1. «RA=0 у spend» → delay 0, группа сразу здорова — паритет с 2.58.45 (та же `retry_after_seconds`), не регресс.
2. «Парковка промахнулась» (reset позже оценки) → re-park на следующие сутки-оценку; между ними resume не происходит (гейты) — failure-semantics 1 дизайна подтверждена кодом (`_quota_kind_of_pause`/`_resume_later`).
3. «Битый result_ref» → стрик 0, delay как после первой паузы, без исключений в горячем пути (тест).
4. «Симлинк-эскейп» и «TOCTOU-подмена» — реализация держит (мои пробы; см. Finding M-4504-1 по мёртвому юнит-тесту).
5. «Пустой пул» → WARN не логируется (не про ротацию), панель даёт «не настроен» без rotation-фея.
6. «Restart во время парковки» → джоба остаётся paused_rate_limit; пробуждение — при следующем `maybe_schedule_rebuilds` (ин-процессного таймера нет) — до-существующее свойство гейтов, честно задокументировано Builder'ом в evidence («Не сделано»); инвариант 0-HTTP не нарушается.

## Blocking findings

**Нет.** Release-blocking 0.

## Non-blocking debt

- **[M-4504-1] Medium — мёртвый юнит-тест symlink-эскейпа (тест-качество, не продукт).** `tests/test_disk_retention_server_t4506.py:362–376` `test_symlink_escape_blocked`: symlink создаётся в `root/link.bin`, но `root` (`tmp_path/"in"`) никогда не создаётся (`_mk` создаёт только `outside`) → `os.symlink` падает FileNotFoundError (WinError 3 / ENOENT) на ЛЮБОЙ ОС → тест гарантированно skip с misleading-причиной «symlinks unavailable on this host»; он пропустился бы и на Linux-проде. Утверждение evidence «на проде Linux симлинки доступны (тест выполнится)» — фактически неверно. Сама ЗАЩИТА корректна и независимо верифицирована Reviewer-пробой на том же коде (`apply_plan` блокирует, victim цел) — дефект только в тесте и в формулировке evidence. **Рекомендация (жёсткая, до T-4507):** одна строка `root.mkdir(parents=True, exist_ok=True)` перед `os.symlink` + корректная формулировка skip-причины; прогнать на хосте с правами symlink.
- **[L-4504-2] Low:** ветки `_quota_parking_seconds` horizon-оверрайд (`est=horizon`) и кап `EMBED_QUOTA_PARK_MAX_SECONDS` не покрыты юнит-тестами. Реализация верифицирована прямым probe Reviewer'а (корректна). Bounded follow-up: 2 маленьких теста.
- **[L-4504-3] Low:** при обоих флагах OFF строка лога `embed rate limit` содержит новое поле `parked=0` — лог не байт-в-байт 2.58.45 (поведенческий паритет — delay/state/note — полный и протестирован; поле предписано самим design-fix §Логи; противоречие с формулировкой D5 «log прежнего формата» — косметика дизайна, journald-грепы не ломает).
- **[L-4504-4] Low:** `tools/disk_retention.py:297–299` `_month_start` использует локальное время — граница `keep_current_month` следует TZ сервера; направление ошибки безопасное (сохраняет больше). Учесть при T-4507, если TZ ≠ UTC.
- **[L-4504-5] Low:** в recursive-сканах retention симлинк-файлы попадают в PLAN (размер читается сквозь ссылку), apply их блокирует — отчёт может показать PLAN-строки, ставшие BLOCKED. Косметика, fail-safe направление.

## Unavailable checks

- Прод-evidence T-4509 (а)–(д) — после деплоя (T-4508), @DevOps; из dev-среды непроверяемо.
- Фактический dry-run retention на прод-корнях (`/home/nik/...`, `/opt/headroom/...`) — корней на dev-машине нет; план пуст, процедура — `docs/deploy-disk-retention-t4506.md` (шаг T-4507).
- Реальное время reset квоты Gemini — принципиально неизвестно; парковка честно помечена оценкой (`est=utc_day_end`), owner-опция `EMBED_QUOTA_RESET_HORIZON_SECONDS` для эмпирической коррекции.

## Владелец-критерии (T-4509) — что остаётся на прод после деплоя

Код-гейт закрывает юнит-механику; на проде после T-4508 остаётся верифицировать:

1. **(а) 0 re-hit:** в journald между `parked=1`-строкой и её `next_allowed_at` НЕТ пар `EMBEDDING_GENERATION_BUILD_START` + `embed rate limit` (сейчас 148 строк/4ч).
2. **(б) Checkpoint цел:** rebuild остаётся `paused_rate_limit`, processed не регрессирует (от ~6395), generation не пересоздан.
3. **(в) Resume после reset:** после провайдерского reset — продолжение ТОЙ ЖЕ generation (gen=1, не 2,3…) с checkpoint, прогресс растёт.
4. **(г) Панель честна:** `GET /api/memory/embeddings` — `rotation: none` + hint, парковка помечена как оценка (`parked ... est=`).
5. **(д) 429-счётчик одинарный:** `429_last_10m` ≈ половина прежнего (дедуп D4), `attempts_total` ≈ константа до reset.
6. **R5-A-005:** выход из FTS-only — векторный контур/KNN на частичных данных; при физически долгом full-ACTIVE — честная ветка §34 (scheduler-proof + прогресс + реальный KNN path), выбор зафиксировать (no-false-acceptance).
7. **R5-C-001-жизнь:** retention развёрнут и первый автопрогон прошёл (systemd timer, `docs/deploy-disk-retention-t4506.md`); R5-B-003 checklist защиты (row-count БД, media, GraphRAG, якоря, .env) — при T-4507.
8. **Owner-решения (конфиг, не код):** `EMBEDDING_QUOTA_GROUP_LABELS` (реальное разделение групп ключей — уберёт degenerate-сигнал) и опционально `EMBED_QUOTA_RESET_HORIZON_SECONDS` (если эмпирически известен реальный reset).

## Вердикт

**Approved** — оба трека соответствуют контрактам (design-fix D1–D6; disk-audit §9 + R5-B/C), механизм против заглушки, OFF-паритет, R17, ΔDDL=0, честные терминальные состояния подтверждены независимо. M-4504-1 (одна строка теста) — зарегистрированный долг с рекомендацией закрыть до T-4507; на кодовое Approved и деплой T-4508 не влияет.

Handoff: @Orchestrator — следующий контроллер-фаз `delivery` (T-4508 deploy → T-4509 прод-приёмка). MEMORY_DELTA: нет (конфликтов с памятью не обнаружено; OpenViking не привлекался — авторитетных артефактов фичи достаточно).

---

# Round 2 — Re-gate corrective micro-fix M-4504-1 + L-4504-3/L-4504-5 (03.10.2026 @Reviewer)

Точечный re-gate дельты микро-фикса после gate T-4504. Код Reviewer'ом не правлен, коммитов нет. Независимость сохранена: все проверки ниже выполнены заново, не из evidence Builder'а.

## Binding (round 2)

- **Reviewed-Commit:** `34ba7d886d6e99a44bc803a91fa197a3030b6e36` (HEAD не сместился; коммитов по-прежнему нет).
- **Working-Tree-Hash (round 2):** `4ccd48bf163e54512cca72a817b2cd62b66c7298e38ef6ef5be01c1331ed2195` — SHA-256 от конкатенации строк «`путь SHA256\n`» по тем же 15 файлам манифеста в том же порядке (формула зафиксирована явно: каждая строка = `"{путь} {хеш}\n"`, UTF-8, пути с backslash как в манифесте round 1).
- **Spec-Hash:** не изменился — `design-fix.md` `7e53d8046194a52f23fb39051aafcbab15c9ba1fc8716f855a95baa5fd44bc67` (байт-в-байт сверён).

## Git base и дельта-скоуп (проверено независимо)

`git status`/`git diff` пересмотрены: изменённых tracked-файлов по-прежнему 9 (4 код-файла трека 1 + 5 плановых/чужой WIP), untracked-вклад фичи — те же 3 файла трека 2 + каталог plans/features. Сверка SHA-256 всех 15 файлов манифеста round 1 против текущего дерева:

- **Изменились ровно 4 файла манифеста — ровно заявленная дельта:**
  - `services\embedding_control_plane.py` → `a8a8393badab0049ddcc9770063da72a201aaca8c862509a079e633bcb22898c`
  - `tools\disk_retention.py` → `400f365d2ff6bd60c4716638cf0cd8343f307681124b60af41ba5ce3ba1f047d`
  - `tests\test_disk_retention_server_t4506.py` → `e16aa059dbaf6a9272a9f35663b78ec16f25b047d20c89504485a4fb9d654070`
  - `plans\features\post-asap4-corrective-pass\tasks.md` → `1fc83089b217ca8ed80d9e4101580a54980c22e0ca8b48cbdbd878f130e6e030`
- **Остальные 10 файлов манифеста — байт-в-байт** совпадают с round 1 (settings.py, graphrag_rebuild.py, test_embedding_control_plane_asap4.py, deploy-doc, ADR-AMEND, archive-request, design-fix, disk-audit, rca-graphrag, requirements-map) — подтверждено хешами, не заявлением.
- `evidence.md` — изменился (`e2c75640…` → `db65b04668338df7d630151c0b140705b310c4ec6eeab05dc5bb4e7266e3b6af`), самореферентно по п.4 постановки (честность описаний + corrective-секция), хеш в дельту Builder'ом сознательно не включался — корректно.
- Чужой WIP (`plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, untracked `node_modules/`, `package*.json`, `.playwright-mcp/`, `extra_images/`) — вне биндинга, как и в round 1; байт-сверка невозможна (не пинились), состав dirty-набора не расширился.

## Проверки round 2 (независимо)

1. **M-4504-1 — RESOLVED.** `test_symlink_escape_blocked` (:362–391): `root.mkdir(parents=True, exist_ok=True)` добавлен (:369) — тест теперь реально выполняется; skip-причина честная (:373–374, «нужны привилегия/Developer Mode» — единственный реальный источник skip); ассерты усилены: симлинк НЕ в плане `_paths(plan) == set()` (:380), apply плана no-op `deleted == 0` (:381–382), подделанный план с симлинком → `blocked == 1` + «BLOCKED» в логе (:385–390), жертва вне корня цела (:391). Прогон на этом хосте: **46 passed / 0 skipped** (EXIT=0, 2.71s) — подтверждено.
2. **L-4504-5 — RESOLVED.** `tools/disk_retention.py:246–252` recursive-ветка `_iter_files`: файловые симлинки исключены из кандидатов плана (`os.path.islink → continue`), паритет с non-recursive (`entry.is_file(follow_symlinks=False)` :240). Вторая линия защиты сохранена: `apply_plan:471` — `os.path.islink(path) or not os.path.isfile(path)` → BLOCKED not-regular-file (покрыт подделанным планом из п.1).
3. **L-4504-3 — RESOLVED.** `embedding_control_plane.py:1308–1325`: при `EMBED_QUOTA_KIND_PARKING_ENABLED=OFF` лог без поля `parked=` (байт-формат 2.58.45, :1316–1325); при ON — с `parked=1|0` (:1308–1315). Завязки тестов на лог-строку: grep `parked=` / `embed rate limit` / `429_last_10m` по tests — 0 ассертов на лог; тест `test_parking_off_bit_identical` (:1545–1568) ассертит поведение (delay 18–22s, note, state), не лог; сам файл тестов байт-в-байт из round 1 — ослабления нет. Противоречие D5-формулировке устранено.
4. **evidence.md честность (п.4) — подтверждена.** 2 места: (а) «Не проверено» — прямо помечено, что прежняя формулировка «на Linux-проде выполнится» была НЕВЕРНОЙ, тест skip'ился на любой ОС; (б) новая секция «Corrective round M-4504-1 + Low-мелочи» с якорями, прогонами и SHA-256-дельтой (все 4 дельта-хеша свёрены с моим расчётом — совпадают). Исторические записи прогонов (45/1) сохранены как история — корректно. Нюанс (не блокёр): строка T-4503 в tasks.md всё ещё упоминает «лог `parked=1|0`» без оговорки про OFF-ветку после L-4504-3 — сводная закрытая запись; честное уточнение живёт в corrective-секции evidence.md.
5. **Контрольные прогоны:** retention-файл **46 passed / 0 skipped**; контроль-плейн + graphrag-соседи (`test_embedding_control_plane_asap4.py` + `test_graphrag_rebuild_asap32.py` + `test_graphrag_memory.py` + `test_rerank_contract_asap32.py`) — **267 passed** (22.9s, EXIT=0). Обе цифры совпадают с заявленными Builder'ом. Полный pytest — по постановке микро-фикса не гонялся: дифф локален (3 код-файла внутри уже прогнанного в round 1 сьюта), интеграционные поверхности (resume-гейты, scheduler, panel) не тронуты; полный прогон обязателен на T-4508 по процедуре деплоя.
6. **Скоуп:** дифф ограничен заявленными 4 файлами + самореферентный evidence.md (см. выше); в коде трека 1 дельта-хunks только в ветке лога `_on_error`; `graphrag_rebuild.py` и `config/settings.py` не тронуты.

## Вердикт round 2

**Approved for delivery** — дельта ровно заявленная (4 файла + evidence), все три микро-фикса подтверждены независимо, тесты зелёные (46/0 и 267), регрессов и ослабления ассертов нет. M-4504-1, L-4504-3, L-4504-5 — закрыты; остаются осознанным bounded-debt **L-4504-2** (2 юнит-теста horizon-оверрайд/кап) и **L-4504-4** (TZ-граница `_month_start`, fail-safe) — в backlog, на delivery не влияют. Handoff: @Orchestrator — `delivery` (T-4508 deploy → T-4509 прод-приёмка). MEMORY_DELTA: нет.
