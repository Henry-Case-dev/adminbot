# ASAP 4.3 — requirements-map.md

Feature: `asap-4-3-cover-style-surgical` — хирургическое восстановление Cover Style + честный Test Style + mobile UI.
Источник (SoT): `plans/current_task.md:25459–26361` (блок владельца, НЕ изменяется). Runtime-код — истина для root cause; старые review.md/отчёты не используются.
Спека = блок владельца. spec/ADR не создаются (не архитектурный эпик). Architect — только при реальном противоречии.
Порядок: план → Builder → targeted tests → real canary → Reviewer → deploy → live acceptance → owner report → возврат к MCA.

## Confirmed root causes (runtime code)

Все пункты проверены по коду 04.10.2026 (PM recon + spot-check).

1. **Долгий browser↔backend запрос.** `POST /cover/test-style` — одна синхронная функция (`web/api/cover_styles.py:841–972`): base gen awaited `:881` (`_generate_test_base`), style edit awaited `:914` (`jobs.run_style_preview`). GET-status route отсутствует (список роутов `web/api/cover_styles.py:165–863`). UI `coverStylePreview` (`web/app.js:7478–7522`) — plain POST без timeout/abort/polling; `api()` (`web/app.js:4010–4048`) пропускает native `TypeError: Failed to fetch`; он рендерится verbatim (`web/index.html:728–730`); `previewBusy` держит кнопку выключенной.
2. **Durability no-op в preview.** `run_style_preview` (`services/cover_style_jobs.py:1547–1565`) вызывает `run_style_job` без `db`/`job_id` → helpers `_persist_state`/`finish_cover_job`/`save_cover_state` no-op (`:528–568`, `:623–627`). Production-path wired: `services/summary_generator.py:2996–3020` (`begin_cover_job` → `run_style_job(db=…, job_id=…)` → `finish_cover_job`). Preview-путь отстаёт от production.
3. **Preview pair не атомарен.** `set_preview` пишет before+after+revision одним UPDATE (`services/cover_style_registry.py:295–331`), но asset inserts — отдельные autocommit (`web/api/cover_styles.py:907–910`, `:941–953`) → orphans/смешанная пара. `preview_job_id` в схеме/коде отсутствует (repo grep — 0). Stale: `preview_revision != revision` (`services/cover_style_registry.py:334–344`).
4. **Placeholders засеяны как DB preview assets.** `SEED_FILES` (`services/cover_style_registry.py:80–85`) + seed-loop `:742–766` пишет `style_example_01.png`/`style_example_02.jpg` в `cover_style_assets` и в `preview_before/after_asset_id` при `preview_revision=None`. Owner §5 требует: только UI fallback, не DB preview.
5. **Medved reference цел** (проверено): seed читает `extra_images` (`services/cover_style_registry.py:94–96`); `_resolve_reference_details` проверяет DB-row/файл/MIME/сигнатуру (`services/cover_style_jobs.py:875–911`), `ALLOWED_MIME` из `services/cover_style_assets.py` (`services/cover_style_jobs.py:33`). RBAC `_assert_can_edit_seeded` (`web/api/cover_styles.py:150–160`) enforced на `POST /cover/test-style` `:863` и всех мутациях. medved_press.png = 475 189 B, sha256[:12] `be0a700ba8d3`.
6. **Prompt limit.** Hardcoded `800` в runtime нет; AST-guard `tests/test_asap42_step2c_image_capacity.py:411–420`. Precedence — `services/image_capabilities.py:526–585` (override → live metadata → registry → cached → unknown). Manual override только env-JSON `COVER_STYLE_CAPABILITY_OVERRIDES` (`:271–275`) — DB/UI нет (§7.2 gap). `run_style_job` резолвит capabilities без live discovery (`services/cover_style_jobs.py:1209`). 400-retry (`:1401–1446`) может отправить второй paid call даже при `recompiled.exceeded`.
7. **Compiler P0–P3 ON** (`services/image_prompt_compiler.py:172–250`): P0+P1 over limit → `exceeded`/`prompt_limit_exceeded`, без строковых ножниц. `SEEDED_INSTRUCTION` = 979 chars (`services/cover_style_registry.py:59–78`).
8. **Mobile.** `.sticky-save` (`web/static/app.css:1654–1670`); `.bottom-nav` flex-child + safe-area один раз (`:2261–2307`); `.more-sheet` (`:2333–2355`) closed = `v-if` unmount (`web/index.html:5485–5488`, фикс 4.2 — регресс-проверка); `.cover-overlay z-index:50` (`:2633–2641`); `.cover-editor` (`:2645–2661`); `.cover-card-previews` 5.75rem (`:2698–2719`). Style card row (`web/index.html:477–523`) — non-wrapping flex, fixed preview + 2 flex-none кнопки без `min-width:0` → overflow на 390px. Editor `web/index.html:528–737`; лимит-строка `:619`; результат `:715–737`. Tool `tools/ui_asap32_cover_styles_e2e.py` — editor, 360px.
9. **`extra_images/` untracked.** `git status` → `?? extra_images/`; не в `.gitignore`, `git check-ignore` пуст. Файлы: medved_press.png 475 189 B; style_example_01.png 2 105 937 B; style_example_02.jpg 401 490 B.

## §0 — «Что сломано сейчас» (якорь 25471–25490)

| # | Требование | Критерий приёмки | Task | Reuse/notes |
|---|---|---|---|---|
| 0.1 | Test Style снова не проходит, UI — сырой `Failed to fetch` | Кнопка запускает job; сырой fetch-текст не финал; ошибки человекочитаемы | T-4842, T-4853, T-4854 | `api()`/`coverStylePreview` переписать на job-контур |
| 0.2 | Вместо базовой preview — случайная заглушка/«ваза» | Base Cover реально генерируется; failure не показывает случайную картинку как пример | T-4843, T-4844 | `_generate_test_base` остаётся источником base |
| 0.3 | Несогласованная пара «До/После» | Пара только от одного успешного job текущей revision | T-4844 | `set_preview` → atomic + `preview_job_id` |
| 0.4 | Ч/Б `style_example_01/02` засеяны в БД неправильно | Placeholders — только UI fallback, не DB preview assets | T-4845 | `SEED_FILES`, seed-loop `:742–766` |
| 0.5 | `medved_press.png` — реальный reference seeded-стиля | Цепочка row→file→mime→edit request; не подменяется placeholder; survived restart | T-4846 | `_resolve_reference_details` уже есть |
| 0.6 | Мобильная вёрстка сломана (save-панели, landscape, overflow, editor, preview) | Контракт §10.1–§10.4 выполнен на 3 viewports + DOM rects | T-4850, T-4851, T-4852 | shell flex уже v3; more-sheet closed fixture 4.2 |
| 0.7 | Summary fail-soft `styled→base→Rich→plain` не сломан | Ladder-тесты зелёные; canary B не выдаёт base fallback за style | T-4856, T-4864 | `services/summary_generator.py:2996–3020` |
| 0.8 | Никакого магического `800` | Capability resolver + manual override; 800 не управляет лимитом | T-4847, T-4848 | AST-guard уже есть |

## §1 — Root cause подтверждение (25494–25517)

| Требование | Критерий | Task | Reuse |
|---|---|---|---|
| Прочитать минимум файлов §1 (web/api/cover_styles.py, web/app.js, web/index.html, app.css, cover_style_jobs/edit/pipeline, image_capabilities, image_prompt_compiler, cover_style_registry, cover_style_assets, extra_images); не доверять старым review; проверить контракт POST; исправить границу browser↔backend, не добавлять timeout | Builder-чиклист подтверждения/опровержения с file:line; при расхождении с recon — запись; правки только после подтверждения | T-4841 | Recon выше; forbidden: ещё один timeout |

## §2 — Durable job contract (25521–25633)

| Требование | Критерий | Task | Reuse/notes |
|---|---|---|---|
| §2.1 Не держать один HTTP до конца генерации; stages BASE_GENERATING→…→DONE/FAILED; UI опрашивает; использовать существующую инфру, не третью очередь | Start короткий; stages видны из job; new queue/framework отсутствует | T-4842, T-4843 | `begin_cover_job`/`save_cover_state`/`load_cover_state`/`finish_cover_job` (`cover_style_jobs.py:502–627`) |
| §2.2 POST start: валидирует access/RBAC, создаёт job, возвращает `job_id`+`status:queued` почти сразу, не ждёт генерации; GET `/api/cover/test-style/{job_id}` (или существующий endpoint без дублирования); состояния queued/base_generating/base_ready/style_editing/saving_preview/completed/failed; diagnostics только stage/started_at/last_progress_at/provider/model/human_message/machine_reason/preview_before_url/preview_after_url; без API keys/полных prompt | Targeted: start < ~1 c и job_id; status-контракт полей; unknown job → 404; нет секретов/prompt | T-4842 | Route list уже есть; не плодить параллельный framework |
| §2.3 Ping реального выполнения: provider async → сохранять task id, polling его, resume после рестарта без второго платного запроса; provider sync → вызов внутри backend worker, UI не держит fetch, heartbeat stage, hard deadline только safety ceiling; повторные status-запросы безопасны/бесплатны; обрыв MiniApp → job не отменяется, после открытия дочитывается | Targeted: reconnect/status-read не создаёт новый image request; restart продолжает тот же task (в рамках task_jobs); stages/heartbeat | T-4843 | heartbeat helpers в `cover_style_jobs.py`; env flags уже есть |

## §3 — Honest errors (25637–25657)

| Требование | Критерий | Task |
|---|---|---|
| Различать provider_error / prompt_limit_exceeded / connection_missing / browser потерял соединение / status временно недоступен; для 4–5 человеческая фраза «Потеряно соединение…» + восстановление и дочитывание job; сырой `Failed to fetch` не финал; `developer_reason` только в раскрываемых деталях | UI-тесты: 5 веток; нет fetch-текста как итога; developer_reason в details | T-4854 |

## §4 — Атомарный preview pair (25661–25705)

| Требование | Критерий | Task | Reuse/notes |
|---|---|---|---|
| Контракт: `preview_job_id`, `preview_revision`, `preview_before_asset_id`, `preview_after_asset_id`, `preview_status=success`; пара валидна только если обе картинки от одного успешного job текущей revision; success — одна атомарная операция before+after+revision+job_id; failure — pair не переписывается частично, before не сохраняется как новый preview, случайная base не показывается примером; orphan-ассеты чистятся после retention; staleness по revision | Targeted: atomic success pair; failure keeps pair; stale ≠ current; no mixed pair | T-4844 | Расширить `set_preview`/схему; +1 nullable column `preview_job_id` (additive DDL, prod PG) либо эквивалентная provenance в job store; без новой таблицы |

## §5 — Ч/Б placeholders (25709–25743)

| Требование | Критерий | Task |
|---|---|---|
| `style_example_01.*`/`style_example_02.*` — только UI fallback: не permanent DB-assets профиля, не «первый успешный preview», не мутируют revision, не копируются как user assets, не заменяются в source tree; display: success pair текущей revision → реальные before/after, иначе Ч/Б; расширение — из фактического файла в extra_images (не выдумывать); после success UI динамически меняет; при failure placeholders/last valid pair не превращаются в «вазу» | Targeted+UI: placeholders не DB preview assets; success заменяет; failure сохраняет; имя файла из listing | T-4845 |

## §6 — Medved reference (25747–25768)

| Требование | Критерий | Task |
|---|---|---|
| Seeded «Графический роман Медведь Press»: reference→medved_press.png, role/description издательский знак; проверено: asset существует, читается backend, MIME валиден, reference row указывает, файл реально уходит в edit, не подменяется placeholder, survives restart/deploy; seeded редактирует только global admin (backend enforcement) | Targeted: reference resolved (row/file/mime/signature), передан в request; RBAC 403 non-admin; git-tracked extra_images | T-4846 |

## §7–§7.2 — Prompt limit (25772–25833)

| Требование | Критерий | Task | Reuse/notes |
|---|---|---|---|
| §7 Capability разрешается per connection/provider+model+operation (image_generate/image_edit), не по имени модели; `800` не хардкодить вне подтверждённой metadata | Resolver принимает operation; grep 800 не управляет | T-4847 | `resolve_capabilities(provider, base_url, model, route=…)` |
| §7.1 Precedence: manual override → provider/model metadata → verified adapter metadata → explicit numeric limit из response → UNKNOWN; парсинг текста — доп. обучение; `maximum prompt length is 800` → observed; `prompt too long` → UNKNOWN | Targeted: precedence; observed N сохраняется per provider+url+model+route; unknown не блокирует | T-4848 | `parse_discovery`, `record_runtime_limit`, `extract_prompt_limit` |
| §7.2 MiniApp: «Ограничение промпта» [Автоматически]/[Задать вручную], единица символы/токены, значение; manual высший приоритет; сохранение стиля не блокируется маленьким лимитом | UI-тест полей + persistence; precedence manual; save style не блокирован | T-4847 | Сейчас override только env `COVER_STYLE_CAPABILITY_OVERRIDES` |

## §8 — Compiler/compact Medved (25837–25867)

| Требование | Критерий | Task |
|---|---|---|
| P0 тех. invariants / P1 основная инструкция / P2 контекст / P3 декор; при limit: убрать дубли, компактно сериализовать, сокращать P3→P2 семантически, не ломать P0, P1 не обрубать; никакого `prompt[:800]`; seeded Medved prompt заменить компактной версией (§8 текст) без потери invariants (PERMsoc один, номер выпуска один, логотип по reference, references по ролям, comic/graphic-novel) | Targeted: нет строковых ножниц; P0/P1 приоритет; порядок P3→P2; compact profile содержит все invariants | T-4848 |

## §9 — Prompt budget UI (25871–25895)

| Требование | Критерий | Task |
|---|---|---|
| Под textarea: «Инструкция: N символов», «Лимит текущей модели: M / неизвестно»; после compile/test: Style/Context/Refs-meta/System/Итого …/…; UNKNOWN → «Провайдер не сообщил точный лимит…»; не показывать ложное 800 | UI-тест счётчиков: known/unknown; breakdown из compiled diagnostics | T-4849 |

## §10–§10.4 — Mobile (25899–26004)

| Требование | Критерий | Task |
|---|---|---|
| §10 Viewports 390×844, 844×390, 1280×800 + Telegram-like WebView geometry/safe-area | Playwright на всех 3 + safe-area emulation | T-4850, T-4858 |
| §10.1 Нет горизонтального overflow; Save button не обрезан; один vertical scroll owner; footer/save видны; bottom nav не перекрывает save; more-sheet не конфликтует с modal; closed more-sheet отсутствует (нет хвоста); keyboard/safe-area один раз; без `bottom: Npx` без контракта | DOM-rect assertions; grep новых bottom-Npx фиксов | T-4850, T-4858 |
| §10.2 Shell header/scrollable main/bottom nav; save area не поверх nav; min-width:0/max-width:100%/box-sizing где нужно; Reviewer проверяет реальные DOM rectangles | Playwright: save area структурно выше nav; geometry | T-4850, T-4861 |
| §10.3 Editor занимает viewport; header фиксирован; body — единственный скроллер; footer `Закрыть/Сохранить стиль` всегда видим, не перекрывает body/bottom-nav; fullscreen nav скрыта или вне usable viewport — один контракт | Playwright geometry editor | T-4851 |
| §10.4 Preview не стена: `[small before] > [small after] Название`; в editor compact; одна горизонтальная группа; масштаб от ширины; стрелка `msr` (не текст/не отдельная строка) | Playwright: grouping, arrow=msr, fit; нет «огромное До / > / огромное После» | T-4852 |

## §11 — Test Style UX (26008–26036)

| Требование | Критерий | Task |
|---|---|---|
| Stage-текст: «Генерируем базовую обложку… / Применяем стиль… / Сохраняем результат…»; elapsed можно, ошибка не по elapsed; double-tap не создаёт повторный paid job; закрыл/вернулся — state восстанавливается; после success before/after без перезагрузки, provider/model, «Стиль применён»; не тратится issue number; ничего не публикуется | Frontend/Playwright state flow; counter не изменён; no publish | T-4853 |

## §12 — Единый контур production/preview (26040–26079)

| Требование | Критерий | Task |
|---|---|---|
| Test и production переиспользуют connection/capability/compiler/reference/adapter/job-resume/failure normalization; различие только preview (без publish/issue) vs production; production fallback: styled→base→Rich без cover→plain sendMessage; текст Summary не падает | Targeted ladder + canary B; base fallback ≠ Style success | T-4843, T-4856, T-4864 |

## §13 — Не трогать лишнее (26083–26097)

| Требование | Критерий | Task |
|---|---|---|
| Не переписывать L1/L2 Summary, GraphRAG, Direct Chat, MCA memory, history, unrelated analytics, generic config UI без доказанного дефекта; legacy-причина при canary фиксируется отдельно | Diff scope: только файлы зон ASAP 4.3; unrelated изменения отсутствуют | T-4841, T-4855, T-4861 (scope check) |

## §14 — Targeted tests (26101–26153)

| Требование | Критерий | Task |
|---|---|---|
| Backend (12): start→job id быстро; stages проходят; reconnect не создаёт новый image request; success pair атомарна; failure не меняет pair; stale ≠ current; placeholders не DB assets; Medved reference resolved; manual limit приоритет; observed numeric сохраняется; unknown не блокирует; preview не расходует issue counter | Все 12 зелёные без полного suite | T-4856 |
| Frontend: Test Style не открывает file picker; Failed to fetch не финал; polling/reconnect; before/after только success pair; placeholders без success; prompt counters; JS syntax/build smoke | Frontend-набор зелёный | T-4857 |
| Playwright: 390×844, 844×390, 1280×800; assertions `scrollWidth<=clientWidth`, SaveBar/Save button в viewport, no intersection SaveBar↔bottom-nav, нет ghost more-sheet, preview помещается; не только скриншот | Tool/trace с DOM-rect assertions | T-4858 |

## §15 — Canary A/B (26157–26191)

| Требование | Критерий | Task |
|---|---|---|
| Canary A: один реальный Medved Press на configured production image provider; success = base реально создана + style edit реально выполнен + reference передан + status completed + UI обе картинки + no Failed to fetch + pair атомарна + issue counter не изменился; падение → чинить причину, повторить только canary | Real run, mock не засчитывается | T-4859 |
| Canary B: после A — один production-path smoke `base cover → style edit → publish`; доказать, что опубликована styled; base fallback ≠ Style success | Real publish evidence | T-4860 |

## §16 — Reviewer (26194–26212)

| Требование | Критерий | Task |
|---|---|---|
| Один Reviewer pass после Builder с Playwright/browser: portrait, landscape, save/footer geometry, preview geometry, Test Style state flow, no file picker, no random «ваза», Ч/Б placeholders, real pair after success; без нового аудита; blocking → вернуть Builder один раз с repro | Review verdict + evidence; blocking-loop ≤1 | T-4861 |

## §17 — Deploy (26216–26227)

| Требование | Критерий | Task |
|---|---|---|
| release/deploy → health → один production browser smoke → Canary A → Canary B → логи только вокруг этих run/job id; без многократных прогонов «для уверенности» | Deploy healthy; live acceptance evidence | T-4862, T-4863, T-4864 |

## §18 — DoD

DoD-чеклист вынесен в отдельную секцию ниже (в блоке владельца фактически **22** пункта, в задании сказано 21 — источник истины: строки 26236–26257).

## §19 — Анти-бюрократия (26264–26280)

| Запрет | Контроль | Task |
|---|---|---|
| Нет десятков ADR; нет 8–10 waves; нет full suite после каждого изменения; не mock вместо real canary; не скриншот как единственное доказательство; не `+4px`; не ещё один timeout; не парсинг ошибки как единственный источник; не новая job-система; base fallback ≠ Style Edit; не трогать MCA | Один план → Builder → targeted → canary → Reviewer → deploy → live; Reviewer+PM scope check | T-4841…T-4865 (весь список) |

## §20 — Owner report (26284–26320)

| Требование | Критерий | Task |
|---|---|---|
| Короткий отчёт простыми словами: что было сломано / что исправили / что проверили на живом боте / работает ли Medved Press (Да/Нет + причина) / что осталось; без commit hash, WTH, task ids, номеров тестов, fingerprints, ADR, сотен строк pytest, machine reason codes; техдоказательства — в plans/features/.../evidence и логах | Отчёт выдан в формате §20 | T-4865 |

## §21 — Возврат к MCA (26324–26337)

| Требование | Критерий | Task |
|---|---|---|
| После deploy+live acceptance: закрыть/архивировать ASAP 4.3; открыть current_task.md; определить следующую незавершённую MCA-задачу; сразу продолжить MCA; low-debt → backlog; продуктовый выбор → `ARCHITECT_DECISION_REQUIRED` | Archive выполнен; следующая MCA определена и запущена | T-4865 |

## Главный критерий (26341–26361)

| Требование | Критерий | Task |
|---|---|---|
| Пользователь на телефоне нажал «Проверить стиль» → нормальный прогресс → настоящая пара «реальная Base Cover → реальная Medved Press cover»; затем реальный Summary с Medved Press опубликовал styled, а не fallback | T-4863 + T-4864 (live), DoD 20–22 | T-4863, T-4864 |

---

## DoD checklist (§18, 22 пункта, 26236–26257)

| # | Пункт | Task(ы) | Evidence |
|---|---|---|---|
| 1 | Test Style не держит один долгий browser fetch | T-4842, T-4843, T-4853 | targeted + Playwright |
| 2 | UI видит durable job progress | T-4842, T-4843, T-4853 | frontend test + canary A |
| 3 | reconnect не создаёт новый paid request | T-4843, T-4856 | targeted |
| 4 | сырого Failed to fetch как итог нет | T-4854, T-4857 | frontend test |
| 5 | успешная preview pair атомарна | T-4844, T-4856 | targeted |
| 6 | failed preview не создаёт смешанную пару | T-4844, T-4856 | targeted |
| 7 | Ч/Б extra_images — fallback placeholders | T-4845, T-4855, T-4857 | targeted + Playwright |
| 8 | placeholders не DB preview assets | T-4845, T-4856 | targeted (DB) |
| 9 | после success placeholders заменяются реальными before/after | T-4845, T-4853, T-4857 | targeted + UI |
| 10 | medved_press.png реально участвует как reference | T-4846, T-4856, T-4859 | targeted + canary A |
| 11 | нет hardcoded universal 800 | T-4847, T-4848 | targeted + grep/AST |
| 12 | есть manual prompt-limit override | T-4847, T-4856 | targeted + UI |
| 13 | compiler сохраняет смысл Medved Press prompt | T-4848, T-4856 | targeted |
| 14 | prompt budget виден в UI | T-4849, T-4857 | frontend test |
| 15 | portrait mobile исправлен | T-4850, T-4851, T-4858, T-4861 | Playwright |
| 16 | landscape mobile исправлен | T-4850, T-4851, T-4858, T-4861 | Playwright |
| 17 | SaveBar не пересекает bottom-nav/more-sheet | T-4850, T-4851, T-4858, T-4861 | Playwright DOM rects |
| 18 | horizontal overflow отсутствует | T-4850, T-4858, T-4861 | Playwright |
| 19 | compact before→after работает | T-4852, T-4858, T-4861 | Playwright |
| 20 | реальный Test Style canary success | T-4859 (pre), T-4863 (live) | canary evidence |
| 21 | реальный production Style canary публикует styled cover | T-4860 (pre), T-4864 (live) | canary evidence |
| 22 | fallback ladder Summary не сломан | T-4856, T-4864 | targeted + live |

## Non-blocking notes (не противоречия, решаются по коду)

- **DDL:** контракт §4 (`preview_job_id`) требует +1 nullable column на `cover_style_profiles` (PostgreSQL; additive) либо эквивалентной provenance в существующем `task_jobs`-store. Новая таблица/очередь запрещена. Архитектор не нужен — выбор фиксируется Builder'ом в T-4844.
- **Placeholders serving:** способ отдачи Ч/Б fallback (read-only route из `extra_images` или fallback-only registry без profile preview) — свободен; acceptance — behavioral (не DB preview assets профиля). T-4845.
- **§18 count:** в блоке владельца 22 checkbox-пункта (в задании — 21). Все 22 включены.
- **extra_images:** untracked, не ignored; добавляются в git в T-4846. Это owner-provided файлы, не мусор.
- **Коммит-гигиена:** в рабочем дереве есть unrelated modified docs и untracked `node_modules/`, `package*.json`, `.playwright-mcp/`, `plans/verification_cache.json` — не стейджить; стейджить только runtime/tests + `extra_images/`.
- **OPEN — Architect needed:** нет.

## Traceability summary

- Покрыты все нумерованные разделы §0–§21 + «Главный критерий»; каждый пункт → ≥1 задача (T-4841…T-4865).
- Orphan-требований нет; orphan-задач нет (каждая задача ведёт к §-пункту или тестам/деплою/архиву).
- DoD: 22/22 покрыты.
- Reuse: `task_jobs`/cover-style job helpers, `CompiledPrompt` diagnostics, `_resolve_reference_details`, `preview_is_stale`, существующий Playwright tool, AST-guard теста `test_asap42_step2c_image_capacity.py`.
