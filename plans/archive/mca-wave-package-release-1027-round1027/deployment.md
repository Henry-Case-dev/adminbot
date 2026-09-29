# deployment.md — `mca-wave-package-release-1027` (прод-деплой 2.58.36, DDL v12→v19)

- **Feature-ID:** `mca-wave-package-release-1027`
- **Дата деплоя:** 29.09.2026, окно 05:20–11:37 UTC (локально Владивосток ~15:20–21:37, +10/+12)
- **Статус: VERIFIED**
- **Авторизация:** @Reviewer `Approved for release` (review.md, round 2, §11.5: H-1 закрыт, 0 блокеров, binding `f103007f…`/`17223b4a…`) + санкция владельца на инкрементальные деплои закрытых пакетов (активация 29.09.2026). Рестарты/DDL/пост-деплой исполнены @DevOps (T-4046/4047/4048), rollback-факты T-4049.

## 1. Binding: re-measure на момент коммита (рецепт Эпика 3)

Гейтовский binding round-2 (29.09.2026 16:42 локального) пере-снят на момент feat-коммита. Метод воспроизведён и **верифицирован байт-в-байт**: STATUS/UNTRACKED/UNTRACKED_REL совпали с гейтовскими (гейтовские компоненты reproduced 3/3), расходится только DIFF — ровно задокументированный гейтом служебный plans-дрейф (`plans/workflow_state.md` чекпоинты Orchestrator'а; review.md §11.3 признал это свойство, не дрейфом релиза).

| Компонент | Гейт round-2 (16:42) | Замер на момент коммита | Вывод |
|---|---|---|---|
| `DIFF_SHA256` | `0765100e…` | **`f95361be95de457335ae5526d86e6bf8113bcab1f9d40d54f08134296b550399`** | служебный дрейф workflow_state.md — ожидаемо |
| `STATUS_SHA256` (159 записей) | `b03182b6…` | **`b03182b69721476aaeba8b11c67d774521146694fa60a568ae508d274446121d`** | **== гейт, байт-в-байт** |
| `UNTRACKED_SHA256` (351, без review.md по рецепту) | `58b94a8f…` | **`58b94a8f09df5514d7c47e05b57259ce9701d89624d90bf4f0f436cd1510a610`** | **== гейт, байт-в-байт** |
| `UNTRACKED_REL` (97) | `f8a67e2f…` | **`f8a67e2fdeb25fb95a6838b1bf6512cd153e64b880cbda53e4364f0ab3fc7bd2`** | **== гейт, байт-в-байт** |
| **`WTH_RELEASE_SCOPE` (рецепт, отчёт исключён)** | `17223b4a…` | **`2175817bc0dbfaa7189a45fe2c70fbb846cc27cb45fb14a519a362b759f12c20`** | см. примечание ниже |
| Полные (вкл. review.md round-2 в манифест, 352/98) | — | UNTRACKED `d7706493…`, REL `6f4ca55e…`, **WTH `61cd1174…` / WTH_RELEASE_SCOPE `19d6eab5…`** | полный снимок момента коммита |

Примечание: «WTH_RELEASE_SCOPE»-значение `2175817b…` = комбинация `sha256("DIFF:f95361be…\nSTATUS:b03182b6…\nUNTRACKED:f8a67e2f…\n")` — актуальный DIFF + гейтовские STATUS/UNTRACKED_REL; это точный «рецепт-снимок» момента коммита (отчёт гейта исключён). Значения `61cd1174…`/`19d6eab5…` — снимок без исключения review.md round-2 (файл существовал на момент замера). Релизный состав (продукт/тесты/untracked-артефакты) между гейтом и коммитом не менялся — подтверждено байт-в-байт по STATUS+UNTRACKED.

- **Reviewed-Commit:** `8bd1389146bd69fe28795b466a43d3eb7dd04c5a` (не менялся; HEAD был == origin/master == `8bd1389` на момент начала T-4046).
- **Spec-Hash:** `9E42620D779AA8613BC5A634F1525CC4E5B997777BC06E1E0EB83E75537D0F7A` (не менялся на момент коммита; post-approval правка эратума §11.4 — санкционированная, в docs-коммите `6470492`, см. §2).

## 2. Коммиты (push `8bd1389..6470492`, ff, без force)

| Коммит | Состав | Факт |
|---|---|---|
| **feat `6285dd7`** (`6285dd7d45e4ab54a24c2b80a81a96eaa16082b2`) | **129 файлов**: 20 untracked wave-артефактов (8 сервисов + 8 py-тестов + JS-тест + UI-harness ×3) + 31 product-M + 68 тест-M + `APP_VERSION` 2.58.35→2.58.36 + README + **8 bump-пере-пинов** (класс version-pin, REQ-REL-07 атомарность «код+тесты+эталон»): 23-й py-файл ×3 ранее чистых (test_decision_making/test_round1025_f8_registry/test_telegram_reactions — по 1 строке `APP_VERSION == "2.58.36"`), 4 JS-пина hotfix7–10 (regex `2\.58\.35`→`2\.58\.36`), F8-эталон `plans/docs/param-registry-round1025.meta.md` (APP_VERSION-штамп; HEAD-штамп остался исторический `87728dc` — полная пере-изданность мета — follow-up) | 39 196 insertions / 22 830 deletions |
| **docs `6470492`** | 83 файла: 7 plans-M (ARCHITECTURE/MEMORY/backlog/metrics/global_map/workflow_state/evidence-hotfix) + `full_audit_results.md` + фичевая папка (spec/ADR-1027-11/tasks/gate-report round-2) + drift-отчёт T-4042 + 10 архивов `plans/archive/mca-*-round1027` (55 файлов) + `plans/docs/mca-round1027-{plan,arch-frames}.md` + hygiene 13 (asap2-PNG ×7, asap21-PNG ×5, `_asap3_wth.py`) + **eratum-фиксы** (санкция round-2 §11.4): spec §3 п.3 счёта **17/33** (была перестановка), spec §3 п.8 **JS 50/50** (не 48), T-4042 §6 стр.2 17/33 + L-2-пометка (safe_fetch позиционные аргументы), L-1-диспозиция (docstring-косметика кодом не правится) | 9 530 insertions |
| **deploy-doc** | этот файл (финальный docs-коммит) | см. git log |

- **(b)-файлы не в коммитах** (уже на проде через import-closure `2deb287`, контроль blob==рабочему дереву повторён): `services/mca_gates.py`, `services/mca_retrieval_context.py`, `services/mca_events.py`, `services/token_counter.py`.
- **(c)-файлы не в коммитах**: `.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json` (никогда); `plans/features/mca-04b-dossier-rebuild/` (3 файла) — остался WIP-untracked, уезжает своим циклом (Wave 2).
- **Отклонение от буквы spec §4.3 «`git diff --check` = 0»:** в staged-диффе 26 281 «trailing whitespace» + 1 «new blank line at EOF» (`services/task_supervisor.py:719`). Классификация: унаследованный стиль волнового контента, одобренного гейтом по контенту; **0 leftover conflict markers**; чистка = правка контента после гейта = недопустимый дрейф binding. Задокументировано как сознательное отклонение.

## 3. Верификация композиции на чистом worktree (урок ASAP-3) — ДО push

`git worktree add <temp> 6285dd7` + `.env` из основного дерева (секрет не покидал машину).

| # | Проверка | Результат |
|---|---|---|
| 1 | **Import-closure 18/18**: 8 wave-сервисов (`task_supervisor`, `message_identity`, `provenance`, `safe_fetch`, `mca_process_registry`, `mca_trace`, `mca_watchdog`, `mca_incidents`) + 4 (b)-модуля + `database` + `direct_chat_service` + `config.settings` (APP_VERSION=2.58.36) + `web.app` + `bot` (с `.env`) | **ALL OK** |
| 2 | Focused-срезы 8/8 | **310 passed** == 17+25+33+25+63+34+43+70 (архивные счёта; эратум 17/33 соблюдён) |
| 3 | Полный pytest на чистом checkout | **9976 passed / 3 failed**, все 3 поимённо: `test_history_cli::test_scope_is_required` (gitignored-фикстура `migrate_history/` отсутствует в worktree), `test_round1025_f8_registry::TestFrozenInvariants::test_ddl_source_unchanged` (CRLF/LF-артефакт, см. §4), `test_tool_coordinator::TestBounds::test_forbidden_paths_out_of_diff` (известный класс, общий с якорем) |
| 4 | **Якорный контроль** (8bd1389 в идентичном LF-worktree, spec §3 п.8 «в той же среде») | **9595/69 — байт-в-байт повторение гейтовского anchor-прогона**; все 3 падения композиции входят в 69 якорных → **дельта новых падений = 0** (волна закрыла 66 якорных пере-пинами) |
| 5 | JS-сьют 50 файлов пофайлово `node` | **50/50 exit 0** |
| 6 | F8 `gen_param_registry_round1025.py --check` | **CHECK OK: реестр 483 == REGISTRY** |
| 7 | Состав против карты | staged == карта T-4042 ± 8 санкционированных version-пинов; (b)/(c) — 0 вхождений |

## 4. CRLF-факт (честная фиксация)

Локальный диск рабочей копии Windows — CRLF (артефакт истории копии; `core.autocrlf=false`, `.gitattributes` нет), git-blob'ы — LF. `git status` чист, blob `6285dd7`-файлов идентичны гейтовски проверенным. Прод при `git pull` получает **LF** (Linux) — поведенчески нейтрально для Python; все предыдущие релизы доставлялись так же. Следствие: frozen-hash пины гейта (sha256 CRLF-диска, напр. `pg_db.py` `b5070374…`) невоспроизводимы на свежем LF-checkout (`test_ddl_source_unchanged` — средовое падение, пройдено на диске основного дерева контролем). На проде тесты не гоняются — деплой не затронуто.

## 5. Прод-деплой: сервер 198.46.175.136, /var/www/admin_bot, systemd `admin_bot` (User=root)

- (a) **`git pull --ff-only`**: прод HEAD `e6af6b2` → **`6470492`** (feat `6285dd7` + docs). Δ env=0 (`.env` без MCA_-override — кодовые дефолты), systemd Environment пуст.
- (b) **DDL v12→v19** — форма spec §5.4, заполнено фактически:

| # | Шаг | Факт | Вердикт |
|---|---|---|---|
| 1 | Preflight | БД `local_database.db` 852 398 080 Б; диск 7.9 ГБ свободно; анкер `6470492` | ✅ |
| 2 | WAL-checkpoint | `wal_checkpoint(TRUNCATE)` → `(0,0,0)` | ✅ |
| 3 | Бэкап `VACUUM INTO` | **`/home/nik/backups/pre_mca_v19_20260929_052904.db`** (850 698 240 Б; путь скорректирован: штатный `var/backups/` — root-only, бэкап в домашнем каталоге nik, тот же диск; R18 «не удалять» соблюдено). Дополнительно runner сделал собственный гейт-бэкап `/var/www/admin_bot/pre_migration_20260929_053213.db` (root; двойная защита) | ✅ |
| 4 | Read-back | `integrity_check=ok`, `user_version=12` копии == прода | ✅ |
| 5 | Применение (рестарт №1, 05:31:51 UTC) | runner: «pre-migration copy created + read-back ok, target_version=12» (05:33:44); **v13 05:33:45 → v14 → v15 → v16 (identity-backfill 1 983 301 сообщение пачками по 1000, ~5 ч 05 мин — штатный bounded/resumable путь ADR-1027-4 D3/D7, приём сообщений в это время не поднят) applied 10:39:09 → v17 10:39:21 → v18 → v19 10:39:21**; «Database initialized» 10:39:21; **Start polling 10:39:32** | ✅ |
| 6 | Post | `user_version = 19`; книга `schema_migrations` — **ровно 8 строк** [12 legacy_baseline, 13 schema_migrations_book, 14 task_jobs, 15 mca_events, 16 message_identity, 17 provenance_contract, 18 embedding_identity, 19 observability_core], **0 дублей**; `integrity_check=ok`; таблиц 65→**71** (аддитивно) | ✅ |
| 7 | Идемпотентный повтор (рестарт №2, 11:26:02) | **0 применений, 0 дублей** (строк «migration v*» в журнале нет; backup-гейт не срабатывал — новых шагов нет); `user_version=19`, книга [12–19] неизменна; polling 11:27:24 (старт ~3 с); health 200 | ✅ |
| 8 | Rollback-compat | на проде не повторялся (избыточный риск на живой БД); факт drill'а гейта §3: v12-код на v19 — старт/данные/схема целы, `user_version` понижается 19→12 legacy-шагами, реконвергенция релизным кодом идемпотентна (сценарии b/c/d/e PASS) | ✅ (drill) |
| 9 | Smoke | см. §6 | ✅ |

- Политика частичного применения (§5.2) не потребовалась: сбоев шагов не было; `user_version` монотонно 12→19.
- Stop-политика: медленный stop ~60 с (SIGTERM timeout → SIGKILL) — pre-existing поведение юнита, ожидаемо.

## 6. Пост-деплой: health, kill-switch'и, per-feature smoke (короткие исполнения)

- **Health:** `GET /api/health` → HTTP 200 `{"status":"ok"}` (после обоих стартов).
- **Версия:** disk+runtime `APP_VERSION = 2.58.36`.
- **NRestarts=0** (после каждого рестарта); **`database is locked` = 0** в окне с 10:39.
- **Traceback-окно:** с 10:39 — ровно 1 (Telegram Flood control `SendVideo` в `handlers/alan_greeting.py` при обработке backlog'а — известный класс rate-limit, не волна); после рестарта №2 — **0**. ERROR-класс — только известные (Flood control, groq transcribe timeout retry).
- **Kill-switch инвентарь:** `KILL_SWITCHES` = **26 product, все 26 resolved ON**, env-override `MCA_*` в прод-окружении **NONE**; **блок mca-17a ровно 8/8 exact-match** (MCA_OBSERVABILITY_ENABLED master, MCA_PROCESS_REGISTRY_ENABLED, MCA_TRACE_SPAN_ENABLED, MCA_JOB_LIFECYCLE_ENABLED, MCA_HEARTBEAT_WATCHDOG_ENABLED, MCA_INCIDENTS_ENABLED, MCA_INCIDENT_PUSH_ENABLED, MCA_TELEMETRY_SPOOL_ENABLED); `MCA_FAULT_INJECTION_ENABLED` (dev-only, вне реестра) = **False** ✔ (26 product + 1 dev-only = 27, == T-4042 §4.2).

| Фича | Критерий | Факт | Вердикт |
|---|---|---|---|
| mca-14 | реестр применён + книга | v13…v19 applied, книга 8 строк/0 дублей, повтор 0/0 (§5) | ✅ |
| mca-13 | события пишутся + retention | `mca_events`: 67+ событий, freshness живая (11:34+); топ: WATCHDOG_SWEEP (57), message_revision (9), message_identity_migration (1); retention/prune — кодовые дефолты, spool ON; события R17-safe (числа/коды) | ✅ |
| mca-01 | supervisor `task_jobs` живой | таблица есть, `fencing_token`-колонка на месте; очередь пуста (фоновой работы с момент старта не требовалось); heartbeat/watchdog-контур уже читает (WATCHDOG_SWEEP каждую минуту, outcome=success) | ✅ |
| mca-03 | identity `message_revisions` | `message_source_records`=613, `message_revisions`=617; live-сообщения с `sent_at`=613 (новые пишутся с identity-полями); post-backfill: import=1 887 027 / live=96 887; наблюдение: 5 `message_revision` outcome=skipped reason_code=source_missing при обработке backlog-edit'ов — документированный fail-soft mca-03 (событие, не падение) | ✅ |
| mca-02 | safe_fetch не ломает загрузки | `[youtube engine] config \| proxy=set \| cookies=set \| resproxy=set` — **cookies сохранены** (приёмка §6.2); VideoDownloader enabled (cobalt localhost:9000 — доверенное локальное соединение); 0 egress-ошибок в окне; SAFE_FETCH_TRUSTED_HOSTS/PORTS — кодовые дефолты | ✅ |
| mca-04a | provenance таблицы | `mca_source_refs`=14 805, `mca_evidence_links`=692; v17-backfill честно промаркирован basis: `backfill: source_ids`=468, `backfill: direct tg_message_id`=224 | ✅ |
| mca-07 | retrieval embedding-поколения | `mca_embedding_index_generations`=2; **WARNING fail-open `episode-lore`/`vector` с 10:39 = 0** (предсказанное исчезновение подтверждено) | ✅ |
| mca-17a | observability API/телеметрия | телеметрия пишется (mca_event=WATCHDOG_SWEEP ежеминутно); `mca_pipeline_runs`/`mca_incidents` созданы (0 записей — крон-саммари в окне не пробегал, инцидентов нет); `GET /api/oversight/processes|incidents` → HTTP 401 (tma-auth gate активен — read-only API защищён) | ✅ |

## 7. Rollback-факты (T-4049)

- **Soft (per-feature, предпочтительный):** env OFF любого из 26 флагов + рестарт → документированный legacy-путь (матрица гейта round-1 п.4; все OFF-паритеты верифицированы в фичевых ревью). Волна: mca-14 `MCA_SCHEMA_MIGRATIONS_ENABLED=false` (legacy hardcoded-путь DDL, boot на v12-схеме работоспособен — boot-drill гейта PASS), mca-13 `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED`, mca-01 `MCA_TX_OWNERSHIP_ENABLED`/`MCA_TASK_SUPERVISOR_ENABLED`, mca-03 `MCA_MESSAGE_IDENTITY_ENABLED`/`MCA_MESSAGE_REVISION_TRACKING_ENABLED`, mca-02 `MCA_SAFE_FETCH_ENABLED`/`MCA_EGRESS_GUARD_ENABLED`, mca-04a `MCA_PROVENANCE_ENABLED`/`MCA_FACT_ATTRIBUTION_ENABLED`/`MCA_EVIDENCE_RECONSTRUCTION_ENABLED`, mca-07 (6 флагов), mca-17a (8 флагов; master `MCA_OBSERVABILITY_ENABLED` выключает паритет целиком).
- **Cold:** revert/checkout прод-кода к **`2deb287`** (2.58.35) / docs-вершины `8bd1389`. **Задокументированное ограничение (drill гейта §3 c/d):** legacy-код на v19-БД при своём init **понижает `user_version` 19→12** (безусловные legacy-шаги v10–v12) — данные/схема/книга целы (аддитивность v13…v19), деструктива нет; следующий запуск релизного кода **реконвергируется идемпотентно** (backup-гейт → v13…v19 self-guard → ровно 8 строк книги, user_version→19). Restore из бэкапа — только аварийный контур (`/home/nik/backups/pre_mca_v19_20260929_052904.db`, integrity ok, R18 не удалять).
- **Тег-анкеры:** `8bd1389` (docs-вершина) / `2deb287` (код 2.58.35) — целы, теги не тронуты (R18).

## 8. Чужие файлы / R17/R18

- `plans/current_task.md` — не менялся (не в диффе коммитов, STATUS==гейту).
- Чужой WIP не закоммичен: `mca-04b` (3 файла), harness-инфра — вне коммитов (§2); в дереве после docs-коммита остаются только (c)-записи + этот deployment.md (закрыт deploy-doc-коммитом).
- Секреты: в коммитах/логах/отчётах нет (R17-скан гейта + прод-пробы печатают только счётчики/статусы); `.env` в worktree-пробах использовался локально, не выписан; значение proxy/токенов не выводилось.
- Бэкапы/теги не удалялись (R18).

## 9. Итог

- **Deployed:** прод HEAD **`6470492`** (feat **`6285dd7`**, docs), **APP_VERSION 2.58.36**, DDL **v12→v19** (книга ровно v13…v19, идемпотентный повтор 0/0), polling с 10:39:32 UTC, health 200, 26+1 kill-switch'ей в ожидаемом состоянии, per-feature smoke 8/8, error-spike нет.
- **Статус: VERIFIED.**
