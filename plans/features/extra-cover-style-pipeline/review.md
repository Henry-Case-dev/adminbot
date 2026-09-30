# review.md — `extra-cover-style-pipeline` (EXTRA, round1029)

- **Feature-ID:** `extra-cover-style-pipeline`
- **Risk-Level:** **R3** (обязательный прод-деплой, PG-DDL 5 таблиц, аддитивное
  изменение публикационного контура Summary, новая внешняя image-edit
  зависимость, кросс-фичевая DDL-развилка). Риск подтверждён; глубина ревью
  расширена до интеграционных краёв и персистентного состояния.
- **Status: Needs Fixes**
- **Reviewed-Commit:** `bbdee1ca44bf6695a1a421a3629792f6a0114edc` (HEAD; коммитов
  EXTRA нет — фича целиком в рабочем дереве).
- **Spec-Hash:** `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF`
  (перепроверен, совпадает с заявленным Builder).
- **Working-Tree-Hash (release-scope manifest):**
  `389993d2f5158b85584a255b00065ddd31894a8db428c129a2c548d6ad721878`
  — SHA-256 от сортированного манифеста строк `<relpath> <sha256(file bytes)>`
  по **102** файлам EXTRA-скоупа (78 tracked-modified + 24 untracked: 7 новых
  `services/*`, `web/api/cover_styles.py`, 7 новых py-тестов, 1 JS-харнесс,
  `tools/_extra_reissue_f8.py`, 5 feature-документов, 2 builder-скриншота).
  **Исключено (чужой WIP / вне scope):** `plans/metrics.md`,
  `plans/workflow_state.md`, `plans/features/mca-04b-dossier-rebuild/`,
  `node_modules/`, `package.json`, `package-lock.json`, `.playwright-mcp/`,
  `extra_images/` (владельческие read-only). Review-отчёты
  (`review.md`, `full_audit_results.md`, `audit_backlog.md`) в manifest не входят.
  Промежуточные метрики: `WTH_TRACKED e4af9684…` (78 файлов),
  `WTH_UNTRACKED c82bd8e5…` (20 файлов без feature-доков).
- **Прочие binding-хэши:** `tasks.md` `82B12AF0703E3483B6E8171578B04FDC91613C88ACDF33BA8BAB4F1DACB205B2`;
  `adr-1028-4` `E9C44ACCADF4FC0F9921A3F73054768A49EA1D8F700C1D744DBC006D92807251`;
  `current_task.md` `D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB`
  (R18 — не изменялся).
- **Git base и объём:** base = HEAD `bbdee1c`; `git diff`-объём — 78 tracked-файлов,
  untracked release-scope — 24 файла. Крупные diff-шумовые файлы (`web/app.py`
  реальный Δ = +4 строки; `test_summary_cover_round1023.py`,
  `test_hotfix5_summary_cover_window_round1025.py`,
  `test_summary_two_call_round1022.py` — реальные Δ 2/7/3 строк) — артефакт
  CRLF-переката (см. Non-blocking).

> **Независимость:** ревью выполнено новым Reviewer-сеансом; реализацию не
> писали, код не правили. Мутационная проверка §90 и browser-проверка выполнялись
> в отдельной temp-копии/на stub-backend, реальное дерево не изменялось.

---

## Краткий итог (для @Orchestrator)

Вердикт — **Needs Fixes**. Публикационный контур, §90-паритет, kill-switch,
F8/каталог, capability resolver и UI — подтверждены независимо. Однако
**несколько заявленных-as-done требований spec/DoD не реализованы end-to-end**
(durable job, stale-revision preview, CoverBrief/dynamic brief в компиляторе,
deep-link с фокусом/возвратом). Детали — в Blocking findings.

---

## Checks performed (команда → факт → вывод)

| # | Проверка | Команда/факт | Вывод |
|---|---|---|---|
| 1 | **§90 Standard Base Cover regression (КРИТИЧНО)** | `tests/test_extra_cover_style_runtime.py::test_no_style_base_cover_rich_regression` зелёный; **мутационная проверка в temp-копии**: замена `media = [build_cover_media(cover_for_publish)]` → `media = []` → тест **FAIL** (`rec.media_paths == [] != [base]`) | **PASS** — тест реально ловит отклонение no-style happy-path. Оговорка: тест изолирует publish-контур (мок `_maybe_apply_cover_style`), не прогоняет реальный hook через весь `_run`. |
| 2 | **T-4145 degraded «Rich без обложки» аддитивен** | `_degrade_without_cover` + `_publish_rich_without_cover` (`services/summary_generator.py`); при `COVER_RICH_DEGRADED_ENABLED`/`COVER_STYLES_ENABLED` OFF — plain (parity). 13 legacy cover-failure тестов переведены в parity-режим (`rich_degraded_enabled=False`) + 1 в новом runtime-тесте | **PASS** — ассерты **не ослаблены**: добавлена только строка `monkeypatch.setattr(...)`; прежние assert'ы сохранены; обе ветки покрыты (runtime-тест проверяет degraded `media=[]`, legacy — plain). |
| 3 | **Style Registry** | AST-гейт `test_no_hardcoded_name_branch_in_module` (§6/§98); PG 5 таблиц + 5 индексов идемпотентны (`services/pg_db.py`, `CREATE TABLE IF NOT EXISTS`); seed идемпотентен (короткое замыкание), фактические имена (`style_example_02.jpg`); asset_id `cas_<sha256[:32]>`; counter retry-reuse + `UNIQUE(profile_id, issue_number)`; revision snapshot; Test Style не трогает counter | **PASS (с оговорками)** — SQL корректен по чтению; однако DB-тесты используют **фейковый in-memory pool** (`_FakePg`), реальная PG-семантика `ON CONFLICT`/`UNIQUE` не прогонялась. Provenance пишется, но asset-id'ы `None` (L-EXTRA-1). |
| 4 | **Capability resolver + Prompt Compiler** | precedence override→discovery→conservative (`resolve_capabilities`); `rg -n "800"` — только в docstring (в код не перенесён); TTL `COVER_STYLE_CAPABILITY_TTL_SECONDS`; units chars/tokens/bytes/unknown; P0/P2 (P0/issue не режутся) — `test_p0_preserved_p2_dropped_first` | **PASS** для resolver/priority; **FAIL** по CoverBrief/dynamic brief (M-EXTRA-2). |
| 5 | **Style-edit: слот, секреты, normalizer, gate §38** | `resolve_style_slot` (base vs style `models.image_style_*`); `check_edit_allowed` блокирует только `image_edit=no`; `edit_image` при `image_edit=no` → `edit_unsupported`, API не вызывается; логов с ключом/полным prompt нет (R17-скан) | **PASS** |
| 6 | **Fail-soft ladder** | runtime-тесты §78–§82; `classify_cover_result`; `_publish_rich_without_cover` сохраняет `<h1>`/абзацы; style failure не перегенерирует base (`rec.image_calls == 1`) | **PASS** |
| 7 | **Durable jobs / recovery / safe-log / heartbeat / cost** | `start_cover_job`/`finish_cover_job`/`save_cover_state`/`CoverJobState` существуют, но **не вызываются из прод-пути** (`_maybe_apply_cover_style` → `run_style_job` без `db`/`job_id`/`state`); safe-log whitelist — PASS; heartbeat `_run_with_heartbeat` — PASS; `record_cost`/`build_timeline` — нет прод-вызовов | **FAIL** (§42/§43 не врезаны) → **H-EXTRA-1**; L-EXTRA-2. |
| 8 | **F8 / каталог / kill-switch** | `tools/gen_param_registry_round1025.py --check` = **CHECK OK** (реестр 488); recount: REGISTRY **488**, categorized **463**, GROUPS **105**, `_TAB_BY_GROUP` **103**, `TAB_RULES` **21**, delta **77**; `dataclasses.fields(Settings)` = **426**; +4 ParamSpec; kill-switch env-only ClassVar default ON; OFF-паритет (`test_kill_switch_off_parity`) | **PASS** — расхождение «Settings 427» = иная метрика (`settings_field_coverage` возвращает (missing,extra), не счётчик); санкция по существу выполнена (см. Non-blocking NB-2). |
| 9 | **Полный pytest / JS / новые наборы** | pytest: **10203 collected, 10201 passed, 2 failed** (257 с) — оба падения **предсуществующие/чужие**: `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff` и `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` падают из-за `web/api/analytics.py`, `web/static/polygon-background.js`, `web/static/telegram-init.js` в diff от старых тегов `pre-round1026-a1`/`e8646af` (проверено `git diff --name-only`); JS: все **52/52** `tests/js/*.js` pass; новые EXTRA-наборы: registry 32 + pipeline 15 + capabilities/compiler 24 + jobs 34 + runtime 7 + api 17 + ui 11 = **140 passed** | **PASS** |
| 10 | **Browser (REQUIRED, §76)** | независимо (Playwright MCP, static server + route-stub `/api/**`): вкладка «Стили обложки», список с seeded `[Пример]` + «Без дополнительного стиля», CRUD/копия, редактор §56, budget §57, reference thumbnail (реальная `medved_press.png`, naturalWidth 1030), Before/After, capability-панель §37 (8 строк), «Настроить подключения →», Test Style; desktop 1280×800 и mobile 390×844 (без горизонтального overflow); console **0 errors**; kill-switch OFF → баннер + disabled select/new. **DC-4/T-4173:** visual §85/§86 (замена чужого логотипа / отсутствие дубля PERMsoc) локально невоспроизводим без edit-capable провайдера — `Unavailable` | **PASS** для структурных/UI-критериев; **Unavailable** для visual §85/§86. |
| 11 | **Staging-перечень** | см. раздел ниже | — |

---

## Requirement/evidence coverage (цепочка требование → spec → tasks → код → тест)

- **REQ-EXTRA-01 (§90) — Standard Base Cover:** подтверждено (Check 1). §90-регресс реален.
- **REQ-EXTRA-02/03 (§3/§23/§54) — style post-processor/normalizer/modes:** `pipeline_mode`, `uses_style_stage`, `normalizer_instruction`, `SEEDED_INSTRUCTION` — подтверждено.
- **REQ-EXTRA-04 (§4/§49–§52) — ladder:** подтверждено (Check 6).
- **REQ-EXTRA-05/06 (§5/§6/§59/§8/§12/§64) — Registry/seed/assets:** подтверждено (Check 3).
- **REQ-EXTRA-07 (§13–§18/§38/§53/§71) — Capability Resolver:** подтверждено (Check 4).
- **REQ-EXTRA-08 (§19–§21/§57/§58) — Compiler + CoverBrief:** **частично** — resolver/priority/P0 работают, но CoverBrief и dynamic scene/base-style-prompt в компилятор не подключены → **M-EXTRA-2**.
- **REQ-EXTRA-09 (§31–§36/§72–§74) — Connections/slots/secrets:** слоты/секреты подтверждены; **§35 deep-link-фокус/возврат — не реализован** → **M-EXTRA-3**.
- **REQ-EXTRA-10 (§25–§30/§60/§66) — counters/revision/provenance:** counter/reuse/concurrency/snapshot/Test-без-counter подтверждены; provenance `base/final_asset_id` всегда `None` → **L-EXTRA-1**.
- **REQ-EXTRA-11 (§39–§48/§68–§70/§91–§92) — durable jobs:** **продуктовая интеграция отсутствует** → **H-EXTRA-1**; §47/§92 не врезаны → **L-EXTRA-2**.
- **REQ-EXTRA-12 (§10/§56/§65–§67/§75/§76) — UI:** редактор/Test Style/RU/budget/mobile — подтверждены; **§10 stale-revision preview и «сохранить результат как preview» отсутствуют** → **M-EXTRA-1**; «Replace» референса — L-EXTRA-4.
- **REQ-EXTRA-13 (§94/§95) — kill-switch/migration/rollback:** подтверждено (Check 8).

### DoD §99 (35) — не покрыто полностью
- п.25 «Durable job state переживает restart» — **не выполнено** (H-EXTRA-1).
- п.30 «Style preview/test работает независимо от Summary» — выполнено (Test Style = только edit-job).
- п.31 «Preview test не расходует production counter» — выполнено.
- п.32 «Before/After UX работает» — выполнено; stale-revision-часть §10 — **нет** (M-EXTRA-1).
- Остальные пункты — покрыты (Check 1–9).

---

## Focused audit coverage (файлы, интеграционные края, краевые случаи)

**Полностью прочитаны:** `services/cover_style_jobs.py` (813), `cover_style_edit.py`
(394), `cover_style_registry.py` (558), `cover_style_pipeline.py` (238),
`cover_style_assets.py` (119), `image_capabilities.py` (301),
`image_prompt_compiler.py` (207), `web/api/cover_styles.py` (547),
изменённый `services/summary_generator.py`, PG-DDL (`pg_db.py` diff),
`param_catalog.py` diff, `config/settings.py` (EXTRA-поля), `web/app.js`
(блок Cover Styles 6749–7068), `web/index.html` (436–668).

**Края проверены:** `_publish_rich_document` (все 4 ветки ladder + `finally`),
`_maybe_apply_cover_style` (fail-open), `resolve_issue_number` (retry-reuse →
уникальность), `duplicate_profile` (копия references), dangling-guard
(`references_using_asset` + 409/confirm), `edit_image` (sync/async/timeout/url),
`_decode_upload`, `/cover/assets/{id}` (авторизация — фронт грузит через
`fetch` с заголовком `X-Telegram-Init-Data` и blob-URL, а не `<img src>`, поэтому
401 вне Telegram не ломает thumbnail — проверено).

**R17:** секретов в ответах API нет (`_public_profile`, `connection_status`
отдаёт только `api_key_set: bool`); логи cover-стадий — whitelist (`SAFE_LOG_FIELDS`,
`prompt_hash`), полный prompt/ключ/сырьё не логируются; `test_no_secrets_in_event` —
зелёный. `current_task.md`/`extra_images/*` не изменялись (R18 подтверждён хэшами).

**Δ DDL:** SQLite `user_version` не поднимается (DDL без PRAGMA/user_version;
`migration_steps()` без v20 — `v20` остаётся за `mca-04b`). PG `DDL_STATEMENTS`
+5 таблиц +5 индексов, идемпотентно.

---

## Counterexamples checked (попытки сломать/опровергнуть)

1. **§90 happy-path (мутация в temp-копии):** удаление cover-медиа → §90-тест
   падает. Тест не «декоративный».
2. **Style failure → вторая генерация base?** runtime-тест: `image_calls == 1`,
   `media_paths == [base]` — повторной генерации нет.
3. **Base failure → rich-without-cover:** `media=[]`, `cover_id=None`, `<img` нет,
   `<h1>`/абзацы сохранены, plain не понадобился.
4. **Degraded OFF / kill-switch OFF:** оба → plain (baseline parity), rich не отправлен.
5. **Capability override > discovery:** `test_override_precedes_discovery` — override побеждает.
6. **`image_edit=no`:** API-вызов не выполняется (`edit_unsupported`), base публикуется.
7. **Counter retry-reuse и конкурентность:** `44→44`; два разных run → разные номера
   (проверено на fake-pool; SQL корректен при PG READ COMMITTED).
8. **Test Style:** issue_number `None`, counter не вызывается, mode=preview.
9. **Upload не-PNG/JPEG/WebP:** `store_file_bytes` → `None` → HTTP 422.
10. **Dangling asset:** 409 без `confirm`, удаление link только с `confirm=true`.
11. **Delay/секрет-утечка:** ответы cover-API не содержат `api_key` (только bool).

---

## Blocking findings

### [H-EXTRA-1] High — durable cover-job (§42/§43, DoD 25, SC-30) объявлен, но не врезан в прод-путь
- **Где:** `services/summary_generator.py:1482` (`_maybe_apply_cover_style` →
  `csj.run_style_job(...)` **без** `db`/`job_id`/`state`); определения
  `services/cover_style_jobs.py:389` (`start_cover_job`), `:412`
  (`finish_cover_job`), `:432` (`save_cover_state`). `rg` по `services/`+`web/`:
  `start_cover_job`/`finish_cover_job`/`save_cover_state`/`CoverJobState` **имеют
  единственных вызывающих — тесты**; `summary_generator.py`/`handlers/*` вообще
  не используют `TaskSupervisor`/`TaskJobStore`/`mca_trace`.
- **Требование:** REQ-EXTRA-11/§3.11/§42/§43: «REUSE durable job … provider
  `task_id` сохраняется …, после restart polling продолжается … не создавать
  новый платный task». Tasks T-4134/T-4135 помечены `[x]`.
- **Наблюдение/evidence:** durable-строка `task_jobs` при реальной публикации
  **не создаётся**; `provider_task_id` нигде не персистится (в `run_style_job`
  `state=None`); рестарт посреди долгой style-стадии теряет состояние и не может
  возобновить polling; при async-провайдере это риск повторного платного task.
- **Impact:** заявленное свойство отказоустойчивости отсутствует; DoD 25 не выполнен.
- **Точная коррекция:** в `_maybe_apply_cover_style` получить `db` (SQLite
  `DatabaseService`/`TaskJobStore`) и `pg`, создать job `start_cover_job`,
  передать `job_id`/`state` в `run_style_job`, сохранять
  `save_cover_state(...)` при смене стадии и `finish_cover_job(...)` по исходу;
  добавить интеграционный тест «restart resume: повторный заход переиспользует
  `provider_task_id`, нового submit нет».
- **Метод верификации:** интеграционный тест на реальном/fake `db` с проверкой
  enqueue/checkpoint/finish и reuse task_id.

### [M-EXTRA-1] Medium (requirement-blocking) — §10/SC-24 stale-revision preview и «сохранить результат как preview» отсутствуют
- **Где:** `web/index.html:576–620` (блок «Как работает стиль» — нет
  `Пример создан для предыдущей версии стиля` / `Обновить пример`);
  `web/api/cover_styles.py:487–547` (`/cover/test-style` возвращает `asset_id`,
  но **не** записывает `cover_style_profiles.preview_after_asset_id`/`preview_revision`);
  `services/cover_style_registry.py` пишет `preview_revision`, но нигде не
  сравнивает его с `revision`.
- **Требование:** §10/T-4156/SC-24: «После успешного теста … можно сохранить
  результат как preview текущего стиля. Если preview был создан для старой
  revision … показывать … и кнопку `Обновить пример`». Tasks T-4156 `[x]`.
- **Наблюдение/evidence:** `rg` по `web/`+`services/` не находит ни строки
  «предыдущей версии»/«Обновить пример», ни записи preview-поля из Test Style.
- **Impact:** preview не помечается устаревшим; пользователь не видит, что
  Before/After соответствует старой версии; сохранение preview из теста недоступно.
- **Точная коррекция:** при Test-Style success записывать
  `preview_after_asset_id`+`preview_revision=revision`; в `_public_profile`
  отдавать флаг `preview_stale` (`preview_revision is not None and
  preview_revision != revision`); в UI показать предупреждение + `Обновить пример`.
- **Метод верификации:** unit-тест на `preview_stale`-флаг + UI-маркер/browser-проверка.

### [M-EXTRA-2] Medium (requirement-blocking) — §19/§21 CoverBrief и dynamic brief/base-style-prompt не подключены к компилятору
- **Где:** `services/cover_style_jobs.py:492–515` (`compile_style_prompt`
  собирает только P0-runtime-invariants, P1 `instruction`, P2 `references`);
  `services/image_prompt_compiler.py:43` (`CoverBrief`) — используется только в тестах.
- **Требование:** REQ-EXTRA-08/§3.8/§19/§21: компоненты `base style prompt`,
  `dynamic cover brief`; CoverBrief — компактный сюжет вместо полной prose.
- **Наблюдение/evidence:** `compile_prompt(..., budget_component=...)` принимает
  сюжетную часть, но ни один прод-вызов не передаёт `CoverBrief.render()`/сцену;
  style-edit prompt не содержит сюжет base-обложки.
- **Impact:** §19/§21 покрыты классами/тестами, но не end-to-end; prompt style-edit
  беднее задуманного.
- **Точная коррекция:** строить `CoverBrief` из данных base-стадии и передавать
  `budget_component=brief.render(max_chars=...)` в `compile_style_prompt`;
  базовый style prompt — из существующего `prompts.summary_cover_style`.
- **Метод верификации:** тест, что в итоговом prompt присутствует сцена/бриф при
  известном лимите и что P0 сохраняется при давлении.

### [M-EXTRA-3] Medium (requirement-blocking) — §35 deep-link без фокуса и без сохранения контекста редактора
- **Где:** `web/app.js:7027–7030` (`openCoverConnections`: `location.hash='#/ai/llm'` + toast).
- **Требование:** §3.9/§35/T-4118: deep-link на `ИИ → Подключения` **с фокусом/подсветкой
  `Обработка стилей обложки`**; «после возврата Style Editor должен сохранить контекст».
- **Наблюдение/evidence:** фокус/подсветка не реализованы (переход на общий экран
  конфигурации + toast); отдельного механизма сохранения/восстановления состояния
  редактора нет.
- **Impact:** требование навигации выполнено частично.
- **Точная коррекция:** передавать hash/state с якорем группы `models_images`
  («Обработка стилей обложки») и восстанавливать открытый Style Editor при возврате.
- **Метод верификации:** browser-проверка: переход → фокус на нужной группе →
  возврат → редактор остался открытым на том же стиле.

---

## Non-blocking debt (bounded, зарегистрировано)

- **L-EXTRA-1 (Low, §30):** `services/cover_style_jobs.py:762–763` —
  `base_asset_id`/`final_asset_id` всегда `None`; provenance не идентифицирует
  итоговую картинку. Bounded (cover-байты и раньше транзиентны).
- **L-EXTRA-2 (Low, §47/§92):** `record_cost` (`:307`) и `build_timeline` (`:230`)
  не имеют прод-вызовов; preview-cost-маркировка §67/§92 не применяется в реальном
  Test Style. `EditResult.meta` не парсит cost.
- **L-EXTRA-3 (Low, §6/§12):** `web/api/cover_styles.py:320–331` — нет проверки
  размера upload (size cap), только тип.
- **L-EXTRA-4 (Low, §12):** UI референсов даёт «Добавить»/«Убрать», но **не**
  «Replace» (замена) — требование §12.
- **L-EXTRA-5 (Low, §75):** `web/index.html:613` — длительность помечена
  «Затемнение: N мс» (бессмысленная подпись; должно быть «Время обработки»).
- **NB-1 (Low, hygiene):** CRLF-перекат увеличил визуальный diff: `web/app.py`
  (реально +4 строки, показано 349/345), `tests/test_summary_cover_round1023.py`
  (2), `tests/test_hotfix5_summary_cover_window_round1025.py` (7),
  `tests/test_summary_two_call_round1022.py` (3). Проверено
  `git diff --ignore-cr-at-eol`; содержимое не пострадало (тесты зелёные), но
  staging требует аккуратности.
- **NB-2 (Low, doc-metric):** `evidence.md` заявляет «Settings 427», но
  `dataclasses.fields(Settings)` = **426**; `settings_field_coverage()` возвращает
  `(missing, extra)`, а не счётчик. F8-фикстура `counts` не содержит Settings.
  На санкцию по существу не влияет (REGISTRY/categorized/GROUPS/TAB — точны).
- **NB-3 (Low, evidence-hygiene):** `evidence.md` Pass 1 в одном месте пишет
  «registry 48 тестов», в другом — «32»; фактически **32** (`pytest -q`).
- **NB-4 (Low, test-fidelity):** DB-тесты Registry/asset используют in-memory
  `_FakePg`; реальная PG-семантика (`ON CONFLICT`, partial unique index,
  `UPDATE … RETURNING`) не прогонялась. `test_sqlite_version_not_bumped` проверяет
  строку DDL, а не `PRAGMA user_version`.

---

## Unavailable checks

- **§85/§86 visual (T-4173, DC-4):** фактическая визуальная нормализация
  (замена чужого publisher-логотипа, отсутствие дубля PERMsoc/badge) требует
  **edit-capable провайдера** (текущий code-default Pollinations/flux edit не
  умеет). Семантика ensure/replace зафиксирована в `SEEDED_INSTRUCTION` и
  P0-инвариантах; фактическая проверка — только на прод-приёмке §100. Обработано
  **честно** (T-4173 `[ ]` с пояснением), но означает: SC-19/SC-20 не подтверждены
  до деплоя.
- **Живой прод-путь style success** (реальный edit-провайдер в Connections) —
  недоступен до включения владельцем; base-путь безопасен без него (§38).
- **Реальный PG** (миграция/идемпотентность/конкурентность на боевой СУБД) —
  вне сессии; unit/integration на fake-pool + чтение DDL.
- **Browser §85/§86 на реальном backend** — только stub-backend (независимо
  воспроизведён, см. Check 10).

---

## Staging-перечень для @DevOps (смешанные/новые файлы)

**Новые файлы (untracked, включать в коммит релиза):**
`services/cover_style_assets.py`, `services/cover_style_edit.py`,
`services/cover_style_jobs.py`, `services/cover_style_pipeline.py`,
`services/cover_style_registry.py`, `services/image_capabilities.py`,
`services/image_prompt_compiler.py`, `web/api/cover_styles.py`,
`tools/_extra_reissue_f8.py`,
`tests/test_extra_cover_style_registry.py`, `tests/test_extra_cover_style_pipeline.py`,
`tests/test_extra_image_capabilities_compiler.py`, `tests/test_extra_cover_style_jobs.py`,
`tests/test_extra_cover_style_runtime.py`, `tests/test_extra_cover_styles_api.py`,
`tests/test_extra_cover_styles_ui.py`, `tests/js/round1029_extra_cover_styles_test.js`,
`plans/features/extra-cover-style-pipeline/**` (spec/tasks/evidence/deployment/adr/review),
`plans/reports/extra_cover_styles_desktop.png`, `plans/reports/extra_cover_styles_mobile.png`.

**Изменённые tracked-файлы (смешанные — отделять чужой WIP):**
- Продукт: `services/summary_generator.py`, `services/pg_db.py`,
  `services/param_catalog.py`, `services/summary_prompts.py`,
  `services/mca_events.py`, `config/settings.py`, `web/app.py`,
  `web/app.js`, `web/index.html`, `README.md`.
- F8/доки: `plans/docs/param-registry-round1025.tsv`,
  `plans/docs/param-registry-round1025.meta.md`,
  `plans/docs/screen-map-round1025.md`,
  `tests/fixtures/round1025/f8_baseline.json`,
  `tests/fixtures/round1025/catalog_baseline.json`.
- Тесты (version/parity-пины): все `tests/test_*.py` и `tests/js/round1025_*` из
  `git status` (78 tracked-файлов; см. manifest в Working-Tree-Hash).

**Вне скоупа (НЕ коммитить как EXTRA):** `plans/metrics.md`,
`plans/workflow_state.md`, `plans/features/mca-04b-dossier-rebuild/`,
`node_modules/`, `package.json`, `package-lock.json`, `.playwright-mcp/`,
`extra_images/` (владельческие read-only).

**Деплой-заметки:** bump `2.58.39`; SQLite `user_version=19` (Δ=0); PG +5 таблиц
идемпотентно; kill-switch'и env-only default ON (`COVER_STYLES_ENABLED`,
`COVER_RICH_DEGRADED_ENABLED`); откат hot `COVER_STYLES_ENABLED=false` /
`COVER_RICH_DEGRADED_ENABLED=false`, cold `git revert`.

---

## Вердикт для @Orchestrator

**Status: Needs Fixes.** Публикационный контур (§90, T-4145 ladder, kill-switch),
F8/каталог, capability resolver и UI структурно подтверждены независимо
(полный pytest 10201/2 — оба fail чужие; JS 52/52; F8 `--check` OK; browser PASS
с 0 console errors). Блокируют: **H-EXTRA-1** (durable job §42/§43 не врезан —
DoD 25 не выполнен) и requirement-blocking Medium **M-EXTRA-1/2/3** (§10
stale-revision preview, §19/§21 CoverBrief/dynamic brief, §35 deep-link focus/return).
После исправлений — re-check исходных находок, §90-регресса, ladder и WTH.

**MEMORY_DELTA (для Orchestrator, не записывать мной):**
- Фича `extra-cover-style-pipeline` (R3, HEAD `bbdee1c`, WTH
  `389993d2f5158b85584a255b00065ddd31894a8db428c129a2c548d6ad721878`) —
  вердикт **Needs Fixes** (H-EXTRA-1 durable job не интегрирован; M-EXTRA-1/2/3).
- Паттерн этой волны: заявленные `[x]` задачи (T-4134/4135/4156/4118) закрыты
  классами/тестами, но не врезаны в прод-путь — при приёмке проверять интеграцию,
  а не наличие helper'ов.

---

## H-EXTRA-1 (round2) — durable job врезана в реальный публикационный путь?

- **Статус: PASS.** Round-1 блокер H-EXTRA-1 закрыт: durable cover-джоба
  создаётся/персистится/завершается **в реальном прод-пути**, не только в тестах.
- **Ревьюер:** независимый повторный проход; код не правился. Дерево — рабочее
  (коммитов EXTRA нет).

### Команда и счётчик (обязательный прогон)

```
.venv\Scripts\python.exe -m pytest tests -k "DurableRestart or ProductionWiring" -q
→ 4 passed, 10208 deselected, 1 warning in 6.06s
```

Дополнительно весь файл: `.venv\Scripts\python.exe -m pytest tests/test_extra_cover_style_jobs.py -q`
→ **39 passed in 2.87s** (без регрессий).

> Прим.: `python` в PATH резолвится в WindowsApps-заглушку; использован интерпретатор проекта
> `.venv\Scripts\python.exe`.

### Доказательство: durable job в прод-пути (не тест-онли)

| Звено | Факт | file:line |
|---|---|---|
| Реальный вызов из публикации | `_publish_rich_document` → `_maybe_apply_cover_style(...)` | `services/summary_generator.py:1333` |
| Единственный **не-тестовый** вызывающий durable-API | `begin_cover_job` / `run_style_job(db,job_id,state)` / `finish_cover_job` | `services/summary_generator.py:1491`, `:1496`, `:1505` |
| `db` берётся из runtime (не заглушка) | `db = getattr(self.memory, "db", None)` | `services/summary_generator.py:1490` |
| `memory` в проде = real `MemoryManager(db)`; `MemoryManager.self.db = db` | `memory = MemoryManager(db, …)`; `self.db = db` | `bot.py:390`; `services/summary_memory.py:1244-1245` |
| `db` в проде = real `DatabaseService(settings.DB_PATH)` | `db = DatabaseService(settings.DB_PATH)` | `bot.py:280` |
| Единственная очередь — `task_jobs` (v14/v19); второй очереди **нет** | `CREATE TABLE … task_jobs`; PG `cover_style_*` — только registry (profiles/references/assets/issue_assignments/provenance), очереди нет | `services/database.py:158`; `services/pg_db.py:388-455` |
| `provider_task_id` персистится немедленно на async-submit | `state.provider_task_id = result.task_id` → `state.mark(STYLE_RUNNING, …)` → `_persist_state` | `services/cover_style_jobs.py:815-820` |
| Персист пишется в durable-строку | `save_checkpoint` → `task_jobs.payload = {"cursor": state_json, "processed": n}` | `services/task_supervisor.py:615-645` |

`rg` по `services/ web/ handlers/ tools/` (без тестов): durable-API `begin/start/finish/
save/load_cover_state`, `CoverJobState`, `run_style_job` вызываются из **одного
продуктового модуля** (`services/summary_generator.py`) + определений в
`services/cover_style_jobs.py`. Прежний round-1 факт «единственные вызывающие — тесты»
более не выполняется.

### Доказательство DoD-25 — resume из `task_jobs`

- **Тест:** `tests/test_extra_cover_style_jobs.py:587` `TestDurableRestart::
  test_restart_resumes_provider_task_from_task_jobs`.
- **Механика resume:** при `state is None` `run_style_job` читает durable-состояние
  `load_cover_state(db, job_id)` (`services/cover_style_jobs.py:695-696`);
  `load_cover_state` → `TaskJobStore.get_checkpoint` → `payload["cursor"]` →
  `CoverJobState.from_json` (`services/cover_style_jobs.py:454-469`).
- **Отсутствие нового платного task:** восстановленный `provider_task_id`
  передаётся как `existing_task_id` в edit-call (`services/cover_style_jobs.py:792`);
  `edit_image` при `existing_task_id` **не делает новый submit**, а только poll
  (`services/cover_style_edit.py:318-320`).
- **Ассерты теста:** `seen["existing"] == "prov-1"` (resume), `meta2["applied"] is True`,
  `store.active() == [jid]` (дублей джоб нет) — прошли.
- **Итог:** DoD-25 (§43) подтверждён на durable-строке `task_jobs`; §90/round-1
  находка по product-integration снята.

### Findings (round2)

- **L-EXTRA-6 (Low, §42/§43, hygiene):** `TaskJobStore.save_checkpoint` пишет чекпойнт
  в ту же колонку `payload`, где `enqueue` хранит бизнес-payload
  (`chat_id/correlation_id/style_id/mode`) — первый `_persist_state` **перезаписывает**
  исходный payload (`services/task_supervisor.py:633-637`;
  `services/cover_style_jobs.py:445-447`). На resume это безопасно (читается «cursor»,
  а `enqueue` на существующей строке — `INSERT OR IGNORE`), но исходные атрибуты джобы
  после первой стадии не сохраняются. Ни один потребитель их сейчас не читает →
  не блокирует.
- **L-EXTRA-7 (Low, §43, scope-observation):** det. ключ `cover_job_key` строится из
  `correlation_id = usage_events.new_correlation_id()` = UUID4 на каждый запуск
  (`services/summary_generator.py:441`; `services/usage_events.py:62-64`). Поэтому
  end-to-end resume **через реальный рестарт процесса** требует, чтобы планировщик/повтор
  вошли с тем же `summary_run_id`; если рестарт порождает новый run-id — старт будет
  новым `cov_…`. Unit-уровень resume из `task_jobs` (DoD-25) подтверждён; кросс-рестарт
  resume по стабильному run-id в этой сессии **не проверялся**. Не блокер для H-EXTRA-1
  (критерий — wiring + resume из `task_jobs`), рекомендован re-check при прод-приёмке.

### Вердикт round2 по H-EXTRA-1

**PASS.** Durable job врезана в реальный публикационный путь (§42/§43): `db`/`job_id`/
`state` передаются в `run_style_job`, джоба создаётся `begin_cover_job`, персистится на
смене стадии и закрывается `finish_cover_job`; единственная очередь — `task_jobs`;
`provider_task_id` персистится и восстанавливается. Прогон
`pytest -k "DurableRestart or ProductionWiring"` → **4 passed** (весь файл 39 passed).
Остаются не-блокирующие L-EXTRA-6/L-EXTRA-7.

---

## M-EXTRA-1/2/3 (round2)

- **Роль:** @Reviewer (только проверка). Код не правился, коммит не делался.
  Дерево — рабочее (untracked EXTRA-файлы присутствуют); проверялись текущие
  файлы на диске.
- **Примечание:** `python` в PATH — WindowsApps-заглушка; все прогоны через
  `.venv\Scripts\python.exe`.

### Команды и счётчики (обязательный прогон M-EXTRA-1)

```
.venv\Scripts\python.exe -m pytest tests -k "PreviewStale" -q
→ 2 passed, 10210 deselected, 1 warning in 6.40s

.venv\Scripts\python.exe -m pytest tests -k "DynamicBrief or CoverBrief" -q
→ 4 passed, 10208 deselected, 1 warning in 5.99s

.venv\Scripts\python.exe -m pytest tests/test_extra_cover_style_jobs.py \
    tests/test_extra_image_capabilities_compiler.py \
    tests/test_extra_cover_styles_api.py tests/test_extra_cover_styles_ui.py -q
→ 95 passed, 1 warning in 3.56s

node tests/js/round1029_extra_cover_styles_test.js
→ EXTRA-COVER-STYLES-UI-OK
```

### M-EXTRA-1 — §10/SC-24 stale-revision preview: **PASS**

`registry.set_preview` пишет preview-поля **без** инкремента `revision`
(`UPDATE … preview_revision = $N`, revision не трогается) —
`services/cover_style_registry.py:291-324`. `preview_is_stale` сравнивает
`preview_revision` с текущей `revision` и корректно возвращает `False` при
`preview_revision is None`/`preview_after_asset_id is None` —
`services/cover_style_registry.py:327-337`.

| Звено | Факт | file:line |
|---|---|---|
| Test Style сохраняет preview текущей revision | `revision=profile.get("revision")` → `set_preview(...)` | `web/api/cover_styles.py:581-585` |
| Флаг в публичном профиле | `"preview_stale": registry.preview_is_stale(profile)` | `web/api/cover_styles.py:80` |
| UI-баннер | «Пример создан для предыдущей версии стиля.» + `data-cover-preview-stale` | `web/index.html:616-619` |
| Кнопка «Обновить пример» | `data-cover-preview-update` → `coverStyleRefreshExample()` | `web/index.html:620-623`; `web/app.js:7116-7121` |
| Проброс флага в state | `preview_stale: !!s.preview_stale`; sync из detail | `web/app.js:6835`, `:6875` |
| Тест | `TestPreviewStale::test_public_profile_stale_flags` / `test_test_style_saves_preview_revision` | `tests/test_extra_cover_styles_api.py:387-427` |

Требование §10/T-4156/SC-24 закрыто: preview сохраняется при успешном Test Style,
помечается устаревшим при расхождении revision, UI показывает баннер и кнопку
обновления. **PASS.**

### M-EXTRA-2 — §19/§21 CoverBrief + dynamic brief/base-style-prompt: **PASS**

Компилятор: `brief_from_text` строит `CoverBrief(scene=…)` детерминированно, без
LLM/сети (`services/image_prompt_compiler.py:102-116`); `compile_style_prompt`
принимает `brief` и передаёт `brief.render()` как `budget_component`
(`services/cover_style_jobs.py:562-564`, `:593-595`).

Живой путь (не только тесты):

| Звено | Факт | file:line |
|---|---|---|
| Реальный вызов | `_publish_rich_document` → `_maybe_apply_cover_style(... cover_prompt=cover_prompt, base_style=style)` | `services/summary_generator.py:1333-1335` |
| Передача base-сцены и base style | `summary_text=cover_prompt`, `base_style_prompt=base_style` | `services/summary_generator.py:1500-1501` |
| Построение brief | `brief = compiler.brief_from_text(summary_text)` | `services/cover_style_jobs.py:769` |
| Прогон в prompt | `compile_style_prompt(..., base_style_prompt=…, brief=brief)` | `services/cover_style_jobs.py:771-773` |
| Источник base style prompt | `style = await self._resolve_cover_style_text(chat_id)` ← `prompts.summary_cover_style` | `services/summary_generator.py:1255`, `:1985-2006` |
| Тест | `TestDynamicBrief::test_run_style_job_prompt_contains_brief_and_base_style` | `tests/test_extra_cover_style_jobs.py:706-730` |

Brief и base style prompt реально попадают в итоговый Style Edit prompt в прод-пути
(единственный не-тестовый вызывающий `_maybe_apply_cover_style`); P0-инварианты
сохраняются. **PASS.**

- **Наблюдение (Low, naming):** параметр `summary_text` в живом пути получает
  `cover_prompt` — visual-промпт base-обложки (Редактор Stage-1 либо
  детерминированный фолбэк из текста саммари, `services/summary_generator.py:1883-1955`),
  а **не** полную Summary-prose. Это соответствует §21 («компактный сюжет»), т.к.
  `cover_prompt` сам выведен из саммари, но имя параметра вводит в заблуждение.

### M-EXTRA-3 — §35 deep-link focus + возврат контекста редактора: **PASS**

`openCoverConnections` сохраняет контекст (`_returnProfileId`), ставит целевую
группу `models_images`, переходит на `#/ai/llm` и через 80 мс применяет фокус
(`web/app.js:7084-7095`). `_applyConfigFocus` находит `[data-config-group="…"]`,
скроллит (`scrollIntoView`) и подсвечивает outline (`web/app.js:7096-7114`).
`data-config-group` рендерится в шаблоне (`web/index.html:1934`), группа
`models_images` определена в каталоге (`services/param_catalog.py:186`).
Возврат контекста: при перезагрузке списка `loadCoverStyles` повторно открывает
редактор (`web/app.js:6772-6781`); поле объявлено (`web/app.js:1585`).

| Звено | Факт | file:line |
|---|---|---|
| Кнопка deep-link в UI | `@click="openCoverConnections()"` | `web/index.html:665` |
| Фокус-группа | `this.configFocusGroup = 'models_images'` | `web/app.js:7090` |
| Подсветка/скролл | `document.querySelector('[data-config-group="…"]')` + outline | `web/app.js:7102-7114` |
| Анкор группы | `:data-config-group="grp.id"` | `web/index.html:1934` |
| ID группы | `GroupSpec("models_images", …)` | `services/param_catalog.py:186` |
| Тест UI | маркеры `data-config-group`, `configFocusGroup`, `models_images` | `tests/test_extra_cover_styles_ui.py:35-37`, `:68-74` |
| Тест JS | `openCoverConnections` → `configFocusGroup === 'models_images'`, `_returnProfileId` | `tests/js/round1029_extra_cover_styles_test.js:131-143` |

- **Наблюдение (Low, granularity):** группа `models_images` озаглавлена
  «Генерация изображений» (`services/param_catalog.py:186`); поля слота
  «Обработка стилей обложки» (`IMAGE_STYLE_BASE_URL`/`IMAGE_STYLE_MODEL`) лежат
  внутри неё (`services/param_catalog.py:852-857`). Отдельного якоря/подсветки
  именно под «Обработку стилей обложки» нет — фокус на всю группу. Toast при
  этом называет «Обработка стилей обложки»; для §35 приемлемо.
- **Наблюдение (Low, SPA):** `_returnProfileId` — in-memory; при жёстком reload
  страницы (не SPA-навигации) контекст редактора не восстановится. В рамках
  SPA-перехода требование выполняется (state `st.current` не сбрасывается).

### Findings (round2, non-blocking)

- **L-EXTRA-8 (Low, §29/§63, edge):** `duplicate_profile` копирует
  `preview_revision` исходника, тогда как `upsert_profile` вставляет новую строку
  с `revision = 1` (`services/cover_style_registry.py:229`, `:347-354`). Если у
  оригинала `preview_revision != 1`, копия сразу считается stale
  (`preview_is_stale` True) с чужим preview. Не блокирует (preview — визуальная
  подсказка), но при дублировании ожидалось бы «пример актуален для копии».
- **L-EXTRA-9 (Low, hygiene):** в `cover_test_style` успешный ответ отдаёт
  `"preview_stale": False` константой (`web/api/cover_styles.py:593`) — корректно
  для сохранённой revision, но не пересчитывается; при рассинхроне `revision`
  ответа и записи возможно ложное `False`. Потребителей, кроме UI, нет.

### Вердикт round2 по M-EXTRA-1/2/3

**PASS / PASS / PASS.** Все три requirement-blocking Medium врезаны в живой
контур, а не только в тесты: (1) `set_preview` без инкремента revision +
`preview_is_stale` + сохранение Test Style как preview + UI-баннер/кнопка;
(2) `brief_from_text`→`CoverBrief` и `base_style_prompt` реально попадают в
Style Edit prompt из `_maybe_apply_cover_style`→`run_style_job`;
(3) deep-link фокусирует `models_images` с подсветкой и сохраняет контекст
редактора. Блокеров нет; L-EXTRA-8/L-EXTRA-9 — не-блокирующие. Вердикт фичи
по round2 — **PASS** (при закрытых L-EXTRA-6/7/8/9 как debt).

---

## Low/гигиена (round2)

- **Роль:** @Reviewer (только проверка, код не правился, коммит не делался).
  Дерево — рабочее (untracked EXTRA-файлы на диске); проверялись текущие файлы.
- **Примечание:** `python` в PATH — WindowsApps-заглушка; все прогоны через
  `.venv\Scripts\python.exe`.

```
.venv\Scripts\python.exe -m pytest tests/test_extra_cover_styles_api.py \
    tests/test_extra_cover_styles_ui.py tests/test_extra_cover_style_registry.py \
    tests/test_extra_cover_style_jobs.py -q
→ 103 passed, 1 warning in 3.79s

node tests/js/round1029_extra_cover_styles_test.js
→ EXTRA-COVER-STYLES-UI-OK
```

| # | Low-фикс | Вердикт | file:line |
|---|---|---|---|
| 1 | provenance base/final asset-id (§30) | **PASS** | `services/cover_style_jobs.py:629`, `:770`, `:827`, `:887-888` |
| 2 | Replace референса (§12) | **PASS** | `web/api/cover_styles.py:374-404`; `services/cover_style_registry.py:408-428`; `web/index.html:538-545`; `web/app.js:7000-7030` |
| 3 | upload cap 4 МБ → 413 (§12/§2.3) | **PASS** | `web/api/cover_styles.py:38`, `:334-337` |
| 4 | метка «Время обработки» (§75) | **PASS** | `web/index.html:632` |
| — | гигиена `web/app.py` (LF, +4/−0) | **PASS** | `git diff --numstat -- web/app.py` → `4 0`; CR-байт в файле **0** |

### 1) provenance base/final asset-id — **PASS**

`_asset_id_of` (`services/cover_style_jobs.py:629-645`) считает sha256 файла
чанками и возвращает `asset_id_for(digest)` = `cas_<hex[:32]>`; файл/PG не
пишет (bounded, §2.1). `meta["base_asset_id"]` заполняется до edit-вызова
(`:770`), `final_asset_id` — на пути успеха (`:827`); обе величины уходят в
`_record_provenance` (`:887-888`) и в `record_provenance` SQL
(`services/cover_style_registry.py:563-564`). Round-1 L-EXTRA-1 («всегда
`None`») снят. Тест `test_extra_cover_style_jobs.py:630-631` проверяет непустые
`final_asset_id`/`base_asset_id` на resume-пути.

- **Наблюдение (Low, bounded):** ранние ветки `run_style_job` —
  `cover_styles_disabled`/`no_style`/`base_failed` (`:710-721`) и
  `edit_unsupported` (`:741-744`) — возвращаются **до** `_record_provenance`,
  т.е. для этих исходов строка provenance не пишется (ID’шники не фиксируются).
  Не регресс и не блокер (эти стадии не доходят до Style Edit), но фиксирую как
  известное ограничение.

### 2) Replace референса — **PASS**

PUT `/cover/styles/{style_id}/references/{ref_id}` (`web/api/cover_styles.py:374-404`)
декодирует upload (тот же size-cap), кладёт ассет и вызывает
`registry.update_reference` (`services/cover_style_registry.py:408-428`):
`UPDATE … SET asset_id = COALESCE($3, asset_id), label = COALESCE($4, label),
description = COALESCE($5, description)`. UI: кнопка «Заменить» с
`:data-cover-replace-input="r.ref_id"` (`web/index.html:538-545`) →
`coverStyleReplaceReference` (`web/app.js:7000-7030`, `method: 'PUT'`).
Тест `tests/test_extra_cover_styles_api.py:443-466` (`test_replace_reference`)
зелёный; JS/UI-маркеры — в наборе.

- **Наблюдение (Low, SQL-fidelity):** `update_reference` использует
  `bool(getattr(cursor, "rowcount", 1))` (`services/cover_style_registry.py:425`),
  тогда как `conn` — real `asyncpg` (`services/pg_db.py:636` `asyncpg.create_pool`),
  а `Connection.execute()` возвращает строку статуса, а **не** курсор с
  `rowcount`. Итог: `getattr` всегда отдаёт дефолт `1` → `ok=True` даже для
  несуществующего `ref_id`, поэтому ветка 404 `reference not found`
  (`web/api/cover_styles.py:401-402`) недостижима. Валидный путь (существующий
  ref) работает корректно: ассет заменяется. Прямого unit-теста на реальную SQL
  нет — API-тест мокает `update_reference`. Не блокер.
- **Наблюдение (Low):** `label`/`description` в PUT передаются как
  `body.label or None` (`:400`), поэтому «очистить описание» через пустую строку
  не сработает — уйдёт `None` → `COALESCE` оставит прежнее значение. Для
  «Replace» без изменения метаданных — ожидаемо; для очистки поля — нет.

### 3) upload cap 4 МБ → 413 — **PASS**

`MAX_UPLOAD_BYTES = 4 * 1024 * 1024` (`web/api/cover_styles.py:38`); в
`_decode_upload` после base64-декода:
`if len(data) > MAX_UPLOAD_BYTES: raise HTTPException(status_code=413, …)`
(`:334-337`). Через `_decode_upload` идут POST references (`:355`), PUT replace
(`:389`) и test-style (`:544`) — лимит применяется ко всем путям загрузки.
Round-1 L-EXTRA-3 (size-cap отсутствовал) снят. Тест
`tests/test_extra_cover_styles_api.py:432-440` (`test_upload_reference_size_cap`
→ 413) зелёный.

### 4) метка «Время обработки» — **PASS**

`web/index.html:632`: `Время обработки: {{ coverStyles.preview.duration_ms }} мс`.
Строка «Затемнение» в `web/index.html` отсутствует (rg + ассерт
`tests/test_extra_cover_styles_ui.py:47`, `:49-50`). Round-1 L-EXTRA-5 снят.

### Гигиена — **PASS**

`git diff --numstat -- web/app.py` → `4 0` (совпадает с `--ignore-cr-at-eol`);
файл `web/app.py` — **0** байт CR (LF, длина 19180). Раздутия CRLF нет; фактический
диф — включение `cover_styles_router` (`web/app.py`, блок `include_router`
после `summary_test_router`). Round-1 NB-1 по `web/app.py` закрыт.

### Вердикт round2 по Low/гигиене

**PASS / PASS / PASS / PASS, гигиена PASS.** Все четыре Low-находки закрыты
сквозь живой контур (не только тестами); прогон 103 passed + JS OK; `web/app.py`
чистый LF `+4/−0`. Остаются не-блокирующие наблюдения: early-return без
provenance-строки (§1), `rowcount` на asyncpg-строке и недостижимый 404 (§2).
Вердикт фичи по этой волне — **PASS**.

---

## Прогоны/WTH (round2)

- **Роль:** @Reviewer (только проверка; код не правился, коммит не делался).
  Дерево — рабочее (untracked EXTRA-файлы на диске; HEAD `bbdee1c`, коммитов нет).
  `python` в PATH — WindowsApps-заглушка; все прогоны через
  `.venv\Scripts\python.exe` (**Python 3.12.0**); **`node v24.16.0`**.
  Временные WTH-скрипты — вне репозитория (temp), дерево не менялось.

### 1) Полный pytest — **PASS (только baseline-fail)**

```
.venv\Scripts\python.exe -m pytest -q
→ 2 failed, 10210 passed, 1 warning in 275.52s (0:04:35)
```

Оба падения — известные baseline `test_forbidden_paths_out_of_diff*`,
**чужие для EXTRA**:

| Тест | Причина |
|---|---|
| `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` | baseline forbidden-paths diff |
| `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | baseline forbidden-paths diff |

Чужой WIP в diff от `pre-round1026-a1`/`e8646af` (проверено
`git diff --name-only`): `web/api/analytics.py`,
`web/static/polygon-background.js`, `web/static/telegram-init.js`. Ни один из
них не входит в EXTRA-манифест (102 файла). Совпадает с ожиданием
**10210 passed / 2 failed**.

### 2) EXTRA-наборы (`tests/test_extra_*.py`) — **PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_extra_cover_style_jobs.py \
  tests/test_extra_cover_style_pipeline.py tests/test_extra_cover_style_registry.py \
  tests/test_extra_cover_style_runtime.py tests/test_extra_cover_styles_api.py \
  tests/test_extra_cover_styles_ui.py tests/test_extra_image_capabilities_compiler.py -q
→ 149 passed, 1 warning in 4.01s
```

Совпадает с ожиданием **149 passed** (7 файлов).

### 3) JS — **PASS 52/52**

```
node --check (изменённые JS: 5× tests/js/round1025_*, round1029_extra_cover_styles_test.js, web/app.js)
→ 7/7 SYNTAX-OK

node tests/js/*.js (все 52 харнесса)
→ JS_PASS=52 JS_FAIL=0 TOTAL=52
```

Совпадает с ожиданием **52/52**.

### 4) F8-check — **PASS**

```
.venv\Scripts\python.exe tools/gen_param_registry_round1025.py --check
→ CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.
```

Совпадает с ожиданием **OK 488**.

### 5) Working-Tree-Hash (rework1) — **MATCH + идемпотентно**

- **Рецепт (canonical):** для каждого `<relpath>` из
  `plans/reports/extra_wth_manifest_rework1.txt` вычислить `sha256(file bytes)`,
  построить строки `"<relpath> <sha256>"`, отсортировать, соединить `"\n"` и
  добавить завершающий `"\n"`; затем `sha256(utf-8)`.
- **Файлы:** **102/102** присутствуют, **0** missing, **0** hash-mismatch (все
  sha256 на диске совпадают с манифестом — дрифта нет).
- **WTH:** `d0203e00fc46b328989fff83c4e4b478a40f71e739dc2d258843cacefed9dc9b`
  — **совпал** с binding-значением.
- **Идемпотентность:** два независимых прогона → тот же хэш (`idempotent=True`).

### Итог round2

| # | Проверка | Ожидание | Факт | Итог |
|---|---|---|---|---|
| 1 | Полный pytest | 10210 passed / 2 failed (baseline `test_forbidden_paths_out_of_diff*`) | 10210 passed / 2 failed (оба baseline, чужие) | **PASS** |
| 2 | EXTRA-наборы | 149 passed | 149 passed | **PASS** |
| 3 | JS `--check` + харнессы | 52/52 | 52/52 (7/7 syntax OK) | **PASS** |
| 4 | F8 `--check` | OK 488 | OK 488 | **PASS** |
| 5 | WTH rework1 | `d0203e0…` | `d0203e0…` (102/102, идемпотентно) | **PASS** |

**Расхождений с ожиданиями нет.** Baseline-пара — предсуществующая и вне
EXTRA-скоупа; новых регрессий нет.

---

## Итог round 2 — финальный вердикт по `extra-cover-style-pipeline`

> **Вердикт: Approved for release — «к деплою ДА».**
> Round-1 `Needs Fixes` снят: все blocing H/M закрыты и врезаны в живой контур.
> Остаточные пункты — только non-blocking debt + обязательные прод-проверки.

- **Роль:** @Reviewer (только проверка; код не правился, коммит не делался).
  Итог собран из секции round 1 (`Needs Fixes`) + секций round 2
  (H-EXTRA-1 / M-EXTRA-1/2/3 / Low-гигиена / Прогоны-WTH); ключевые звенья и
  binding-хэши **перепроверены независимо** в этой сессии.
- **Независимая перепроверка round 2 (эта сессия):**
  `.venv\Scripts\python.exe -m pytest tests -k "DurableRestart or ProductionWiring
  or PreviewStale or DynamicBrief or CoverBrief" -q` → **10 passed**;
  EXTRA-наборы 7 файлов → **149 passed**; `node
  tests/js/round1029_extra_cover_styles_test.js` → **EXTRA-COVER-STYLES-UI-OK**;
  provenance wiring — `services/summary_generator.py:1333`, `:1490-1508`;
  `services/cover_style_jobs.py:389/417/454/483/695/769-773/815-820`;
  `services/cover_style_registry.py:291-337/408-425`; `web/api/cover_styles.py:80/578-593`;
  `web/app.js:7084-7121`.

### Binding

- **Reviewed-Commit:** `bbdee1ca44bf6695a1a421a3629792f6a0114edc` (HEAD; коммитов
  EXTRA нет — фича целиком в рабочем дереве).
- **Spec-Hash:** `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF`
  (`spec.md`; перепроверен на диске — совпал).
- **Working-Tree-Hash:** `d0203e00fc46b328989fff83c4e4b478a40f71e739dc2d258843cacefed9dc9b`
  (`extra_wth_manifest_rework1.txt`, 102/102 файлов, 0 missing, 0 hash-mismatch;
  рецепт canonical, идемпотентен — перепроверено независимо).
- **Прочие binding:** `tasks.md` `82B12AF0703E3483B6E8171578B04FDC91613C88ACDF33BA8BAB4F1DACB205B2`
  (совпал); `adr-1028-4` `E9C44ACC…807251`; `current_task.md` `D6AD5DFB…DCAF2EB` (R18, не изменялся).

### 1) Закрыты ли все H/M round 1? — **ДА**

| Round-1 находка | Round-2 вердикт | Доказательство (перепроверено) |
|---|---|---|
| **H-EXTRA-1** durable job §42/§43 (DoD-25) | **PASS** | `_maybe_apply_cover_style` строит `begin_cover_job`→`run_style_job(db,job_id,state)`→`finish_cover_job` (`summary_generator.py:1490-1508`); resume из `task_jobs` (`cover_style_jobs.py:695-696,454-469`); `provider_task_id` персистится (`:815-820`), `existing_task_id` не делает повторный submit (`cover_style_edit.py:318-320`); `pytest -k "DurableRestart or ProductionWiring"` → 4 passed |
| **M-EXTRA-1** §10/SC-24 stale-revision preview | **PASS** | `set_preview` без инкремента revision (`registry:291-324`); `preview_is_stale` (`:327-337`); флаг в `_public_profile` (`cover_styles.py:80`); UI-баннер + «Обновить пример» (`index.html:616-623`, `app.js:7116-7121`) |
| **M-EXTRA-2** §19/§21 CoverBrief + dynamic brief | **PASS** | `brief_from_text`→`CoverBrief` (`compiler:102-116`); `compile_style_prompt(brief=…)` (`jobs:562-595`); живой путь `summary_text=cover_prompt, base_style_prompt=base_style` (`summary_generator.py:1500-1501`); `jobs:769-773` |
| **M-EXTRA-3** §35 deep-link focus/return | **PASS** | `openCoverConnections` сохраняет `_returnProfileId`, ставит `models_images`, фокус/подсветка (`app.js:7084-7114`); анкор `data-config-group` (`index.html:1934`); группа `models_images` (`param_catalog.py:186`) |

Round-1 Low (L-EXTRA-1…5) также сняты сквозь живой контур (provenance base/final
asset-id, Replace референса, upload-cap 4 МБ→413, метка «Время обработки»,
`web/app.py` LF `+4/−0`). **Блокирующих находок не остаётся.**

### 2) Суждение по остаточному PG-риску — **приемлемо как задокументированное ограничение, НЕ Needs Fixes**

- **Факт:** DB-слой фічи тестируется на in-memory `_FakePg` (NB-4); реальная
  asyncpg-семантика `ON CONFLICT`, partial unique index
  (`idx_cover_style_assets_sha`), `UPDATE … RETURNING` (counter) и `rowcount`
  на `conn.execute()` — на боевой СУБД в сессии **не прогонялись**. `update_reference`
  использует `bool(getattr(cursor, "rowcount", 1))` (`registry:425`), тогда как
  asyncpg отдаёт строку статуса → ветка 404 «reference not found» недостижима.
- **Почему это НЕ блокер:**
  1. **Fail-open по архитектуре:** PG недоступен → `_pool_of(pg) is None`/исключение
     → base cover публикуется без стиля (§1/§49). Blast radius ограничен
     Style-стадией, публикационный контур (§90) не задет.
  2. **SQL прочитан и корректен:** DDL идемпотентен (`CREATE … IF NOT EXISTS`);
     counter-path использует `fetchrow("UPDATE … RETURNING")` — это правильный
     asyncpg-API (в отличие от `execute`+`rowcount`); `resolve_issue_number`
     обёрнут в `conn.transaction()`, retry-reuse через `PRIMARY KEY(profile_id,
     summary_run_id)` + `ON CONFLICT DO NOTHING`.
  3. **Единственный конкретный дефект** (`rowcount`) — bounded: валидный путь
     (существующий ref) работает, портится только HTTP-код для несуществующего
     refID при отсутствии impact на данные; уже зафиксирован как non-blocking.
  4. Остаточные unit-пробелы — стандартные, широко используемые конструкции PG;
     риск реализуется **только на боевой СУБД**, поэтому переносится в обязательную
     прод-приёмку, а не в код-фикс.
- **Условие приемлемости (binding):** перечисленные ниже прод-проверки **обязательны**
  и блокируют закрытие приёмки §100. Без их положительного результата вердикт
  «к деплою ДА» недействителен.

### 3) DC-4 / T-4173 — **Unavailable, помечено честно — ДА**

- `tasks.md` T-4173 — `[ ]` с пометкой **«⏳ Pass 2 (blocked-by DC-4)»**; семантика
  ensure/replace зафиксирована в `SEEDED_INSTRUCTION` (§24) и P0-инвариантах, но
  фактическая **визуальная** проверка §85/§86 требует edit-capable провайдера и
  вынесена в прод-приёмку §100.
- DC-4 объявлен как продуктовая предпосылка (не блокер кода/деплоя): текущий
  code-default (Pollinations/flux) edit не умеет → Style stage даёт §38-ошибку,
  base публикуется (`spec.md:481`, `tasks.md:24/150/151/437`, `adr-1028-4:70/152`,
  `deployment.md:95`, `evidence.md:176`). Живой style-success без edit-capable
  провайдера и visual §85/§86 — **Unavailable**; SC-19/SC-20 не подтверждены до
  деплоя (задокументировано, не замаскировано).

### Открытые non-blocking (debt, не блокируют релиз)

- **L-EXTRA-6** (§42/§43, hygiene): `save_checkpoint` перезаписывает ту же колонку
  `payload`, где `enqueue` хранит бизнес-payload (`task_supervisor.py:633-637`;
  `cover_style_jobs.py:445-447`). На resume безопасно (читается «cursor»,
  `enqueue` — `INSERT OR IGNORE`), потребителей исходных атрибутов нет.
- **L-EXTRA-7** (§43, scope): `cover_job_key` зависит от `correlation_id` =
  UUID4 на каждый запуск; кросс-рестарт resume по стабильному run-id в сессии не
  проверялся → обязательная прод-проверка (см. ниже).
- **L-EXTRA-8** (§29/§63, edge): `duplicate_profile` копирует `preview_revision`
  исходника, тогда как новая строка имеет `revision=1` → копия сразу `stale` с
  чужим preview (`registry:229,347-354`). Косметика.
- **L-EXTRA-9** (§10, hygiene): `cover_test_style` возвращает `preview_stale=False`
  константой (`cover_styles.py:593`) — не пересчитывается при рассинхроне
  revision/записи; потребителей кроме UI нет.
- **Provenance early-branch:** ранние ветки `run_style_job`
  (`cover_styles_disabled`/`no_style`/`base_failed`/`edit_unsupported`, `:710-744`)
  возвращаются до `_record_provenance` → строка provenance для них не пишется.
  Не регресс (стадии не доходят до Style Edit).
- **`update_reference` rowcount:** `bool(getattr(cursor,"rowcount",1))`
  (`registry:425`) на asyncpg-строке статуса всегда `1` → 404-ветка недостижима;
  валидный путь работает. Решение 200-vs-404 — на прод-приёмке.
- **PG real-pool:** реальная asyncpg-семантика (`ON CONFLICT`, partial unique,
  `UPDATE … RETURNING`, rowcount) не покрыта unit/fake-pool — см. п.2 и
  прод-проверки.

### Обязательные прод-проверки (блокируют закрытие приёмки §100; binding для вердикта)

1. **PG-миграция/идемпотентность:** применить `DDL_STATEMENTS` на боевой PG
   (5 таблиц + 5 индексов, вкл. partial unique `idx_cover_style_assets_sha`
   и `idx_cover_style_issue_unique`); прогнать старт дважды → без ошибок и дублей.
2. **Real-pool CRUD-smoke:** создать/дублировать/редактировать/удалить Style
   Profile; add/replace/remove reference; upload ассета (дедуп по `sha256,scope`
   через `ON CONFLICT`/partial unique) — на реальном asyncpg, не fake-pool.
3. **Counter/concurrency:** два параллельных Summary на одном стиле → разные
   `issue_number`; повтор с тем же `summary_run_id` → тот же номер; `UNIQUE(profile_id,
   issue_number)` держит; Test Style counter не расходует.
4. **`UPDATE … RETURNING` + `resolve_issue_number`** под реальной транзакцией
   READ COMMITTED (нет пропущенных/задвоенных номеров).
5. **`update_reference` rowcount:** PUT на несуществующий `ref_id` — зафиксировать
   ожидаемое 200/404; при необходимости — не-блокирующий hotfix.
6. **Durable restart-resume (L-EXTRA-7):** рестарт процесса с тем же
   `summary_run_id` посреди style-стадии → polling возобновляется из `task_jobs`,
   **нового платного task нет** (`provider_task_id` переиспользован).
7. **DC-4 / T-4173 (§85/§86):** с edit-capable провайдером — замена чужого
   логотипа, отсутствие дубля PERMsoc/issue-badge, нормализация номера; живой
   style-success end-to-end (base→style→reference→issue→styled→Rich).
8. **Ladder/parity на проде:** no-style (base+Rich без деградации), style failure
   → base published, base failure → Rich без изображения, rich failure → plain;
   kill-switch OFF → plain-parity.
9. **Операционное:** health 200, `database is locked`=0, `APP_VERSION` `2.58.39`;
   R17-скан прод-логов (секреты/промпты не текут).

**Итог:** H-EXTRA-1 и M-EXTRA-1/2/3 закрыты, Low/гигиена закрыты; остаточный
PG-риск и DC-4/T-4173 приняты как задокументированные ограничения с обязательными
прод-проверками выше. **Approved for release — «к деплою ДА».**
