# ASAP 4.2 — requirements-map.md (Step 1 @PM, 04.10.2026)

Feature: `asap-4-2-summary-surgical-reliability` — срочный corrective pass после ASAP 4.1. Один feature, хирургический проход (не новый слой архитектуры). Источник требований — ТЗ владельца, оно само является требованиями.

**Источник (не менять):** `plans/current_task.md:23847–25458` — блок «ASAP 4.2 — Surgical Summary Reliability, Real Provider E2E & MiniApp UX Repair», секции #0–#60, DoD 50. Прочитан полностью. `current_task.md` не изменяется (R17 + указание Orchestrator'а). Якоря валидны, пока файл append-only; SHA фиксируется при приёмке.

**Правила:** ID `R8-xxx` присвоены PM как прямая проекция текста владельца; интерпретации помечены «(PM)». Якорь = строка начала секции. Спец/ADR — Step 2 @Architect (колонка ⏳). Не создаётся отдельный conflict-audit (overkill): найденные конфликты/AMEND — в сносках ниже.

**Режим (23859–23872):** правильный порядок 23885–23898: RCA(известен) → точечные фиксы → targeted tests → локальный integration → REAL provider canary → ОДИН full suite → Reviewer browser → deploy → REAL production acceptance → MCA. Запрещённый anti-pattern 23874–23883. Max 8–10 шагов, без разрастания. Не трогать (25383–25393): SourceWindow, RichMessage renderer, Base Cover generation, GraphRAG, MCA features, history, unrelated modules.

---

## A. 9 зафиксированных production root blockers (23838–23948)

| BL | Root cause (verbatim-смысл) | R8-группа | Задачи |
|---|---|---|---|
| BL-1 | fail-closed ID/evidence validation | R8-A/B/C | T-4802…T-4805 |
| BL-2 | LLM вынуждена перепечатывать реальные Telegram IDs | R8-A | T-4802/T-4803 |
| BL-3 | один битый evidence ref уничтожает весь L2 document | R8-C | T-4805 |
| BL-4 | NanoGPT Style Edit использует неверный/неподтверждённый execution contract | R8-I | T-4812 |
| BL-5 | prompt-limit/capability discovery не доведён до рабочего runtime | R8-J | T-4814 |
| BL-6 | model-capacity resolver может быть зажат stale registry | R8-F | T-4808 |
| BL-7 | liveness abstraction есть, адаптеры почти не используют streaming/status | R8-G | T-4810 |
| BL-8 | production acceptance ASAP 4.1 не поймала дефекты | R8-P | T-4835…T-4839 |
| BL-9 | MiniApp UX-регрессии «фиксились» косметически, не root cause | R8-M | T-4823…T-4827 |

---

## B. Матрица требований (порядок владельца — 16 групп)

### (1) Source anchors self-validating + SourceAnchorMap + unassigned (#2–#3)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-A-001 | 23952 | Раw TG IDs больше не основной модельный контракт: короткие **self-validating source anchors** (пример `m00BD-K7`), создаваемые только кодом. Ordinal/base36 index внутри immutable SummarySourceWindow + suffix-checksum/tag из message_id + source/run fingerprint | fixture: LLM оперирует только anchors; raw ID не требуется; формат компактен; опечатка `m0012→m0021` не может сослаться на другое сообщение | 1,2 | T-4802 |
| R8-A-002 | 23986 | **Инварианты SourceAnchorMap:** mapping создаёт код; immutable на время run; один anchor ↔ ровно один source message; checksum валидируется кодом; битый anchor не становится другим валидным source; после validation код переводит anchors обратно в реальные IDs; mapping не попадает в публичный текст | unit: immutability, уникальность, checksum-mismatch → reject, silent alias collision невозможен, обратный перевод ID, R17 (mapping не в тексте) | 1,2 | T-4802 |
| R8-A-003 | 24000 | **`unassigned_message_ids` вычисляет код:** `mentioned = union(valid anchors)`; `unassigned = source_anchors − mentioned`. Старое поле — optional, не source of truth | unit: unassigned пересчитывается приложением; расхождение LLM-значения игнорируется; пустой/некорректный input не ломает | 3 | T-4803 |
| R8-A-004 | 23954 | LLM не обязана точно перепечатывать длинные реальные ID сотни раз; наивная плотная шкала `m000001…` без защиты запрещена | дизайн-тест: нет плотной шкалы без checksum; нет требования raw-ID от LLM | 1 | T-4802 |

### (2) L1 repair, не invalidate (#4–#6)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-B-001 | 24021 | Убрать fail-closed: один `unknown_message_id` не должен уничтожать весь L1 → fallback package. Новый flow: parse → normalize → validate anchor syntax/checksum → remove invalid locally → recompute unassigned → drop only empty dependent topic/event → semantic validation → **repaired map**. Fatal только если не осталось полезной semantic structure | fixture: 1 битый anchor → L1 usable/repaired, valid структура сохранена; missing-only → честный fatal; «1 битый → entire INVALID» невозможно | 4 | T-4804 |
| R8-B-002 | 24048 | Correction retry только для реально неремонтируемого: invalid JSON, structural schema failure, полностью пустой/непригодный output. Не делать дорогой повтор из-за 1–2 broken anchors, которые код удаляет сам. Correction prompt содержит конкретную validator reason | тесты: broken-anchor-only → НЕ retry; invalid_json/schema/empty → retry с reason; счётчик retry не растёт на ремонтируемых | 4 | T-4804 |
| R8-B-003 | 24062 | L1 остаётся компактной semantic map (index над source): topics{title, source_anchors, participants, short_hint}, events{kind, source_anchors}, relationships{optional}. Не возвращать full text/timestamps/author/chronology copy — materialize из SourceWindow | тест: L1 output без текстов сообщений/метаданных; fixture плотного окна → компактная map | 7 | T-4804 |

### (3) L2 evidence repair не убивает document (#7)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-C-001 | 24094 | Убрать `one invalid evidence ref → document=None → Legacy`. Flow: Writer draft → normalize evidence anchors → remove invalid → paragraph remains → Reviewer checks unsupported/misattributed. Paragraph без evidence после repair = reviewer signal, **не** уничтожение document | fixture: 1 битый evidence ref → документ публикуем, абзац сохранён, сигнал Reviewer выставлен; document=None только при неремонтируемом | 5 | T-4805 |

### (4) Writer → Reviewer → targeted revision + Full SourceWindow (#8–#9)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-D-001 | 24124 | Reviewer возвращает **структурированный verdict**: paragraph_id, reason (speaker/quote/number-date/unsupported/lost reply/paragraph без evidence/перепутанные люди), relevant source anchors, repair instruction | контракт-тест ReviewResult: reason-коды, anchors, instruction; находки без refs/с выдуманным ID отбрасываются | 6 | T-4806 |
| R8-D-002 | 24145 | Writer получает на revision **только** исходный paragraph + нужные source excerpts + конкретную проблему; не регенерировать всю статью; количество revision bounded | тест: локальный косяк → правка одного абзаца; whole-article regen не вызывается; revision bounded | 6 | T-4806 |
| R8-D-003 | 24157 | **Reviewer видит оригинальный SourceWindow** (semantic map/fact package — подсказки): speaker, reply, quote/paraphrase, number/date, forwarded source, timeline, major omission | §47-сценарий: Reviewer ловит wrong speaker из оригинала, которого нет в FactPackage | 7 | T-4806 |

### (5) Prompt audit (#10)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-E-001 | 24179 | Audit реальных L1/Writer/Reviewer prompts: нельзя одновременно «сырой истории у тебя нет» и «вот полное окно — оригинал истина». Старые FactPackage-only формулировки убрать; не наслаивать новый контракт поверх старого | grep/канон-тест: противоречащих инструкций нет; Writer/Reviewer-промпты ссылаются на Full SourceWindow; старые формулировки отсутствуют | 8 | T-4807 |

### (6) Capacity resolver live metadata precedence + cache key (#11–#12)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-F-001 | 24203 | Если модель физически вмещает source → `WHOLE_WINDOW` без искусственного chunking; иначе `CAPACITY_OVERFLOW` с coverage 100%. Не возвращать 50000 chars / N messages / «важные» как normal flow | §44-тесты: large → WHOLE_WINDOW; малый контекст → overflow 100% coverage; happy-path без chunking-веток | 9 | T-4808 |
| R8-F-002 | 24233 | Precedence: explicit override → verified live provider/model metadata → verified route metadata → fresh provider cache → internal registry fallback → conservative unknown. Stale family registry не занижает live capability навсегда | unit по цепочке приоритетов; fixture: live metadata сильнее stale registry; fallback последний | 10 | T-4808 |
| R8-F-003 | 24248 | Cache key = `provider + base_url + model + route/capability fingerprint`; смена provider/model/base_url инвалидирует решение | тесты: смена любого компонента → re-resolve; fingerprint в ключе; runtime 400/context-length → переоценка | 11 | T-4808 |

### (7) Output reserve capability-aware (#13)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-F-004 | 24258 | Reserve учитывает `effective_context`, `max_output`, `target_output`, `safety_margin`; не один вечный `4000` для всех, если metadata даёт реальный лимит | тест: разные модели/лимиты → разный reserve из capability; константа 4000 не основной механизм | 11 | T-4809 |

### (8) Streaming liveness (#14–#16)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-G-001 | 24273 | Для OpenAI-compatible сначала проверять реальную поддержку `stream=true`; если да: submit stream → приём SSE/events → обновление `last_activity_at` → сборка финала. Пока stream жив — запрос жив | §51 real canary: stream=true → SSE activity → last_activity обновляется → финал собран | 12 | T-4810 |
| R8-G-002 | 24290 | Не придумывать provider status API: async jobs → poll real endpoint; streaming → monitor stream; opaque sync → adaptive watchdog. Не «пинговать» несуществующий endpoint | no-ping тест: за запрос только реальные маршруты; режим следует декларации адаптера | 12 | T-4810 |
| R8-G-003 | 24302 | Hard timeout — только safety fuse, не primary health metric. Primary = provider/stream activity | тест: живой длинный stream не убивается wall-clock; явно зависший → cancel/fallback | 13 | T-4810 |

### (9) Retry multiplication контроль (#17)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-H-001 | 24316 | Один `LLMExecutionSupervisor` владеет lifecycle: primary → optional transport retry → fallback provider/model → optional fallback transport retry → final failure. Stage не запускает сверху свои ×3. Inspector показывает реальное число network attempts | тест: один logical запрос → ровно один attempt-бюджет (≤4 HTTP, ASAP 4.1 T-4612); отсутствие вложенных ×3; Inspector `network_attempts` реален | 14,17,18 | T-4811 |

### (10) NanoGPT edit: реальный provider contract + ImageProviderAdapter routes (#18–#20, #29)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-I-001 | 24334 | Production: `nano-gpt.com` / `qwen-image-3-pro` / HTTP 400. Проверить актуальный provider contract и реализовать в adapter. Не считать `/images + input_references` правильным только потому, что mock это ожидает | real canary: реальный endpoint/schema/auth/refs/response/error → HTTP 2xx + реальный image; mock не засчитывается | 14 | T-4812 |
| R8-I-002 | 24351 | Настоящий `NanoGPTImageAdapter.submit_edit` знает: edit endpoint, request schema, auth, references, response schema, error schema, sync/async, result extraction. Generic adapter — только при реально совпадающем контракте | unit/adapter-тесты под реальный контракт; no generic-invention для NanoGPT; sync/async корректно | 15 | T-4812 |
| R8-I-003 | 24368 | Интерфейс `ImageProviderAdapter`: `submit_generation / submit_edit / get_status / get_result`; provider-specific routes; никакого универсального invented `/images + input_references` для всех | контракт-тест интерфейса; маршруты резолвятся per-provider; generic route не форсится | 14,15 | T-4812 |
| R8-I-004 | 24540 | HTTP 400 body нельзя терять. Логировать безопасно: status, provider reason_code, sanitized provider error, request_id, route, model. Не логировать: key, full private prompt, data URLs/reference bytes | тест: 400-ответ → в логе есть status/route/model/reason, нет key/prompt/bytes | 16 | T-4813 |

### (11) Dynamic image prompt-limit, без hardcode 800, без [:N] (#21–#26)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-J-001 | 24383 | Не делать глобальный hardcode `800`; лимит — per `provider + base_url + model + operation/route` | grep-тест: константа 800 не управляет лимитом; резолв per-route | 18 | T-4814 |
| R8-J-002 | 24395 | `ImageModelCapabilities.prompt_limit` реально заполняется. Precedence: override → live provider metadata → live route metadata → verified adapter/docs registry → cached runtime-discovered → unknown. Machine-readable 400 (prompt max N chars) → extract N → cache → recompile → ONE retry | unit: precedence; 400-extract → cache → ровно 1 retry; prompt_limit.known на реальном маршруте | 17 | T-4814 |
| R8-J-003 | 24427 | Смена NanoGPT → другой provider: prompt limit, edit route, reference rules, capabilities определяются заново; NanoGPT-specific 800 не протекает | тест: смена provider/model → кэш/резолв заново; 800 не наследуется | 18 | T-4814 |
| R8-J-004 | 24444 | Запрещён `prompt = prompt[:800]`; компилятор работает по смысловым блокам P0 (механика edit) / P1 (стиль-бренд) / P2 (детали Summary) / P3 (декор). Сначала режется P3, затем P2 → short semantic brief; P0+P1 абсолютный приоритет | тест: нет строковых ножниц; P0/P1 не режутся; порядок сокращения P3→P2 | 20,21 | T-4815 |
| R8-J-005 | 24469 | Сокращение prompt не уничтожает идею владельца: оригинальный style prompt хранится целиком в БД; compiled runtime prompt — отдельный derivative; Inspector: Original N chars / Resolved limit M / Compiled K | DB-тест: оригинал сохранён целиком; compiled отдельно; Inspector три числа | 19 | T-4816 |
| R8-J-006 | 24487 | Если P0+P1 не помещаются — не молча обрезать: (1) validated compact semantic profile; (2) иначе `prompt_limit_exceeded`; (3) Base Cover публикуется; (4) MiniApp показывает понятную причину | тест: непомещаемый P0+P1 → `prompt_limit_exceeded`, Base Cover опубликован, понятный reason в UI | 21 | T-4815 |

### (12) Medved Press compact profile + seeds end-to-end + cover (#27–#28, #37, #42–#46)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-K-001 | 24500 | Medved Press compact profile сохраняет ядро: edit Base Cover; сохранить сцену/персонажей/композицию; modern Russian graphic novel/comic; `PERMsoc` главный title; branding `Медведь Press`; issue number; 2–3 comic plaques/callouts; supplied logo reference как branding; не плодить дубли; русский текст; печатная comic-композиция. Формулировку можно ужать — смысл нельзя | тест/manual: compact profile содержит всё ядро; регресс стиля; смысл не потерян | 22 | T-4817 |
| R8-K-002 | 24522 | Cover pipeline остаётся fail-soft: TEXT_READY → Base Cover → optional Style Edit → RichMessage → Plain. Style fail → Base; Base fail → Rich text без image; Rich fail → Plain | регресс-тесты fail-soft ladder (ASAP 4.1 T-4620 R6-F-004 сохранён) | 22,26 | T-4822 |
| R8-K-003 | 24807 | `extra_images/medved_press.png` — реальный durable reference end-to-end: `cover_style_references` (profile_id=medved_press) → `cover_style_assets` (filename, sha256, disk_path читаемый) → asset-serving API отдаёт те же bytes. Если корректно — не трогать, зафиксировать evidence; если stale/dangling — чинить конкретный defect, не создавать дубль | e2e-проверка цепочки UI↔API↔references↔assets↔bytes; sha256 совпадает с import seed; дублей нет | 23 | T-4818 |
| R8-K-004 | 24811 | `style_example_01.png` (Before) и `style_example_02.jpg` (After) реально **seeded** как default placeholders/examples (чёрно-белые намеренно) | seed-тест: оба файла импортированы и отдаются как placeholders | 24 | T-4818 |
| R8-K-005 | 24981 | UI различает `Пример` / `Последний тест`; placeholder не выдаётся за реальный результат | UI/provenance-тест: метки корректны; placeholder никогда не помечен как real test | 25 | T-4818 |
| R8-K-006 | 24909 | `Протестировать стиль` НЕ открывает File Explorer (wiring bug). Реальная семантика: safe test brief → реальная Base Cover через configured Base Cover provider/model → реальная Style Edit → две реальные картинки → Base→Styled. Не тратит issue counter; не публикует RichMessage; preview обновляется и сохраняется; при падении — последний успех не уничтожать + понятная ошибка | тест: click test-style → file picker NOT opened; upload только по явному действию; counter не потрачен; previews реальные; persist после reopen; fail → last success сохранён | 26–29 | T-4819 |
| R8-K-007 | 24996 | Reference assets UI: миниатюра, название, role description, заменить/удалить при правах; upload отделён от test-style. `medved_press.png` связан с реальным `cover_style_references.asset_id`; сквозная трассируемость | UI-тест + трассировка цепочки; upload-действие отдельно от test | 23,44 | T-4820 |
| R8-K-008 | 25032 | Medved Press — полноценный style entity (тот же contract, editor, seeded, issue numbering, refs, connection/model override), не hardcoded if/else. Seed `Графический роман Медведь Press [Пример]` редактирует только admin (backend RBAC + API + UI + `Доступы/Права`), не только disabled button. Non-admin: видеть/выбрать согласно правам, но не менять canonical definition/refs/issue/provider. Custom styles — общая permission model | RBAC-тесты backend/API/UI; non-admin не может менять seeded; custom — по общей модели | 30,31,45 | T-4821 |

### (13) MiniApp UX (#31–#40, #42–#47)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-M-001 | 24612 | Root cause перекрытия — **закрытая/minimized `.more-sheet`**, которая остаётся fixed-overlay (z-index 50, только transform translateY). Требование: при `moreOpen=false` шторка отсутствует в DOM **или** computed hidden/non-interactive; visible intersection с viewport = 0px; не перехватывает pointer/touch; не создаёт stacking overlay. Предпочтительно размонтирование (v-if/transition, как backdrop). НЕ лечить высотой `.bottom-nav`, размером кнопок, safe-area, `sticky-save bottom:+N`, padding, z-index SaveBar | Playwright геометрически (getBoundingClientRect/hit-test): closed more-sheet visible intersection = 0; SaveBar видим/кликабелен/не перекрыт; bottom-nav нормального размера | 33,34,48 | T-4823 |
| R8-M-002 | 24716 | После фикса `.more-sheet` — SaveBar contract отдельно на mobile portrait/Telegram WebView/desktop narrow/wide: доступен, не перекрывает поля, не висит бессмысленной полосой, нормальная z-index hierarchy, content доскролливается до последнего поля. Не смешивать с more-sheet багом | layout-verification на 4 viewport; SaveBar OK; это не повод двигать SaveBar пикселями | 34,35 | T-4824 |
| R8-M-003 | 24740 | Раздел «Модули»: **удалить Quick Access panel** («Быстрое управление») полностью — дублирует cards, второй набор toggle, путает. Оставить один список/сетку module cards: название, человеческое описание, status, toggle, избранное, Настроить. Не заменять другим дублем | browser/JS-тест: Quick Access отсутствует в DOM; одна карточка на модуль; toggle один | 32 | T-4825 |
| R8-M-004 | 24774 | Style list preview компактный **до открытия редактора**: before/after mini-images (Базовая обложка → После стиля), не full-size cover. Arrow — `MaterialSymbolsRounded[FILL,GRAD,opsz,wght]`, не текстовый `→`. Before/after снаружи editor dialog; в editor preview компактный, изображения с разумными max-width/height, desktop/mobile адаптивны; giant image wall удалён | browser: список компактен; arrow — Material icon; before/after виден до editor; editor не занимает экраны картинкой | 36,37,38,39 | T-4826 |
| R8-M-005 | 25081 | Human-readable naming во всех новых UI-блоках: русский нейминг, понятное краткое описание, developer key вторично, machine reason — в Developer details. Пример: «Стиль не применён: провайдер отклонил запрос.» вместо `prompt_limit_cached_adapter_miss` | UI-тест: основной вид человекочитаем; machine reason только в Developer details | 47 | T-4827 |

### (14) Тестовая стратегия (#49–#52)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-N-001 | 25148 | **Этап 1 — targeted root-cause tests** (список §49: L1 invalid anchor repair, checksum mismatch, unassigned code, L2 invalid evidence repair, targeted revision, NanoGPT edit contract + error parsing, prompt-limit discovery/cache invalidation, capacity live metadata precedence, streaming liveness, seed extra_images, preview persistence, test-style no counter/no upload, RBAC seeded, mobile bottom-layout measurements, Modules Quick Access absent). Если targeted красные — full suite не запускать | targeted-набор зелёный; список §49 покрыт | 40 | T-4828 |
| R8-N-002 | 25182 | **Этап 2 — локальный integration:** Summary synthetic SourceWindow 1000+ messages WHOLE_WINDOW→L1→Writer→Reviewer + один bad L1 anchor + один bad L2 evidence → **Hybrid survives, Legacy not used**; Style: seed→list→preview→test→update на реальных seed assets | integration-тест: Hybrid выживает, Legacy не использован; style flow end-to-end | 41 | T-4829 |
| R8-N-003 | 25223 | **Этап 3 — REAL provider canary ДО full suite (release blocker):** text canary (stream=true → SSE activity → last_activity → final content) | REAL canary зелёный; mock не засчитывается | 42 | T-4830 |
| R8-N-004 | 25238 | REAL NanoGPT Style Edit canary: real endpoint/schema/reference → HTTP 2xx → real image result. Если красный — чинить provider contract; не запускать full suite поверх нерабочего E2E | REAL canary зелёный | 43 | T-4831 |
| R8-N-005 | 25258 | **Только после canary — ОДИН full suite:** pytest, JS, F8/registry, нужные static checks. После docs-only изменений full suite не повторять | один полный прогон зелёный | 44 | T-4832 |

### (15) Browser acceptance (#48, #56)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-O-001 | 25112 | Reviewer через browser-use + Playwright: mobile (save bar не перекрыт, editor доступен, style list compact, before/after видно, modal в экране, test style без file picker), desktop (Modules без Quick Access, style card без giant image, editor читаемый, save bar без пустой полосы, before/after компакт), interaction (seeded reference, seeded before/after, test style real base+edit → previews обновлены → reopen → persist, counter не потрачен, file picker не открыт). Скриншоты/trace как evidence | browser-acceptance пройдена; evidence сохранён; геометрические проверки, не только скриншот | 39,48 | T-4833 |

### (16) Deploy + REAL production acceptance (#53–#58)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-P-001 | 25383 | Deploy на production (процедура проекта: git pull --ff-only, systemd admin_bot) | deploy выполнен, версия поднята | 49 | T-4834 |
| R8-P-002 | 25273 | **Production acceptance №1 — большой Hybrid Summary:** SourceWindow 100%, WHOLE_WINDOW если capacity позволяет, L1 usable/repaired, Writer usable, Reviewer completed, Final HYBRID, Legacy NOT USED. Один bad anchor/evidence не переводит в Legacy | реальный prod-run удовлетворяет чек-листу; evidence с метриками | 45 | T-4835 |
| R8-P-003 | 25293 | **Production acceptance №2 — Medved Press:** Base Cover ✓, Selected Style=Medved Press, reference ✓, provider/model resolved ✓, prompt limit resolved ✓, Style Edit HTTP 2xx ✓, styled image ✓, Published=Styled ✓. HTTP 400 = FAILED; публикация Base Cover доказывает только fallback | реальный prod-run; HTTP 2xx + styled cover | 46 | T-4836 |
| R8-P-004 | 25314 | **Production acceptance №3 — Test Style UX:** open card → seeded placeholders → Test style → NO file picker → real base → real styled → two previews updated → reopen → persist | реальный prod MiniApp-flow | 47 | T-4837 |
| R8-P-005 | 25332 | **Production acceptance №4 — UI:** closed `.more-sheet` 0px intersection / не перекрывает SaveBar; open работает; safe-area; keyboard; Quick Access removed; compact previews; seeds visible; RBAC correct. Скриншоты/trace как evidence | browser-use/Playwright на проде; evidence | 48 | T-4838 |
| R8-P-006 | 25353 | **Production acceptance №5 — смена model/provider logic:** change provider/model → capability cache invalidated → context/prompt limit/routes re-resolved; NanoGPT limit не протекает | integration/automation-тест; нет протечки 800 | 57 | T-4839 |
| R8-Q-001 | 25367 | **Archive запрещён до живой приёмки.** No `Approved for release` только по mocks; no archive до real Summary / real Medved edit / real Test Style; no возврат к MCA до production acceptance. Если blocker требует owner creds/денег/доступа — честно `PENDING OWNER`. Уже настроенный prod provider считается доступным для acceptance | archive выполняется только после всех live-приёмок; иначе `PENDING OWNER` | 50 | T-4840 |

### Cross-cutting — Run Inspector root-cause visibility (§28–§30)

| ID | Якорь | Требование владельца | Тестируемый критерий | DoD | Задача |
|---|---|---|---|---|---|
| R8-K-002 | 24522 | Cover pipeline fail-soft ladder (см. группу 12) | регресс lazy ladder | 22,26 | T-4822 |
| R8-I-004 | 24540 | HTTP 400 diagnostics (см. группу 10) | sanitized-лог без секретов | 16 | T-4813 |
| R8-L-001 | 24561 | **Run Inspector — root-cause visibility.** L1: input mode, source count, anchors generated, anchors repaired/dropped, correction retry, semantic map final status. L2: paragraph count, evidence refs, invalid refs repaired, review issues, revision count, final status. Style: provider, model, adapter/route, original prompt chars, compiled prompt chars, resolved prompt limit + source, references count, HTTP status, sanitized provider error, published cover styled/base/none | Inspector-карточки читают structured state; поля присутствуют; default-вид человекочитаем; R17-safe (числа/коды) | 30 | T-4804, T-4805, T-4810, T-4814, T-4816, T-4826 |

---

## C. Сноски-конфликты / AMEND (без отдельного conflict-audit)

- **AM-1:** ASAP 4.1 семантическая карта (T-4607, `schema_version` v1) использует `message_ids` (сырые TG ID). R8-A вводит self-validating anchors → **AMEND контракта L1 map** (поля `source_anchors` вместо/рядом с `message_ids`), вероятный bump `schema_version`. Требует решения @Architect (Step 2).
- **AM-2:** ASAP 4.1 T-4613 поставил Mode A/B как «контрактные слоты default OFF» (live-верификация PENDING OWNER). R8-G требует **реально работающий streaming liveness** на поддерживающем prod route → ASAP 4.2 снимает posture «слоты OFF» для подтверждённого маршрута (это extension, не fork; флаги `SUMMARY_LLM_STREAMING_MODE_ENABLED` / `SUMMARY_LLM_ASYNC_MODE_ENABLED` остаются).
- **AM-3:** `services/cover_style_edit.py` использует invented `POST {base_url}/images` + `input_references`, а mock-тесты закрепляют этот контракт. R8-I требует реальный provider contract → **замена маршрута/схемы**, mock-тесты не являются доказательством (owner 24347). Возможен конфликт с существующими тестами — переписать под реальный контракт.
- **AM-4:** `services/image_capabilities.py` уже декларирует precedence из 5 уровней и «800 не хардкод», но `prompt_limit` фактически не заполняется (unknown), поэтому `image_prompt_compiler.compile_prompt` идёт в unknown-ветку. R8-J — доработка до рабочего runtime, не новый модуль.
- **AM-5:** Inspectors/events ASAP 4.1 (T-4621–4624) — база для R8-L (root-cause visibility §30); добавляем поля (anchors repaired/dropped, provider error sanitized, original/compiled prompt), не новый продукт.

## D. DoD 50 → R8/задачи (покрытие)

| DoD | R8 | Задача | DoD | R8 | Задача |
|---|---|---|---|---|---|
| 1 | A-001/004 | T-4802 | 26 | K-006 | T-4819 |
| 2 | A-002 | T-4802 | 27 | K-006 | T-4819 |
| 3 | A-003 | T-4803 | 28 | K-006 | T-4819 |
| 4 | B-001/002 | T-4804 | 29 | K-006 | T-4819 |
| 5 | C-001 | T-4805 | 30 | K-008 | T-4821 |
| 6 | D-001/002 | T-4806 | 31 | K-008 | T-4821 |
| 7 | B-003/D-003 | T-4804/T-4806 | 32 | M-003 | T-4825 |
| 8 | E-001 | T-4807 | 33 | M-001 | T-4823 |
| 9 | F-001 | T-4808 | 34 | M-001/002 | T-4823/T-4824 |
| 10 | F-002 | T-4808 | 35 | M-002 | T-4824 |
| 11 | F-003/004 | T-4808/T-4809 | 36 | M-004 | T-4826 |
| 12 | G-001/002 | T-4810 | 37 | M-004 | T-4826 |
| 13 | G-003 | T-4810 | 38 | M-004 | T-4826 |
| 14 | I-001/003 | T-4812 | 39 | O-001 | T-4833 |
| 15 | I-002/003 | T-4812 | 40 | N-001 | T-4828 |
| 16 | I-004 | T-4813 | 41 | N-002 | T-4829 |
| 17 | J-002 | T-4814 | 42 | N-003 | T-4830 |
| 18 | J-001/003 | T-4814 | 43 | N-004 | T-4831 |
| 19 | J-005 | T-4816 | 44 | N-005 | T-4832 |
| 20 | J-004 | T-4815 | 45 | P-002 | T-4835 |
| 21 | J-004/006 | T-4815 | 46 | P-003 | T-4836 |
| 22 | K-001/002 | T-4817/T-4822 | 47 | P-004 | T-4837 |
| 23 | K-003/007 | T-4818/T-4820 | 48 | M-001/P-005 | T-4838 |
| 24 | K-004 | T-4818 | 49 | P-001 | T-4834 |
| 25 | K-005 | T-4818 | 50 | Q-001 | T-4840 |

## E. Мини-матрица (навигация)

| Requirement | Источник | Feature | Spec | Задачи | Evidence |
|---|---|---|---|---|---|
| R8-A-001…004 | 23952–24018 | anchors + SourceAnchorMap + unassigned | ⏳ @Architect | T-4802/T-4803 | ⏳ |
| R8-B-001…003 | 24021–24090 | L1 repair + compact map | ⏳ | T-4804 | ⏳ |
| R8-C-001 | 24094–24120 | L2 evidence repair | ⏳ | T-4805 | ⏳ |
| R8-D-001…003 | 24124–24176 | Reviewer verdict + targeted revision + full source | ⏳ | T-4806 | ⏳ |
| R8-E-001 | 24179–24199 | prompt audit | ⏳ | T-4807 | ⏳ |
| R8-F-001…004 | 24203–24269 | capacity resolver + output reserve | ⏳ | T-4808/T-4809 | ⏳ |
| R8-G-001…003 | 24273–24313 | streaming liveness + fuse | ⏳ | T-4810 | ⏳ |
| R8-H-001 | 24316–24331 | retry multiplication | ⏳ | T-4811 | ⏳ |
| R8-I-001…004 | 24334–24379, 24540–24557 | NanoGPT contract + routes + 400 diag | ⏳ | T-4812/T-4813 | ⏳ |
| R8-J-001…006 | 24383–24496 | dynamic prompt limit + compiler | ⏳ | T-4814/T-4815/T-4816 | ⏳ |
| R8-K-001…008 | 24500–25078 | Medved profile/seeds/style entity/RBAC | ⏳ | T-4817…T-4822 | ⏳ |
| R8-M-001…005 | 24612–25108 | MiniApp UX | ⏳ | T-4823…T-4827 | ⏳ |
| R8-N-001…005 | 25148–25269 | tests targeted→integration→canary→suite | ⏳ | T-4828…T-4832 | ⏳ |
| R8-O-001 | 25112–25349 | browser acceptance | ⏳ | T-4833 | ⏳ |
| R8-P-001…006 | 25273–25363 | deploy + prod acceptance | ⏳ | T-4834…T-4839 | ⏳ |
| R8-Q-001 | 25367–25457 | archive gate + MCA return | ⏳ | T-4840 | ⏳ |

**Coverage:** DoD 50/50 покрыт задачами; каждый Builder-таск ссылается на ≥1 R8-ID; orphan-требований нет. Спец-колонка заполняется @Architect (Step 2). Секции §28/§29/§30 и §59 (не трогать) учтены как cross-cutting (R8-K-002, R8-I-004, R8-L-001, ограничения в шапке).
