# mca-release — evidence Lane B (T-5225 → T-5226)

**Дата:** 07.10.2026 @Builder (lane B3-mcarelease-laneB, read-only верификация; writer = только этот файл).
**Замороженное состояние:** HEAD == origin/master == `3e3bdb78c3891552b144b4c4b5a1c70ee7b99890` (docs-only поверх `e16be7e`/2.58.66), `origin/master..HEAD` = 0 коммитов — ff-дисциплина цела, чужие ветки не затёрты. Кандидат = uncommitted worktree-дельта (контент mca-21 + артефакт-фиксы), в полёте деплоев нет. ENV: Windows/PowerShell, `.venv`, `PYTHONIOENCODING=utf-8`.

## T-5225 — финальные проверки на замороженном HEAD

### Заморозка-доказательство (SHA256 изменённых/новых файлов кандидата)

Изменённые (19, `git status` M):

| Файл | SHA256 |
|---|---|
| `info_text.md` | `17f1059937b5fa8355a495479b80d805d297f4bed1176c603205c678072d66c7` |
| `plans/MEMORY.md` | `e24db30a9831f6dfe2e50f2cc37affa7eef8f598bb863355e2b6ed7d7a291a12` |
| `plans/archive/mca-17c-analytics-matrix-round1047/evidence.md` | `7f52280813da88837bfb8af8acb064fb6a57c279cd31ecebe0e7cf556268552b` |
| `plans/backlog.md` | `d40f0d2233569f2c12ecb130e0a7920f22e64c3a0ef92f0e2dc5bf6d3cd65a93` |
| `plans/docs/intelligence_user_guide.md` | `f0fc8f8806ae8e733a405f4581540b4df9087863d164c28d00e45405d51d985e` |
| `plans/docs/mca-round1027-arch-frames.md` | `f41fec5c3f1ad58c1213c10bb8c84a0dabd65572a17d80c9e90989da13e9f4dc` |
| `plans/reports/mca20_wth_manifest_review.txt` | `8a13c9588a1612afa01c6ddea42cbb69c9f1881749822c8e53812a99c610fb73` |
| `plans/workflow_state.md` | `692b5a541e90864da14d7f222f456e3eafdf5518cf99c12c908721b4e2da64e1` |
| `services/info_service.py` | `61105570f3b5b61f994dd27bddf513d9f356ff9d84f34bca07777cfb322f6ac8` |
| `tests/test_help_guide_round1014.py` | `6a9224925da92abb5560bc51da6d78000a5ee26ede1561b200fc4edc469d8148` |
| `tests/test_help_ui_round1020.py` | `1e79a6b4a133e658da3513755499d7a7abb10c24d38db4a20dc2cc5798d4039b` |
| `tests/test_help_ui_round1022.py` | `cb735a88d00cdb61d992a8e2bf2a5805019883521b4bcc25b86b9467b19d2dc4` |
| `tests/test_help_ui_round1023.py` | `00bf5057c3b56ee65025879be7adcc19420cb31fc050ef9aca79b9d5f76807fb` |
| `tests/test_info_handlers.py` | `64f239f22615428d21f108bc7cc29502cf0b9ec45bbb2b2079bbe6be3961f838` |
| `tests/test_info_service.py` | `b64aff7d8538fcea3c84c36c45c711eb85388f9b77cb8130dc7e76d7cd26876c` |
| `tests/test_mca17c_invariants_round1047.py` | `6dcc65885f86373575656861a2ba59a48a4af2a022abfb63ef350116b530ab85` |
| `tests/test_tool_coordinator_round1026.py` | `31ddbe8dae400191d88646398cd4e43f12814b1270075b09d4a4be099df72ca0` |
| `tests/test_unified_image_request_round1026.py` | `06596a3cfaec859726c41102e3adf59a432a7ea2721677140a09aa8feb355140` |
| `tests/test_webapp_api.py` | `6a15ce40d4bdc9c18e1eab40d2d6c3be2d52be5d5ac043fba5f7e1a1d08d21db` |

Новые (кандидат mca-21):

| Файл | SHA256 |
|---|---|
| `tests/test_mca21_guides_content.py` | `c77e6a0d2d139f72ad9425a096803102dcaf2601679edf263eab6bdd5c207156` |
| `plans/features/mca-21-guides/adr-1028-22-guides.md` | `033fb9ab6068c3b0e57af3188e9f4e08a09fd40923167285872f5ac0ba035e06` |
| `plans/features/mca-21-guides/evidence.md` | `a5438cc3dcf1b8f95b026ef2c9a63045d64608b5d074a27b312820b3011a3bd0` |
| `plans/features/mca-21-guides/matrix.md` | `cf33d3c31b615508b62e0f9260ddd095c45f14da3b7efd4674fcf6da39e035d0` |
| `plans/features/mca-21-guides/report.md` | `09e65e9c36d219d00c1a512c4d1313c7ce8b3ad80ac88338a897beda5e470ddb` |
| `plans/features/mca-21-guides/requirements-map.md` | `1dc7964e15be2795b55ba5299dcdc3a2d036c284d250bb98c75f29da4e065f1d` |
| `plans/features/mca-21-guides/spec.md` | `5e25e950c1a03f04d4da621d485b0f904259ae8b35ab31a2ca52813718d690be` |
| `plans/features/mca-21-guides/tasks.md` | `64646ab7fb96280fe5a6dc00b1efa4bee299fe7fb555e3801c287888d021be47` |

Прочее untracked (`node_modules/`, `.playwright-mcp/`, `tools/_d2_*/_t51*/…`, png-артефакты) — мусор сверки T-5191, НЕ кандидат, не хешировался.

### Полный pytest (foreground)

**12359 passed / 5 failed / 12364 collected, 449.45s (0:07:29), EXIT=1.**

- **4 стабильных pre-existing identity — точная сверка базлайна (backlog §121):**
  1. `tests/test_tool_loop.py::TestChatWithTools::test_query_chat_memory_count_reaches_model` — подпись прежняя: формат строки поиска (`'Найдено 7 упоминаний «бензин»…'` не входит в широкий префикс-ответ);
  2. `tests/test_webapp_nav_disclosure_ui.py::TestModulesRework106::test_memory_rag_and_sleep_tabs` — `…and 5 == 3` (memory-вкладки);
  3. `tests/test_webapp_status_control.py::TestStatusEndpoint::test_status_public_for_all_roles` — расхождение множеств ключей статуса (`'random'` отсутствует);
  4. `tests/test_mca09_intents_block_e_round1040.py::test_registry_process_intent_initiative` — `assert 'implemented' == 'disabled'`.
- **5-й failure: `tests/test_dream_worker.py::TestDistillation::test_cluster_distilled_to_belief`** — НЕ входит в четвёрку. Изолированный перепрогон: **`1 passed in 2.86s`** → флейк pollution-семьи (#121): в логе полного прогона каскад `services.database: connection unrecoverable | op=random_state` / `rollback failed | op=random_draw_journal` перед assert'ом (`[('run','ok'…'review','kept')] != [('run','ok'…'distilled','ok')]`) — деградация соединения от соседнего теста, изолированно воспроизводится зелёным. **Дисклеймер для Reviewer:** это имя НЕ входило в заранее названный список флейков (nostalgia/history_cli/mca09-cancelled/betterstack) — классифицирую как флейк нового имени (pollution-семья, изолированный PASS), не как новое падение; выносится на review-линзу.
- Известные флейки брифа (nostalgia, history_cli, mca09-cancelled, betterstack) в этом прогоне **не срывались** — перепрогоны не требовались.
- Рост к базлайну: collected 12338→12364 (+26 — контент/миграционные тесты mca-21), passed 12338→12359, failed 4→5 (пятый — см. выше).

### JS / F8 / collect / census / frontier

| Замер | Ожидание | Факт |
|---|---|---|
| js (`node tests/js/*.js`) | 62/62 | **PASS=62 FAIL=0** |
| F8 `tools/gen_param_registry_round1025.py --check` | OK 523 | **«CHECK OK: реестр 523 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны», EXIT=0** |
| collect-only | 0 ошибок | **12364 collected, 0 errors, EXIT=0** |
| reason_code (живой импорт `len(mca_events.REASON_CODES)`) | 280 | **280** |
| KS (`len(mca_gates.KILL_SWITCHES)`) | 85 | **85** |
| тулы (`len(TOOL_CALLING_TOOLS)`) | 14 | **14** |
| каталог (`len(pc.REGISTRY)`) | 523 | **523** |
| реестр процессов (`len(PROCESS_REGISTRY)`) | 47 | **47** |
| APP_VERSION | 2.58.66 без бампа | **2.58.66** (DEFERRED — бамп только при канон-доставке T-5216) |
| frontier (свежая БД, `PRAGMA user_version` + `schema_migrations`) | v33, 0 pending | **user_version=33, applied 33/33, 0 pending** — Δ DDL=0 |

Все Δ-инварианты = 0 (DDL/каталог/KS/reason/тулы/реестр) — расхождений с санкциями ADR-1028-24 D6 нет.

### R17-скан диффа

Скан `git diff` + новых файлов кандидата (mca-21): паттерны секретов (`sk-`, `api_key=`, `Bearer`, `password=`, `bot<id>:<hash>`, `xox`, `AKIA`, PEM) → **SECRET_HITS=0**; живые чаты (`-100…`) → **CHAT_ID_HITS=0**.

## T-5226 — backup read-back + путь возврата

### Backup read-back (локальная проверка процедуры; прод НЕ подключался)

По прецеденту pre_migration-гвардов (`services/memory_backup.py::migration_backup`, ADR-1027-1 D2: `VACUUM INTO` + free-space + read-back) на свежей throwaway v33-БД (temp, удалена после прогона):

- копия создана: `backup_copy_created: True`;
- read-back копии: **`integrity_check: ok`, `user_version: 33`**, пробная строка из `channel_state` читается (**`readback-ok`**), таблиц в копии 91. EXIT=0.

**Свежий backup прод-БД** — процедура локально отработана; исполнение на проде — на релиз-окне DevOps (T-5228): guard срабатывает автоматически перед любым шагом схемы (сейчас 0 pending → на окне без код-действий не сработает), явная копия = `VACUUM INTO '<цель>'` из живого соединения (WAL-консистентно, `memory_backup.py:110`) либо `sqlite3 <prod.db> ".backup '<цель>'"` (фоллбек `:125`), затем обязательный read-back `PRAGMA integrity_check` + `PRAGMA user_version == 33`. Подключаться к прод из этой лейны запрещено (AGENTS.md fail2ban-дисциплина) — команда передана, не исполнена.

### Путь возврата (проверенный, cold 2.58.65→2.58.66→2.58.65)

- **soft:** KS-тумблеры (85, env-оверрайдов 0) — read-side фичи гасятся без кода; прецедент mca-17c T-5198 «rollback soft (read-side нейтрален)».
- **cold:** код — revert/откат на предыдущий feat-коммит (`e16be7e` → состояние 2.58.65 `3dfc892`) + рестарт; **БД — без действий**: v33 аддитивна (только `CREATE TABLE/INDEX IF NOT EXISTS`, «НИ ОДНОГО UPDATE/DELETE», «старый код v32 не читает — cold-совместимо» — докстринг `_migrate_factcheck_temporal_v33`, `services/database.py:3830-3842`); форвард-путь v32→v33 и retry — тесты `test_t5150_startup_migrations_round1046` зелёные в этом прогоне; аддитивность схемы — `test_mca14_schema_additive_round1027` зелёный; канон-откаты mca-21 (v6→v5, v2→v3 с `prev_html`/`prev_markdown`) — зелёные в этом прогоне. Прод-прецедент совместимости в обе стороны: mca-17c деплой «cold revert e16be7e — БД совместима в обе стороны» (архив 10.47, итог блока I).
- **Команды проверки после возврата:** `/healthz` 200 (порт 443); `PRAGMA user_version == 33`; F8 `--check` OK 523; KS 85 / reason 280 / каталог 523 / тулы 14 / реестр 47 (живой импорт); focused-смоуки затронутой фичи.
- Перечень per-фичевых revert-коммитов 2.58.45→2.58.66 — домен release-manifest T-5228 (@DevOps); restore-якоря: pre_migration-копия (`pre_migration_*.db`, ротация 1), daily `local_database_*.db` (`backups/`), `prev_*`-слепки канонов в БД.

## Вердикт

**Замороженный HEAD валиден.** Полный набор зелёный с точной сверкой базлайна: 4 pre-existing identity совпадают поимённо и по подписям; 5-й failure — pollution-флейк с зелёным изолированным перепрогоном (вынесен на Reviewer как флейк нового имени, не как новое падение); js/F8/collect/census/frontier — все = санкциям, Δ = 0; ff-дисциплина цела; R17 — 0 секретов; backup-процедура доказана read-back'ом, путь возврата документирован с опорой на проверенные тесты и прод-прецедент.
