# deployment.md — mca-18-self-model (prod 2.58.62)

**Статус: VERIFIED** (T-5094 @DevOps, серверное UTC 05.10.2026 21:18–21:24; локальная сессия 06.10.2026).

## 1. Коммиты и деплой

- **feat `4c70477`** (69 файлов): runtime/tests + bump + release-пины + фичевый пакет планов (spec/ADR-1028-18/threat/tasks/requirements-map/evidence/review + WTH-манифест + scanner-отчёт + `plans/docs/mca-round1027-arch-frames.md` §1.2.7). Из биндинга — манифест итер.2 37 файлов (`plans/reports/mca18_wth_manifest_review.txt`, MANIFEST_SHA256 `d7d0071f…bb8c59`); вне манифеста добавлены release-owned: `README.md` (header), F8 meta-pin, 19 py-пинов, 3 stale py-пина 2.58.57, 4 js-харнесса, `tools/_mca18_release_bump.py` (тул бампа — прецедент `_mca10b_release_bump.py`), санкционированный `tests/test_mca18_s1_scope_round1042.py`.
- Push: `23cb2a1..4c70477 master -> master` (ff, без force); прод `git pull --ff-only` чистый: `e26dcf9 → 4c70477`.
- deploy-doc: этот файл (отдельный коммит поверх feat).

## 2. Preflight (биндинг/бамп)

- **Per-file identity gate** (прецедент mca-15/10b, [P-1]): 37 файлов манифеста против дерева — **35 байт-в-байт**; **2 санкционированных дрейфа** (Scanner-recheck S-1, «к деплою ДА»): `services/mca_self_model.py` = `106a8f69…f1ddf2` — побайтно совпал с биндингом recheck (S-1-fix `_scope_mismatch_reason` fail-closed), `evidence.md` — append recheck-записи. Продуктового дрейфа нет → гейт PASS.
- **[D-1] disclosure (процесс-файлы вне кандидата):** `plans/backlog.md` — append «Раунд 10.42» (нон-блокеры S-2/S-3, live-гейты) — вне манифеста, домен PM T-5096, **не коммитился**; `plans/workflow_state.md` — **не коммитился**; `plans/docs/mca-round1027-arch-frames.md` — включён в feat по санкции T-5094: §1.2.7 (санкции mca-18) + исторический docs-only хвост mca-05 (§1.2.6 + ADR-1027-12 в §4, санкция 01.10.2026 пост-фактум по уже выпущенной v21). Ревью-тулы `tools/_mca18_reissue_f8.py`/`_mca18_repin_routes.py` (в манифесте) — оставлены untracked по инструкции T-5094 (не коммитились, хеши верифицированы в дереве).
- Бамп-тул: APP_VERSION `2.58.61→2.58.62`, README header, F8 meta-pin, 19 py-пинов, **3 stale 2.58.57-пина** (`test_webapp_design_tokens`/`f6`/`hotfix6` — красные #2–4 ревью закрыты), 4 js-харнесса (`2\.58\.61→2\.58\.62`). 30 файлов, 0 хвостов; исторические упоминания версий в docstring'ах не тронуты.

## 3. Прод-факты

- До деплоя (верифицировано): prod HEAD `e26dcf9`, `/healthz` 200 `{"status":"ok","version":"2.58.61"}`, PID 3927271, NRestarts=0; БД `user_version` 30, таблиц 112, book `(30, random_uses)`.
- **Рестарт #1** 21:18 UTC → PID **4018876**, NRestarts=0, ExecMainStatus=0. Guard 21:18:53, миграция v31 21:18:54–55, polling 21:19:08.
- **Рестарт #2 (идемпотентность)** 21:23 UTC → PID **4020624**, NRestarts=0; в журнале миграций/guard-копий/ротаций **0** — no-op; polling 21:23:33.
- `/healthz` **200 `{"status":"ok","version":"2.58.62"}`** ×2 (оба рестарта); `/api/health` **200** ×2.

## 4. Миграция v30→v31

- **Бэкап-guard (mca-14, fail-closed):** `pre_migration_20261005_211627.db` **1.319 GB**, создан 21:18:53, read-back ok @**v30** («pre-migration copy created + read-back ok | target_version=30»). Старая guard-копия 10b (`pre_migration_20261005_132427.db`) ротирована disk_retention'ом 21:18:54 — ожидаемое «keep 2 newest» (прецедент mca-09/10b); якорь — новая guard-копия.
- **Применена ровно один раз** (21:18:54–55, бут #1), пошаговый журнал: 4 таблицы (`mca_self_identity`/`mca_trait_observations`/`mca_behavior_rules`/`mca_adoption_links`) + 9 колонок `graph_facts` (`subject_entity_id`→`revision`) под PRAGMA-guard.
- **Состояние после:** `user_version` **31**, `schema_migrations` `(31, self_model)` **×1**, таблиц **116** (112+4), integrity ок (индексы: `idx_graph_facts_subject_entity`, `idx_graph_facts_chat_kind`, `idx_mca_trait_obs_chat_observed`, `idx_mca_trait_obs_agent_observed`, `idx_mca_behavior_rules_scope_status`, `idx_mca_behavior_rules_agent_status_dim`); сид `mca_self_identity` 1 строка (agent_id uuid4, seed ON CONFLICT DO NOTHING); остальные v31-таблицы **0 строк**; все 16225 строк `graph_facts.revision=1`.
- **Данные целы** (spot-check v30→v31, между рестартами): `task_jobs` 659→661, `mca_events` 11633→11644 (активность бутов), `mca_bot_outputs` 93=93, `mca_random_draws` 7=7, `summary_runs` 16=16, `mca_episodes` 0=0, `graph_facts` 16225=16225.
- **PG no-op:** `pg_db.py` вне диффа; тело v31 SQLite-only (GEN-R4).
- **Kill-switches:** env-оверрайдов **0** (в прод-`.env` нет `MCA_SELF_MODEL_ENABLED`/`MCA_TRAIT_RULES_ENABLED`/`MCA_LEGACY_TRAITS_MIGRATION_ENABLED`) → все 3 default ON (реестр 73→76).

## 5. Проверки

| Набор | Результат |
|---|---|
| Focused mca-18 (7 файлов, вкл. s1-scope) | **96 passed** (сходится с Scanner-recheck) |
| Смежные: dream 16 + js-unit 38 + F8-реестр + 3 stale-пиновых файла | **172 passed** |
| 4 js-харнесса (node, новые пины) | **4/4 OK** |
| Полный pytest | **12088 passed / 4 failed / 1 skipped** (6:47) — 0 новых падений |
| Журнал после обоих рестартов | **0 ERROR/CRITICAL/Traceback**, 0 «database is locked» |
| R17 (скан журналов на секреты) | **0 утечек** |

- **Pre-existing reds (4, вне дельты mca-18, backlog §121):** `test_webapp_nav_disclosure_ui::test_memory_rag_and_sleep_tabs` + `test_webapp_status_control::test_status_public_for_all_roles` (status-pin experience/intents), `test_mca09_intents_block_e::test_registry_process_intent_initiative` (pollution mca-09↔17a — standalone passed), `test_tool_loop::test_query_chat_memory_count_reaches_model` (backlog mca-15). Прошлый независимый прогон 12082/7: дельта = +3 s1-теста, −3 stale-пина (закрыты sweep'ом).

## 6. Rollback

- **Soft:** `MCA_SELF_MODEL_ENABLED=false` в прод-`.env` + рестарт — промпт-путь бит-в-бит 2.58.61 (legacy `build_persona_prompt_block`); при необходимости + `MCA_TRAIT_RULES_ENABLED=false`/`MCA_LEGACY_TRAITS_MIGRATION_ENABLED=false`. v31 инертна для выключенных осей.
- **Cold:** `git revert 4c70477` (или checkout `e26dcf9` = 2.58.61); v31 строго аддитивна/идемпотентна — v30-код не читает v31-объекты; restore из `pre_migration_20261005_211627.db` — только R18-авария.
- Наблюдения/черты/правила, накопленные до cold-revert, теряются из чтения (fail-safe), события остаются в `mca_events`.

## 7. Notes

- **[D-1] disclosure:** drift кандидата против манифеста итер.2 = ровно санкционированный список Scanner-recheck (mca_self_model.py хеш-в-хэш + s1-тест + appends evidence/review/scanner); 35/37 байт-в-байт. arch-frames включён по санкции T-5094 (см. §2).
- **Live-приёмка T-5095 — [PENDING OWNER]** (реальный чат, без имитации): поведение self-model-кадра, витрины, сценарий paired-replay — на санкции владельца. До live поведенческую приёмку на проде не заявлять.
- Нон-блокеры scanner'а — в backlog (Раунд 10.42, домен PM): S-2 (кап 24ч не enforcement), S-3 (UNIQUE на mca_behavior_rules), S-4 (guards без прод-вызовов), UI-active_rules (витрина vs кадр), I-flake.
- ADR-1028-18 → **Accepted по merge** (merge `plans/ARCHITECTURE.md` §122+ — домен PM T-5096).
- Деплой-механика: прод-пулл `--ff-only`, systemd `admin_bot`; guard-полка и бэкапы не удалять (R18). Ревью-тулы `_mca18_reissue_f8.py`/`_mca18_repin_routes.py` остались untracked в рабочем дереве (вне репо-истории).
