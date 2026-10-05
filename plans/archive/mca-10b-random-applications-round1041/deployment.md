# deployment.md — mca-10b-random-applications (prod 2.58.61)

**Статус: VERIFIED** (T-5064 @DevOps, серверное UTC 05.10.2026; сессия после тихой гибели предыдущей DevOps-сессии — состояние дерева восстановлено и довыполнено).

## 1. Коммиты и деплой

- **feat `780f77c`** (83 файла): runtime/tests/F8-артефакты + bump + release-пины. Из биндинга — манифест ITER2 82 файла (`plans/reports/mca10b_wth_manifest_review.txt`); вне манифеста добавлены release-owned: `README.md` (header), `tests/test_scope_selector_round1025.py` (пин), 4 js-харнесса (пины), `tools/_mca10b_release_bump.py` (тул бампа — прецедент `_mca09_release_bump.py`).
- **docs `bcb1a32`** (8 файлов): spec/ADR-1028-17/threat/tasks/requirements-map/evidence/review + WTH-манифест.
- Push: `897ce4f..bcb1a32 master -> master`; прод ff `5fe2d31 → bcb1a32` (`git pull --ff-only`, чистый).

## 2. Preflight (биндинг/бамп)

- **Per-file identity gate** (прецедент mca-15, [P-1] — рецепт агрегата не документирован): 82 файла манифеста против дерева — **61 байт-в-байт**; **21 файл дрейфовал ровно на release-bump** (2.58.60→2.58.61): бинарный revert строки версии восстанавливает хэш ревью для всех 21 (включая `config/settings.py` = `ed8d5c72…` и meta). Продуктового дрейфа нет → гейт PASS, дрейф санкционирован release-bump-conventions (прецедент mca-09 [D-1]).
- Бамп-тул `tools/_mca10b_release_bump.py`: APP_VERSION + README header + F8 meta-pin + 19 py-пинов (манифест) + `test_scope_selector` (вне манифеста — не имел фичевой дельты) + 4 js-харнесса. Historical markdown в комментариях не тронут.
- Release-pin sweep завершён: хвостов `2.58.59` в js и паразитных `2.58.60`-пинов нет; оставшиеся `2.58.60` — семантические («OFF = бит-в-бит 2.58.60», база ревью/спеки) — не пины.
- Ревью + аддендум подтверждены: `review.md` — **Approved финал** (F-1/F-2 rework recheck, scope ровно 4 файла).

## 3. Прод-факты

- До деплоя (верифицировано, не предположение): prod HEAD `5fe2d31`, `/healthz` 200 `{"status":"ok","version":"2.58.60"}`, PID 3869967, NRestarts=0.
- **Рестарт #1** 13:23:08 UTC → PID **3925252**, NRestarts=0, ExecMainStatus=0. Полная готовность ~13:27 (guard 1.3 ГБ ~2.5 мин — норма).
- **Рестарт #2 (идемпотентность)** 13:31:08 UTC → PID **3927271**, NRestarts=0, ExecMainStatus=0; в журнале с 13:31 миграций/guard-копий нет — **no-op**.
- `/healthz` **200 `{"status":"ok","version":"2.58.61"}`** ×2 (оба рестарта); `/api/health` **200** ×2.

## 4. Миграция v29→v30

- **Бэкап-guard (mca-14, fail-closed):** `pre_migration_20261005_132427.db` **1.319 GB**, создан guard'ом при буте #1, read-back ok @**v29** (`memory_backup: pre-migration copy created + read-back ok | target_version=29`). Ручной DevOps-бэкап `pre_migration_20261006_20261005_131830_manual.db` (1.387 GB, sha256 `e46ac03e…`, read-back @v29: integrity ok, таблиц 109, book 18) был сделан ДО рестарта и **ротирован disk_retention'ом** при буте — ожидаемое поведение «держать новыйшей» (прецедент mca-09); якорь остался — guard-копия.
- **Применена ровно один раз** (13:26:59 UTC, бут #1): `mca_episodes.last_retrieved_at` added, `last_used_in_chat_at` added, `mca_associations`, `mca_archive_coverage`, `mca_belief_reviews` — «migration v30 applied | random_uses».
- **Состояние после:** `user_version=30`, `schema_migrations`: `(29, intents)` ×1 + `(30, random_uses)` **×1**, таблиц **112** (109+3), `idx_mca_episodes_last_used` на месте, integrity ok; новые таблицы **0 строк**.
- **Данные целы** (spot-check v29→v30): `task_jobs` 655→656, `mca_events` 11055→11061 (активность бута, рост), `mca_bot_outputs` 88=88, `mca_intents` 0=0, `mca_random_draws` 0=0, `summary_runs` 15=15, `mca_episodes` 0=0.
- **PG no-op:** в теле `_migrate_random_uses_v30` PG-вызовов нет (SQLite-only контур; контрольно — grep тела функции).

## 5. Проверки

| Набор | Результат |
|---|---|
| 10b блоки A–D (`.venv`, локально) | **59 passed** |
| Репро F-1/F-2 (`block_c -k "F1 or F2"`) | **4 passed** |
| Смежные: F8-реестр/param_catalog/tabs/budget_guardrails/l1-TestCanon | **134 passed** |
| js-unit (`test_webapp_js_unit.py`, харнессы с новыми пинами) | **38 passed** (4 hotfix N-2 reds закрыты sweep'ом) |
| Соседи rework: dream_worker + mca-06 DE + mca-17a | **134 passed** |
| Prod-venv (prod-чекинут 2.58.61, до рестарта): блоки A–D + F1/F2 | **59 passed** + **4 passed** |
| F8 `--check` (локально и на проде) | **CHECK OK, реестр 510**, EXIT=0 |
| env-оверрайды kill-switch'ей | **0** (`MCA_RANDOM_USES_ENABLED` не задан → default ON) |
| Журнал после обоих рестартов | **0 ERROR/CRITICAL/Traceback** |
| R17 (скан 13 секрет-подобных env-переменных в журнале с 13:23) | **0 утечек** |

- **Pre-existing reds (не дельта 10b, вне манифеста):** `test_tool_loop::test_query_chat_memory_count_reaches_model` — воспроизводится, 1 failed (mca-15-text stale, backlog @Orchestrator); `test_migrate_env_to_pg` — **не воспроизводится, 21/21** (снят, как в mca-09). Ревью ранее доказало на чистом HEAD через worktree: status-pin, 4 js-харнесса (закрыты бампом), mca-09↔17a pollution — все вне 10b.

## 6. Rollback

- **Soft:** `MCA_RANDOM_USES_ENABLED=false` в `.env` + рестарт — вся 10b-поверхность OFF (честный `disabled`/`not_run`), бит-в-бит 2.58.60; v30 аддитивна/инертна (не пишется/не читается). Per-use аварийное отключение — каталог `random.uses.*=false`.
- **Cold:** `git revert 780f77c` (или checkout `897ce4f` = 2.58.60); `user_version` 30 мультивалидна (v29-код не читает v30-объекты); restore из `pre_migration_20261005_132427.db` — только R18-авария.
- Live-применения при cold-revert теряются (fail-safe, события остаются в `mca_events`).

## 7. Notes

- **[D-1] disclosure:** дрейф 21 файла после снапшота ревью = ровно release-bump, верифицирован binary hash-revert к хэшам ITER2; sweep расширен на 4 js-харнесса (2.58.59→2.58.61) и `test_scope_selector` — release-owned, закрыл N-2 reds.
- **Live T-5065 — [PENDING OWNER]** (реальный чат: применения/визуализация на проде; без имитации). До live приёмку применений на проде не заявлять (spec §13.7).
- F-1 (честный исход selection + закрытие trace-run) и F-2 (зависшие queued exploration-job) — rework по аддендуму ревью; регресс-фикстуры в блоке C.
- N-1 (живой wiring memory_recall-селектора), N-3 (leaked aiosqlite в тест-окружении), N-4 (ссылка spec §11 на строку матрицы) — backlog @Orchestrator, не блокеры.
- Prod checkout содержит untracked `info_text.md.bak.epic44…` (старый мусор, не тронут).
