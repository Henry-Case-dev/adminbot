# ER-08 (W18): реальные потери контекста L1, семантика лимитов и дедлайнов

**Ветка:** `feat/er08-limits-context`, база `a9fcf7f9` (= 2.58.147 + EVR2 канон +
ER-65 снимок). Коммиты: `7c3185ed` (L1/metered/дедлайны), `58342e6e` (№31 +
отчёт), `d2488cea` (правки по ревью `w18-er08-review.md`, см. §1.5).
**Решение владельца:** `plans/owner_inputs/2026-11-02-limits-economics-decision.md`.
**План-карта:** `plans/features/evol/arch/limits-residual-plan.md` (№13/14/17/24/27/29/30/31).
**Совместимость:** ASAP-EVIDENCE-ROUTING-01 v3 (контракт
`plans/features/evol/arch/evidence-routing-contract.md`, запись
`audit/w13-evidence-routing.md` §11–§12) — не нарушена: изменения касаются
ДОСТАВКИ данных и семантики счётчиков, не ослабляют safety-классы.

Все утверждения ниже проверены по коду и числам на базе `a9fcf7f9` и на
кандидате (замеры — `py -3` на фикстуре `_probe_er08_base.py`, копии проб
лежат в `WorkspaceData/runs/82f8a5b9ffe17cb4/er08-limits-context-f5e4666327d5/`).

---

## 1. Что реально терялось и что изменено (по пунктам)

### 1.1. №13/№24 — окно L1 и бюджет пакета

**Что терялось.** `L1_WINDOW_LINE_CHARS = 200` при 20 строках давал пол 200:
строка резалась `body[:cap]` — **только голова**. Второе, более важное: бюджет
пакета был код-константой `DIRECT_L1_CONTEXT_TOKENS = 1600`
(`services/direct_l1.py:684-688` до правки), выведенной НЕ из окна модели
(`auto_budget.STAGE_POLICIES` не содержал стадии L1). Из-за этого при
реалистичном окне (20 реплик × 500–700 символов) пакет переполнялся и
`_cap_context` сразу резал окно 20 → 10 строк.

**Замер ДО (база a9fcf7f9, фикстура «20 реплик, claim/контрдовод в хвосте»):**

```text
l1_context_tokens()                 = 1600
window_line_chars(20 строк)         = 200
L1_REPLY_BLOCK_CHARS                = 400
пакет                               = 7603 симв. / 1522 токена
контрдовод в хвосте 19-го сообщения = НЕ ДОСТАВЛЕН
claim в хвосте 20-го               = НЕ ДОСТАВЛЕН
claim в хвосте цитаты (reply)      = НЕ ДОСТАВЛЕН (доставлено 400 из 749)
перегрузка (длинное окно)          = 20 → 10 строк, claim в цитате НЕ ДОСТАВЛЕН
```

**Изменение (`services/direct_l1.py`):**

* `clip_body(body, cap)` (`:908`) — срез **head+tail** с маркером `CLIP_MARK`;
  используется для строк окна (`render_window_lines`), цитаты, hint-секций и
  остаточного сжатия. Длина среза не меняется — меняется состав.
* `resolve_l1_context_budget(...)` (`:980`) — бюджет из **существующего**
  Model Capacity Resolver + Stage Auto Budget: новая стадия `direct.l1`
  добавлена в `services/auto_budget.py` (`STAGE_POLICIES`, арифметика `direct`,
  safety-reserve ровно один раз). Приоритеты: явный hot-ключ
  `limits.direct_l1_context_tokens` (ручной cap оператора) → бюджет стадии из
  реального окна модели (с учётом `mandatory_tokens` систем-промпта и reserve
  вывода) → пол `L1_CONTEXT_FLOOR_TOKENS = 1600` (не хуже прежнего). Если
  L1-слот умеет откатиться на main-модель, берётся **минимум** двух окон
  (fallback-main резолвится sync-функцией `model_capacity.fallback_window_for_model`
  — второй сетевой discovery в платный путь не добавляется).
* Живая проводка: `_plan_direct_l1` (`services/direct_chat_service.py:5323`)
  и инициативный L1 (`:11856`) передают `budget_tokens=`; второй путь раньше
  вообще не передавал бюджет.
* Шаг 0 в `_cap_context` (`:1165`): прежде чем **выбрасывать** старые реплики,
  каждая строка окна укорачивается (160/120/90 символов, head+tail). Прежний
  первый шаг резал 20 → 10 строк даже при переполнении на несколько токенов.

**Замер ПОСЛЕ (тот же сценарий):**

```text
resolve_l1_context_budget(deepseek-v4-flash) = 112933 ток.
                                              (окно 131072, source=verified_registry)
window_line_chars(20 строк, этот бюджет)     = 1200   (было 200)
reply_block_chars                            = 1200   (было 400)
message_cap_chars                            = 8192   (Writer-путь 800)
пакет                                        = 14076 симв. / 2476 токенов
все 4 маркера (хвост сообщения, хвосты 19-го и 20-го, хвост цитаты) = ДОСТАВЛЕНЫ
```

Тот же сценарий при **статическом операторском** бюджете 1600 (ветка, где
hot-ключ задан явно): пакет 6943 симв. / 1494 токена, окно **20 из 20 строк**
сохранено (база: 20 строк, но 3 из 4 claim'ов терялись), все 4 маркера
доставлены. Под перегрузкой (20 × 700 симв. + hints 2000): 10 из 20 строк —
как и на базе, но claim в цитате **сохранён** (на базе терялся).

Замер масштабирования от окна: слот `qwen-max` (32768) → 27603 ток.,
`gpt-4-mini` (8192) → 6233 ток., `deepseek-v4-flash` (131072) → 112933 ток.

### 1.2. №14 — блок «ОТВЕТ НА» (reply)

**Что терялось.** Цитата резалась `text[:400]` (`direct_chat_service.py:5209`
до правки) и повторно `[:L1_REPLY_BLOCK_CHARS]` в `build_l1_context`; секция
**не входила** в protected-набор `_cap_context`, поэтому при переполнении её
обрезал фактор `0.6/0.3/0.1` головным срезом, а остаточное переполнение резало
её как «крупнейший незащищённый блок».

**Изменение.** `reply_block_chars(budget)` (`direct_l1.py:929`): доля
`L1_REPLY_SHARE = 0.10` от бюджета, пол 400 (прежний канон), потолок 1200
(класс C — цитата не превращается во второй пакет); срез head+tail
(`_l1_reply_block` → `_l1.clip_body`). Секция `L1_REPLY_SECTION` добавлена в
protected `_cap_context` и в шаг head+tail — при переполнении сжимается ОКНО,
а не цитата (это и есть цель пункта).

**Замер.** Цитата 749 символов: было доставлено 400 (claim на ~745-м терялся) →
стало 640 при статическом бюджете и 749 при динамическом.

### 1.3. №31 — слепой срез evidence у планировщика (Direct Orchestrator)

`ORCHESTRATOR_EVIDENCE_SNIPPET_CHARS = 400` даёт планеру слепой головной срез
текста инструмента. `EvidenceSource` уже несёт структурные
`status/total_chars/delivered_chars/truncated/delivered`
(`services/direct_execution.py:186-199`). **Изменение минимальное и аддитивное:**
в блок «EVIDENCE SO FAR» добавлена структурная шапка
`[tool | status=… | delivered=N/M | truncated=yes|no]`, сам сниппет остаётся
добавкой. Расход планировщика растёт на ~40 символов НА ИСТОЧНИК (числа шапки),
порядок величины не меняется; поведение плана не меняется.

### 1.4. №17 — `_CHAT_CONTEXT_MAX_CHARS = 2000` (chat_context)

**Не менялось осознанно.** Это отдельный модуль (`services/chat_context.py`) с
двумя живыми потребителями (`handlers/search.py:93`, `handlers/factcheck.py:374`);
его переход на динамический бюджет — самостоятельная правка «окно/reader»,
которая не входит в класс потерь L1 и не блокирует её. Приоритет якоря и
keep-end цепочки там уже корректны (см. план §1, №17/№18). Риск отложенной
правки ограничен: узкий factcheck-fallback и поиск получают 2000 символов,
широкий фактчек-путь идёт мимо этого лимита.

### 1.5. Правки по ревью `w18-er08-review.md` (F-4, F-5 + неблокирующие)

**F-4 — hot-значение пробивало окно модели (реальный дефект).** Было:
`floor = max(1600, l1_context_tokens())` включал hot-значение, поэтому hot был
одновременно полом и потолком — `hot=200000` при окне 131072 давал бюджет
200000, то есть запрос длиннее окна модели. Стало
(`resolve_l1_context_budget`): физическая граница — `BudgetResult.auto_input_budget`
(вход стадии до policy-капа, уже после клампа fallback-окном); итог
`budget = min(policy_budget, available)`, затем `min(·, hot)`, пол —
`min(L1_CONTEXT_FLOOR_TOKENS, available)`. Hot по-прежнему авторитетен НИЖЕ
окна, факт клампа виден в `clamped_by_window=True`.

| Сценарий (окно 131072, mandatory 400) | Было | Стало |
| --- | --- | --- |
| hot не задан | 112737 `model_window` | 112737 `model_window` |
| hot=2400 (ниже окна) | 2400 `hot` | 2400 `hot` (без клампа) |
| hot=200000 (выше окна) | **200000 `hot`** | **112737 `hot`, `clamped_by_window=true`** |
| hot=50000, неизвестная модель (окно 16384) | 50000 | **≤16384** |

**Честный `source`.** `model_window` больше не пишется, когда бюджет сужен
fallback-моделью: `source=model_window_fallback` (+ `fallback_model` в meta).
Проверка: `deepseek-v4-flash` + fallback `gpt-4-mini` → `model_window_fallback`,
бюджет = 5885 при доступном входе основной модели 112737.

**F-5 — честная граница середины сообщения (тест-валидность).** Ревью верно
указало: прежние тесты доказывали выживание ХВОСТОВЫХ маркеров, а не смыслового
контрдовода из СЕРЕДИНЫ реплики. Добавлены два теста, фиксирующие границу
явно, а не «зелёным» умолчанием:

* `test_mid_message_counterargument_at_static_1600_is_lost` — 20-строчное окно,
  реплика 755 симв., контрдовод «но на самом деле в 1017 нет функции X…» на
  позиции 325-382. При явном hot=1600 (кап строки 200: голова 120 + хвост 77)
  контрдовод **НЕ доезжает** — assert именно на это; на бюджете из окна модели
  (112737, кап 1200) — доезжает.
* `test_mid_message_counterargument_needs_budget_above_line_cap` — порог в
  числах: при 1600 и 5000 (кап 600, голова 360) не доезжает, при 5600 (кап 672,
  голова 403) доезжает; измеренный порог для этой фикстуры ≈ **5400** бюджета
  (кап 648). То есть граница — не «хвост против середины», а геометрия среза:
  `голова = 0.6 × кап_строки`, `кап_строки = 0.12 × бюджета` (при 20 строках).

**Остаточная граница, зафиксированная честно (не решена в этом слайсе).** Потолок
строки окна `L1_WINDOW_LINE_CHARS_MAX = 1200` (класс C) означает: реплика
длиннее ~1200 символов сохраняет голову 720 и хвост 477, а её СЕРЕДИНА теряется
даже на производном бюджете. Для Telegram-сообщений до 1200 символов потерь нет;
для более длинных — есть, и это отдельное решение (поднять потолок строки или
резать длинную реплику по границам предложений/claim'ов), которое меняет расход
входных токенов L1 и потому не входит в правку по ревью.

**Неблокирующие пункты ревью (сделаны):**

* `chain_meta["cost_calls"]` — «денежный» счётчик выводится рядом с `metered`
  в simple- и adaptive-цепочке, отказ `chain_cost_limit` объясняется числами.
* `plans/features/evol/audit/asap-evidence-routing-matrix.md` п.40 — убрано
  расхождение doc/код (`ORCHESTRATOR_MAX_TIME_SECONDS=90` → общий резолв
  `MCA_TOOL_CHAIN_TIMEOUT_SECONDS`, дефолт 360).
* `clip_body` — срез не попадает ВНУТРЬ URL (`_url_safe_cut`: голова тянется до
  конца URL, хвост отступает к его началу); длина среза может вырасти на длину
  URL (bounded). Тест `test_clip_body_does_not_cut_inside_url`.

---

## 2. `metered_calls` — счётчик инструментов, не деньги

**Что было.** `METERED_TOOLS` (10 инструментов) целиком попадал под
`TOOL_CHAIN_MAX_METERED_CALLS = 4` и `ORCHESTRATOR_MAX_METERED_CALLS = 4`,
поэтому 5-й read-only вызов (`execute_web_search` / `fetch_article` /
`fact_check`) отклонялся как `chain_cost_limit` («финансовая экономия»). При
этом денежные caps выключены и, по решению владельца, не являются контролем
расходов.

**Изменение (`services/tool_loop.py`, `services/direct_execution.py`):**

* `METERED_EVIDENCE_READ_ONLY = {execute_web_search, fetch_article, fact_check}`
  и `cost_limited_tool(name)` (`tool_loop.py:73-86`): «денежный» счётчик
  относится только к операциям, которые тратят деньги на производство
  результата (медиа, генерация, длинные media-конвейеры, vision).
* Лимит применяется к отдельному счётчику `cost_calls` (`tool_loop.py:595`,
  `direct_execution.py:499`); `metered` остаётся фактом метричности вызова
  (envelope/MCA-20, `chain_meta["metered"]` не меняется).
* Анти-петлевая защита сохранена и не тронута: `TOOL_MAX_TOTAL_CALLS = 6`,
  `TOOL_MAX_ROUNDS = 4`, `_TOOL_CALLS_PER_ROUND_MAX = 2`,
  `_TOOL_MAX_SAME_CALL = 2`, дедуп по отпечатку, side-effect-guard, реальные
  квоты и rate-limit провайдера в `tool_router`.

**Доказательство (тесты):** read-only поиск проходит 6 вызовов и упирается в
`chain_call_limit` (анти-петля), а не в `chain_cost_limit`; 4 платных
`summarize_video` исполняются и 5-й даёт `chain_cost_limit`; повтор того же
вызова третий раз даёт `dedup`.

**Граница (проверено кодом и тестом).** Денежный механизм
(`services/mca_money_limits.py`) сейчас **инертен**: ни один runtime-модуль его
не импортирует (`test_mca11_money_limits_round1028::test_no_runtime_callers_off_parity`,
воспроизведено на кандидате), `MCA_MONEY_LIMITS_ENABLED` по умолчанию `OFF`, а
при неизвестной цене (`price_known=false`) `check_and_reserve` не отказывает и
помечает `ceiling_exact=false`. Поэтому включение флага в будущем не может
молча срезать проверку фактов через этот путь: единственный отказ — реально
исчерпанный scope-cap, и это честное финансовое ограничение, а не «счётчик
инструментов».

---

## 3. Аудит дедлайнов: Direct Orchestrator vs Tool Chain

**Что найдено (замер ДО, база):**

```text
tool_loop chain deadline           = 360 с   (MCA_TOOL_CHAIN_TIMEOUT_SECONDS)
adaptive orchestrator deadline     =  90 с   (DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS)
ChainBudget() simple-цепочки       = 360 с   (сырая код-константа)
max_total / max_metered            = 6 / 4    (сырые код-константы)
per-tool таймауты (tool_router)    = 25 (поиск) / 45 (статья) / 180 / 300 (видео)
```

**Рассогласование подтверждено:** adaptive-цепочка обрывалась на 90 с, тогда
как tool-цепочка и собственные per-tool таймауты допускают 360 с; легитимный
план из 3–4 read-only шагов (search 25 + article 45 = 70 с на шаг) физически
не успевал и получал `chain_timeout` при живом SLA хода 360 с. Дополнительно
`ChainBudget` (simple/adaptive) игнорировал `MCA_TOOL_CHAIN_TIMEOUT_SECONDS`,
`MCA_TOOL_MAX_TOTAL_CALLS` и `MCA_TOOL_MAX_METERED_CALLS` — оператор менял
настройку, а действовала она только на один из двух путей исполнения.

**Изменение (SLA НЕ тронут):** `orchestrator_max_time_seconds()`
(`direct_execution.py:137`) по умолчанию резолвит ТОТ ЖЕ дедлайн, что и
tool-цепочка; явный `DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS` (settings/env)
остаётся операторским override. `ChainBudget` берёт timeout/total/metered из
тех же резолверов `tool_loop` (`_chain_timeout_seconds`, `_max_total_calls`,
`_max_metered_calls`).

**Замер ПОСЛЕ:** orchestrator 360 с = chain 360 с; при
`MCA_TOOL_CHAIN_TIMEOUT_SECONDS=180` — 180 с на обоих путях; при явном
override 45 с — 45 с. `ChainBudget().deadline` = now + 120 с при настройке 120,
`max_total/max_metered` = 5/3 при соответствующих настройках.

---

## 4. Видимость стоимости: неизвестная цена ≠ ноль

Учёт использования и расчётной стоимости сохранён (usage-события, `cost_usd`,
`price_known`, `price_version`, `execution_graph_source` фильтрует
`SUM(cost_usd) FILTER (WHERE price_known)`). Найдена и закрыта одна реальная
щель: метрик-витрина `mca_events.metrics` суммировала только числовой
`cost_usd` и **молча пропускала** строки без цены — сумма выглядела полной.
Теперь группа `cost` отдаёт `known_rows`, `unknown_rows`, `price_known`
(`services/mca_events.py`), т.е. «тарифа нет» видно как неизвестность.

Замер (тест `test_metrics_cost_group_marks_unknown_price`): 2 строки
(0.25 / цена известна; `None` / `price_known=false`) → `by_category.summary=0.25`,
`known_rows=1`, `unknown_rows=1`, `price_known=false`.

---

## 5. Тесты и числа

Новый файл `tests/test_er08_limits_context.py` — 27 тестов (CONTRACT/REGRESSION):
потери окна/цитаты/сообщения/hints, бюджет из окна модели, клампинг бюджета
окном (в т.ч. fallback-окно неизвестной модели), приоритет hot-ключа ниже окна,
честный `source`, честная граница середины реплики (два теста), AST-проводка
живого пути, durable-оси plan_meta, структурный статус evidence у планировщика
(№31), разделение metered/деньги + `cost_calls` в `chain_meta`, сохранение
анти-петель, граница денежных caps, дедлайны, URL-безопасный срез, видимость
неизвестной цены.

Обновлены тесты, которые утверждали ПРЕЖНИЙ контракт (счётчик платных вызовов
резал read-only поиск), — это осознанная правка под решение владельца:

| Тест | Было | Стало |
| --- | --- | --- |
| `test_tool_chains_round1026::test_metered_call_limit_four` | 4 поиска | `test_metered_call_limit_four_paid_tools` — 4 `summarize_video` |
| тот же файл | — | + `test_read_only_evidence_not_cost_limited`, `test_read_only_evidence_same_call_still_deduped` |
| `test_mca11_chain_stages_round1028::test_chain_cost_limit_maps_financial` | поиск | `summarize_video` (маппинг `financial_limit_reached` сохранён) |
| `test_asap8_v6_wc_direct_matrix::test_metered_cost_budget_exhaustion` | поиск | `summarize_video` + новый `test_read_only_evidence_not_cost_limited` |
| `test_soul1_machine_profile_no_core`, `test_soul1_composer_parity_off` | стаб без `budget_tokens` | сигнатура стаба = продакшн |

Сводные прогоны (`py -3 -m pytest ... -q -p no:randomly`):

```text
27 тестов test_er08_limits_context.py                          → 27 passed
поток-набор (er08 + evidence_window + asap7_direct_l1 +
  direct_l1_corrective_r1 + direct_l1_l1d_contract + tool_chains +
  tool_loop + mca11_chain_stages + asap8_v6_wc_direct_matrix +
  asap8_v6_wc_direct_d04 + mca13_event_contract +
  evol_evidence_routing + soul1_machine_profile + soul1_composer_parity_off)
                                                               → 425 passed

широкий срез: tests/ -k "direct or initiative or tool or l1 or evidence or
prompt or smartsearch or search or parity or cost or metered"
  кандидат (правки по ревью) → 13 failed, 3880 passed, 2 skipped
  база  a9fcf7f9              → 13 failed, 3853 passed, 2 skipped
  набор падений ИДЕНТИЧЕН: 5× test_direct_fallback_recompose_asap32,
  test_mca11_money_limits::test_no_runtime_callers_off_parity (упоминание
  модуля в docstring evidence_policy), test_mca20_rework1_f1_f2,
  6× summary_* (порядок/состояние; поодиночке проходят).
  Разница +27 passed = новые тесты ER-08.
```

Известные пред-существующие падения проекта (`test_samples_fewshot` 2,
`test_direct_fallback_recompose_asap32` 5) не затронуты.

---

## 6. Что намеренно НЕ менялось

* **Денежные caps** не включались и не расширялись (`MCA_MONEY_LIMITS_ENABLED`
  остаётся `OFF`, `mca_money_limits` не подключался к runtime).
* **SLA 360 с** не увеличен; новые числа лимитов не вводились — только доли
  существующего бюджета (`L1_REPLY_SHARE`, `L1_MESSAGE_SHARE`, `L1_WINDOW_SHARE`)
  и потолки класса C (1200 симв. строки/цитаты, 8192 симв. сообщения).
* Новый бюджетный движок не создавался: используется существующий
  `model_capacity` + `auto_budget.resolve_stage_budget` (одна стадия добавлена).
* Не тронуты: SSRF/URL-политика, RBAC/квоты/privacy, байтовые лимиты
  загрузок/vision, 4096-чанки Telegram, anti-flood инициативы, петли/breaker,
  `L1_WINDOW_MESSAGES`, `L1_PERSONA_FRAME_CHARS`, `_REPLY_CHAINS_MAX_CHARS`,
  `_CHAT_CONTEXT_MAX_CHARS` (§1.4), `TOOL_MAX_ROUNDS`,
  `_TOOL_CALLS_PER_ROUND_MAX`, `web/**`.
* Инструкции LLM не сокращались: все изменения — про доставку данных
  (ADDENDUM #3 §2.10 соблюдён).

---

## 7. Граница: что докажет только живой прогон

1. **Фактические цифры прода.** В проде эффективный бюджет зависит от
   (а) конфигурации L1-слота (`models.direct_l1_model_name` / hot-ключей),
   (б) значения hot-ключа `limits.direct_l1_context_tokens`. Если оператор
   задал этот ключ явно, он остаётся высшим приоритетом (но уже не может
   превысить окно модели — F-4), и динамика не применится: осознанная семантика
   «ручного решения», проверить наличие значения можно только на живой
   hot-конфигурации (в репозитории значения нет). Наблюдаемость:
   `plan_meta.l1_context_budget` / `l1_context_source`
   (`hot|model_window|model_window_fallback|floor`) на usage-строке
   `step="l1_planner"` + `AUTO_CONTEXT_BUDGET`/`MODEL_CAPACITY_RESOLVED`.
2. **Первая холодная резолюция capacity для L1-модели** может один раз
   выполнить discovery провайдера (таймаут 2 с, кэш 24 ч / 300 с для fallback).
   Раньше та же резолюция происходила позже в том же ходе (композер), поэтому
   суммарная стоимость хода не растёт, но относительный порядок — да. Проверяется
   только на живом провайдере (latency p95 хода).
3. **Поведение планировщика** (растёт ли заполнение `external_claims` и качество
   контрдоводов) при большем пакете — продуктовая проверка на живых ответах:
   ожидаемые оси — `input_chars`, `input_tokens` L1, доля планов с
   `external_claims`, `evidence_policy` классы.
4. **Реальный эффект снятия метered-тормоза с read-only**: сколько
   дополнительных read-only вызовов реально уходит на ход и как это меняет
   latency/стоимость у провайдера — из живых `chain_meta`/`mca_events`.
5. **Дедлайн-паритет** проявляется только на длинном evidence-ходе (3–4
   read-only шага); локальный тест доказывает совпадение значений резолверов, а
   не факт «план доехал».

## 8. Остаточные наблюдения (не блокируют этот слайс)

* **Потолок строки окна 1200 символов** (`L1_WINDOW_LINE_CHARS_MAX`, класс C):
  реплика длиннее ~1200 символов сохраняет голову 720 и хвост 477, её середина
  теряется даже на производном бюджете. Для Telegram-сообщений до 1200 символов
  потерь нет. Решение (поднять потолок строки до платформенного лимита или
  резать длинную реплику по границам предложений/claim'ов) меняет расход
  входных токенов L1 — на ревью не запрашивалось, выношу Архитектору.
* **`_CHAT_CONTEXT_MAX_CHARS = 2000`** (№17): модуль `chat_context` остаётся на
  статическом капе для поиска/узкого фактчека — отдельная правка «окно/reader».
* **Writer-путь `<Current_Question>`** по-прежнему режет сообщение на 800
  символов (`limits.chat_current_question_max_chars`) для L2/System2. Для L1
  это закрыто (кап из бюджета), для писателя — отдельное решение: смена
  байтов payload требует сверки с зафиксированным снимком сборки.
* **`ORCHESTRATOR_QUERY_CHARS = 800`** у планировщика: длинный запрос режется
  головным срезом. Не входило в класс потерь L1 (планер L1 получает полный
  текст); при желании усиливается тем же `clip_body` одной строкой.
