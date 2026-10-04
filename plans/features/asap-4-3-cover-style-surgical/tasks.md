# ASAP 4.3 — tasks.md (Step 0 @PM, 04.10.2026)

Feature: `asap-4-3-cover-style-surgical` — corrective pass: durable Test Style job + честный UX + atomic preview + placeholders + Medved reference + prompt limit/бюджет + mobile UI. Один feature.

**Нумерация:** **T-4841+** (T-4840 — max используемый, проверено `rg T-48`). Формат: ID, роль, цель, **критерий приёмки**, якорь, зависимости, DoD. Источник: `plans/current_task.md:25459–26361` (не изменяется). Трассировка: `requirements-map.md`. Reuse-заметки — там же (root causes).

**Порядок (owner §19):** один план → Builder → targeted tests → real canary → Reviewer → deploy → live acceptance → отчёт владельцу → MCA. Никаких 8–10 waves, никакого полного suite после каждого изменения.

**Метки:** `[REAL]` — реальный provider/публикация (mock не засчитывается); `[PENDING OWNER]` — предпосылка владельца (prod-доступ/run). DoD-ссылки — `D18-N` (в §18 фактически 22 пункта). Запрещено: ADR-волны, третья job-очередь, ещё один timeout, `+4px`-костыли, full-suite между шагами, MCA/unrelated-код.

**Коммит-гигиена:** стейджить только runtime/tests + `extra_images/` (owner-provided, сейчас untracked); НЕ стейджить unrelated modified docs и untracked `node_modules/`, `package*.json`, `.playwright-mcp/`, `plans/verification_cache.json`.

---

## Step 0 — Root cause confirmation (без правок)

- [ ] **T-4841 [@Builder]** — Подтвердить root cause по §1: прочитать файлы из списка (`web/api/cover_styles.py`, `web/app.js`, `web/index.html`, `web/static/app.css`, `services/cover_style_jobs.py`, `cover_style_edit.py`, `cover_style_pipeline.py`, `image_capabilities.py`, `image_prompt_compiler.py`, `cover_style_registry.py`, `cover_style_assets.py`, `extra_images/*`); сверить с recon-фактами (requirements-map) 6 пунктов: синхронный POST, no-op durability `run_style_preview`, неатомарный pair, seed placeholders, Medved chain/RBAC, mobile геометрия. **Критерий:** чиклист подтверждено/опровергнуто с file:line; runtime НЕ меняется; при реальном противоречии — запись в requirements-map и стоп к Архитектору (ожидаемо: нет). **Якорь:** 25494–25517. **Dep:** —. **DoD:** —.

---

## Step 1 — Builder blocks (зоны)

### Зона 1 — Durable job contract (порядок: 1a → 1b)

- [ ] **T-4842 [@Builder]** — Zone 1a: короткий start + status endpoint (§2.1/§2.2). `POST /api/cover/test-style`: access/RBAC + seeded-admin (`_assert_can_edit_seeded`), создаёт/регистрирует preview job в **существующей** инфраструктуре, возвращает `{job_id, status:"queued"}` без ожидания генерации. `GET /api/cover/test-style/{job_id}` (или существующий job endpoint без дублирования): stage/started_at/last_progress_at/provider/model/human_message/machine_reason/preview_before_url/preview_after_url; состояния queued/base_generating/base_ready/style_editing/saving_preview/completed/failed; без API keys/полных prompt; unknown job → 404. **Критерий:** start возвращается быстро (job_id до генерации); повторный status-read бесплатный; секретов/prompt нет; третья очередь не создана. **Якорь:** 25521–25606. **Dep:** T-4841. **DoD:** 1,2.
- [ ] **T-4843 [@Builder]** — Zone 1b: durable execution + resume (§2.3). Провести preview через `begin_cover_job` → `run_style_job(db=…, job_id=…, …)` → `finish_cover_job` (сейчас `run_style_preview` `services/cover_style_jobs.py:1547–1565` вызывает без db/job_id → no-op); base gen + style edit внутри job; heartbeat реального stage; provider async task id сохранять/переиспользовать (polling его), sync — внутри backend worker; hard deadline — только safety ceiling; обрыв MiniApp/рестарт: job не отменяется, продолжается тот же task, без второго paid request; reconnect дочитывает состояние. **Критерий:** stages реально проходят; reconnect/status-read не создаёт второй image request; base реально создаётся (owner §0.2). **Якорь:** 25608–25633. **Dep:** T-4842. **DoD:** 1,2,3.

### Зона 2 — Atomic preview pair

- [ ] **T-4844 [@Builder]** — Zone 2: явный preview-контракт (§4). `preview_job_id` + `preview_revision` + `preview_before_asset_id` + `preview_after_asset_id` + `preview_status=success`; пара валидна только от одного успешного job текущей revision; success — одна атомарная операция (before+after+revision+job_id); failure — pair не переписывается частично, before не становится «новым preview», случайная base не показывается примером; stale = `preview_revision != revision`; orphan-ассеты чистятся после retention. Схема: +1 nullable column `preview_job_id` на `cover_style_profiles` (additive DDL, PG) или эквивалент в `task_jobs`-store — без новой таблицы/очереди. **Критерий:** targeted 4–6 §14: atomic pair / failure keeps / stale ≠ current / no mixed pair. **Якорь:** 25661–25705. **Dep:** T-4843. **DoD:** 5,6.

### Зона 3 — Placeholders + Medved + git

- [ ] **T-4845 [@Builder]** — Zone 3a: placeholders = UI fallback (§5). Убрать запись `style_example_01/02` из `cover_style_assets`/preview-колонок сида (`services/cover_style_registry.py:742–766`); UI: есть success pair текущей revision → реальные before/after, иначе Ч/Б placeholders; имена/расширения — из фактического listing `extra_images` (не хардкод `.png`/`.jpg`); placeholders не мутируют revision, не копируются как user assets, не заменяются результатом теста; после success UI динамически меняет; failure сохраняет placeholders/last valid pair. **Критерий:** targeted 7 §14 + UI: не DB preview assets; success заменяет; failure сохраняет. **Якорь:** 25709–25743. **Dep:** T-4841. **DoD:** 7,8,9.
- [ ] **T-4846 [@Builder]** — Zone 3b: `extra_images/` в git + Medved reference (§6). (a) `git add extra_images/` — сейчас untracked, не ignored; свежий checkout и тесты получают 3 файла (medved_press.png 475 189 B, style_example_01.png, style_example_02.jpg); (b) verify цепочки: asset row → disk read → MIME/signature → reference row → реально в edit request → не подменяется placeholder → survives restart/deploy; seeded редактирует только global admin (RBAC backend). Фиксить только конкретный найденный дефект. **Критерий:** `git ls-files extra_images` → 3 файла; targeted: reference resolved + RBAC 403. **Якорь:** 25747–25768. **Dep:** T-4841. **DoD:** 10.

### Зона 4 — Prompt limit / compiler / budget

- [ ] **T-4847 [@Builder]** — Zone 4a: manual override в MiniApp (§7/§7.1 precedence-часть/§7.2). Capability резолвится per connection/provider+model+operation (generate/edit); в настройке image connection/model/operation: «Ограничение промпта» [Автоматически]/[Задать вручную] + единица символы/токены + значение; manual — высший приоритет; persistence override (сейчас только env `COVER_STYLE_CAPABILITY_OVERRIDES`); сохранение стиля не блокируется маленьким лимитом. Не переписывать generic config UI за пределами этого поля. **Критерий:** targeted 9 §14 (manual precedence) + UI-тест поля; style save разрешён. **Якорь:** 25772–25833. **Dep:** T-4841. **DoD:** 11,12.
- [ ] **T-4848 [@Builder]** — Zone 4b: observed limit + bounded retry + compact Medved (§7.1/§8). Machine-readable `maximum prompt length is N` → observed capability per provider+base_url+model+route; «prompt too long» без N → UNKNOWN; unknown не блокирует отправку; 400-retry: не слать второй paid call, если `recompiled.exceeded` или prompt не короче (`services/cover_style_jobs.py:1401–1446`); seeded Medved instruction (`services/cover_style_registry.py:59–78`, 979 chars) → компактная версия §8 с сохранением invariants (PERMsoc один, номер выпуска один, логотип по reference, references по ролям, comic/graphic-novel), обновить существующую seeded row. **Критерий:** targeted 10–11 §14; grep/AST: 800 не управляет лимитом; invariants на месте. **Якорь:** 25786–25812, 25837–25867. **Dep:** T-4847. **DoD:** 11,13.
- [ ] **T-4849 [@Builder]** — Zone 4c: prompt budget UI (§9). Под textarea: «Инструкция: N символов», «Лимит текущей модели: M / неизвестно»; после compile/test: Style / Context / Refs-meta / System / Итого …/…; UNKNOWN → «Провайдер не сообщил точный лимит. Запрос будет отправлен без искусственного ограничения.»; никакого ложного 800. Источник — существующие `prompt_diagnostics` compiled meta. **Критерий:** frontend-тест счётчиков (known/unknown) + breakdown. **Якорь:** 25871–25895. **Dep:** T-4848. **DoD:** 14.

### Зона 5 — Mobile UI

- [ ] **T-4850 [@Builder]** — Zone 5a: shell/save-area контракт (§10/§10.1/§10.2). Shell: header / scrollable main / bottom nav; save area структурно не поверх nav; `min-width:0`/`max-width:100%`/`box-sizing` для flex/grid детей; нет горизонтального overflow; Save button не обрезан; один vertical scroll owner; footer/save полностью видны; nav не перекрывает save; keyboard/safe-area один раз; без новых `bottom: Npx` без измеримого контракта. **Критерий:** Playwright geometry (T-4858) + grep: нет новых bottom-Npx костылей. **Якорь:** 25899–25963. **Dep:** T-4841. **DoD:** 15,16,17,18.
- [ ] **T-4851 [@Builder]** — Zone 5b: editor mobile контракт (§10.3). Editor занимает доступный viewport; header фиксирован как часть editor layout; body — единственный скроллер; footer `Закрыть/Сохранить стиль` всегда видим, не перекрывает body и не конфликтует с shell bottom-nav; при fullscreen editor shell navigation скрыта либо гарантированно вне usable viewport — один ясный контракт. **Критерий:** Playwright geometry editor (footer/body/nav). **Якорь:** 25965–25974. **Dep:** T-4850. **DoD:** 15,16,17.
- [ ] **T-4852 [@Builder]** — Zone 5c: compact `До → После` (§10.4). Список: `[small before] msr-chevron [small after] Название` в одной горизонтальной группе; editor mobile — компактно; картинки масштабируются от доступной ширины; стрелка — MaterialSymbolsRounded `.msr`, не текст и не отдельная строка; карточка wrapping-safe (`min-width:0`); никакого giant image wall. **Критерий:** Playwright: grouping, arrow=msr, fit; нет «огромное До / > / огромное После». **Якорь:** 25976–26004. **Dep:** T-4851. **DoD:** 19.

### Зона 6 — Test Style UX

- [ ] **T-4853 [@Builder]** — Zone 6a: polling/stages/reconnect (§11). После нажатия — stage-текст «Генерируем базовую обложку… / Применяем стиль… / Сохраняем результат…»; elapsed можно, но решение об ошибке не по elapsed; кнопка не создаёт повторный paid job при двойном тапе (`previewBusy`-контур переделать на job_id); закрыл editor и вернулся → состояние job восстанавливается (job не отменяется); после success — before/after без перезагрузки MiniApp, provider/model, «Стиль применён»; test не тратит issue number; ничего не публикуется в Telegram. **Критерий:** frontend-тесты + Playwright state flow; counter не изменён; no publish; повторный тап без нового job. **Якорь:** 26008–26036. **Dep:** T-4842, T-4844. **DoD:** 1,2,3,(9).
- [ ] **T-4854 [@Builder]** — Zone 6b: honest errors (§3). Различать: provider_error / prompt_limit_exceeded / connection_missing / browser потерял соединение / status временно недоступен; для 4–5 человеческая фраза «Потеряно соединение с сервером. Генерация могла продолжиться; пробуем восстановить состояние.» + reconnect и дочитывание job; сырой `Failed to fetch` никогда не финал; `developer_reason` — только в раскрываемых деталях. **Критерий:** frontend-тесты 5 веток; fetch-текст не итог. **Якорь:** 25637–25657. **Dep:** T-4853. **DoD:** 4.

---

## Step 2 — Targeted tests (без полного suite)

- [ ] **T-4855 [@Builder]** — Обновить тесты, пинящие старое поведение: `tests/test_asap42_step3_style_integration.py`, `tests/test_asap42_step2c2_miniapp_seeds.py`, `tests/test_extra_cover_styles_ui.py` (+ найти `rg` по `SEED_FILES`/preview seeding/`test-style` и обновить только затронутые). Не ломать не относящееся. **Критерий:** обновлённые файлы зелёные; список изменённых тестов — в evidence. **Якорь:** §5/§14 (26101–26130). **Dep:** Step 1. **DoD:** 7,8,9.
- [ ] **T-4856 [@Builder]** — Backend targeted, 12 пунктов §14: (1) start→job id быстро; (2) stages; (3) reconnect/status-read без второго image request; (4) success pair атомарна; (5) failure не меняет pair; (6) stale ≠ current; (7) placeholders не DB assets; (8) Medved reference resolved; (9) manual limit приоритет; (10) observed numeric сохраняется; (11) unknown не блокирует; (12) preview не расходует issue counter. Плюс ladder `styled→base→Rich→plain` (DoD 22). **Критерий:** 12/12 + ladder зелёные, без full suite. **Якорь:** 26105–26120. **Dep:** T-4842…T-4848. **DoD:** 5,6,7,8,11,12,13,22.
- [ ] **T-4857 [@Builder]** — Frontend targeted: Test Style не открывает file picker; `Failed to fetch` не финал; polling/reconnect; before/after только success pair; placeholders без success; prompt counters; JS syntax/build smoke (`node --check`). **Критерий:** frontend-набор зелёный. **Якорь:** 26122–26130. **Dep:** T-4853, T-4854, T-4849. **DoD:** 4,9,14.
- [ ] **T-4858 [@Builder]** — Playwright geometry: viewports `390×844`, `844×390`, `1280×800` + Telegram-like safe-area; assertions по `getBoundingClientRect()`: `scrollWidth<=clientWidth`; SaveBar и Save button полностью в viewport; нет intersection SaveBar↔bottom-nav; нет ghost more-sheet в closed state; preview before/after помещается; editor footer/body. Не ограничиваться скриншотом. Reuse/обновить `tools/ui_asap32_cover_styles_e2e.py`. **Критерий:** tool зелёный на 3 viewports, assertions приложены. **Якорь:** 26132–26153. **Dep:** T-4850…T-4852. **DoD:** 15,16,17,18,19.

---

## Step 3 — REAL canary [REAL]

- [ ] **T-4859 [@Builder]** `[REAL]` — **Canary A — Test Style** (§15): один реальный запуск Medved Press на configured production image provider. Success: base реально создана; style edit реально выполнен; Medved reference реально передан; API status → completed; UI получил обе картинки; нет `Failed to fetch`; pair записана атомарно; issue counter не изменился. Падение → чинить конкретную причину, повторить только этот canary (не full suite, не 20 identical runs). **Критерий:** canary PASS, mock не засчитывается; evidence в `plans/features/asap-4-3-cover-style-surgical/`. **Якорь:** 26161–26178. **Dep:** T-4856, T-4857. **DoD:** 20.
- [ ] **T-4860 [@Builder]** `[REAL]` — **Canary B — Production path** (§15): один реальный smoke `base cover → style edit → publish`. Доказать, что опубликована именно styled cover; `Rich + base fallback` НЕ считается успехом Style stage. **Критерий:** styled опубликована; evidence. **Якорь:** 26180–26191. **Dep:** T-4859. **DoD:** 21,(22).

---

## Step 4 — Reviewer

- [ ] **T-4861 [@Reviewer]** — Один Reviewer pass после Builder (§16): Playwright/browser — portrait, landscape, save/footer geometry, preview geometry, Test Style state flow, отсутствие file picker, нет случайной «вазы» как fallback, Ч/Б placeholders, real generated pair после success; плюс scope-check §13 (не тронуто лишнее). Без нового архитектурного аудита. Blocking defect → вернуть Builder **один раз** с reproducible case. **Критерий:** verdict + evidence; blocking-loop ≤1. **Якорь:** 26194–26212. **Dep:** T-4858, T-4859, T-4860. **DoD:** 7,9,15,16,17,18,19.

---

## Step 5 — Deploy

- [ ] **T-4862 [@DevOps]** — Deploy (§17.1–2): release/deploy по процедуре проекта, health, bump версии, rollback-заметка. **Критерий:** сервис healthy. **Якорь:** 26216–26227. **Dep:** T-4861. **DoD:** —.

---

## Step 6 — Live acceptance [REAL][PENDING OWNER]

- [ ] **T-4863 [@Orchestrator/@Builder]** `[REAL][PENDING OWNER]`(prod) — Live acceptance A: один production browser smoke MiniApp + **Canary A** на проде (телефонный flow «Проверить стиль»); issue counter не изменён; логи только вокруг run/job id. **Критерий:** полный mobile-flow на живом проде; evidence. **Якорь:** 26218–26226, 26345–26357. **Dep:** T-4862. **DoD:** 20.
- [ ] **T-4864 [@Orchestrator/@Builder]** `[REAL][PENDING OWNER]`(prod) — Live acceptance B: реальный Summary с выбранным Medved Press публикует **styled** cover (не base fallback); fallback ladder `styled→base→Rich→plain` не сломан; логи только вокруг этих run/job id. **Критерий:** styled опубликована; ladder подтверждён; evidence. **Якорь:** 26223–26225, 26257, 26359–26361. **Dep:** T-4863. **DoD:** 21,22.

---

## Step 7 — Owner report + archive + MCA resume

- [ ] **T-4865 [@PM/@Orchestrator]** `[PENDING OWNER]`(live acceptance) — Отчёт владельцу простыми словами (§20: что было сломано / что исправили / что проверили на живом боте / работает ли Medved Press Да/Нет + причина / что осталось; без hashes/task ids/тестов/fingerprints) → архивировать ASAP 4.3 → открыть `plans/current_task.md`, определить следующую незавершённую MCA-задачу → **сразу продолжить MCA** (§21); low-debt → backlog; продуктовый выбор → `ARCHITECT_DECISION_REQUIRED`. **Критерий:** отчёт выдан; архив корректен; следующая MCA определена и запущена без ожидания владельца. **Якорь:** 26284–26337. **Dep:** T-4863, T-4864. **DoD:** — (gate).

---

## PENDING OWNER (сводно)

| PO | Предпосылка владельца | Гейт |
|---|---|---|
| PO-1 | Прогон Canary B как настоящей production-публикации (если нужен доступ к прод-каналу/роли) | T-4860 |
| PO-2 | Prod-доступ (URL/сессия) для live acceptance A/B | T-4863, T-4864 |
| PO-3 | Подтверждение, что Test Style на проде не тратит issue counter и не публикует RichMessage | T-4863 |
| PO-4 | Возврат к MCA допускается только после live acceptance | T-4865 |

**Итог:** 25 задач (T-4841…T-4865). Зоны Builder: 1 (T-4842→4843) → 2 (T-4844) → 3/4/5 параллельно после T-4841 → 6 (T-4853→4854); затем tests T-4855–4858 → canary T-4859–4860 → Reviewer T-4861 → deploy T-4862 → live T-4863–4864 → отчёт/архив/MCA T-4865. `[REAL]` — T-4859, T-4860, T-4863, T-4864; `[PENDING OWNER]` — T-4863, T-4864, T-4865 (+PO-1/T-4860).
