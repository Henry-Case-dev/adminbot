# deployment.md — ASAP-3.2 `asap-32-runtime-reliability-graphrag-provider-discovery` (round1029, инцидент-фикс кодировки)

> **Feature-ID:** `asap-32-runtime-reliability-graphrag-provider-discovery`
> **Risk-Level:** R3
> **Deploy:** `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, Ubuntu 24.04, venv `/var/www/admin_bot/venv`)
> **Дата:** 01.10.2026 (сервер UTC 30.09 21:24–21:33; локальное 01.10 00:24–00:33 MSK)
> **Статус:** **VERIFIED** (деплой + пост-деплой гейты пройдены; production acceptance T-4236-partial — крон-прогон 01:00 UTC поставлен под наблюдение, см. §Watch)

## 1. Binding (re-measure на commit-момент)

| Параметр | Review Round 2 (гейт) | На момент коммита (DevOps) | Вывод |
|---|---|---|---|
| Reviewed-Commit (HEAD) | `1287130b8f88dd9809ae440e2e7859af139e1de0` | `1287130b` (не изменился до коммитов) | ✓ |
| Spec-Hash | `E0F752CBAABF932011C77166BA6FF0465865AE718671D311B5571BDE7FA878AA` | пересчитан не был (spec не менялся; файл в коммите `f5054df` идентичен гейтовскому — per-file хеш манифеста 336/336) | ✓ |
| Working-Tree-Hash | `0f6e0f5fddc229c6fe626d663fb7e5cf7f16097dca045400deec3a5ae384bfa6` | **гейт-хеш воспроизведён байт-в-байт** перед коммитом (рецепт Builder воспроизведён точно; 336/336 per-file записи совпали с живым деревом — **нулевой дрейф релизных входов**). Актуальный WTH после обновления заголовка манифеста: **`f4a0064b8eefd1568789181face6893d22807222e93567c625ade244cb077f24`** | ✓ дрейф только служебный |
| WTH-манифест | `plans/reports/asap32_wth_manifest_review.txt` | перезаписан тем же рецептом: HEAD `1287130b`, staged=EMPTY, aggregate `git diff HEAD` `572fa7a6…` / 486233 B (было `06e4466b…` / 485424 B, +809 B), tracked-modified-count 79 | дрейф агрегата = tracked-доки (бухгалтерия Orchestrator: `plans/workflow_state.md` checkpoint и др.), 0 строк кода фичи; все untracked per-file — байт-в-байт гейтовские |

Атрибуция дрейфа соответствует N-ASAP32-8 (свойство рецепта) и прецеденту round1027/wave-1027: DevOps переизмеряет binding на commit-моменте.

## 2. Коммиты (пуш `1287130..f5054df`)

1. **FEAT `5aa4626`** — `fix(round1029): ASAP-3.2 summary encoding integrity — restore 221 corrupted literals, fp-recheck in activation transaction (APP_VERSION 2.58.40)` — 5 файлов, +1489/−19:
   - `services/summary_fact_package.py` — H-ASAP32-1 байт-ремонт (221 строка; runtime-литералы `FALLBACK_TOPIC_NAME` = «Общий ход обсуждения», `DESCRIPTION_SEPARATOR` = « · », сайт `rstrip(" ·")` L279);
   - `services/graphrag_rebuild.py` — M-ASAP32-2 fp-recheck первой операцией `_body` внутри `write_transaction` активации (новый файл, 887 строк; на проде пока dormant — не импортируется задеплоенным кодом 2.58.39, планировщик GraphRAG стартует из НЕ задеплоенного bot.py);
   - `tests/test_summary_fact_package.py` — `TestSourceEncodingIntegrity` ×3 (нетавтологические, чувствительность доказана ревью 3/3 FAIL на pre-fix копии);
   - `services/summary_semantic_reduction.py` — **обязательная зависимость стейджинга** (отклонение от буквальных «3 файлов» задания, санкционировано review.md Round-1 §Staging.1): ленивый импорт в `summary_fact_package` L909 под default-ON `SUMMARY_SEMANTIC_REDUCTION_ENABLED`; без него первый крон-саммари упал бы ImportError;
   - `config/settings.py` — артефакт бампа 2.58.39→2.58.40; против прода 2.58.39 diff аддитивен (единственная изменённая строка — `APP_VERSION`; новые env-only ClassVar).
2. **DOCS `f5054df`** — `docs(round1029): ASAP-3.2 — spec/ADR-1028-5/tasks/evidence/review (round-2 APPROVED FOR RELEASE…) + full_audit_results (rounds 1+2) + WTH manifest at-commit` — 13 файлов (+1807).
3. **DEPLOY-DOCS** — этот файл (коммит после верификации).

Чужой WIP НЕ тронут и НЕ закоммичен (см. §6).

## 3. Локальные гейты перед пушем

| # | Проверка | Результат |
|---|---|---|
| 1 | Целевые наборы `.venv`, чистый `__pycache__`: test_summary_fact_package + test_summary_semantic_reduction_asap32 + test_l2_budget_asap31 + test_graphrag_rebuild_asap32 | **84 passed** (вкл. 3 encoding-integrity) — parity с evidence Round 2 |
| 2 | Свежий импорт `python -B` литералов по кодпоинтам (0x41E…, sep 0x20·0xB7·0x20) | OK |
| 3 | F8 `tools/gen_param_registry_round1025.py --check` | CHECK OK, реестр 488, карта полна, идемпотентно |
| 4 | R17-скан стейджируемого набора (added-строки + untracked: sk-/xox/ghp/AKIA/PEM/tg-token/JWT/AIza) | 0 попаданий |

## 4. Деплой

- Prod HEAD до: `c0e0362` (2.58.39). `git pull --ff-only origin master` → **`f5054df`**. Код-файлы дельты — ровно 5 из фича-коммита; прочее — docs-коммиты между старым продом и гейтом (`e335412`, `1287130`: ARCHITECTURE/backlog/archive — 0 runtime-эффекта).
- **DDL = 0** (pg_db.py не деплоился), **seeds = 0** (bot.py не деплоился), миграций нет.
- Пред-рестарт проверка на проде: `venv/bin/python -B` свежий импорт литералов по кодпоинтам → **LITERALS_OK**.
- Рестарт: `sudo -n systemctl restart admin_bot` → `active`; SmartModule scheduler started `cron 0,6,12,18 Asia/Yekaterinburg` (21:24:36 UTC).

## 5. Пост-деплой верификация

| # | Гейт | Ожидание | Факт |
|---|---|---|---|
| 1 | `GET /healthz` (127.0.0.1:8000) | 200 + `2.58.40` | `{"status":"ok","version":"2.58.40"}` ✓ |
| 2 | `GET /api/health` | 200 | 200 ✓ |
| 3 | Каталог F8 на проде (read-only подсчёт тем же инвариантом, что `--check`) | 488/427/463/105/103/21 | REGISTRY **488** / settings-bound **427** / categorized **463** / GROUPS **105** / _TAB_BY_GROUP **103** / TAB_RULES **21** ✓ (+ F8 `--check` CHECK OK) |
| 4 | Кодировка на проде: свежий импорт модуля (файлы, которые исполняет сервис) | литералы чистые | **LITERALS_OK** (кодпоинт-ассерты) ✓ |
| 5 | Error-spike | нет | journal: **0** ERROR/CRITICAL/Traceback после рестарта; базлайн до рестарта — 18 за последние ~10 ч предыдущего процесса → спайка нет ✓ |
| 6 | Kill-switches (резолв на проде) | дефолт по release-плану | SUMMARY_SEMANTIC_REDUCTION_ENABLED=True, DIRECT_LLM_DECISION_ENABLED=True, MEDIA_EXECUTION_POLICY_ENABLED=True, GRAPHRAG_SHADOW_REBUILD_ENABLED=True; IMAGE_FALLBACK_MODEL пусто (fallback выключен) ✓ |
| 7 | R17 | секреты не в логах/отчётах | логи/журнал содержат только run_id/chat_id/счётчики ✓ |
| 8 | Health-сервис | жив | UptimeHeartbeat каждую минуту, WATCHDOG_SWEEP success ✓ |

## 6. Чужие файлы (подтверждение)

Закоммичено только скоуп ASAP-3.2 (18 файлов в двух коммитах). Чужой WIP остался незакоммиченным и нетронутым: `services/cover_style_*.py`, `web/*`, `tests/*` (модифицированные якоря чужих фич), `plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`, `plans/docs/mca-round1027-*`, `plans/features/mca-04b-dossier-rebuild/`, `node_modules/`, `package*.json`, `extra_images/`, `.playwright-mcp/`, незакоммиченные тесты asap32 (Pass-сеты вне гейта — остались локально: `tests/test_*_asap32.py` 7 шт., `tools/ui_asap32_cover_styles_e2e.py`, `services/media_execution.py`). `plans/current_task.md` не менялся (R17).

## 7. Watch: крон-прогон с фиксом (T-4236 partial)

- Расписание: cron `00:00/06:00/12:00/18:00` Asia/Yekaterinburg (SUMMARY_START 19:00/01:00/07:00/13:00 UTC), один чат `-1002661910336`, mode `hybrid_l2`.
- Базлайн 2.58.39 (5 последних прогонов в журнале): все `status=ok`, `publication_status=ok`, `fallback` ∈ {none, legacy} — **мета-текст ни разу**; последняя длительность 677s.
- **Следующий прогон — первый на 2.58.40: 01:00 UTC (06:00 YEKT) 01.10.2026.**
- Ожидание (закрывает класс инцидента 2.58.37, фикс H-ASAP32-1): `SUMMARY_COMPLETE status=ok`, `publication_status=ok`; fallback-пакет НЕ пустой либо `fallback=legacy` — **никогда мета-текст**; имя fallback-темы «Общий ход обсуждения» и разделитель « · » — литералы чистые (подтверждено импортом до и после рестарта).
- **Наблюдатель установлен на проде** (read-only, /tmp): `nohup /tmp/asap32_watch.sh` (pid 2570440) — ждёт 01:14 UTC, снимает окно журнала через `systemctl status -n 2000` и пишет вердикт в **`/tmp/asap32_watch.log`**; самоудаляющийся по завершении.
- Ручная проверка (если наблюдатель недоступен): `systemctl status admin_bot -n 400 | grep -e SUMMARY_COMPLETE -e ERROR` → ожидание выше; при `status=failed`/`fallback`-аномалии — см. §8.

## 8. Откат

- **Soft (без отката кода):** env `SUMMARY_SEMANTIC_REDUCTION_ENABLED=false` + рестарт — редукция выкл., каскад байт-в-байт прежний (OFF-путь покрыт тестами); приватные ключи не затрагиваются.
- **Cold revert 2.58.39:** `cd /var/www/admin_bot && git checkout c0e0362 -- . && git reset --hard c0e0362` (или `git revert 5aa4626 f5054df`) → `sudo -n systemctl restart admin_bot`; health-гейт `version=2.58.39`. Prod-база данных не мигрировала (DDL=0) — откат кода безопасен; новых PG-таблиц/колонок нет, seeds нет.
- GraphRAG-контур на 2.58.40 **не активирован** (нет стартового планировщика — bot.py не деплоился): fp-recheck в проде спит до будущего полного деплоя ASAP-3.2.

## 9. Честные границы (не сделано этим деплоем)

- Полная зона D1–D14 ASAP-3.2 (GraphRAG rebuild/Media/Capacity/Direct Decision/UI-редизайн, §107–§135) остаётся незакоммиченной и НЕ деплоилась — отдельным полным деплоем после MCA-очереди/решения владельца; этот релиз = точечный инцидент-фикс (3 файла фикса + зависимость + бамп).
- Production acceptance §76–§79 (T-4234/T-4235/T-4236 полные) не выполнялась: live image/GraphRAG/Summary+Direct acceptance требует полного деплоя зоны D.
- Browser smoke против прода не проводился: деплой не затрагивает web/* (фронтенд прод-билда не менялся).

## 10. Итог

**VERIFIED.** Прод: `f5054df`, версия 2.58.40, health 200, каталог 488/427/463/105/103/21, литералы чистые, ошибок нет, kill-switches дефолтные, откат готов (cold revert 2.58.39, DDL=0). Крон-прогон 01:00 UTC — под наблюдением (наблюдатель + процедура §7).
