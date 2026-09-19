# Round 10.23 — независимый сквозной аудит @Scanner (Шаг 6)

> **Тип:** diff-based scan всего раунда (9 фич F1–F9) + инварианты + безопасность + DDL/каталог/тесты.
> **Baseline:** `731a845` (HEAD 10.22) → **HEAD `2e056e7`**, 22 коммита.
> **Дифф:** 118 файлов, **+13192 / −523** (`git diff 731a845..HEAD --stat`).
> **Проверенные спеки/ADR:** `plans/features/round1023-architecture.md`,
> `*-round1023/{spec.md,ADR-1023-*.md,tasks.md}`, отчёты `round1023_f*_reviewer.md`.
> **Метод:** чтение диффа выборочно по всем общим/новым файлам, инструментальные пробы (каталог,
> aiogram-версия, node --check), полный `pytest`.
> **R19:** код НЕ менялся, коммитов НЕТ — только этот отчёт, `global_map.md` и `audit_backlog.md`.

---

## 1. Итог

| Severity | Кол-во |
|---|---|
| **Critical** | **0** |
| **High** | **0** |
| **Medium** | **2 → 0** |
| **Low** | **4** |
| **Info** | **4** |

**Вердикт:** блокирующих (Critical/High) находок нет. Medium-находки — не блокеры Merge,
но их желательно закрыть/подтвердить до/сразу после деплоя (см. §3). **Раунд передаётся
в Merge/деплой** при условии осознанного принятия Medium-находок владельцем.

> **Follow-up (шаг 6.1, пост-аудит-полировка 10.23):** обе Medium-находки **ЗАКРЫТЫ**
> отдельным коммитом `fix(services,tests): раунд 10.23 — correlation-id изображений (M1)
> и изоляция response_mode в Stage-2 (M2) (scanner follow-up)`. Подробности — в §2.
> Low/Info оставлены как tech-debt (не меняются).

---

## 2. Findings

### Medium

#### M1. ✅ ЗАКРЫТО (follow-up). F7 × F5/F6: телеметрия изображения «отвязывается» от родительского `correlation_id` → дашборд показывает картинку вместо дерева ответа
- **Файлы:** `services/image_generation.py:465` (`maybe_handle_keyword` → `generate_and_send(...)`
  без `correlation_id`), `services/summary_generator.py:652-664` (`_deliver_rich` → `generate_image(image_prompt, chat_id=chat_id)`),
  `services/direct_chat_service.py:1295-1313` (`_image_pre_gate_block` → `maybe_handle_keyword`),
  `services/usage_events.py:139-146` (`corr=(correlation_id or new_correlation_id())`).
- **Суть:** для пре-гейта картинок прямого чата и для обложки саммари `correlation_id` не
  прокидывается. `usage_events.record` тогда генерирует НОВЫЙ id. Поскольку событие
  `step='image'` пишется ПОСЛЕ стадий Stage-1/Stage-2, именно оно становится «последним
  вызовом» — `GET /api/analytics/usage/latest` берёт его correlation и отдаёт дерево из
  **одной** ноды «Изображение», полностью пряча реальные Stage-1/Stage-2 последнего ответа.
  Для tool-пути (`tool_router._generate_image` → `generate_and_send(correlation_id=…)`) корреляция
  корректна — рассинхрон только на пре-гейте и обложке.
- **Почему важно:** это ровно тот сценарий, ради которого делался «Flow node последнего вызова»
  (F7). Для саммари с обложкой и для запросов «Бот, нарисуй…» дашборд систематически вводит в заблуждение.
- **Как исправить:** прокинуть `correlation_id` в `_deliver_rich` (он уже есть в `_run`, `summary_generator.py:259`),
  в `_image_pre_gate_block` и в `image_generation.maybe_handle_keyword`/`generate_and_send`.
- **Статус (follow-up):** ✅ закрыто. `direct_chat_service.handle` передаёт `correlation_id` в
  `_image_pre_gate_block` → `ToolContext(correlation_id=…)` → `maybe_handle_keyword` →
  `generate_and_send`; `summary_generator._run` передаёт его в `_deliver_rich` → `generate_image`.
  Регрессионные тесты: `test_pre_gate_forwards_correlation_id`,
  `test_keyword_forwards_ctx_correlation_id`, `test_cover_image_gets_summary_correlation_id`.

#### M2. ✅ ЗАКРЫТО (follow-up). F3: `response_mode` утекает в user-content Stage-2 (нарушение spec §3.1)
- **Файлы:** `services/factcheck_service.py:180` (`"content": "АНАЛИЗ (JSON):\n" + json.dumps(data, …)`),
  `services/direct_chat_service.py:945` (`"content": "СПРАВКА (JSON):\n" + json.dumps(data, …)`).
- **Суть:** spec F3 §3.1 прямо требует: «`response_mode` не попадает в user-content Stage-2».
  Однако `parse_factcheck_analysis`/`parse_direct_synthesis` кладут поле в возвращаемый dict, и
  он целиком уходит в user-сообщение Stage-2 (поле `response_mode` видно модели). Summary-ветка
  этого не делает (`digest` отдельно) — то есть поведение трёх оркестраторов рассинхронизировано.
  Тестов, фиксирующих изоляцию, нет (в `test_verbilizer_response_modes_round1023.py` проверяется
  только наличие/нормализация поля, не его отсутствие в Stage-2).
- **Почему важно:** формально нарушен заявленный инвариант изоляции рутера; служебный enum
  подмешивается в контент. Функционально безвредно, но это spec↔код дрейф.
- **Как исправить:** исключать `response_mode` (а также `cover_prompt`, если он появится в direct/factcheck)
  при сборке JSON для Stage-2, либо скорректировать spec §3.1, если утечка признана допустимой.
- **Статус (follow-up):** ✅ закрыто (выбран путь изоляции). Новый хелпер
  `system2_handoff.stage2_payload(data)` отбрасывает служебные поля (`response_mode`, `cover_prompt`);
  `factcheck_service` (Stage-2 `АНАЛИЗ (JSON)`) и `direct_chat_service` (Stage-2 `СПРАВКА (JSON)`)
  строят user-content через него. Summary-ветка и так передавала только `digest`. Тесты:
  `test_stage2_payload_strips_service_fields`, `test_stage2_user_content_excludes_response_mode`
  (фактчек и прямой чат).

### Low

#### L1. F5: `image_calls` — отдельный счётчик при том же значении лимита → двойной платный бюджет
- **Файлы:** `services/worker_budget.py:201-227` (`consume`: лимит берётся из метрики,
  `used <= limit`), `services/worker_budget.py:265-271` (`METRIC_IMAGE_CALLS` переиспользует
  `LIMIT_CALLS_*`).
- **Суть:** у `image_calls` собственный счётчик `used`, но лимит равен `llm_calls`-лимиту.
  Чат с лимитом 60 получает до 60 LLM-вызовов **плюс** до 60 генераций изображений (итого до 120 платных
  операций). ADR-1023-5 D4 сформулирован как «переиспользует существующий per-chat paid-call лимит»,
  что читается двояко (значение лимита vs общий счётчик). В ADR это уже вынесено в Open Question №1
  («подтвердить/уточнить лимит»).
- **Как исправить:** подтвердить с владельцем семантику; при желании общего капа — считать
  `llm_calls + image_calls` против одного лимита.

#### L2. F6: `_strip_safe_html` применяется и к rich-каналу → инлайновый HTML Article затирается
- **Файл:** `services/summary_generator.py:366` (`raw = _strip_safe_html(raw)` — до выбора канала),
  `services/smartmodule_utils.py:40-82` (`strip_lore_html` убирает `b/i/em/strong/u/s/…`).
- **Суть:** H2-фикс (саммари-канал не рендерит HTML) применён безусловно. Для rich-канала
  (Сценарий Б: «разрешено всё») это срезает инлайновые `<b>/<i>` из вывода Рассказчика.
  Блочные теги (`table/h1/ul`) не трогаются, поэтому ущерб частичный.
- **Как исправить:** применять strip только при канале `plain` (условие уже доступно в `_generate_two_call`).

#### L3. F5: `_download_bytes` качает URL, управляемый провайдером, без проверки хоста и без стримингового лимита
- **Файл:** `services/image_generation.py:291-301`.
- **Суть:** POST-режим доверяет `data[0].url` и делает по нему GET; проверка `max_bytes` — уже
  ПОСЛЕ полной загрузки тела в память. При компрометации/подмене провайдера возможен SSRF
  (в т.ч. на внутренние адреса) и раздувание памяти большим ответом. Провайдер/URL — admin-only
  (`models.image_base_url`), поэтому риск низкий.
- **Как исправить:** при желании — стримить с ограничением байт и/или ограничить хост/схему.

#### L4. F2: одноразовая миграция `factcheck_context_messages` шумит WARNING на каждом старте
- **Файл:** `services/config_migrations.py:255-271`.
- **Суть:** при `before`, установленном владельцем (не равно дефолту 6), функция при каждом запуске
  падает в ветку WARNING «before уже настроен владельцем — НЕ трогаем» (значение legacy остаётся
  навсегда, маркера «мигрировано» нет). Идемпотентность соблюдена, но лог-шум безвредный.
- **Как исправить:** необязательно; можно фиксировать факт миграции отдельным маркером/удалять legacy.

### Info

- **I1.** `services/thread_chain.py:127` — `for _ in range(max(1, depth))`: при `depth=0` цепочка всё
  равно возвращает 1 ход. Если `limits.chat_thread_max_depth=0` задуман как «отключить граф», текущее
  поведение отличается от ожидания (безвредно, но неочевидно).
- **I2.** `services/tool_schemas.py:241` — устаревший комментарий «итоговый tool-сет — 7 инструментов»
  (фактически 9 после F5). Doc-only.
- **I3.** Fallback-путь `SYSTEM2_*` может дать 3-й физический LLM-вызов: Stage-1 → пустой/невалидный
  Stage-2 → одиночный путь (`summary_generator._run`, `factcheck_service.check_claim`). Инвариант
  «ровно 2» относится к штатному пути; fallback задокументирован. Analytics корректно пишет `step=single`.
- **I4.** `services/image_generation.py` занесён в `SEND_ALLOWLIST`, но сканер egress
  (`test_outgoing_guard_round1022._SEND_RE`) его не находит (реальной raw-точки в файле нет —
  вызов идёт через `telegram_send.send_photo`). Также сам `bot.send_photo` не покрыт регэкспом
  сканера (паттерн `.send_photo(` отсутствует) — точка защищена «договором», а не тестом.

---

## 3. Подтверждённые инварианты (проверено независимо)

1. **physical-two-call-pipeline** — ✅. Роутер `response_mode` живёт в том же JSON Stage-1; тесты
   `test_direct_two_call_round1022`/`test_summary_two_call_round1022` фиксируют `await_count == 2`.
   F1/F6 поля (`response_mode`, `cover_prompt`) едут в Stage-1 JSON, третьего вызова нет.
2. **validator-loop без regex-реза клише** — ✅. `verbalize_validated` только бракует и регенерирует
   (≤2); `sanitize_outgoing` режет исключительно технические маркеры (`fact:\d+`, `msg:\d+`,
   reasoning-теги, target-маркер). F4-паттерны компилируются через `re.escape`, не выполняются как regex.
3. **egress-реестр** — ✅. `send_rich_message` — обёртка с `sanitize_outgoing`; `handlers/info.py`
   (существующая rich-точка справки) в `SEND_ALLOWLIST` с обоснованием; `send_photo` — тонкая обёртка
   без подписи (обосновано). Тест покрытия проходит.
4. **imported-history-immutable / manual-overrides-immutable** — ✅. `get_messages_around` — только
   SELECT; `smart_messages` не мутируется; `persona_dossier_overrides`/персоны не тронуты. F4 пишет в
   новую `anticliche_cache`, F7 — в `llm_usage_events`, F9 — в `bot_settings.content.*`.
5. **R16/R17/R18** — ✅. Секретов в диффе/трекаемых файлах нет (грепы `sk_`/`gsk_`/`ghp_`/`Bearer <token>`/
   `ssh-rsa`/`PRIVATE KEY` — только фейковые тест-фикстуры и старые `migrate_history`). `SecretMaskFilter`
   повешен на консольный handler; `httpx` приглушён до WARNING; логи фич — коды/числа/класс ошибки.
   `IMAGE_API_KEY` — secret-каталог, в сид не пишется, наружу только маска.
6. **`parse_mode=None`** — ✅. Plain-доставка не изменена; rich — отдельный `send_rich_message` без
   `parse_mode`; `deep_research` прямого чата — существующий safe-HTML «Летописца» (`escape_lore_html`).
7. **Порядок роутеров `bot.py`** — ✅. Изменения только DI-args/вызовы миграций + воркер
   (`anticliche_worker`) вне гейта; порядок роутеров не сдвинут. `web/app.py` — два новых include
   (`/api/anticliche`, `/api/analytics`) без конфликтов путей.
8. **Δ каталога** — ✅ факт `REGISTRY = 457` (было 439): F2 +2, F5 +5, F6 +1, F8 +10; `Settings`-поля 416,
   `GROUPS 96`, `_TAB_BY_GROUP 94`. Пин-тесты (`test_param_catalog`, `test_frontend_tab_mapping`) обновлены
   в тех же коммитах. `limits.factcheck_context_messages` — `hidden=True`, из UI исключён.
9. **DDL/миграции** — ✅. PG `anticliche_cache`, `llm_usage_events`, `llm_model_prices` — `CREATE/INDEX IF NOT EXISTS`
   + идемпотентные сиды (`ON CONFLICT DO NOTHING`); SQLite **не тронут (v12)**; канон-миграции info v4→v5
   (`INFO_CANON_VERSION=5`) и guide v1→v2 (`GUIDE_CANON_VERSION=2`) идемпотентны, с бэкапом `prev_*` и явным
   reset-эндпоинтом. Ручные правки гайда не затираются (drift-preserve).
10. **Безопасность** — ✅. RBAC: `/api/anticliche*` и `/api/analytics*` — global admin; `/api/info/guide/backup`
    и `/info/guide/reset` — `edit_info`. GET-режим изображений строго анонимный (ключ не уходит в query;
    httpx INFO приглушён + маскировка). SQL — только параметризованные запросы; `date_trunc`-unit из
    фиксированного whitelist. UI-рендер фраз анти-клише/аналитики — Vue mustache (экранирован); `v-html`
    только для info/guide через существующий `sanitizeHtml`/DOMPurify.
11. **aiogram** — ✅ установлен **3.31.0**, `Bot.send_rich_message` и `InputRichMessage.media` присутствуют
    (`_rich_media_supported()` true); guard остаётся defense-in-depth.
12. **Тесты** — ✅ полный прогон зелёный (см. §4); новых «тавтологичных» или ослабленных эталонов в
    изменённых старых тестах не обнаружено (правки — под новые каноны/сигнатуры, с комментариями).

---

## 4. Фактический pytest

```
.venv/Scripts/python.exe -m pytest -q --tb=line -p no:randomly
7418 passed, 1 warning in 95.99s (0:01:35)
```

Заявленные ~7418/0 **воспроизведены точно**. Единственное предупреждение —
`StarletteDeprecationWarning` (httpx с testclient), не связано с раундом.

**After follow-up (шаг 6.1):** `7418 → 7424 passed, 1 warning` (+6 регрессионных тестов
на M1/M2), 0 падений, 0 изменений в остальном поведении пайплайна.

Дополнительно: `node --check web/app.js` → OK.

---

## 5. Что проверялось по фичам (кратко)

- **F1** — единый токен `TARGET_MARKER`/`CORE`; маркер в обоих рендерах (`summary_xml` до `_escape`,
  `canonical_context`/`chat_context`), ровно один раз в `<Global_Context>`; анти-эхо в `outgoing_guard`;
  правило в 3 Stage-1 промптах; ограничение саммари (команда не в `smart_messages`) задокументировано.
- **F2** — `get_messages_around` (anchor + before/after, fail-open), keep-end бюджет `format_chat_context`
  с приоритетом якоря/цепочки, `render_reply_chains` в бюджет, `_trusted_text` без chat_context,
  per-chat глубина, правило веб-поиска, legacy-миграция.
- **F3** — enum + fail-safe `serious`, роутер только Stage-1, `compose_verbalizer_system`/`channel_enabled_rules`,
  канальные блоки (plain text-only / html-capable / rich), override буллитов для `deep_research`, kill-switch.
- **F4** — PG-кэш, memoized `get_rules`, `re.escape`-детектор, недельный воркер с fail-open статусами,
  guard пустого кэша, S10.22-4b lookbehind (в т.ч. пробел+запятая), API под global admin.
- **F5** — tool `generate_image` (9-й, в конец), POST(URL/b64)/GET(аноним) режимы, бюджет `image_calls`,
  пре-гейт ключевиков без `tool_choice`, анти-двойная генерация, секрет только env/PG.
- **F6** — `cover_prompt` в Stage-1 JSON, `sendRichMessage` (html/markdown + media), тихий фолбэк с
  даунгрейдом rich→plain по содержимому, egress-регистрация, cap 300.
- **F7** — DDL в PG, сквозной `correlation_id` Stage-1/tool/Stage-2, cost/`price_known`, TTL-кэш цен,
  retenion, fail-open API, RBAC global admin.
- **F8** — Stage-1/Stage-2 PG-промпты + режимы, `resolve_prompt` (пустота не обнуляет промпт),
  UI-табы/секции по `stage`, монитор анти-клише, `params-meta` без hidden.
- **F9** — справка v5 (`info_text.md` байт-в-байт) и guide v2, версионирование по содержимому,
  backup/reset под RBAC, runbook отката.

---

## 6. Рекомендации к шагу 7

- **Обязательных возвратов @Builder нет** (0 Critical / 0 High).
- Перед деплоем желательно: закрыть **M1** (корреляция изображений — дёшево, один параметр) и
  принять решение по **M2** (убрать `response_mode` из Stage-2 JSON либо обновить spec §3.1).
- L1–L4 и I1–I4 — не блокеры, можно вынести в tech-debt.
