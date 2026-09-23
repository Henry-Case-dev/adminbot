# review.md — S3 `summary-l1-clusterizer-round1026` (T-3275, Step 5 @Reviewer)

- **Feature-ID:** `summary-l1-clusterizer-round1026` (Эпик 2, S3; T-3275)
- **Status: Approved** — оба мандатных ленса (requirements/correctness + focused change audit) пройдены независимо; Critical 0 / High 0; блокирующих Medium нет. Live — **PENDING OWNER VERIFICATION** (вне автономного контура S3).
- **Дата:** 23.09.2026. Вход: `spec.md`, ADR-1026-5, `tasks.md`, `evidence.md`, `plans/current_task.md` §80–§82/§92–§96/§106/§108–§109, реальный код и дифф.

## Git base и инспектированный скоуп изменений

- **База:** `4007081` (== `origin/master`; annotated-тег `pre-round1026-s3` = `7637cc4e…` → `4007081`).
- **Дифф (не закоммичен):** 57 изменённых + 4 untracked (`services/summary_l1_contract.py`, `services/summary_l1_clusterizer.py`, `tests/test_summary_l1_clusterizer.py`, папка фичи). Изменённые: `config/settings.py`, `services/{summary_prompts,prompt_migrations,param_catalog}.py`, `.env.example`, `README.md`, `plans/docs/canon/architecture.md`, реестр/карта/ScreenMap, F8-фикстуры, ~43 теста (re-pin чисел/версии). **Вне diff:** `services/summary_generator.py`, `services/summary_xml.py`, публикация/обложка (`image_generation.py`, `telegram_send.py`), `web/**`, `plans/current_task.md` — врезки L1 нет (T-3273 DEFERRED). `git diff 4007081 --name-only` + `git status` сверены.

## Checks performed (воспроизведено @Reviewer)

- `py -3 -m pytest -q` (`.venv`, Python 3.12): **8685 passed / 0 failed / 1 warning** (111.25 s) == baseline 8569 + 116.
- Новый файл: **116 passed**; целевые регрессы (two-call/cover/filter/restore-integration): **65 passed**.
- JS: все **43/43** файла `tests/js/*.js` поштучно — OK (`node --check web/app.js` — OK ранее).
- `git diff --check` — exit 0 (чисто); импорт-проверка каталога: **REGISTRY 468 / Settings fields 426 / categorized 443 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21** (prompts-groups 21→22).
- F8: `tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 468 == REGISTRY…`, exit 0; `sha256(param_catalog.py)` = `6531f653…7812` == фикстура; delta 56→57.
- R18: тег `pre-round1026-s3` на месте; `var/backups/s3-round1026-20260923-183119/BASELINE.md` есть; `stash@{0}` цел. `APP_VERSION` **2.58.22** синхронен (settings/README/пины; `web/index.html` использует `?v=__APP_VERSION__` — отдельный cache-bust не требуется).

## Requirement/evidence coverage (все [x] блоков A–F подтверждены кодом+тестами)

- **D1 (ровно 1 вызов):** в `run_l1` ровно один `await call(messages)`; третьего вызова нет; живой путь не тронут — `await_count==2`, `steps=[stage1,stage2]`, Stage-1 == `SUMMARY_EDITOR_SYSTEM_PROMPT`, OFF-цепочка байт-в-байт. Регресс-тест нетривиален (при врезке L1 `await_count` стал бы 3).
- **D5/§95:** строгая схема (top-5/thread-4/fact-2 ключа, лишние → `invalid`); `schema_version` строго int==1 (bool отсечён); лимиты 100/30/1000/200/500; пространства ID (payload — TG; DB `id` — только §93-упаковка; неоднозначность/пропуск → `id_space_mismatch`); evidence ⊆ треда; один id — ровно в одном треде; `unassigned ∩ threads = ∅`; авто-`unassigned`; канонизация/перенумерация/дедуп/ASC — детерминированы (двойной прогон байт-идентичен); fail-closed все 5 статусов (`usable` = ok/truncated); «L1 не пишет саммари» — канон + структурные капы, прозы/заголовков в выходе нет.
- **D2:** `response_mode`/`cover_prompt` — опциональные служебные поля того же JSON; `_resolve_cover_prompt`/`compose_cover_image_prompt`/rich-путь/§104 не тронуты.
- **D4/F8:** Δ каталога ровно **+1** (468/426/443; GROUPS/`_TAB_BY_GROUP`/TAB_RULES без изменений); промпт PG-only (`settings_field=None`, `env_name=None`, `advanced/synthesizer`); `SUMMARY_L1_*` — env-only ClassVar (Settings 426 не изменилось); F8 переиздание корректно (repin sha256, регенерация TSV/meta/ScreenMap +1 строка/0 удалений, фикстуры/ассерты не ослаблены, `--check` зелёный).
- **Канон (ADR-1013-3):** `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT` == эталон `plans/docs/canon/architecture.md` байт-в-байт; `PREV_SUMMARY_L1_CLUSTERIZER_R1026` (база без общего блока маркировки — прецедент `PREV_SUMMARY_EDITOR_R1023`); ступень `PROMPT_MIGRATIONS` идемпотентна, кастом не перезаписывается, pre-seed skip; `ROLLBACK_MIGRATIONS` документирован; «один промпт — один источник» (PG-ключ). Текст канона не нарушает канон-политику (типографика-правило относится к выходному тексту бота, не к исходникам промптов; `«Стиль обложки»` — как в существующем Stage-1).
- **Инварианты:** Δ DDL=0 (DDL/schema-файлов и `pg_db.py` в diff нет); CSP/zero-build (только stdlib + существующие сервисы); R17 (логи `L1_*` — числа/коды/host; текст сообщений/сырой ответ не логируются — тесты); R18; §57–§73/F0–F11/S1/S2 не сломаны (полный pytest/JS зелёные); маркер-тесты не ослаблены (только re-pin чисел/версии).

## Focused audit coverage

Проверены: изменённые и новые файлы, их критические зависимости (`system2_handoff.parse_json_object`/нормализаторы/R17-фильтр, `summary_filter.estimate_and_split`, `summary_context_restore.build_l1_payload`, `token_counter.resolve_chat_limit`, приватный мост `llm_client._post`/`_fallback_with_retries`/`_fallback_active`), границы пространств ID, детерминизм, fail-closed, R17-логи, канон-миграции, F8-артефакты, отсутствие новых внешних зависимостей и сетевых/DB-точек в новых модулях. Секретов/утечек не найдено; инъекций/фабрикации ID не найдено (неизвестный id → `invalid`).

## Blocking findings

Нет (Critical 0 / High 0; блокирующих Medium / нарушений принятых инвариантов нет).

## Non-blocking debt (подтверждено независимо; не блокирует)

| ID | Sev | Локация | Наблюдение / evidence | Fix |
|---|---|---|---|---|
| L-R1026S3-1 | Low | `summary_l1_clusterizer.py:470` (вне `try:` :477) | `resolve_l1_slot()` вне fail-closed: проброс исключения вопреки docstring («любое исключение → error/invalid»). S3 не в живом пути. | Перенести резолв в `try` до врезки S5 |
| L-R1026S3-2 | Low | `summary_l1_contract.py:399-413` | `evidence_message_ids: []` принимается (`status=ok`, проверено пробой); §94 подразумевает evidence | Требовать ≥1 evidence (`invalid_fact`) либо документировать политику |
| L-R1026S3-3 | Low | `summary_l1_clusterizer.py:199-215` | Строка без `tg_message_id`: single-chunk → `message_id: null`, fragmented → `IdSpaceMismatch` (несогласованность; S1/S2 гарантируют поле) | Унифицировать fail-closed |
| R-R1026S3-1 | Info | `summary_l1_clusterizer.py:357-404` | Dedicated-путь (`llm._post`) не пишет analytics (`_record_analytics` module/step/correlation_id) и не учитывает global usage / per-chat BYOK, в отличие от `generate`; в S3 нет потребителя | Публичный метод клиента на S5 |
| R-R1026S3-2 | Info | `summary_l1_clusterizer.py:181-244` | Оценка бюджета считает только токены текста (+маркеры), без system-промпта и JSON-обёртки §92 → фактический ввод больше оценки; спека предписывает существующий эстиматор | Наблюдать/учесть overhead на S5 |
| R-R1026S3-3 | Info | `plans/workflow_state.md:61`, `plans/MEMORY.md:8` | Активный пойнтер не отражает Step 4 @Builder (синк ожидается на Step 8–10 @PM/@Memory) | Синк на шаге метрик/архивации |
| I-R1026S3-1 | Info | `tests/js/round1025_hotfix{7,8,9,10}_*.js` | Regex обновлён на `2.58.22`, метка assert осталась «2.58.21» (косметика) | Поправить при следующем re-pin |
| I-R1026S3-2 | Info | `summary_l1_contract.py:50-51,360` | `THREAD_ID_RE` c `$` пропускает trailing `\n` (влияния нет — перенумерация `thread_%03d`) | `\Z` при желании |

## Unavailable checks

- **Live-приёмка владельца** (Telegram WebView) — PENDING OWNER VERIFICATION (автономный контур S3 её не заменяет).
- E2E §113 (Mini App) — S9, вне S3.
- Реальные провайдерские ответы L1 в прод-среде — будут доступны только после врезки S5/S6 (сейчас модуль вызывается лишь тестами с моками).

## Итог

**Approved.** Требования §80–§82/§92–§96/§106/§108–§109 выполнены в границах автономного контура S3; живой путь, публикация и обложка не тронуты; fail-closed, пространства ID и канон-дисциплина подтверждены кодом, тестами и воспроизведёнными прогонами. Non-blocking debt зарегистрирован (`full_audit_results.md`, `audit_backlog.md`) и адресован S5.
