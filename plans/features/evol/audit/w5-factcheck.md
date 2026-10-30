# W5 — Фактчек: доказательность + фирменный «Критический разнос»

Дельта `plans/current_task.md` §§5.1–5.4 (строки 1091–1141). Ветка `evol/impl`,
кандидат — рабочее дерево на базе `18baa36b` (без коммитов). Дата: 31.10.2026.

## 1. Итог

Фактчек остаётся доказательной проверкой утверждений, но публичный ответ
получает **отдельный явный раздел «Критический разнос»** — резкую критику
ТОЛЬКО той части тезиса, которую прогон уже признал ошибочной. Раздел
генерируется в **существующей** публичной Writer/verbalizer-фазе из той же
структуры проверенных утверждений: второго LLM-вызова, отдельной
«модели-разносчика» и дополнительного web-search нет. Речевая директива —
редактируемый заводской промпт с дословным текстом владельца, зарегистрированный
в едином EVOL-реестре (`declare_prompt` + печать ревизии). Семантический guard
детерминированный и серверный: полностью подтверждённый тезис, неполные данные,
технический сбой поиска и fallback раздела не получают.

## 2. Файлы

| Файл | Изменение |
| --- | --- |
| `services/factcheck_prompts.py` | `FACTCHECK_CRITIQUE_DIRECTIVE` (дословно «Жестко разъеби тейк автора и поясни почему он не прав.»), `FACTCHECK_CRITIQUE_HEADING`, `critique_policy_for_findings`, `critique_policy_for_verdict`, `build_critique_section_block`, `resolve_critique_directive` |
| `services/factcheck_service.py` | настройка `resolve_critique_section` (chat → global → factory, default ON), `_critique_section_block`, `_speech_style_hint`; блок раздела + Style Policy hint подключены в **три** публичные Writer-фазы (two-call Stage-2, одиночный 10.21, temporal-вербализатор) |
| `services/factcheck_renderer.py` | `split_critique_section`, `critique_publishable` (gate по вердикту), отдельный блок `<b>Критический разнос</b>` до разбора/источников, `allow_critique` (default True) в `render_factcheck`/`render_plain` |
| `services/factcheck_orchestrator.py` | `_apply_critique_section_setting`: настройка OFF → раздел снимается ДО презентации (факты/источники/оговорки остаются) |
| `services/prompt_composer.py` | `speech_style_hint(chat_id)` — активный Style Policy hint для речевых маршрутов вне композера (единственный владелец hint — `style_policy`) |
| `services/prompt_registry.py` | блок `factcheck.critique.directive` (declare_prompt, `ui=catalog_pending`), метка `factcheck-critique-w5`, печать `cfcd9009df17`, бамп `FACTORY_SET_SHA256_12` → `519663a57eb6` |
| `tests/test_evol_factcheck_critical.py` | новый контрактный набор §5.4 (8 кейсов, 9 тестов: кейс 4 параметризован) |
| `tests/test_hot_config.py`, `tests/test_unified_core_route_coverage.py` | минимальная ре-база двух пинов, которые фиксировали **старую** сборку system-промпта одиночного пути (новая санкционированная инструкция §5 меняет состав; намерение тестов — «hot-канон применён», «второго Core нет» — сохранено) |

`services/prompt_style_blocks.py` и `services/public_speech_guard.py` **не
изменялись** — см. §4.

## 3. Реальный путь payload (проверен, не предположение)

```
FactcheckRequest → resolve_claim_publication → retrieval (один поиск)
  → ветка: check_claim_envelope (temporal) | check_claim (legacy/two-call)
     ├─ two-call Stage-2: compose_verbalizer_system(base+КРИТИЧЕСКИЙ РАЗНОС,
     │   mode, "plain", character_block=Core+Expression, style_directives=Style hint)
     ├─ одиночный 10.21: канон + КРИТИЧЕСКИЙ РАЗНОС + Core/Expression + Style hint
     └─ temporal: база + КРИТИЧЕСКИЙ РАЗНОС + Core/Expression + Style hint
  → CheckedVerdict (verdict_text содержит раздел, структура не менялась)
  → _apply_critique_section_setting (OFF → раздел снят)
  → build_presentation (egress-whitelist)
  → _apply_delivery_guard (public_speech_guard)
  → render_factcheck: split_critique_section + critique_publishable
  → deliver_factcheck → send_chunked_reply(parse_mode="HTML")
```

Раздел отделяется от тела детерминированно по заголовку `Критический разнос:`
(ищется как отдельная строка ИЛИ после конца предложения — egress-guard может
схлопнуть переводы строк, раздел всё равно остаётся блоком). Renderer печатает
его своим блоком **до** «По утверждениям»/«Источники»: ссылки в раздел не
попадают, HTML/чанкинг/entity-safe доставка не ломаются.

## 4. Реальные причины и находки аудита

1. **Style не доходил до фактчека.** `speech_owner_block` отдаёт только
   speech-base + Core + Expression; Style Policy hint (`style_policy` —
   единственный владелец, слой SOUL-16) на публичных маршрутах вне композера
   отсутствовал. Итог: активные правила стиля владельца до Writer фактчека не
   доезжали. Исправлено минимально: `prompt_composer.speech_style_hint` +
   передача в `compose_verbalizer_system(style_directives=...)` и в два
   самосборных пути. Пустой hint (ось OFF/правил нет) → сборка байт-в-байт
   прежняя. Второго Core не добавлено (проверено: маркер Core ровно 1 раз).
2. **`public_speech_guard` не является причиной нейтрализации характера.**
   Guard срезает только закрытые формулы метаречи/overclaim/машинные артефакты;
   мат, ирония и резкость не входят ни в один детектор. Проверено кейсом 1:
   после `_apply_delivery_guard` раздел и его формулировки сохраняются
   байт-в-байт. Изменений в guard не требуется.
3. **`compose_verbalizer_system` уже поддерживает `style_directives`** (MCA-08
   D5, хвост rules → style) — новый сборщик не вводился.
4. **Схемы не менялись.** `FactcheckPresentation`/`CheckedVerdict` остались
   прежними (фриз W3/W5 соблюдён): раздел — структурная интерпретация текста
   Writer'а на уровне renderer'а, а не новое поле egress-контракта. Это
   сохраняет все существующие frozen-тесты схем.
5. **Реестр промптов.** Директива зарегистрирована как заводской блок
   (`declare_prompt` + метка + печать + бамп отпечатка набора): правка текста
   без бампа метки/печати роняет CI-аудит EVOL-018. `resolve_critique_directive`
   читает активную редакцию через реестр: появится PG-ключ каталога — правка
   владельца начнёт применяться сразу; до этого действует опечатанная заводская
   редакция. Скрытого второго хранилища и вечной «custom override» нет.
6. **Настройка.** `flags.factcheck_critique_section_enabled`, default **ON**
   внутри включённого фактчека, наследование — существующий механизм
   (`chat_params.get_chat_param_sourced`: chat-override → global → заводской
   дефолт). Мастер-тумблер модуля (`flags.factcheck_enabled`) не дублируется и
   не изменяется.
7. **Кеш/повторная доставка.** Кеша готовых вердиктов нет (P0-FACTCHECK-§6),
   поэтому «устаревший» раздел не переиспользуется; предохранитель двойной
   доставки (`already_delivered`) сохранён.

## 5. Семантический guard (детерминированный, не пожелание модели)

| Вердикт/условие прогона | Политика | Раздел |
| --- | --- | --- |
| `refuted` | allowed | публикуется |
| `mixed` (есть опровергнутые/недоказанные части) | allowed | публикуется, критика только ошибочных частей |
| `supported` | forbidden | инструкция Writer'у не даётся, написанный раздел отбрасывается |
| `insufficient_evidence` | forbidden | нет «разоблачения»; границы проверки честные |
| `reason_code ∈ {deadline_exceeded, provider_unavailable, source_missing}` | forbidden | технический исход, не опровержение |
| `fallback_used` / нет доказательств прогона | forbidden | нет доказанного разгрома |
| legacy one-call (структуры нет) + доказательства есть | self_assessed | Writer критикует только то, что сам назвал ошибочным; при «всё сошлось» — раздел не выводится |

Двойная защита: политика влияет на инструкцию Writer'а, а renderer-gate
(`critique_publishable`) отбрасывает раздел, даже если модель его написала.

## 6. Приёмка §5.4 — PASS/FAIL

Все кейсы offline: моковый анализатор/источники/Writer, без сети и без живых
отправок.

| # | Кейс | Результат |
| --- | --- | --- |
| 1 | `false` → обоснованный разнос + разрешённый style layer | **PASS** — директива дословно в фактическом payload, Expression-слой ровно 1 раз, отдельный `<b>Критический разнос</b>`, egress-guard сохраняет текст |
| 2 | `partially_true` → критика только опровергнутых/недоказанных | **PASS** — «Подтверждается частично», подтверждённая часть остаётся с меткой «подтверждается», раздел идёт до разбора по частям |
| 3 | `true` → нет выдуманного опровержения | **PASS** — директивы в payload нет, написанный моделью раздел отброшен, факты и источники на месте |
| 4 | `insufficient_evidence` / `source_missing` → без ложного разгрома | **PASS** — оба варианта: честный заголовок, раздела нет, «выдумал» не публикуется |
| 5 | Core/Expression активного чата → однократное попадание в фактический payload; scope/владелец источника | **PASS** — каждый маркер ровно 1 раз, `chat_id` прогона передан в резолверы, наследование `chat → global → factory` проверено на двух чатах |
| 6 | Настройка OFF → факты/источники остаются, секции нет, мастер-тумблер не тронут | **PASS** — раздел снят до презентации, тело и «Источники» сохранены, ключи осей различаются |
| 7 | Render/HTML/чанкинг/цитаты | **PASS** — ссылка в строке своего утверждения, `href` только из EvidenceMap, каждая часть чанка — валидный HTML, заголовок один раз, reply только у первой части |
| 8 | legacy/two-call/fallback (+реестр) | **PASS** — Core ровно 1 раз на обоих LLM-путях, директива 1 раз, жанровый канон на месте, fallback-текст без раздела, раздел не противоречит запретам канона, печать реестра цела |

Прогоны (cwd = рабочее дерево, интерпретатор `.venv`):

* `tests/test_evol_factcheck_critical.py` → **9 passed**;
* целевой регресс (renderer/orchestrator/w6/w7/two-call/service/prompts/
  attribution + EVOL-018 + полнота реестра + unified_core + hot_config) →
  **178 passed**;
* `-k factcheck` по всему `tests/` → **578 passed, 2 failed**; оба падения —
  `test_factcheck_post_release_w1.py::TestAggregatorFailureTaxonomy` (живой
  DuckDuckGo в провайдер-каскаде), воспроизводятся и без моих изменений
  (проверено прогоном на базовой ревизии) → pre-existing/сетевые, не связаны с
  W5.

## 7. Вне этого лейна (сознательно)

* **UI-настройка** «Критический разнос» (переключатель + редактор директивы с
  версиями + превью структуры) — отдельный лейн настроек (`web/**`,
  `services/param_catalog.py`: ключи `flags.factcheck_critique_section_enabled`
  и `prompts.factcheck_critique_directive`). Рантайм уже читает оба механизма,
  UI-зависимости в сервисе нет. Каталог не трогал: добавление ключей меняет
  пиннутые счётчики каталога и вкладок (чужой лейн).
* `handlers/factcheck.py` не менялся: настройка резолвится в сервисе по
  `chat_id`, поэтому legacy- и v2-маршруты получают её одинаково.

## 8. Остаточные риски

1. Раздел распознаётся по заголовку: если Writer напишет его без заголовка,
   текст останется в теле (раздел не появится, но и разметка не сломается);
   если заголовок встретится в теле как ссылка на раздел — сработает первый
   вариант, раздел всё равно останется отдельным блоком.
2. Качество «резкости» — поведение модели, а не тестируемое свойство (по §5.4
   ручная оценка запрещена); контрактом проверяются структура, семантика
   допустимости и голосовые слои.
3. Два stale-пина отпечатка реестра в чужих тестах (`test_p0_prompts_core.py`,
   `test_expression_isolation_followup.py` ожидают `03776db327b4`) уже падали на
   HEAD (`1ce70bfedd8c`) и остаются красными; актуальный отпечаток набора —
   `519663a57eb6` (мой бамп). Это бухгалтерия чужого лейна, не поведение W5.
