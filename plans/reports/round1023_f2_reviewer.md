# Отчёт @Reviewer — раунд 10.23, Фича F2 `factcheck-deep-context-round1023`

> **Ревьюер:** @Reviewer (Senior Principal Engineer — качество / безопасность / архитектура / прод-готовность).
> **Дата:** 19.09.2026. **Шаг:** 5 (строгий аудит). **Итерации:** 1 (commit `eeb186a`) → **2 (commit `3861cf6`)** → **3 (commit `cacfbc5`)**.
>
> **ФИНАЛЬНЫЙ СТАТУС: ✅ Approved (итерация 3).**

---

# ИТЕРАЦИЯ 3 (commit `cacfbc5`, review iter2 fixes) — FINAL

> **Коммит:** `cacfbc5` — `fix(services,tests): раунд 10.23 F2 — keep-end усечение окна (якорь/after/цепочка), Low-чистка (review iter2)`.
> **Родитель:** `b1bce2c` (F3 review-iter1 уже влит). Диапазон ревью: `git diff cacfbc5^ cacfbc5` (8 файлов, +159/−59) — F3-правки не приписываю F2.
> **Метод:** полный diff фикса; адресные чтения call-site; **собственные инструментальные пробы** (keep-end: 8 000–10 000 случайных конфигураций — бюджет/якорь/newest-after/цепочка/nearest-before); целевой + полный pytest.

## Status: **Approved**

Все находки итерации 2 (R1023F2-10 High + R1023F2-11…14 Low) закрыты **по существу** и подтверждены мной независимо. `format_chat_context` переведён на keep-end с приоритетом якоря (`anchor_message_id`), проброшенным из `handlers/factcheck.py`; бюджет строго соблюдён, якорь/свежие `after`/цепочка выживают при длинных сообщениях, старые `before` вытесняются первыми. Мёртвый параметр `chat_context` удалён из `_trusted_text` (контракт зафиксирован тестом), при этом `chat_context` по-прежнему доставляется в LLM через `build_user_content`. Docstring/ADR/spec/canon синхронизированы, добавлен реальный эталон-тест байтов. Полный pytest — **7127 passed / 0 failed** (заявленные 7120 не воспроизвёл; расхождение в сторону большего числа тестов, 0 failed — всё зелёное).

**Сводка итерации 3:** 0 Critical / 0 High / 0 Medium / 3 Low (остаточные, не блокирующие).

## Проверка keep-end (инструментальные пробы)

| Свойство | Результат |
|---|---|
| Бюджет `len(out) ≤ max_chars` | **0 нарушений** на 8 000 конфигураций (max_chars 200…4000) и на 10 000 (300…4000) |
| Якорь выживает, когда его строка влезает | **0 пропусков** (`anchor_miss=0`) |
| Новейший `after` выживает (anchor + after в бюджете, без цепочки) | **0 пропусков** (`miss_newest_after=0`; keep-end по `after`) |
| `<reply_chains>` сохраняется, когда влезает после якоря | **0 пропусков** (`chain_miss=0`) |
| Старые `before` вытесняются первыми | подтверждено детерминированно: `B1/B6` отсутствуют, ближний `B4` сохранён при наличии места |
| Приоритет (якорь → цепочка → свежие after → ближние before) | подтверждён: `miss_nearest_before` возникает лишь когда бюджет занят `after`/цепочкой — это и есть заданный приоритет |
| Обратная совместимость (`anchor_message_id=None`) | keep-end по окну; вызовы без параметра работают (`handlers/search.py`, `tests/test_epic65.py`) |

Детерминированный кейс (13 сообщений ~200+ симв., `max_chars=1800`, цепочка): `len=1731 ≤ 1800`, `ANCHOR=True`, `A13=True`, `CHAIN=True`, `B1/B6=False`.

## Находки итерации 3 (Low, не блокирующие)

### [Severity: Low] R1023F2-15 — Порядок приоритета в docstring/ADR переставлен местами (код верен)
**File:** `services/chat_context.py:78-81`; `plans/features/factcheck-deep-context-round1023/ADR-1023-2.md` (Decision 5).
**Problem:** Docstring/ADR утверждают порядок «якорь → **свежие after** → **reply_chains** → before», тогда как код (и задание итерации 3, и inline-комментарий `# 2) … цепочка резервируется СРАЗУ`) использует «якорь → **reply_chains** → свежие after → before».
**Why it matters:** Только документация; поведение — то, что требовалось (цепочка важнее after). Future-правка может «исправить» код под неверный doc.
**Required fix:** Привести формулировку в docstring и ADR к фактическому порядку (цепочка перед after).

### [Severity: Low] R1023F2-16 — Строка-якорь длиннее бюджета → якорь вытесняется
**File:** `services/chat_context.py` (`if anchor_idx is not None and len(rendered[anchor_idx][0]) <= content_budget`).
**Problem:** Если единственная строка-якорь (гигантское сообщение) превышает `content_budget`, она не сохраняется вовсе; остаётся keep-end `after`/`before`.
**Why it matters:** Поведение задокументировано («сохраняем, если влезает хотя бы один»), а текст якоря и так приходит в `<claim>`, поэтому не блокирует. Но при желании можно транкировать саму строку якоря.
**Required fix:** Опционально — транкировать тело строки якоря, а не отбрасывать; либо явно зафиксировать в ADR как принятое ограничение.

### [Severity: Low] R1023F2-17 — Для `handlers/search.py` направление усечения изменилось на keep-end
**File:** `handlers/search.py:89` (`format_chat_context(rows)` — без `anchor_message_id`).
**Problem:** Общая функция при отсутствии якоря теперь сохраняет **свежие** строки вместо **старых** (до-F2 было keep-oldest). Для поискового контекста это, скорее, улучшение, но изменение поведения нигде для search не зафиксировано.
**Why it matters:** Скрытый поведенческий сдвиг в смежном модуле (F2 трогает общую функцию).
**Required fix:** Отметить в отчёте/ADR, что для search-пути без якоря усечение стало keep-end (осознанно), либо покрыть тестом `test_epic65` явное ожидание.

## Регресс-проверка итерации 3

| Код итерации 2 | Статус | Доказательство |
|---|---|---|
| **R1023F2-10** (High, keep-end) | **Закрыт** | Новый алгоритм: якорь-приоритет, keep-end `after`, цепочка из остатка, `before` от ближнего; `anchor_message_id` проброшен из `handlers/factcheck.py:81`. Пробы: budget_viol=0, anchor_miss=0, newest_after_miss=0, chain_miss=0. Тесты `test_keep_end_anchor_after_chain_survive_long_messages`, `test_keep_end_keeps_nearest_before_when_room`. |
| **R1023F2-11** (docstring + эталон-тест) | **Закрыт** | Честный docstring; реальный байтовый эталон `test_small_window_exact_reference_bytes`; `test_no_chain_equals_empty_string_default` больше не выдаёт себя за легаси-эталон. |
| **R1023F2-12** (мёртвый параметр) | **Закрыт** | `_trusted_text(rag, results, tool_context)` — параметр удалён; тест `test_trusted_text_has_no_context_param` фиксирует контракт; `test_context_still_delivered_to_llm_user_content` подтверждает, что `chat_context` по-прежнему идёт в LLM через `build_user_content`. |
| **R1023F2-13** (комментарий отката) | **Закрыт** | `prompt_migrations.py:168-175` актуализирован: откат снимает только ступень F3, F2-правило веб-поиска сохраняется (в стеке F1→F2→F3). |
| **R1023F2-14** (spec↔ADR) | **Закрыт** | `spec.md §3.1` синхронизирован с ADR по guard'ам миграции (legacy==дефолт → skip; документированное ограничение `before==дефолт`). |

**Инварианты (финально):**
- `imported-history-immutable` — **OK** (`database.py` не менялся; только READ).
- Порядок роутеров/миграций `bot.py` — **OK** (`bot.py` не менялся).
- R16/R17/R18 — **OK** (логи без raw-сообщений/секретов).
- egress-реестр / `parse_mode=None` — **OK** (не тронуты).
- Δ каталога — **OK**: REGISTRY 441 / Settings 411 / categorized 416, GROUPS 92 / TAB_RULES 20.
- Канон-атомарность — **OK** (ADR/spec/canon синхронны в коммите).
- `physical-two-call-pipeline` — **OK** (`check_claim` по-прежнему 2 вызова; `chat_context` доставляется в Stage-1 user-content).

**Тесты (прогнано мной, `.venv`, Python 3.12.0):**
- `pytest -q -k "factcheck or thread_chain or catalog or memory_core_round1020 or webapp_api or epic65 or target_marking"` → **566 passed / 0 failed**.
- Полный `pytest -q` → **7127 passed / 0 failed**, 1 warning (сторонний `StarletteDeprecationWarning`). Заявленные @Builder 7120 не воспроизвёл (у меня больше на 7 при 0 failed) — расхождение несущественно, но стоит выровнять baseline.
- Рабочее дерево: незакоммиченных правок кода нет (только `plans/**`), что соответствует коммиту.

**Вердикт:** F2 готова к приёмке. Остаточные Low (R1023F2-15…17) — документация/edge, не блокируют; рекомендуется устранить при следующем касании файла.

---
---

# ИТЕРАЦИЯ 2 (commit `3861cf6`, review iter1 fixes) — история

> **Коммит:** `3861cf6` — `fix(services,handlers,tests): раунд 10.23 F2 — бюджет reply_chains, fail-open, паритет глубины, grounding-якоря (review iter1)`.
> **Родитель:** `01cb839` (F3 уже влит). Диапазон ревью: `git diff 01cb839 3861cf6` (12 файлов, +398/−52).
> **Метод:** полный diff фикса; адресные чтения; **инструментальные пробы** (`format_chat_context` на 4000 случайных конфигурациях, проверка truncation-direction, сравнение с до-фиксовым алгоритмом); целевой + полный pytest.

## Status: **Changes Requested**

Все находки Итерации 1 (R1023F2-01…09) закрыты **по существу** и подтверждены мной — это честно и качественно. Но при проверке бюджета (главного High итерации 1) обнаружен **унаследованный, но теперь критичный** дефект политики вытеснения окна: `format_chat_context` режет окно со стороны **старейших** сообщений, поэтому при длинных сообщениях из `<chat_context>` **исчезают якорь и все `after`-сообщения, а также целиком `<reply_chains>`**. Бюджет при этом соблюдён (≤ `max_chars`), но именно то, ради чего фича делалась, не доходит до модели. Политика противоречит docstring («старые вытесняются первыми») и критерию приёмки spec §7. Тестов на это нет.

**Сводка итерации 2:** 0 Critical / **1 High** (R1023F2-10) / 0 Medium / 4 Low (R1023F2-11…14).
**Ранее открытые (итерация 1):** R1023F2-01…09 — **все закрыты** (детали в §«Регресс-проверка итерации 2»).

---

## Находки итерации 2

### [Severity: High] R1023F2-10 — Окно вытесняется со «старейшего» конца → якорь, `after` и `<reply_chains>` пропадают при длинных сообщениях
**File:** `services/chat_context.py`
**Location:** `format_chat_context`, стр. 103–124 (цикл накопления), стр. 121–122 (`break`).
**Problem:** Цикл идёт по `rows` в ASC (старые → новые) и **обрывается на первом переполнении**, оставляя уже накопленные (самые старые) строки:
```python
for row in rows:                      # ASC: BEFORE…, anchor, AFTER…
    ...
    if total + len(line) + 1 > content_budget:
        break                          # ← останавливает на «BEFORE», якорь/after уже не попадут
    lines.append(line)
```
При `content_budget ≈ 1850` (2000 минус обёртка) и сообщениях по ~300 символов (Telegram допускает 4096) окно из 6 before + якорь + 6 after не влезает — и сохраняются **только самые старые `before`**. Инструментальная проба (13 сообщений ~330 симв. + цепочка):
```
len(out)=1806  ANCHOR=False  AFTER=False  chain=False  <reply_chains=False
```
То есть при длинных репликах: (1) якорь-сообщение отсутствует в `<chat_context>`; (2) все `after`-сообщения выброшены; (3) `<reply_chains>` не вставляется вовсе (`chain_limit = content_budget − len(body) − 1` ≤ 0 → `_truncate_reply_chains` возвращает `""`).
**Why it matters:** Критерий приёмки spec §7 — «Фактчек получает N сообщений до **и** N после целевого; цепочки реплаев инжектируются». Для длинных сообщений (частый случай) фича **молча деградирует до «несколько старых сообщений до»**: ни после-контекста, ни цепочки. Бюджет не «обходится» (это подтверждено), но enforcement бюджета уничтожает полезную нагрузку. Docstring при этом утверждает обратное («старые сообщения вытесняются первыми», стр. 76–77), т.е. код противоречит и тексту, и замыслу. Ни один тест не проверяет выживание якоря/`after` при длинном окне.
**Required fix:** Сменить политику на **keep-end** (как уже сделано для цепочки): вытеснять самые старые `before` первыми, сохраняя якорь и наиболее свежие `after` — например, накапливать строки и при переполнении удалять с головы (`while total > content_budget: total -= len(lines.pop(0))+1`), либо проходить с конца и разворачивать. Добавить тест: длинное окно (сообщения по 300+ символов) → в выводе присутствуют якорь и последнее `after`, а старые `before` вытеснены; `reply_chains` присутствует, если остаётся бюджет. Обновить/подтвердить docstring.

---

### [Severity: Low] R1023F2-11 — Docstring всё ещё обещает «байт-в-байт прежний вывод», а новый бюджет меняет усечение для больших окон; тест лег-байтов тавтологичен
**File:** `services/chat_context.py:88-91`; `tests/test_factcheck_deep_context_round1023.py` (`test_no_chain_byte_for_byte_legacy`).
**Problem:** Инвариант «`reply_chains=""` → байт-в-байт прежний вывод» больше не выполняется: новый `content_budget` резервирует место под обёртку, поэтому длинные окна усекаются иначе. Проба сравнения нового кода с до-фиксовым алгоритмом на 2000 случайных длинных окнах дала **366 расхождений** (старый мог выдавать до `max_chars + обёртка` ≈ 2124 при `max_chars=2000`). Новое поведение корректнее (строго ≤ `max_chars`), но заявление в docstring неверно. Тест `test_no_chain_byte_for_byte_legacy` сравнивает новую функцию с ней же (`format_chat_context(rows)` vs `format_chat_context(rows, reply_chains="")`) — тавтология, инвариант не проверяет.
**Why it matters:** Документация врёт, а «эталонный» тест создаёт ложную уверенность ровно вокруг контракта F1/F2 о неизменности вывода.
**Required fix:** Либо восстановить точное легаси-поведение при `reply_chains=""` (не резервировать обёртку, когда цепочки нет), либо переформулировать docstring («усечение может отличаться для окон сверх бюджета») и заменить тест реальным сравнением с зафиксированным эталоном.

---

### [Severity: Low] R1023F2-12 — `_trusted_text` сохраняет неиспользуемый параметр `chat_context`
**File:** `services/factcheck_service.py` (`_trusted_text`, ~стр. 210–222).
**Problem:** После R1023F2-04 `chat_context` в теле функции не используется (намеренно исключён), но параметр остался и передаётся обоими call-site.
**Why it matters:** Мёртвый параметр провоцирует будущего разработчика вернуть его в `parts` «для симметрии» и снова открыть R1023F2-04.
**Required fix:** Убрать параметр (и поправить call-site) либо явно пометить `# noqa: ARG001` с комментарием, почему он сохранён.

---

### [Severity: Low] R1023F2-13 — Устаревший комментарий отката в `prompt_migrations.py` (конфликт со F3-ступенью)
**File:** `services/prompt_migrations.py:171-172` vs `:178`.
**Problem:** Комментарий гласит: «F2: Аналитик откатывается на непосредственный прежний канон F1 (`PREV_FACTCHECK_ANALYST_R1023_F2`)», а код откатывает на `PREV_FACTCHECK_ANALYST_R1023_F3` (F3 влит поверх и переопределил цель). Т.е. F2-откат на F1-слепок больше не выражен напрямую.
**Why it matters:** Аудит F2 (и аварийный откат по документации) вводит в заблуждение. Функционально это корректное поведение стека F2→F3, но комментарий принадлежит F2-следу.
**Required fix:** Обновить комментарий (откат снимает только ступень F3, F2-правило веб-поиска сохраняется), либо добавить в `ROLLBACK_MIGRATIONS` явную вторую ступень для F2 при необходимости.

---

### [Severity: Low] R1023F2-14 — `spec.md §3.1` не отражает уточнённый guard миграции
**File:** `plans/features/factcheck-deep-context-round1023/spec.md` (bullet legacy).
**Problem:** В spec осталось «переносит значение в `before`, если `before` не задан», тогда как фактический guard (и ADR) добавлены условия «legacy == своему дефолту → skip» и «`before` == дефолту → переносим». ADR обновлён, spec — нет.
**Why it matters:** Расхождение spec↔ADR по контракту миграции — при следующем аудите будет неясно, какое поведение эталон.
**Required fix:** Синхронизировать bullet spec §3.1 с ADR §Decision 2 / §«Известные ограничения».

---

## Регресс-проверка итерации 2 (что подтверждено)

| Код итерации 1 | Статус | Доказательство |
|---|---|---|
| **R1023F2-01** (High, бюджет) | **Закрыт** | `format_chat_context` считает обёртку + окно + цепочку; `_REPLY_CHAINS_MAX_CHARS=1200`. Проба: **4000** случайных конфигураций (`max_chars` 50…5000, окно 0…12, цепочка 0…8) → `len(out) ≤ max_chars`, **0 нарушений**; `_truncate_reply_chains` даёт валидные теги и keep-end. |
| **R1023F2-02** (per-chat глубина) | **Закрыт** | `handlers/factcheck.py` теперь `await _cp_g(chat_id, "limits.chat_thread_max_depth", hot.get(...))` — как direct; тест `test_per_chat_depth_applied_in_both_paths` (глубина 2 → `["tg:70","tg:60"]`, `tg:50` отсутствует). |
| **R1023F2-03** (fail-open рендера) | **Закрыт** | Выборка + цепочка + рендер в общем `try/except→''`; тест `test_fetch_fail_open_on_render_error` (monkeypatch `format_chat_context` → boom → `""`). |
| **R1023F2-04** (grounding-якоря) | **Закрыт** | `_trusted_text` больше не включает `chat_context`; тесты: `chat_context` не даёт месяцев (`months == frozenset()`), RAG-якоря сохранены (`03.2021`/`fact:7`), фантомный `[03.2021]` из контекста вырезается. Легитимные RAG/поиск/tool-якоря не сломаны. |
| **R1023F2-05** (тавтологичный тест) | **Закрыт** | `test_direct_parity_alias_and_line_rendering` теперь сверяет с конкретным канон-рендером; добавлен поведенческий `test_collect_chain_parity_direct_vs_util` (direct `_collect_thread_chain` == util на общей фикстуре). |
| **R1023F2-06** (кап 41) | **Закрыт** | Docstring + ADR + spec: кап по `before+after`, якорь сверх → max 41; тест `test_cap_plus_anchor_max_rows` (60 сообщений, якорь id=41 → `cap+1`). |
| **R1023F2-07** (`<reply_chains>` в инвентаре) | **Закрыт** | `<reply_chains`/`</reply_chains>` в `CONTEXT_LABEL_EXEMPT_PREFIXES`; точка `factcheck_context` расширена (бот-ходы без ts); сэмпл `_sample_factcheck` включает под-блок; тесты. |
| **R1023F2-08** (guard миграции) | **Закрыт** | legacy == своему дефолту → skip; `before` == дефолту → переносим, кастом (≠дефолт) — нет; известное ограничение задокументировано в ADR; тесты (`test_legacy_equal_default_skipped`, `test_env_default_before_not_clobbered_by_default_legacy`). |
| **R1023F2-09** (API hidden) | **Закрыт** | Тесты `test_config_hides_internal_factcheck_legacy_key` / `test_params_meta_hides_internal_factcheck_legacy_key` — legacy не отдаётся, `before/after` отдаются. |

**Инварианты (повторно):**
- `imported-history-immutable` — **OK** (`get_messages_around` не менялся, только `SELECT`; `database.py` в фиксе не тронут).
- Порядок роутеров/миграций `bot.py` — **OK** (в фиксе `bot.py` не менялся).
- R16/R17/R18 — **OK** (логи только `chat=%s`/ключи; новые — число-значение порога, не секрет).
- egress-реестр / `parse_mode=None` — **OK** (не тронуты).
- Δ каталога — **OK**: REGISTRY **441** / Settings **411** / categorized **416**, GROUPS 92 / TAB_RULES 20 (фикс каталог не менял; тесты зелёные).
- Канон-атомарность — **OK**: canon `architecture.md`/`backlog.md` + ADR + spec синхронно обновлены.

**Тесты (прогнано мной, `.venv`, Python 3.12.0):**
- `pytest -q -k "factcheck or thread_chain or catalog or memory_core_round1020 or webapp_api"` → **517 passed / 0 failed**.
- Полный `pytest -q` → **7105 passed / 0 failed**, 1 warning. Заявленное число подтверждено.
- **Замечание:** в рабочем дереве на момент ревью присутствуют **незакоммиченные** правки F3 (`services/factcheck_service.py`, `negative_constraints.py`, `prompt_style_blocks.py` — review iter1 F3). На прогон F2 не влияют, но коммит `3861cf6` не является «чистым» состоянием дерева.

---

## Требования к @Builder (итерация 2)

1. **R1023F2-10 (High):** сменить политику усечения окна на **keep-end** (вытеснять старые `before` первыми; сохранять якорь и свежие `after`); добавить тест на выживание якоря/`after`/цепочки при длинных сообщениях; сверить docstring.
2. **R1023F2-11…14 (Low):** docstring/тест лег-байтов; убрать мёртвый параметр `_trusted_text`; актуализировать комментарий отката `prompt_migrations.py:171-172`; синхронизировать `spec.md §3.1` с ADR.

После исправления — полный pytest (ожидаемо ≥7105/0) и повторный прогон инструментальной пробы бюджета.

---
---

# ИСТОРИЯ: Итерация 1 (commit `eeb186a`) — исходный аудит

> **Ревьюер:** @Reviewer (Senior Principal Engineer — качество / безопасность / архитектура / прод-готовность).
> **Дата:** 19.09.2026. **Шаг:** 5 (строгий аудит). **Итерация:** 1.
> **Коммит:** `eeb186a` (`feat(services,handlers,web,tests): раунд 10.23 F2 …`). Baseline HEAD `731a845`, после F1 `7fc0e55`.
> **Объём:** 35 файлов, +1230 / −138. Новый `services/thread_chain.py`; окно (`database.get_messages_around`, `handlers/factcheck.py`), граф реплаев, канон-промпт, каталог (+2, hidden), миграция legacy.
> **Метод:** чтение `spec.md` / `ADR-1023-2.md` / `tasks.md` / `round1023-architecture.md`; `git show eeb186a --stat`; полный `git diff eeb186a^ eeb186a`; адресные чтения всех call-site БД/промпта/каталога; самостоятельный прогон целевого и полного pytest.
> **@Memory Шаг-0 (риск роста фантомных `fact/msg`-якорей):** отчёт в репозитории **отсутствует** (`plans/reports/` содержит только `round1023_f1_reviewer.md`). Риск проанализирован мной напрямую по коду (см. R1023F2-04).

---

## Status: **Changes Requested**

Фича сделана на хорошем инженерном уровне: двунаправленное окно корректно по границам, граф реплаев вынесен в общий util без дублирования, канон-миграция промпта атомарна и обратима, egress/`parse_mode`/порядок роутеров не тронуты, полный pytest зелёный (7040/0 — подтверждено мной лично). Ломающего прод бага я не нашёл.

Но заявленный контракт нарушен в двух местах, и оба — ровно там, где спека обещала «кап/инвариант, чтобы не раздувать стоимость». Функция `format_chat_context` теперь **обходит собственный потолок `max_chars`** и инжектит неограниченный по длине блок `<reply_chains>` в промпт, а глубина графа в фактчеке **не совпадает с direct** (per-chat override игнорируется), хотя ADR прямо требует «паритет с direct». Плюс «тест паритета» — тавтология (делегат сравнивается с делегатом), он не проверяет ничего и создаёт ложную уверенность. По правилу «при сомнении — отклоняй» это Changes Requested.

**Сводка:** 0 Critical / **1 High** / **4 Medium** / **4 Low**.

| Sev | Кол-во | Коды |
|---|---|---|
| Critical | 0 | — |
| High | 1 | R1023F2-01 |
| Medium | 4 | R1023F2-02…05 |
| Low | 4 | R1023F2-06…09 |

**Тесты (прогнано мной в `.venv`, Python 3.12.0):**
- `pytest -q -k "factcheck or thread_chain or catalog"` → **297 passed / 0 failed**, 1 warning (сторонний `StarletteDeprecationWarning`).
- Полный `pytest -q` → **7040 passed / 0 failed**, 1 warning. Заявленное число @Builder подтверждено.

---

## 1. Findings

### [Severity: High] R1023F2-01 — `<reply_chains>` обходит потолок `max_chars` и уходит в промпт без ограничения длины
**File:** `services/chat_context.py`
**Location:** `format_chat_context` — сигнатура стр. 24, бюджет стр. 28/64–67, инжект стр. 70–72.
**Problem:** Двунаправленное окно аккуратно срезается по `_CHAT_CONTEXT_MAX_CHARS = 2000` (`if total + len(line) > max_chars: break`), но `reply_chains` дописывается к `body` **после** этого и не участвует в бюджете:
```python
body = "\n".join(lines)
if reply_chains:
    body = body + "\n" + reply_chains          # ← вне max_chars
return ("<chat_context " + _CONTEXT_NOTE + ">\n" + body + "\n</chat_context>")
```
Длина цепочки нигде не ограничена: `render_reply_chains` собирает `format_chain_line` по каждому ходу, а `format_context_item` **не транкает** текст. Одно сообщение в Telegram — до 4096 символов, глубина по умолчанию 6 (а с per-chat override — больше). Итого в промпт может уйти +~24 КБ к блоку, который сам модуль объявляет 2000-символьным бюджетом.
**Why it matters:** Это прямое нарушение контракта самой функции («Потолок max_chars») и rationale модуля (SIGIR'26: «длинный контекст ВРЕДИТ верификации»). Двойной урон: (1) растёт стоимость/латентность фактчека без аппетита владельца, (2) `max_chars` перестаёт быть гарантией качества — получаем тот самый раздутый контекст, от которого защищались. Ни один тест не проверяет длину итогового `<chat_context>`.
**Required fix:** Включить `reply_chains` в бюджет: либо транкать рендер цепочки (лимит символов/сообщений) внутри `render_reply_chains`, либо считать `len(reply_chains)` в `total` и резать цепочку тем же приёмом (старые/дальние ходы вытесняются первыми). Добавить тест: длинная цепочка (сообщения по 1000+ символов) → `len(format_chat_context(..., reply_chains=...)) <= max_chars` (или явный, задокументированный отдельный лимит цепочки).

---

### [Severity: Medium] R1023F2-02 — Глубина графа в фактчеке игнорирует per-chat override → паритета с direct нет
**File:** `handlers/factcheck.py`
**Location:** `_build_reply_chains`, стр. 111–112.
**Problem:** Фактчек резолвит глубину только глобально:
```python
depth = hot.get("limits.chat_thread_max_depth", settings.CHAT_THREAD_MAX_DEPTH)
```
А direct (`services/direct_chat_service.py:2424-2425`) — через per-chat override:
```python
_depth = await _cp_g(chat_id, "limits.chat_thread_max_depth",
                     hot.get("limits.chat_thread_max_depth", settings.CHAT_THREAD_MAX_DEPTH))
```
`get_chat_param` — это переопределение уровня чата; если владелец настроил глубину для конкретного чата, direct её увидит, а фактчек — нет.
**Why it matters:** ADR-1023-2 §Decision 4 и spec §3.2 требуют «глубина = `limits.chat_thread_max_depth` (паритет с direct)». Для чатов с per-chat настройкой цепочка в фактчеке будет короче, чем в direct, — недостоверный «паритет» и скрытая потеря контекста (ровно та функция, ради которой фича делалась). Регресса нет, но контракт не выполнен.
**Required fix:** Резолвить глубину так же, как direct (`await _cp_g(chat_id, "limits.chat_thread_max_depth", hot.get(...))`) либо явно зафиксировать в ADR, что per-chat override на фактчек не распространяется, и покрыть это тестом. Молчаливое расхождение недопустимо.

---

### [Severity: Medium] R1023F2-03 — Fail-open `_fetch_chat_context` сломан: рендер вынесен из `try`
**File:** `handlers/factcheck.py`
**Location:** `_fetch_chat_context`, стр. 73–82.
**Problem:** До F2 весь путь — `get_recent_messages` **и** `format_chat_context` — был внутри `try/except → return ""`. Теперь внутри `try` только выборка, а рендер снаружи:
```python
    try:
        rows = await _db.get_messages_around(...)
    except Exception:
        logger.warning(...); return ""
    reply_chains = await _build_reply_chains(...)
    return format_chat_context(rows, trigger_message_id=..., reply_chains=reply_chains)
```
При этом docstring функции (стр. 65) обещает: «Fail-open: **любая** ошибка БД/построения цепочки → ''».
**Why it matters:** `format_chat_context` теперь не защищён. Любое исключение в рендере (нестандартная строка/данные из БД) выйдет наружу из `_fetch_chat_context`. В `factcheck_handler` вызов обёрнут только специфичными `except` (`LLMBadResponseError`, `AllSearchEnginesFailedException`, `LLMError`) — рендер-ошибка туда не попадёт и уронит обработчик вместо мягкой деградации. Это регресс заявленной гарантии, пусть и маловероятный по триггеру.
**Required fix:** Вернуть рендер внутрь `try` (как было) либо обернуть `format_chat_context` отдельным `try/except → ""` с R17-safe логом. Обновить/расширить тест `test_fetch_fail_open_on_db_error` на ошибку рендера.

---

### [Severity: Medium] R1023F2-04 — Расширение окна + chain увеличивает пул grounding-якорей (`ММ.ГГГГ`) — риск @Memory не митигирован
**File:** `services/factcheck_service.py`
**Location:** стр. 133–136 (`collect_allowed_anchors(self._trusted_text(...))`), `_trusted_text` стр. 193–199.
**Problem:** `_trusted_text` включает `chat_context` (а с F2 — и вложенный `<reply_chains>`) в источник «доверенных якорей». `collect_allowed_anchors` (`services/grounding_validator.py:57-69`) собирает `_MONTH_RE = (\d{2})\.(\d{4})`, а `format_context_item` для `kind="msg"` печатает `ДД.ММ.ГГГГ ЧЧ:ММ` — из каждого таймстампа окна рождается месяц-якорь (`«01.01.1970»` → якорь `01.1970`). Было ≤6 сообщений, стало до 40 + вся цепочка реплаев. Соответственно `strip_phantom_tags` начнёт **сохранять** теги `[ММ.ГГГГ | …]`, «заземлённые» лишь болтовнёй чата, которую сам контекст помечает «НЕ доказательства».
**Why it matters:** Это ровно тот риск, который @Memory обязан был поднять на Шаге 0 (отчёта нет). Пометка «не доказательства» защищает *смысл*, но не grounding-валидатор: поверхность «легальных» дат растёт без ограничения, ослабляя анти-фантомный guard. `fact:\d+` не растёт (в chat_context только `tg:`/`msg:`), но месячные якоря — да.
**Required fix:** Принять явное решение и зафиксировать в ADR + покрыть тестом: исключить `chat_context`/`reply_chains` из `collect_allowed_anchors` (anchors только из `rag`/`results`/`tool_context`), **или** доказать тестом, что рост числа якорей не меняет поведение strip на репрезентативных примерах. «Просто оставили ноту» — недостаточно.

---

### [Severity: Medium] R1023F2-05 — Тест «паритет direct» тавтологичен, реального паритета не проверяет
**File:** `tests/test_factcheck_deep_context_round1023.py`
**Location:** `test_direct_parity_aliases_and_line`, стр. 220–227.
**Problem:**
```python
assert _ChainItem is thread_chain.ChainItem
...
assert DirectChatService._chain_line(None, item, {}) == \
    thread_chain.format_chain_line(item, {})
assert DirectChatService._chain_line(None, item, {}) == \     # ← дубль-копипаста
    thread_chain.format_chain_line(item, {})
```
`DirectChatService._chain_line` — это **делегат** `thread_chain.format_chain_line` (см. `direct_chat_service.py:2445`), т.е. тест сравнивает функцию с её собственным телом делегирования. Он не может упасть даже при полной потере паритета. Поведенческий паритет `_collect_thread_chain` (direct) ↔ `collect_thread_chain` (util) **не проверяется**: ни глубина, ни per-chat override (ср. R1023F2-02), ни бот-линки/TTL. При этом идентичный `assert` продублирован дважды.
**Why it matters:** ADR/T-2109 объявляют «регресс direct обязателен», а ключевой тест фичи — фиктивный. Это ложная уверенность: R3-риск (вынос цепочки ломает direct) формально «покрыт», фактически — нет.
**Required fix:** Заменить тавтологию на поведенческий тест: прогнать `DirectChatService._collect_thread_chain` и `thread_chain.collect_thread_chain` на одном фикстурном `db`/`message` (с бот-линками и parent-цепочкой) и сверить возвращаемые `ChainItem` поэлементно; отдельно — тест, что per-chat `chat_thread_max_depth` применяется в обоих путях. Убрать дублирующий `assert`.

---

### [Severity: Low] R1023F2-06 — Кап считается по `before+after`, якорь не входит → фактически до 41 сообщения
**File:** `handlers/factcheck.py` / `services/chat_context.py` / `spec.md §3.1`.
**Location:** `_clamp_window`, стр. 94–97.
**Problem:** `b + a ≤ FACTCHECK_CONTEXT_TOTAL_CAP (40)`, но БД возвращает `older + anchor + newer` → максимум **41** сообщение. Spec §3.1 формулирует «суммарное число сообщений не превышает кап», ADR §Cost — «окно ≤ … + якорь + …; кап 40» (т.е. якорь вне капа). Формулировки спеки и ADR расходятся.
**Why it matters:** Не баг, а неоднозначность контракта, которая при следующей правке легко превратится в off-by-one и сломает тест границ.
**Required fix:** Привести спеку и ADR к одной формулировке («кап = сумма before+after, якорь сверх») и добавить тест на фактическое число строк (≤41) при `before=after=1000`.

---

### [Severity: Low] R1023F2-07 — Новый `<reply_chains>` вне инвентарного канона «нет голого текста»
**File:** `services/canonical_context.py` (`CONTEXT_POINTS`) / `tests/test_memory_core_round1020.py`.
**Location:** точка `factcheck_context` (canonical, стр. 164–166); сэмпл `_sample_factcheck` фильтрует только строки, начинающиеся с `[`.
**Problem:** Блок `<reply_chains …>…</reply_chains>` теперь живёт внутри `<chat_context>`, но точка-инвентарь его не описывает (сэмпл отбрасывает строки без `[`), поэтому строки-обёртки структурно вне критерия. Внутренние строки цепочки каноничны (проверено), но сам под-блок не покрыт.
**Why it matters:** Канон заявлен как сгенерированный из реестра; появился новый элемент представления — реестр/сэмпл не обновлены. При следующей правке это даст слепую зону.
**Required fix:** Либо добавить в `CONTEXT_POINTS`/`_SAMPLES` сэмпл с `<reply_chains>`, либо явно зафиксировать, что под-блок — структурная обёртка и критерию не подлежит (как `label_exempt`), с тестом.

---

### [Severity: Low] R1023F2-08 — Миграция перезапишет `before`, равный дефолту, даже если владелец задал его явно; env-дефолт может быть затёрт
**File:** `services/config_migrations.py`
**Location:** `migrate_factcheck_context_defaults`, стр. 255–267.
**Problem:** Условие «кастом не затираем» — это `before_int != default_int` (сравнение с код-дефолтом), а не «ключ явно задан». Следствия: (1) если владелец осознанно выставил `before=6` (равное дефолту), а legacy=12 — миграция молча поставит 12; (2) если `FACTCHECK_CONTEXT_BEFORE` задан через env (например, 10), а legacy=6, то `default_int=10 == before_int`, `legacy(6) != before(10)` → `before` перезапишется на 6, т.е. env-дефолт будет затёрт старым legacy.
**Why it matters:** Редкие, но реальные сценарии неожиданной потери явной настройки — прямо против духа «кастом не затираем».
**Required fix:** Различать «ключ есть в PG» и «ключ отсутствует» (проверять факт наличия записи, а не её численное равенство дефолту), либо явно задокументировать эти два сценария в ADR и покрыть тестами.

---

### [Severity: Low] R1023F2-09 — `hidden` не покрыт API-тестами на исключение из витрин; остаётся в дереве прав и `/debug_config`
**File:** `web/api/routes.py` (`get_config` стр. 334–338, `get_params_meta` стр. 550–554), `web/api/access.py` (`param_permissions_list`/`get_roles_tree`), `services/debug_config.py`.
**Problem:** Фильтрация `hidden` добавлена в два эндпоинта, но: (а) `get_roles_tree`/`param_permissions_list` отдают legacy-ключ в матрицу прав (это, вероятно, намеренно — «права/пины не ломаем», но нигде не зафиксировано), (б) `/debug_config` печатает его как обычный параметр; (в) нет ни одного теста, который бы дергал `/api/config` или `/api/config/params-meta` и проверял, что `limits.factcheck_context_messages` реально исчез из ответа. Тест `test_legacy_hidden_but_in_registry` проверяет только флаг в реестре.
**Why it matters:** «Скрытие» подтверждено только на уровне поля `ParamSpec`, а не на уровне контракта API. Регресс фильтра (например, кто-то перепишет `get_config`) пройдёт незамеченным.
**Required fix:** Добавить API-тест: `get_config` и `get_params_meta` не содержат `limits.factcheck_context_messages`, но содержат `before/after`. Явно задокументировать, что в дереве прав legacy остаётся осознанно (пины/права).

---

## 2. Проверка контракта

### 2.1. `tasks.md` (чексбоксы)
- [x] **T-2107** ADR-1023-2 + spec — **подтверждено** (контент соответствует коду, Human Gate по 6/6/40 зафиксирован).
- [x] **T-2108** двунаправленное окно, `before/after`, каталог `limits_factcheck` — **подтверждено** (но см. R1023F2-06 по капу).
- [x] **T-2109** граф реплаев общим util, fail-open — **подтверждено частично** (util вынесен, fail-open есть; паритет глубины не выполнен — R1023F2-02; тест паритета фиктивен — R1023F2-05).
- [x] **T-2110** правило веб-поиска в Stage-1 Аналитик — **подтверждено** (`factcheck_tools` содержит `execute_web_search`, правило исполнимо при активном tool-loop).
- [x] **T-2111** канон-миграция (слепок `PREV_FACTCHECK_ANALYST_R1023_F2` + migrate/rollback + `plans/docs/canon/**`) — **подтверждено**, слепок F1 побайтово совпадает с `eeb186a^`.
- [x] **T-2112** UI параметры — **подтверждено** (generic-рендер `limits_factcheck` в `web/app.js:73`; правки HTML/JS не требовались).
- [x] **T-2113** тесты окна/графа/миграции/промпта/каталога — **подтверждено частично** (есть покрытие, но паритет direct фиктивен — R1023F2-05; нет тестов на длину `<chat_context>`, API-скрытие и grounding-якоря).
- [x] **T-2114** регресс — **подтверждено** (полный pytest 7040/0 прогон мой).
- [ ] **T-2115** деплой + живая приёмка — **вне скоупа код-ревью** (ожидаемо pending, @DevOps).

### 2.2. Инварианты `round1023-architecture.md §4`
- `physical-two-call-pipeline` — **OK**: `_check_claim_two_call` не менялся, tool-loop внутри Stage-1; новых LLM-вызовов нет.
- `imported-history-immutable` — **OK**: `get_messages_around` только `SELECT`, мутаций `smart_messages` нет.
- egress-реестр — **OK**: `services/telegram_send.py`/`outgoing_guard.py` в коммите не изменялись, новых send-точек нет.
- R16/R17/R18 — **OK**: логи только `chat=%s`/коды; raw-сообщения не логируются; egress не тронут.
- `manual-overrides-immutable` — **OK**: `persona_dossier_overrides` не затронуты.
- `parse_mode=None` — **OK**: не тронут.
- Порядок роутеров `bot.py` — **OK**: добавлен только вызов `migrate_factcheck_context_defaults` (порядок существующих миграций/роутеров не сдвинут).
- Канон-атомарность ADR-1013-3 — **OK**: константа + PREV-слепки + `PROMPT_MIGRATIONS` + `ROLLBACK_MIGRATIONS` + `plans/docs/canon/**` + тесты в одном коммите.

### 2.3. Δ каталога (жёстко)
- `REGISTRY` = **441** (было 439, Δ +2) — подтверждено тестом и прогоном.
- `Settings` dataclass-полей = **411** (Δ +2); `FACTCHECK_CONTEXT_TOTAL_CAP` — `ClassVar`, в `dataclasses.fields` не входит — подтверждено тестом.
- `categorized` = **416** (Δ +2); `GROUPS` = 92, `TAB_RULES` = 20, `_TAB_BY_GROUP` = 90 — **без изменений** (`tma-menu-freeze` соблюдён).
- Legacy `FACTCHECK_CONTEXT_MESSAGES` — в реестре (права/пины целы), `hidden=True`, из `get_config`/`params-meta` исключён; активный код-путь legacy не читает (единственная ссылка — `config/settings.py` и миграция) → **R1 (дублирование источника правды) закрыт**.

### 2.4. Двунаправленное окно — фактическая проверка
- Якорь выбирается отдельным `SELECT … ORDER BY id ASC LIMIT 1`, `older` — `id < anchor` (DESC→reverse), `newer` — `id > anchor` (ASC), итог **ASC**, якорь ровно один раз — подтверждено тестом `test_bidirectional_asc_and_anchor_once`.
- Границы `0/0` → только якорь; `10/10` → всё окно — тест есть.
- Anchor не найден / ошибка БД → `get_recent_messages(before+after)` — тесты есть.
- Кап 40 (по `before+after`) и обрезка `after` — тест есть (см. R1023F2-06 про якорь).
- Legacy не является вторым источником правды — подтверждено grep по коду.

---

## 3. Требования к @Builder (точный список)

1. **R1023F2-01 (High):** ограничить `<reply_chains>` бюджетом `format_chat_context` (транк/учёт в `max_chars`) + тест на длину итогового блока.
2. **R1023F2-02 (Medium):** глубина графа в фактчеке — через per-chat резолв, как в direct (`_cp_g`), либо явная фиксация отклонения в ADR + тест.
3. **R1023F2-03 (Medium):** вернуть `format_chat_context` под fail-open `try/except → ""` + тест на ошибку рендера.
4. **R1023F2-04 (Medium):** решение по grounding-якорям из `chat_context`/`reply_chains` (исключить или доказать тестом) с фиксацией в ADR.
5. **R1023F2-05 (Medium):** заменить тавтологичный `test_direct_parity_aliases_and_line` на поведенческий тест паритета direct↔util (+per-chat depth); убрать дубль-`assert`.
6. **R1023F2-06…09 (Low):** свести формулировку капа в spec/ADR (+тест фактического числа строк); обновить/явно исключить инвентарную точку `factcheck_context` для `<reply_chains>`; уточнить guard миграции «ключ задан vs равен дефолту»; добавить API-тесты скрытия legacy (`/api/config`, `/api/config/params-meta`) и зафиксировать намеренное присутствие в дереве прав.

После исправлений — повторный прогон полного pytest (ожидаемо ≥7040/0) и обновление `plans/reports/round1023_f2_reviewer.md`.

---

## 4. Что сделано хорошо (чтобы не потерять при доработке)
- Вынос `_collect_thread_chain` в `services/thread_chain.py` без дублирования логики; обратно-совместимые алиасы `_ChainItem`/`_speaker_tag` сохранены.
- Канон-миграция промпта: `PREV_FACTCHECK_ANALYST_R1023_F2` побайтово равен канону после F1, `PROMPT_MIGRATIONS` покрывает обе ступени (pre-F1 и F1), `ROLLBACK_MIGRATIONS` снимает только правило веб-поиска — обратимость корректна.
- Миграция legacy идемпотентна, значение legacy не удаляется (обратимость), кастом `before` в базовом сценарии не затирается.
- Бары fail-open на БД/цепочке, R17-safe логи, `hidden` реализован без роста Δ каталога.
