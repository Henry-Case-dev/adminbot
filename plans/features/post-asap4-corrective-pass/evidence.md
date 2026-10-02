# post-asap4-corrective-pass — evidence.md

## Corrective-диск (T-4506 @Builder, 02.10.2026)

Retention/cleanup-политика диска: сервер-sайд скрипт + тесты. **Коммитов НЕТ**
(по постановке T-4506); исполнение чистки на проде — **T-4507 @DevOps**, не
запускалось (боевых удалений 0, в т.ч. в dev-среде — скрипт гонялся только в
dry-run и на tmp-фикстурах).

### Baseline → состояние

- Baseline: HEAD `34ba7d8` (asap-4 архив; прод-состояние 2.58.45), рабочее
  дерево содержало чужой незакоммиченный WIP (`plans/backlog.md`,
  `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`,
  `plans/workflow_state.md`, untracked `node_modules/`, `package*.json`,
  `.playwright-mcp/`, `extra_images/`) — **не тронут, в мой дифф не входит**.
  В ходе сессии в дереве появился ещё один чужой дифф — AMEND T-4502 в
  `plans/archive/.../adr-1028-7-...md` (+15 строк, параллельный трек GraphRAG)
  — **не мой, не тронут**. Мой вклад ограничен 4 файлами ниже.
- Мой вклад (только новые файлы, ни один существующий файл не изменён):
  - `tools/disk_retention.py` (новый, ~640 строк, только stdlib);
  - `tests/test_disk_retention_server_t4506.py` (новый, 46 тестов);
  - `docs/deploy-disk-retention-t4506.md` (новый, deployment-инструкция);
  - этот `evidence.md` + правка чекбокса T-4506 в `tasks.md` (плановые файлы).

### Реализация — якоря

- Whitelist-классы (декларативные `RetentionRule`, CLI корни не расширяет):
  `tools/disk_retention.py:96-159`, `default_rules():125-159` — 7 классов из
  disk-audit §9: якоря home-каталогов (keep 2 новейших по ранжирующему пулу
  всех мест якорей + текущий месяц), ad-hoc `local_database.db.bak.*` (>14д),
  `.playwright-mcp` (>7д), `/tmp/pytest-of-nik` (>3д), `adminbot_test_*`
  (>3д), ротир. логи `proxy.log.N` (>14д, активный `proxy.log` паттерну не
  соответствует), `migrate_history` (>7д, **только** `--with-owner-confirm`).
- HARDCODE denylist (сильнее whitelist): `tools/disk_retention.py:53-90` —
  рабочая БД+WAL/shm; именованные копии/суточный `local_database_2*.db`;
  ВСЕ `pre_migration_*.db` (вкл. якорь pass'а `pre_migration_20261002_101544.db`);
  маркер `pre_v` (pre_v21 и будущие якоря); `.env*`; `*history*`; `*cookie*`;
  сегменты `media|uploads|graphrag|chroma|lancedb|embeddings|memory|venv|.git|
  chrome-profile`; `migrate_history` — conditional-сегмент (`:90`, `:275`).
- Dry-run по умолчанию; `--apply` — единственный путь к удалению:
  `main():589`, взаимно исключающие `--apply`/`--dry-run` (argparse group).
- Удаление по-файлу, примитив НЕ доверяет плану (повторные проверки каждого
  пути: whitelist-контейнмент `:280`, denylist `:257`, паттерн правила;
  только `unlink` файлов, каталоги не удаляются, симлинк-эскейп блокируется):
  `apply_plan():433`.
- Отчёт: df до/после + «освобождено» на каждую ФС-точку, план с размерами,
  построчный лог PLAN/DELETE/BLOCKED: `df_snapshot():405`, `render_report():513`.
- apt-кэш: только безопасная каноническая команда `apt-get clean` argv-списком
  без shell, опционально `--with-apt` при `--apply`; `rm -rf /var/lib/apt/lists/*`
  скрипт НЕ исполняет (только печатает как ручную команду DevOps):
  `APT_CLEAN_CMD:492`, `run_apt_clean():498`.
- Kill-switch env-only default-ON: `ADMINBOT_DISK_RETENTION_ENABLED=0` →
  полный no-op: `ENABLED_ENV:48`, `retention_enabled():327`.
- `--json` — машиночитаемый план/отчёт/df для evidence T-4507.
- Отличие от существующего контура: `services/disk_retention.py` (F9/ADR-1024-2)
  — runtime-ротация каталога бэкапов приложения (`keep=1`); новый скрипт его
  НЕ дублирует и каталог `backups/` приложения не трогает (нет в whitelist).

### Проверки — команды и фактические результаты

| Проверка | Команда | Результат |
|---|---|---|
| Целевой файл | `.venv\Scripts\python.exe -m pytest tests\test_disk_retention_server_t4506.py -q` | **45 passed / 1 skipped** (skip — symlink-тест, привилегия ОС; дважды идентично) |
| Полный pytest (финал) | `.venv\Scripts\python.exe -m pytest tests --timeout=120 -q` (детач, вывод в файл — L-ASAP4-9) | **10818 passed / 2 failed / 1 skipped**, 313s — 2 failed = ровно known pre-existing round1026 `forbidden_paths_out_of_diff`/`_vs_baseline` (падают от факта некоммитнутого диффа; ожидание задачи «10773+новые / 2 known» выполнено: +45 passed, +1 skipped) |
| F8 каталог | `.venv\Scripts\python.exe tools\gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`, **EXIT=0** (Δ каталога = 0) |
| CLI smoke (dev, Windows) | `python tools/disk_retention.py` / `--json` / `--apply` | EXIT=0 во всех режимах; dry-run — дефолт; apply на пустом плане — `deleted=0`; kill-switch `ADMINBOT_DISK_RETENTION_ENABLED=0` → «disabled … no-op», EXIT=0 |
| EOL/BOM | байт-чек 3 новых файлов | UTF-8 **без BOM**, **LF** (CR=0) у всех |
| py_compile | оба новых .py | EXIT=0 |

Замечание-честность по прогонам: в **промежуточном** полном прогоне был 1 флак
`test_betterstack_handler.py::TestNoRedirect::test_real_302_not_followed_by_opener`
— документированный pre-existing средовый флак с 10.19 (`S10.19-27`,
loopback-сокеты/тайминги; ARCHITECTURE.md:3260), вне моего диффа (файл чисто
аддитивный); в изоляции 5/5 зелёный; в финальном полном прогоне — зелёный.
Второй промежуточный провал — мой собственный boundary-тест (граница возраста
«ровно 3д» + дрейф часов) — исправлен запасом ±60с, финальный прогон чистый.

### Покрытие критериев (T-4506: R5-C-001, R5-C-003-механизм)

- policy-математика: возраст (строгая граница `>`, тест с запасом ±60с),
  количество (`keep_newest` с ранжирующим пулом по всем местам якорей —
  audit §7.1 «1–2 последних», denied-файлы занимают слоты), текущий месяц,
  размерный кап (`max_total_bytes`) — `TestPolicyAge/KeepNewest/CurrentMonth/
  MaxTotalBytes`.
- never-touch на protected-пути: рабочая БД+WAL/shm, суточный, pre_v21,
  pre_migration_20261002_101544, ad-hoc bak (гейтится только своим правилом),
  `.env*`, история, cookies, media/uploads/graphrag/memory/venv/chrome-profile —
  в whitelist-каталоге ни один не попадает в план и не удаляется даже из
  подделанного плана — `TestDenylist` (5 тестов) + `TestAuditReplayAnchors`
  (диспозиция аудита §9 воспроизведена на фикстурах: `pre_mca_v19` —
  кандидат, 3 якоря — protected).
- dry-run ничего не удаляет; apply удаляет ровно отобранное; повторный прогон
  — no-op — `TestDryRunAndApply`.
- Kill-switch/контейнмент: ничего вне whitelist-корней (sibling-каталог не
  сканируется), подделанный план (чужой путь/чужое правило/паттерн-мисматч)
  блокируется, симлинк-эскейп заблокирован (скан не следует файловым симлинкам
  + повторная islink-проверка в `apply_plan`; тест выполняется — corrective
  03.10 M-4504-1, см. ниже), каталоги не удаляются —
  `TestWhitelistContainment`.
- migrate_history — только `--with-owner-confirm` (гейт правила + независимый
  сегмент-guard), свежие (<7д) не удаляются даже с флагом — `TestOwnerConfirmGate`.
- apt — argv-список без shell, dry-run никогда не зовёт, `--with-apt` зовёт
  ровно раз, отсутствие бинарника не фатально — `TestAptClean`.
- CLI-контракт: dry-run дефолт, `--json` парсится, `--apply`+`--dry-run`
  взаимоисключающи, контракт `default_rules()` закреплён тестом — `TestCli`.

### Не проверено / вне задачи (честно)

- Прод-исполнение чистки НЕ выполнялось (постановка: только код+тесты;
  исполнение — T-4507 @DevOps по `docs/deploy-disk-retention-t4506.md`).
- Реальные прод-корни (`/home/nik/...`, `/opt/headroom/...`, `/tmp`) на
  dev-машине отсутствуют — CLI-прогон даёт пустой план; фактический dry-run
  на проде с реальным планом — шаг 4.1 процедуры T-4507.
- Симлинк-тест — **[исправлено 03.10, corrective M-4504-1 — см. секцию
  в конце файла]** изначальная формулировка «skip на Windows из-за привилегии;
  на Linux-проде выполнится» была НЕВЕРНОЙ: тест skip'ился на ЛЮБОЙ ОС
  (корень под симлинк не создавался → `os.symlink` падал FileNotFoundError).
  Теперь тест выполняется там, где доступно создание симлинков — на этом
  хосте выполняется (46 passed / 0 skipped); ветка apply-блокировки покрыта
  подделанным планом (defense-in-depth).
- Browser-verification не требуется (CLI-инструмент, UI не менялся).

### Как DevOps ставит и запускает (T-4507)

Полная процедура — `docs/deploy-disk-retention-t4506.md`: systemd service
(dry-run) + еженедельный таймер (Mon 06:30, Persistent) + logrotate headroom;
первая чистка: dry-run → сверка плана с audit §9 → `df -h` до → `--apply`
(tee в лог) → `df -h` после → checklist защиты. Ожидание аудита: 18G → ~16.1G
(−1.9G); с owner-confirm по migrate_history — до ~15.1G.

---

## Corrective-GraphRAG (T-4503 @Builder, 03.10.2026)

Механизм-фикс embedding quota по контракту `design-fix.md` (T-4502 @Architect,
Risk R2): kind-aware парковка spend/daily-групп, рестарт-персистентный
resume-backoff, честная диагностика пула, дедуп 429-счётчика, двойной
kill-switch. **ΔDDL = 0** (новые данные только в `task_jobs.result_ref` JSON и
значениях `embedding_quota_state` — схема не тронута). **Коммитов НЕТ, деплоя
НЕТ.** Retention-инструмент T-4506 (`tools/disk_retention.py` + тесты) не
трогался.

### Baseline → состояние

- Baseline: HEAD `34ba7d8`, worktree с чужим незакоммиченным WIP
  (`plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`,
  `plans/docs/mca-round1027-arch-frames.md`, AMEND T-4502 в
  `plans/archive/.../adr-1028-7-*.md`, untracked `node_modules/`,
  `package*.json`, `.playwright-mcp/`, `extra_images/`) и моим вкладом T-4506
  (4 файла) — **всё не тронуто, в дифф T-4503 не входит**.
- Мой вклад T-4503 (4 существующих файла + плановые):
  - `services/embedding_control_plane.py` (D1, D3, D5 — флаги/парковка/
    диагностика/`_on_error`);
  - `services/graphrag_rebuild.py` (D2, D4 — backoff/стрик/дедуп);
  - `config/settings.py` (6 env-only ClassVars, default ON / 0.0-оверрайд);
  - `tests/test_embedding_control_plane_asap4.py` (+19 тестов, 50→69).

### Якоря file:line по design-матрице (актуальные, после правок)

| Пункт | Реализация | Тест (tests/test_embedding_control_plane_asap4.py) |
|---|---|---|
| D1 parking-решение | `embedding_control_plane.py` `_quota_parking_seconds()` :449–493, `_utc_day_end()` :443–445; применение в `_on_error` :1277 (delay) | `test_parking_spend_until_utc_day_end`, `test_parking_respects_provider_ra`, `test_rpm_tpm_unchanged` |
| D1 честная note/лог/панель | note :1294–1299 (`parked kind=X est=Y` vs `429 ... ra=...`); лог `parked=1|0` :1306–1315; panel `rotation` :1583+ | `test_parked_note_and_panel_honest` |
| D1 resume-гейты (СУЩЕСТВУЮЩИЕ, не менялись) | `graphrag_rebuild.py` `_resume_later` (сверка `next_allowed_at` + перепланирование, sleep-кап 6ч), `_ensure_job` AUTO_RESUME-ветка (рестарт-гейт) | `test_resume_waits_until_next_allowed`, `test_restart_parked_not_woken` |
| D2 backoff-формула | `graphrag_rebuild.py` `_resume_backoff_delay()` :252–265 (`min(20×2^streak, 3600)×jitter≤25%`), применение: CoolingDown-default-ветка :1425–1436, LLM-ветка без RA :1495–1497 | `test_backoff_doubles_with_cap_and_jitter` |
| D2 персистентность/отмена | `_quota_streak()` :267–284, `_clear_quota_streak()` :286–316, `_quota_kind_of_pause()` :318–334, `_pause_bookkeeping(+streak/kind)` :378–411, `_apply_pause` passthrough :1332–1341; сброс — `run_job` после checkpoint :1178–1180 | `test_backoff_streak_survives_reload`, `test_success_resets_streak` |
| D2 horizon 24h без изменений | `_pause_started_at`/`_horizon_exhausted` не менялись; парковка не сбрасывает `pause_started_at` | `test_parking_consumes_horizon` |
| D3 диагностика пула | `pool_rotation_diagnosis()` :314–324, `_maybe_warn_degenerate_rotation()` :326–347 (≤1/10мин), `_rotation_panel_block()` :349–362, WARN из `embed()` :1124 и `provider_panel()` :1583–1584 | `test_degenerate_pool_hint`, `test_diag_log_rate_limited` |
| D4 дедуп 429 | удалён `record_rate_limit()` из CoolingDown-конверсии `graphrag_rebuild.py` (комментарий :1418–1420); истина — `_on_error` `embedding_control_plane.py` :1280; легаси-LLM-ветка сохраняет единственный инкремент :1489 | `test_429_counted_once_per_real_hit` |
| D5 OFF-паритет | флаги `quota_kind_parking_enabled()` :97–101, `resume_backoff_enabled()` :104–109 (рядом с `quota_group_cooldown_enabled`); env-декларации `settings.py` :826–848 | `test_parking_off_bit_identical`, `test_backoff_off_bit_identical`, `test_flag_matrix_parking_backoff` (4 сочетания) |

(Номера строк зафиксированы после финальной правки; расхождение ±3 строки
возможно при последующих правках — имена функций стабильны.)

### Семантика (проверенная)

- spend/daily БЕЗ Retry-After → `next_allowed_at = конец суток UTC + margin`
  (`EMBED_QUOTA_RESET_MARGIN_SECONDS=300`; cap `EMBED_QUOTA_PARK_MAX_SECONDS=86400`;
  оверрайд `EMBED_QUOTA_RESET_HORIZON_SECONDS>0` → фикс-горизонт, note
  `est=horizon`), note `parked kind=spend est=utc_day_end`, state=exhausted.
- spend/daily С Retry-After → `min(RA, ceiling 300s)` (AM-1), note прежнего
  точного формата; rpm/tpm/rate/unknown — бит-в-бит прежняя семантика.
- Backoff применяется ТОЛЬКО к паузам без provider-горизонта (CoolingDown с
  истёкшим `next_allowed_at`; LLM-ветка kind unknown/tpm без RA) — поверх
  parking не наслаивается; стрик инкрементируется на каждую
  exhausted-паузу (`rate_limit:quota_group`), обнуляется первым успешным
  батчем (`run_job`), живёт в `result_ref` (толерантный парсер: битый JSON → 0).
- D4: `429_last_10m` теперь считает ровно реальные 429 (`_on_error`);
  CoolingDown-конверсия и `provider`-ветки счётчик не трогают; легаси-LLM-ветка
  сохраняет единственный инкремент (исключение шло мимо executor'а).
- D5: `EMBED_QUOTA_KIND_PARKING_ENABLED`/`EMBED_RESUME_BACKOFF_ENABLED` —
  env-only, default ON, OFF = бит-в-бит 2.58.45 (парность проверена матрицей
  4 сочетаний). D3-диагностика под мастер-флагом `EMBED_CONTROL_PLANE_ENABLED`.

### Проверки — команды и фактические результаты

| Проверка | Команда | Результат |
|---|---|---|
| Новые тесты | `pytest tests\test_embedding_control_plane_asap4.py -k "parking or backoff or degenerate or diag_log or counted_once or parked_note or flag_matrix or rpm_tpm or restart_parked or resume_waits or success_resets"` | **19 passed** |
| Целевой файл (полный) | `pytest tests\test_embedding_control_plane_asap4.py -q` | **69 passed** (50 существующих + 19 новых, регресса 0) |
| Целевые соседи | `pytest tests\test_summary_wave_d_asap4.py tests\test_summary_wave_c_asap4.py tests\test_pipeline_analytics_asap4.py tests\test_cover_style_wave_b_asap4.py tests\test_disk_retention_server_t4506.py -q` | **246 passed / 1 skipped** |
| GraphRAG-соседи | `pytest tests\test_graphrag_rebuild_asap32.py tests\test_graphrag_memory.py tests\test_rerank_contract_asap32.py tests\test_summary_asap_hotfix_round1027.py -q` | **206 passed** |
| Полный pytest (финал) | `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider` | **10837 passed / 2 failed / 1 skipped**, 328s — 2 failed = ровно known pre-existing round1026 `forbidden_paths_out_of_diff`/`_vs_baseline` (не my-diff; ожидание «≥10818+новые / 2 known» выполнено: 10818+19=10837) |
| F8 каталог | `.venv\Scripts\python.exe tools\gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`, **EXIT=0** (новые env-флаги в каталог не входят, Δ=0) |
| py_compile | 3 изменённых .py | EXIT=0 |
| EOL | `git ls-files --eol` по 4 файлам | index==worktree (crlf/crlf settings, lf/lf остальные), смешения нет |
| BOM | байт-чек 4 файлов | UTF-8 **без BOM** у всех |

### Покрытие acceptance T-4503 (design-fix §Acceptance)

1. spend-429 без RA → день-конец UTC+margin, exhausted, note `parked ... est=...`;
   resume до срока → 0 HTTP (`test_parking_spend_until_utc_day_end`,
   `test_resume_waits_until_next_allowed`).
2. Рестарт не будит: `_ensure_job` при живом `next_allowed_at` → None,
   generation/attempts не тронуты (`test_restart_parked_not_woken`).
3. Backoff ×2/потолок 3600/jitter ≤25%/перезагрузка/сброс успехом
   (`test_backoff_doubles_with_cap_and_jitter`,
   `test_backoff_streak_survives_reload`, `test_success_resets_streak`).
4. rpm/tpm/rate бит-в-бит (`test_rpm_tpm_unchanged`).
5. Degenerate-пул → панель `rotation: none` + hint; WARN ≤1/10мин
   (`test_degenerate_pool_hint`, `test_diag_log_rate_limited`).
6. Ровно 1 инкремент 429 на реальный хит (`test_429_counted_once_per_real_hit`).
7. OFF-паритет обоих флагов + матрица 4 сочетаний
   (`test_parking_off_bit_identical`, `test_backoff_off_bit_identical`,
   `test_flag_matrix_parking_backoff`).
8. R17: панель/ноты/логи — только alias/счётчики/group-id
   (`test_parked_note_and_panel_honest` — ключ «secret-key-material» в панели
   отсутствует; WARN содержит только counts).
- Horizon 24h: парковка расходует, не сбрасывает `pause_started_at`
  (`test_parking_consumes_horizon`).

### Не сделано / вне скоупа (честно)

- Resume-гейты §68 (`_ensure_job`/`_resume_later`) намеренно НЕ менялись —
  по контракту design-fix D1 используются существующие. Граница следствия:
  рестарт ПРОЦЕССА во время многочасовой парковки оставляет джобу в
  `paused_rate_limit`; пробуждение после `next_allowed_at` в этом случае
  происходит при следующем триггере `maybe_schedule_rebuilds` (старт
  vec-инициализации/embed-recovery/пост-release), ин-процессного таймера после
  рестарта нет — это до-существующее свойство гейтов (для 20s-пауз выглядело
  незаметно). Инвариант «0 HTTP до срока (вкл. рестарты)» соблюдён; ин-процесс
  (без рестарта) resume строго в срок через самоперепланирование `_resume_later`.
- Прод-evidence T-4509 (а)–(д) — @DevOps, после деплоя (T-4508); здесь только
  юнит/интеграционная верификация.
- R17-скан полного диффа — @Reviewer (локальные проверки в тестах сделаны).
- ADR AMEND (design-fix §ADR) — docs-коммит, вне кодового вклада Builder.
- Browser-verification не требуется (backend-only, UI не менялся).

### Rollback-заметка (для T-4508)

Soft: `EMBED_QUOTA_KIND_PARKING_ENABLED=0` + `EMBED_RESUME_BACKOFF_ENABLED=0`
+ рестарт = поведение 2.58.45 (паритет закреплён тестами). Cold: revert;
новые ключи `result_ref` (`quota_exhaust_streak`, `quota_kind_last`) старым
кодом игнорируются толерантным парсером — downgrade безопасен.

---

## Corrective round M-4504-1 + Low-мелочи (03.10.2026 @Builder)

Микро-фикс по `review.md` (gate T-4504 Approved, release-blocking 0):
finding **M-4504-1** (Medium, мёртвый symlink-тест) + необременительные
Low-мелочи **L-4504-3** и **L-4504-5** (обе тривиальны, сделаны).
**Коммитов НЕТ.** F8 не гонялся (изменения каталога не затрагивают).

### Изменения (дифф-якоря)

1. **M-4504-1** — `tests/test_disk_retention_server_t4506.py:362-393`
   `TestWhitelistContainment::test_symlink_escape_blocked`:
   - добавлен `root.mkdir(parents=True, exist_ok=True)` перед `os.symlink`
     (раньше корень не создавался → `os.symlink` падал FileNotFoundError
     → тест skip'ался на ЛЮБОЙ ОС с misleading-причиной «symlinks
     unavailable»; прежнее evidence-утверждение «на Linux-проде выполнится»
     было неверно — исправлено выше по файлу);
   - skip-причина переформулирована честно: «symlink creation unavailable
     on this host (Windows: нужны привилегия/Developer Mode)» — теперь это
     единственный реальный источник skip;
   - ассерты усилены (следствие L-4504-5 — иначе тест стал бы вакуумным):
     симлинк НЕ в плане (`_paths(plan) == set()`), apply плана — no-op,
     подделанный план с симлинком → `blocked=1` + «BLOCKED» в логе,
     жертва вне корня цела (defense-in-depth apply не ослаблен).
2. **L-4504-5** — `tools/disk_retention.py:246-251` `_iter_files`,
   recursive-ветка: файловые симлинки больше не кандидаты плана
   (`os.path.islink` → skip; паритет с non-recursive веткой
   `follow_symlinks=False`). PLAN-строки, которые apply потом блокировал
   как шум, больше не печатаются. Повторная islink-проверка в `apply_plan`
   (`:471`) сохранена как вторая линия защиты (подделанные планы).
3. **L-4504-3** — `services/embedding_control_plane.py:1308-1325`
   `_on_error` (лог): при `EMBED_QUOTA_KIND_PARKING_ENABLED=OFF` поле
   `parked=` из лога убрано (байт-формат 2.58.45); при ON поле осталось
   (`parked=1|0`; для RA-кейсов честный `parked=0` — осмысленный сигнал
   режима парковки). Завязок на поле в тестах нет (grep `parked=` по
   tests — только note-ассерты, лог-строку не проверяет никто).

Не тронуто (debt, из review): **L-4504-2** (2 юнит-теста horizon-оверрайд/
кап — реализация уже верифицирована прямым probe Reviewer'а), **L-4504-4**
(TZ-граница `_month_start` — направление ошибки безопасное).

### Прогоны (после фикса, 03.10.2026)

| Проверка | Команда | Результат |
|---|---|---|
| Retention-файл | `.venv\Scripts\python.exe -m pytest tests\test_disk_retention_server_t4506.py -q -rs` | **46 passed / 0 skipped** — симлинк-тест РЕАЛЬНО выполняется на этом хосте (создание симлинков доступно, probe `SYMLINK_OK`); прежнее ожидание «45 passed / 1 skipped» снято |
| Контроль-плейн + GraphRAG-соседи | `pytest tests\test_embedding_control_plane_asap4.py tests\test_graphrag_rebuild_asap32.py tests\test_graphrag_memory.py tests\test_rerank_contract_asap32.py -q` | **267 passed** |
| py_compile | 3 изменённых .py | EXIT=0 |
| CLI smoke | `python tools/disk_retention.py --json` (dry-run) | EXIT=0 |
| EOL/BOM тест-файла | байт-чек | LF, без BOM |

Полный pytest по постановке микро-фикса НЕ гонялся (затронуты ровно 3
код-файла из скоупа уже прогнанного сьюта; изменения локальны).

### Дельта vs review-манифест (для Reviewer)

Пересчитан SHA-256 всех 15 файлов манифеста review (WTH `4d2c7b04…`).
Отличаются от review-состояния ровно 4 файла, все — мой вклад этого
corrective round'а:

```
services\embedding_control_plane.py      a8a8393badab0049ddcc9770063da72a201aaca8c862509a079e633bcb22898c
tools\disk_retention.py                  400f365d2ff6bd60c4716638cf0cd8343f307681124b60af41ba5ce3ba1f047d
tests\test_disk_retention_server_t4506.py e16aa059dbaf6a9272a9f35663b78ec16f25b047d20c89504485a4fb9d654070
plans\features\post-asap4-corrective-pass\tasks.md 1fc83089b217ca8ed80d9e4101580a54980c22e0ca8b48cbdbd878f130e6e030
```

Остальные 10 файлов манифеста — SHA-256 байт-в-байт совпадают с review.
`evidence.md` (этот файл) — самореферентен, хеш не пинится. Чужой WIP вне
манифеста (`plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`,
`plans/docs/mca-round1027-arch-frames.md`, untracked `node_modules/`,
`package*.json`, `.playwright-mcp/`, `extra_images/`) — не тронут.
Базовый HEAD по-прежнему `34ba7d8`.
