# ADR-1026-7 — S5 «L2 Писатель»: контракт §97–§99, серверный форматтер §98/§101/§102/§105, слот §82 и врезка за kill-switch

- **Статус:** Accepted (Step 2 @Architect, 23.09.2026)
- **Фича:** S5 `summary-l2-writer-formatter-round1026` (Эпик 2, этапы «L2 — Писатель» §97–§99 и «Форматирование» §100–§103/§105)
- **Тип:** backend/LLM (ровно 1 вызов L2) + детерминированный серверный форматтер (0 LLM); **Δ DDL = 0**; **Δ каталога = +1** (санкция: промпт-ключ L2)
- **Связано:** **ADR-1022-4** (Саммари two-call) — **AMEND (состав Stage-2; effective S5)**; **ADR-1023-3** (`response_mode`) и **ADR-1023-6** (`cover_prompt`, rich/plain-каналы) — **AMEND (семантика L2-пути; effective S5)**; ADR-1022-3/5 (2-вызовность), ADR-1023-1/-8, ADR-1024-4/-10, ADR-1025-8 (hotfix4) — REUSE; ADR-1013-3 (канон) — задействован; ADR-1025-24 **D4** (гейт S6/S10) — governed-by; ADR-1026-1/-2/-4 — REUSE; **ADR-1026-5** (L1-контракт, врезка S5) / **ADR-1026-6** (пакет фактов) — REUSE
- **Baseline:** HEAD `7722d66` == `origin/master`, `APP_VERSION` 2.58.23, pytest `.venv` 8737/0, JS 43/43, каталог 468/426/443/100/98/21, Δ DDL=0 (SQLite v12)

## Контекст

§80/§81 задают целевой пайплайн: фильтр → восстановление → L1 Кластеризатор → пакет фактов → L2 Писатель → форматирование → существующие `generate_image`/`sendRichMessage`. Сейчас Саммари — ровно **2 физических LLM-вызова** (Stage-1 «Редактор» → Stage-2 «Рассказчик»). ADR-1026-5 D1 уже решил: вариант (a) — L1 заменяет Stage-1, L2 заменяет Stage-2; третий вызов — блокер; AMEND ADR-1022-4 вступает в силу на S5. Открытыми остались 7 вопросов Step 1: состав §98-форматтера; слот L2 (каталог vs env-only); судьба «Рассказчика»/`PREV_*`/миграции; судьба `digest`; лимиты вывода; deploy/bump; граница врезки и гейта D4. S4 поставил `FactPackage` v1 (`service{response_mode,cover_prompt}`, `threads` без авторов, `deliverable`=ok/truncated) и follow-up'ы S3/S4.

## Решения

**D1. L2 — отдельный изолированный модуль `services/summary_l2_writer.py`; вход = пакет фактов §96, выход = структурированный документ §99; ровно 1 LLM-вызов.**
- Вход: контент-секция `FactPackage` (не `service`, не сырой лог): на тему `name`/`description`/`chronology`/`facts[].text`+`evidence_message_ids`/отобранные `fragments`, компактно (§96). Выход: `{"schema_version":1,"title":str,"paragraphs":[{"text":str,"emphasis":str|null}]}` (парсер — существующий `system2_handoff.parse_json_object`). Один вызов через существующий LLM-контур (`module="summary", step="l2_writer"`) с отдельным слотом.
- **Запрет выдуманных цитат — инструкции + пост-валидация.** Промпт запрещает цитаты и приписывание реплик. Детерминированная пост-валидация: кавычковая вставка обязана нормализованно-совпасть с текстом пакета (`facts ∪ fragments`); нет совпадения → снять кавычки (косвенная речь), выдуманная цитата не публикуется как цитата; цитата с **именованной** атрибуцией → **fail-closed** `invalid` (`quote_attribution`), т.к. в пакете нет карты автор↔текст (S4 сохранил изоляцию) и L2 не вправе приписывать реплику; повтор невозможен (3-й вызов запрещён).
- Альтернатива «только промпт, без валидации» отклонена: нарушает REQ-S5-05 (нет гарантии); «авто-переписывание валидатором» отклонено: правка прозы кодом = фабрикация; «fail-closed на любую кавычку» отклонена: избыточно рушит доставку на реальных пересказах.

**D2. Серверный форматтер `services/summary_article_formatter.py` — детерминированный код (0 LLM), rich/pain-пути и лимиты.**
- Композиция §98: `title` (H1) → опциональное вступление → абзацы событий → необязательное заключение; отдельные типы блоков не вводятся (вступление/заключение — обычные абзацы). Rich: `<img src="tg://photo?id=…">` + `<h1>` (**настоящий H1**, не жирный) + `<p>` с ≤1 `<b>`; экранирование — `sanitize_outgoing` → `html.escape(..., quote=True)` (порядок sanitize ДО escape — инвариант `telegram_send`), разрешены только `img/h1/p/b`, MarkdownV2 не смешивается. Plain (§105): `<b>title</b>` + абзацы/совместимые `<b>`-акценты через `sendMessage parse_mode="HTML"`; превышение → разбивка **по границам абзацев** (≤4096); при недоступности HTML — финальный даунгрейд в текст без разметки, без потери.
- Лимиты: `title` ≤200/одна строка; абзацев ≤ `limits.max_summary_parts` (существующий ключ) и ≤498 блоков; rich ≤32 000 символов (< Bot API 32 768/500 блоков, подтверждено core.telegram.org/bots/api, Rich Messages); абзац ≤900; `emphasis` — дословная подстрока своего абзаца, иначе снимается. Деление «промпт vs код»: тон/содержание/запреты — промпт; структура/лимиты/экранирование/эмодзи/ссылки/акценты — код.
- **Доставка — существующий механизм.** `send_rich_message` получает явный параметр `content_format="html"` (default `"auto"` = текущее поведение байт-в-байт), т.к. авто-детектор `_looks_rich` распознаёт `<h1` как markdown. `generate_image`/`build_cover_media`/`SUMMARY_COVER_MEDIA_ID`/порядок публикации (§104) — без изменений.

**D3. Слот L2 (§82): модель/провайдер/ключ — env-only; промпт — каталог +1 (санкция); UI-слот — S6.**
- `SUMMARY_L2_BASE_URL`/`SUMMARY_L2_MODEL_NAME`/`SUMMARY_L2_API_KEY` (ClassVar) + `resolve_l2_slot()` — зеркало `resolve_l1_slot` (hot-first `models.summary_l2_*`/`keys.summary_l2_api_key`; пустое поле пары → глобальная; «не выбрано» → глобальная основная модель; наследование ≠ аварийное резервирование; `dedicated`). **Δ каталога = 0.**
- Промпт — **новый PG-ключ** `prompts.summary_l2_writer_system_prompt` (группа `prompts_summary`, advanced, `synthesizer`): **Δ каталога = +1 — санкционировано** (ADR-1013-3 требует `resolve_prompt`+`PREV_*`+`PROMPT_MIGRATIONS`+эталон; §85 «один промпт — один источник»). F8 переиздаётся по штатной процедуре ADR-1026-2 (REGISTRY 468→469, categorized 443→444; Settings/GROUPS/`_TAB_BY_GROUP`/TAB_RULES без изменений).
- Kill-switch `SUMMARY_HYBRID_L2_ENABLED` (default False) — **env-only** + hot-first `flags.summary_hybrid_l2_enabled`, per-chat через `_chat_limit`; каталог — **S6** при врезке (прецедент S3: до врезки нет живого потребителя, UI не показывает фиктивные значения, §86). Лимиты вывода — существующие ключи (`limits.max_summary_parts`), новых нет.
- Альтернатива «каталог сразу (+3 модели/+1 секрет/+флаг)» отклонена: мёртвый UI до врезки и лишний Δ каталога без потребителя; S6 добавит без переработки резолвера.

**D4. Судьба «Рассказчика»/`digest`: новый L2-канон; legacy-промпты сохраняются (REUSE, не SUPERSEDE); `digest` — только OFF-путь.**
- Новый канон `SUMMARY_L2_WRITER_SYSTEM_PROMPT` **отдельный** от L1/Рассказчика; `PREV_SUMMARY_L2_WRITER_R1026` (база без финальной ступени) + идемпотентная ступень `PROMPT_MIGRATIONS` (pre-seed skip, кастом не перезаписывается) + документированный `ROLLBACK_MIGRATIONS` (new→PREV) + эталон `plans/docs/canon/architecture.md` — **одним коммитом** (ADR-1013-3).
- `SUMMARY_NARRATOR_SYSTEM_PROMPT`/ключ `prompts.summary_narrator_system_prompt` и `SUMMARY_EDITOR_SYSTEM_PROMPT` + `digest`/`system2_handoff` — **REUSE без изменений** (OFF/legacy Stage-1/Stage-2 и откат); не удаляются (§83). ON-путь не читает/не эмитит `digest`. `response_mode` на ON-пути управляет уровнем детализации, **не** legacy-блоками `MODE_CASUAL_*` (их «торопливое письмо» противоречит §97); каналы rich/plain по-прежнему решаются наличием обложки (ADR-1023-6), как в коде.

**D5. Врезка — за kill-switch; ровно 2 вызова на обоих путях; ON активируется после live-приёмки Эпика 1 (гейт D4).**
- OFF (default): `_run` идёт прежней веткой `SYSTEM2_SUMMARY_ENABLED` → `_generate_two_call`; новые модули в живом пути не импортируются; поведение **байт-в-байт**. ON: `rows → §92-payload → run_l1 (1) → build_fact_package (0) → run_l2 (1) → formatter (0) → доставка`; ровно 2 физических вызова, 3-й невозможен. ON-ветка врезается в `_run` за флагом после S1/S2; `_generate_two_call` сохраняется. В S5 ON верифицируется **на моках** (`await_count==2` для обоих путей); реальный ON — гейт S6/S10 + D4.
- Граница с публикационным гейтом: S5 меняет только генерацию/формат текста; сам публикационный ON в проде не включается (флаг OFF), поэтому гейт не открывается.

**D6. Fail-closed §106 и детерминизм.**
- `L1Result`/`FactPackageResult` не `usable`/`deliverable` → L2 **не вызывается** (`L2_SKIPPED` + reason), публикации нет. L2 `empty`/`invalid`/`error` (вкл. `quote_attribution`) → `L2_ERROR`/`SUMMARY_FAILED`, **без** legacy-фолбэка (это 3-й вызов) — пустое/выдуманное не публикуется, без бесконечных повторов. Текст готов, обложки нет → публикуется текст (§105). Классы `SUMMARY_GENERATION_FAILED`/`COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED` различимы. Детерминизм: строгий парсер, фиксированный порядок, вход не мутируется, двойной прогон байт-идентичен. ID: вход — TG `message_id` пакета; выход id не содержит (валидатор вырезает `fact:`/`msg:`/числа).

**D7. Инварианты/deploy.**
- Δ **DDL=0**; Δ **каталога=+1** (санкция D3) + переиздание F8 (ADR-1026-2); CSP/zero-build; R17/R18; §104/`generate_image`/обложка/XML/`web/**` не тронуты; §57–§75/F0–F11/S1–S4 не сломаны; логи аддитивны.
- **Deploy = ДА (T-3342 применим):** меняются рантайм-файлы (2 новых модуля; `summary_prompts.py`, `prompt_migrations.py`, `param_catalog.py`, `config/settings.py`, `telegram_send.py`) и сид нового PG-промпт-ключа → **bump `APP_VERSION` 2.58.23 → 2.58.24** + `README.md` + cache-bust; перед деплоем — минимальные §114-тесты. Альтернатива **NOT_APPLICABLE отклонена**: рантайм/каталог реально меняются, «bump без поставки» оставил бы прод/master рассинхронизированными; kill-switch OFF не отменяет поставку кода/канона и version-tracking. Откат: annotated-тег **`pre-round1026-s5`** → `7722d66` (T-3308); hard — `git revert`; **hot-OFF** — `flags.summary_hybrid_l2_enabled=false`; канон-откат — `rollback_prompt_canons` (`SUMMARY_L2_WRITER_SYSTEM_PROMPT`→`PREV_SUMMARY_L2_WRITER_R1026`).

## AMEND / REUSE-карта (полностью — spec §3/§6/§9)

| Ранее | Действие | Что именно |
|---|---|---|
| **ADR-1022-4** (Редактор→Рассказчик) | **AMEND (состав Stage-2; effective S5)** | ON: Stage-2 «Рассказчик» → L2-Писатель + серверный форматтер; OFF байт-в-байт; сохранены 2 вызова, изоляция слоя, fallback-политика, kill-switch `SYSTEM2_SUMMARY_ENABLED`, validator-loop OFF, доставка |
| **ADR-1023-3** (`response_mode`) | **AMEND (семантика L2-пути; effective S5)** | ON: режим → уровень детализации §97-совместимо, без legacy `MODE_CASUAL_*`; нормализация/эмитент (L1) — без изменений; каналы rich/plain по обложке (ADR-1023-6) |
| **ADR-1023-6** (`cover_prompt`/rich/plain) | **AMEND (формат rich-тела; effective S5)** | ON: rich-тело = `<h1>`+`<p>`/`<b>` вместо `<p>`-обёртки plain; обложка/прикрепление/`compose_cover_image_prompt`/hotfix4/§104 — без изменений |
| **ADR-1026-5 / ADR-1026-6** | **REUSE** | L1-контракт и пакет фактов не меняются; S5 — их первый потребитель (врезка) |
| **ADR-1022-3/5**, **ADR-1023-1/-8**, **ADR-1024-4/-10**, **ADR-1025-8**, **ADR-1026-1/-2/-4** | **REUSE** | 2-вызовность, канон-маркировка, hotfix4, S1/S2/S4 не переписываются |
| **ADR-1013-3** | **задействован** | Новый PG-промпт L2: `PREV_*` + миграция/ROLLBACK + эталон + байт-тесты одним коммитом |
| **ADR-1026-2** | **запускается** | Δ каталога +1 → переиздание frozen-артефактов F8 (repin/recount) |
| **ADR-1025-24 D4** | **governed-by** | ON не активируется до live-приёмки Эпика 1 (S6/S10 + D4); S5-верификация — на моках |
| **ADR-1026-7** | **НОВЫЙ, Accepted** | Step 2 @Architect |

## Последствия

- После врезки (S6, по санкции и после live-приёмки) Саммари получает H1-статью из структурированного документа, без произвольного HTML и без отдельной LLM-конвертера; сохранены ровно 2 вызова.
- Легитимная умеренная ирония сохраняется, но точность приоритетна; выдуманные цитаты не публикуются, приписанные реплики отсекаются fail-closed.
- OFF-путь и legacy-промпты/`digest` нетронуты — обратимость полная; канон-откат документирован.
- Ограничения (документируются): слот модели/флаг без UI до S6; `response_mode`-детализация — эвристика; валидация цитат не различает «цитата из пакета, но не тот автор» (в пакете нет авторства) — такие случаи попадают под `quote_attribution`-гейт только при явной именованной атрибуции; follow-up S3/S4 (L-R1026S3-1/-2/-3, R-R1026S3-1/-2, L-R1026S4-1/-2/-3, I-R1026S4-1/-2) закрываются/документируются в S5 (spec §10).

## Ссылки

- `plans/features/summary-l2-writer-formatter-round1026/{spec.md, tasks.md}`; `plans/ARCHITECTURE.md` §74/§75.
- Архивы: `plans/archive/summary-l1-clusterizer-round1026/adr-1026-5-*.md`, `plans/archive/summary-fact-package-round1026/adr-1026-6-*.md`.
- Код: `services/{summary_l1_clusterizer.py, summary_l1_contract.py, summary_fact_package.py, summary_generator.py, summary_prompts.py, prompt_migrations.py, telegram_send.py, param_catalog.py}`, `config/settings.py`.
- Внешние: aiogram **3.31.0** (`InputRichMessage`); Telegram Bot API, раздел Rich Messages (`sendRichMessage`/`InputRichMessage`/Rich HTML: `<h1>`/`<p>`/`<b>`; лимиты 32 768 символов / 500 блоков).
