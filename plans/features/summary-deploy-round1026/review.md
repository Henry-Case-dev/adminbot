# Review — S10 `summary-deploy-round1026` (единый Reviewer gate T-3474/T-3475; линза 1 requirements/correctness + линза 2 focused change audit)

- **Feature-ID:** `summary-deploy-round1026` (Эпик 2, §107/§114/§115/§116/§117; P0, gate-фича)
- **Risk-Level:** **R2** (подтверждён фактическим diff: одна строка code-default + docstrings + тесты; §104-контур, OFF-генерация, DDL, каталог, секреты, зависимости и роутинг не затронуты; активация полностью обратима env/hot/per-chat OFF + `git revert`; повышение до R3 не требуется)
- **Status: Approved** — Critical/High/блокирующих Medium = **0**; обе линзы пройдены независимо; отклонения @Builder (D-a/D-b/D-c) — допустимы, non-blocking. Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Reviewed-Commit:** `76abf911eee7ffc731cbf0fa9a2227b1a21f8c38` (HEAD == `origin/master`, closing-docs S6; annotated-тег `pre-round1026-s10`, tag-obj `be7760295` → `76abf91`; правки S10 **НЕ закоммичены** — `git status`: 39 M + 2 ??; untracked-манифест Working-Tree-Hash — **8 файлов**, кроме `review.md`)
- **Working-Tree-Hash:** `a17093d83db7a8434411567090611b1502264d4eb52a38c60a07ca6ea18646a9`
  - Рецепт (детерминированный, как в S6/S7/S8): SHA-256 манифеста (UTF-8; строки соединены LF + завершающий LF) = строка `git-diff 76abf91 sha256=8b8fd7c3cc940dddb85706804a0637e47def272a266a8423be108efceed554ab` (SHA-256 **сырых байт** stdout `git diff 76abf91`, **уже с записью в `plans/reports/audit_backlog.md`**) + по строке `<путь> sha256=<hash>` для каждого untracked-файла (сортировка, POSIX-пути), **кроме** `plans/features/summary-deploy-round1026/review.md` (сам отчёт).
  - Per-file (SHA-256, lowercase): adr `9de3e08e8d316eebe4a8ed9e32684998d328e7d697bfae747b9be1fe02088a3f`, evidence `7597762946f974245693bbc2722aa3d9584c5d882d8e4c72902eb0eb8f378f74`, procedure-115 `f2118692ccd8726d18fbf79e580fa0b557b485c26166793e767a1299778027da`, results `781867a0360781dbd248edd4786df4b6077b4197d1e496bcb0b60e05f053fa0d`, sec114-harness `b5fac423c0fc02c31934578456df34d1ba7f03ab53aa0f2616ad4a20fa08d31e`, spec `41ee0c6e7b102a21be34223578df0fbb03b759741a911ce39be9b34c8079ae3c`, tasks `c2bf9b5590297a4d81d3913ee3a5b4c79b4a97a6c0ab55b041d3ed88022d7503`, `tests/test_summary_deploy_round1026.py` `8d5028581010255744f0470460de754f333da32974f15402520ffe3beb782dbc`.
- **Spec-Hash:** `41ee0c6e7b102a21be34223578df0fbb03b759741a911ce39be9b34c8079ae3c` (**не менялся**; заявленный Builder `41ee0c6e…` подтверждён — правок `spec.md` не было)
- **Binding связан с текущим состоянием worktree:** любая правка product code / untracked-кода / relevant untracked-документов / `spec.md` после этой фиксации делает approval устаревшим и требует пересчёта.

## 1. Git base и фактический объём изменений (линза 2)

- **База:** `76abf91` (== `origin/master`; tag `pre-round1026-s10` → `76abf91`, tag-obj `be7760295` — проверено `git show-ref --tags` / `git cat-file -p`). Коммитов S10 нет; `git status --porcelain` — 39 M + 2 ??-записи.
- **Трекинг-дифф (37 файлов @Builder + 2 управляющих Orchestrator/Memory):** `config/settings.py` (default ON + комментарий + `APP_VERSION`), `services/summary_generator.py` (только docstrings), `services/summary_l2_writer.py` (только docstring), `README.md`, `plans/docs/param-registry-round1025.meta.md` (провенанс-штамп), 28 тест-модулей/helper + 4 JS-теста (version-pins 2.58.28→2.58.29 и/или явный OFF).
  - `plans/workflow_state.md` (машинный блок rev 34→40) и `plans/MEMORY.md` (S10-баннер Step 0) — **управляющие документы Orchestrator/Memory**, вне product code; машинный блок отражает post-Step-4 состояние (phase=review, next_agent=Reviewer) и является orchestrator-managed. Проверкой bindings учтён (входит в `git diff`), но этот gate его не создавал и не менял.
- **Untracked:** `plans/features/summary-deploy-round1026/` (spec/ADR/tasks + evidence/results/procedure-115/sec114-harness) и `tests/test_summary_deploy_round1026.py`.
- **Вне diff (независимо проверено пустым `git diff --name-only 76abf91 -- …`):** `services/image_generation.py`, `services/telegram_send.py`, `services/summary_prompts.py`, `services/prompt_migrations.py`, `services/summary_filter.py`, `services/summary_context_restore.py`, `services/summary_l1_clusterizer.py`, `services/summary_fact_package.py`, `services/summary_article_formatter.py`, `services/summary_test_run.py`, `web/api/routes.py`, `web/**`, `db/**`, `services/param_catalog.py`, `bot.py`, манифесты зависимостей.
- **AST-идентичность (независимое сравнение @Reviewer, `pre-round1026-s10` vs worktree, docstrings сняты):** `_run`, `_run_hybrid_l2`, `_hybrid_l2_enabled` — идентичны; весь `services/summary_generator.py` (AST без docstrings) — идентичен baseline; весь `services/summary_l2_writer.py` — идентичен baseline. `config/settings.py` отличается только по AST-значимым правкам (default `False`→`True` и `APP_VERSION`) — соответствует `git diff`.
- **R18 цел:** annotated-тег `pre-round1026-s10` → `76abf91` (obj `be7760295`); бэкап `var/backups/s10-round1026-20260924-100654/`; `.env.bak.round1026-s10`; `stash@{0}` (round1025) — на месте.

## 2. Выполненные проверки (независимо воспроизведено @Reviewer)

| Проверка | Команда/метод | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9026 passed, 0 failed**, 1 warning (154.97 с) — заявленное 9026/0 подтверждено |
| Флак-кандидат | `pytest tests/test_summary_memory.py` (изол.) | **79 passed** — таймаут teardown не воспроизводится |
| JS (47 файлов) | цикл `node tests/js/*.js` | **OK=47, FAIL=0** |
| `git diff --check` | — | exit **0** |
| Каталог / версия | импорт `param_catalog`/`settings` | **469/426/444/100/98/21**; `APP_VERSION` **2.58.29**; `SUMMARY_HYBRID_L2_ENABLED` **True**; `SUMMARY_FILTER_ENABLED` **True** |
| Каталог `--check` | `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` |
| Δ DDL | `db/**` вне diff + regex по изменённым модулям | **0** |
| Зависимости | diff манифестов/локов | **0 новых** |
| Границы diff | `git diff --name-only 76abf91 -- <запрещённые>` | **пусто** |
| Хэши evidence | пересчёт SHA-256 всех 20 заявленных файлов | **все MATCH** |
| Kill-switch (рантайм) | reload `settings` при env `SUMMARY_HYBRID_L2_ENABLED` = (нет/`false`/`true`) | **True / False / True** — `_env_bool` семантика и обратимость подтверждены |
| `_env_bool` | `config/settings.py:23-27` | default только при отсутствии env; явный `false` → OFF |
| Резолв-цепочка | `services/chat_params.py:344-377` `get_chat_param`/`_resolve_from_root` | `overrides[key] → hot.get(key, default)`; не-каталожный ключ → значение без каста (kill-switch работает) |

## 3. Линза 1 — требования/correctness

- **§107 / REQ-S10-01/-03 (SC-01/SC-03) — OK (ядро фичи):** активация = code-default `_env_bool("SUMMARY_HYBRID_L2_ENABLED", True)` (`config/settings.py:988-989`); при отсутствии override `_run` резолвит `hybrid=True` (`services/summary_generator.py:407`, `:470-483`) и уходит в `_run_hybrid_l2` **без ручного действия**. Рантайм-проба: default **True**. Фича **не остаётся выключенной**.
- **§107 / REQ-S10-02 (SC-02/SC-14) — OK:** теневой режим, поэтапный rollout, длительное сравнение с Legacy и UI-селектор Legacy↔Hybrid **не введены** (diff не содержит UI/флагов режима); «ручная активация» отсутствует.
- **§107 kill-switch / REQ-S10-03 (SC-03/SC-15) — OK:** явный `false` (env + рестарт / hot `flags.summary_hybrid_l2_enabled` / per-chat) возвращает legacy `_generate_two_call`; цепочка `per-chat → hot → env/default` байт-в-байт сохранена (AST `_hybrid_l2_enabled` идентичен baseline); покрыто `test_explicit_false_is_kill_switch`/`test_per_chat_override_respected`/`test_hybrid_disabled_by_explicit_false`.
- **§107 фильтр / REQ-S10-04 (SC-04) — OK:** `SUMMARY_FILTER_ENABLED` default True (не менялся); врезка S1 в `_run` (`:447-452`) сохранена; `test_filter_default_on_is_applied`.
- **§107 роутинг / REQ-S10-05 (SC-05) — OK:** слоты `SUMMARY_L1_*`/`SUMMARY_L2_*` — независимые env-only `ClassVar`, пусто → глобальная модель; `test_independent_l1_l2_slots`.
- **§114 / REQ-S10-06/-07/-08 (SC-06/SC-07/SC-08) — OK:** все 11 сценариев покрыты классом `TestSec114Scenarios` (`tests/test_summary_deploy_round1026.py:199-336`), чек-лист «сценарий→тест» — `sec114-harness.md`. **0 реальных отправок**: шпионы `sg.send_text`/`send_rich_message`/`generate_image_verbose` + guard-функции, бросающие при обходе (`services.telegram_send.*`, `services.image_generation.generate_image_verbose`); тестовые результаты в основной чат **не публикуются**. Порядок «проверка → деплой» зафиксирован.
- **§115 / REQ-S10-09/-10 (SC-09/SC-10/SC-18) — OK (документарно/детерминированно; live ⏳):** `procedure-115.md` — 7 проверок + rich (`<img>` → настоящий `<h1>` → `<p>`) и plain (`<b>title</b>` + абзацы); проверено детерминированными тестами `test_scenario_10_rich_message_h1` (порядок `img<h1<p`, `content_format="html"`) и `test_scenario_11_plain_text_fallback` (нет `<h1>`). Читаемость/живой прогон — за @DevOps/владельцем.
- **§116 / REQ-S10-11 (SC-11) — OK (чек-лист):** 15 критериев «не завершён» не нарушены — новый пайплайн включён; фильтр ON; L1/L2-модели по слотам; L1 не пишет Саммари; L2 получает содержание; rich `<h1>` настоящий; обложка сверху; `generate_image` не переписан; отсутствие обложки не теряет текст; причина сбоя устанавливаема; вторая аналитика не создаётся. Критерии относятся к модулям S1–S9, **вне diff** (их покрытие сохранено полным регрессом).
- **§117 / REQ-S10-12 (SC-12) — OK:** `results.md` содержит все **14** пунктов §117 с трассировкой к S1–S10; «живые» пп.7/8/11/12/13/14 помечены ⏳ post-deploy.
- **§85-UI / REQ-S10-14 (SC-14) — OK:** `param_catalog.py`/`web/**`/`summary_test_run.py` вне diff; правок каталога/F8/новых UI-тумблеров/селектора нет.

## 4. Линза 2 — focused change audit

- **Границы diff:** подтверждены фактом (§1); `param_catalog.py` вне diff; F8 не переиздаётся (`--check` OK).
- **Δ DDL=0:** `db/**` вне diff, 0 DDL-хитов в изменённых модулях.
- **CSP/zero-build:** `web/**` вне diff.
- **0 новых зависимостей:** манифесты/локи вне diff.
- **2-вызовность:** ON-путь — ровно 2 LLM-вызова (`await_count==2` в §114-harness и S5/S6-тестах); кода новых вызовов нет.
- **Version-pins:** 17 pytest + 4 JS переведены 2.58.28→2.58.29; `tests/test_round1025_f8_registry.py` — комментарий цепочки bump + строгий ассерт; `README.md` v2.58.29.
- **Целостность OFF-default-тестов:** перепрофилирование `test_flag_default_off`→`test_flag_default_on`, `test_hybrid_disabled_by_default`→`test_hybrid_disabled_by_explicit_false` (+`test_hybrid_enabled_by_default`); в legacy-тестах добавлен **явный** OFF (`gen._hybrid_l2_enabled = AsyncMock(return_value=False)` / `_HYBRID_FLAG: False`) — assertions **не ослаблены**, только явная фиксация режима.
- **Продуктовая логика не тронута:** AST `_run`/`_run_hybrid_l2`/`_hybrid_l2_enabled` и весь `summary_l2_writer.py` идентичны baseline (только docstrings); `config/settings.py` — default + комментарий + `APP_VERSION`.

## 5. Отклонения @Builder — вердикты

- **[D-a] `plans/docs/param-registry-round1025.meta.md` (провенанс-штамп версии, вне точного ADR D1) — ДОПУСТИМО, non-blocking, не drift.** Обновлён **только** `APP_VERSION` 2.58.28→2.58.29. Правка **обязательна** для зелёного регресса: `tests/test_round1025_f8_registry.py:188-193::test_meta_provenance` ассертит `APP_VERSION in meta`. Прецедент S5–S9 (файл штатно обновляется при bump — `git log` подтверждает правки в closing-коммитах S5–S9). Каталог/TSV/F8 не переиздаются; `--check` OK. Классификация: **не fix, не spec amend** — штатный bump-артефакт федорации версии; рекомендую @Architect при merge (§81) явно назвать файл в D7-описании bump-цепочки (doc-only, non-blocking).
- **[D-b] массовый «явный OFF» в legacy-тестах шире точного списка D1 — ДОПУСТИМО, non-blocking.** Все правки — в `tests/**` (префикс `tests/**` прямо разрешён ADR D1); суть — перевод legacy-тестов на **явный** аварийный OFF вместо опоры на дефолт (до S10 дефолт был OFF, поэтому поведение тестов сохранено). ON-путь остаётся покрыт §114-harness и S5–S6-интеграцией; assertions не ослаблены, `skip`/`xfail` не добавлены. Классификация: **не fix, не spec amend**.
- **[D-c] флак `tests/test_summary_memory.py` (teardown-таймаут Windows asyncio) — ИНФРАСТРУКТУРНЫЙ ШУМ, не регресс.** Независимо: изолированный прогон `test_summary_memory.py` — **79 passed**; полный прогон — **9026/0** без таймаутов. Файл вне diff; S10 его не касается. Классификация: **не fix**; наблюдение (Windows asyncio teardown), при повторе — отдельный хотфикс.

## 6. Counterexamples (проверено, не гипотезы)

1. **«Фича осталась выключенной» (§107/§116)** — рантайм-проба `settings.SUMMARY_HYBRID_L2_ENABLED` = **True**; `.env` не пинит `false`; `_run` при default-резолве уходит в `_run_hybrid_l2` (`test_run_reaches_hybrid_without_manual_action`). OK.
2. **Kill-switch не работает** — env `false` → OFF; hot/per-chat `false` → legacy (`test_explicit_false_is_kill_switch`, `test_hybrid_disabled_by_explicit_false`); цепочка `_resolve_from_root` сохранена. OK.
3. **Логика пайплайна изменена под видом docstring** — AST-сравнение без docstrings: `_run`/`_run_hybrid_l2`/`_hybrid_l2_enabled` и весь `summary_l2_writer.py` идентичны baseline. OK.
4. **Реальные отправки в §114-тестах** — guard на `services.telegram_send.*`/`services.image_generation.generate_image_verbose` бросает при обходе; отправки идут только в шпионы. OK.
5. **Протечка секрета/сырого текста в логи (R17)** — `test_r17_no_raw_text_in_logs`: секрет доставлен, но в логах отсутствует. OK.
6. **Δ DDL/каталога скрытно ≠ 0** — `db/**`/`param_catalog.py` вне diff; `--check` OK; каталог 469/426/444/100/98/21. OK.
7. **Устаревшие version-pins маскируют рассинхрон** — ассерты строгие (`==`, без `>=`); README/settings синхронны 2.58.29. OK.
8. **Воскрешение/ослабление OFF-тестов** — перепрофилирование без удаления и без `skip`/`xfail`; OFF-путь фиксируется явным флагом. OK.

## 7. Блокирующие findings — **нет**

Critical = 0; High = 0; requirement-/architecture-blocking Medium = 0. Отклонения D-a/D-b/D-c — non-blocking (§5).

## 8. Non-blocking debt

- **[L-R1026S10-1] [info, docs, non-blocking] — OPEN:** `plans/workflow_state.md` (машинный блок) отражает post-Step-4 состояние (rev **40**, phase=`review`, next_agent=`Reviewer`); `evidence.md` §6 классифицирует этот файл как «пред-существующий до Step 4». Формулировка неточна (содержимое описывает завершённый Step 4). Файл — orchestrator-managed, вне product code; этот gate его не изменял. **Fix:** уточнение формулировки в evidence при merge (doc-only); машинный блок менять только через `workflow_checkpoint` (@Orchestrator).
- **[L-R1026S10-2] [info, docs, non-blocking] — OPEN:** возможен doc-drift нумерации строк в `config/settings.py`-комментарии (evidence §1 указывает «978–988»; фактически default — `:988-989`, `APP_VERSION` — `:1827`). **Fix:** @Architect приводит номера при merge (doc-only).
- **[L-R1026S10-3] [low, coverage, non-blocking] — OPEN:** §116 (15 критериев) не имеет единого machine-verified теста (документарный чек-лист + неизменность модулей S1–S9). Для R2 достаточно; точка роста — параметризованный §116-чек-лист отдельным решением.

## 9. Недоступные проверки (Unavailable checks)

- **Live §115 (7 пост-деплой-проверок на проде)** — не выполнялась: **PENDING OWNER VERIFICATION** (@DevOps/владелец, T-3478; требует деплоя 2.58.29). Вне этого gate.
- **Live-составляющая §117 пп.7/8/11/12/13/14** (пример статьи/логи/скриншот карты/результаты первого запуска/подтверждение публикации) — **PENDING OWNER VERIFICATION**; детерминированная часть оформлена (`procedure-115.md`/`results.md`).
- **§116 machine-verification** — см. L-R1026S10-3 (недоступно как единый тест; покрыто неизменностью модулей S1–S9 + полным регрессом).
- **Реальная прод-конфигурация `.env`** — намеренно не читалась; локальный `.env` не пинит `SUMMARY_HYBRID_L2_ENABLED`; проверка прод-`.env` — часть D7-процедуры @DevOps.

## 10. Handoff

- **@Orchestrator → APPROVED** (единый gate: линза 1 + линза 2 пройдены; Critical/High/блокирующих = 0). Далее: commit/push (без force) → **T-3476** merge (`plans/ARCHITECTURE.md` §81, ADR-1026-12 Accepted) → **T-3477** archive → **T-3478** deploy/активация (2.58.29, §115) → **T-3479/T-3480** handoff; live — PENDING OWNER VERIFICATION.
- Binding: Reviewed-Commit `76abf91`, Working-Tree-Hash `a17093d8…`, Spec-Hash `41ee0c6e…`; любая последующая правка product code / relevant untracked-файлов / `spec.md` делает approval устаревшим.
- Отдельный Scanner-отчёт/approval **не создаётся** (Scanner удалён намеренно; обязанности — в линзе 2 этого gate).
