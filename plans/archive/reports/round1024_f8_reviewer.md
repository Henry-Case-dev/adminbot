# Ревью F8 `dead-extractor-paradigms-round1024` — раунд 10.24, шаг 5

- **Коммит:** `d79c5bf` (HEAD)
- **Ревьюер:** @Reviewer
- **Дата:** 20.09.2026
- **Baseline-заявление:** pytest 7591 — **подтверждено: 7591 passed** + `node --check web/app.js` OK
- **Статус:** **Changes Requested**

## Резюме

Корневой фикс F8 сделан верно и, что важно, **воспроизводимым тестом**: traits
исполняются после гейтов `disabled/daily_limit/cooldown` и до ранних return'ов
`no_anchors/unchanged/no_context/budget/…`, парадигмы от traits не зависят,
kill-switch `DEEP_SLEEP_EXTRACT_FIX_ENABLED` (env-only, default ON) возвращает
прежний порядок. `parse_bridge_answer` валидные элементы не теряет
(подтверждено characterization-тестом). Fail-open и R17-safe логирование этапов
через `trace_step`/`external_log` на месте. Δ DDL = 0, меню TMA не тронуто.

Но слой **Empty State врёт о причине пустоты** — ровно то, против чего затевался
P0 («ложные отчёты», UPD2 п.6). Плюс API-контракт `/api/memory/deep-sleep` теперь
смешивает скоупы (список — чат, счётчики — глобально), а причина последнего
прогона может быть взята у чужого чата. Это не косметика: владелец снова не
сможет отличить «LLM не нашла связей» от «идемпотентность» и «нет данных» от
«другой чат скипнулся».

---

## Findings

### F1 — [High] `unchanged` выдаётся за `duplicate`; Empty State дезинформирует
- **Файл:** `web/api/memory_agi.py:465` (`_DEEP_REASON_MAP`), `web/app.js:6338`
- **Проблема:** `"unchanged": "duplicate"`. Внутри `unchanged` = LLM вернула
  `{"paradigms":[]}` / `UNCHANGED`, что по промпту означает «связи нет или
  данных мало» (`services/dream_prompts.py:169`, `237-283`). Это НЕ
  «все выводы уже записаны ранее». UI-текст для `duplicate` — «все выводы уже
  записаны ранее (идемпотентность)».
- **Почему это важно:** Главный артефакт фичи — честный Empty State с причиной
  (spec §9, UPD3 №4). Владелец увидит «идемпотентность» там, где LLM просто
  ничего не синтезировала, и снова решит, что экстрактор мёртв/работает
  впустую. Это воспроизводит исходную проблему «ложного отчёта».
- **Как чинить:** маппить `"unchanged"` → `"empty"` (код есть в spec §5.1,
  JS-подпись «источников пока недостаточно» соответствует смыслу промпта) ИЛИ
  ввести отдельный код `unchanged` в spec §5.1 и отдельную подпись в
  `emptyReasonLabel`. Добавить тест на маппинг.

### F2 — [Medium] Причина последнего прогона может быть у чужого чата
- **Файл:** `web/api/memory_agi.py:473-491` (`_last_deep_reason`), `:518`, `:543`
- **Проблема:** `recent_dream_log(limit=50)` вызывается **без `chat_id`** (весь
  лог, DESC). Если у выбранного чата нет строк среди последних 50 глобальных,
  `scoped` пуст → fallback на глобальные строки → в `paradigms_reason`
  подставляется причина **другого чата**.
- **Почему это важно:** Empty State выбранного чата покажет чужую причину
  (`no_anchors`/`error`/…), что прямо противоречит цели честной диагностики.
  В этом же файле уже есть корректный паттерн — строки `831` и `946` вызывают
  `recent_dream_log(..., chat_id=chat_id)`.
- **Как чинить:** при `chat_id is not None` делать
  `db.recent_dream_log(limit=50, chat_id=chat_id)` и **не** падать на глобальные
  строки; нет строк → `None` → код `empty`/`never`. Обновить мок
  `_ApiDb.recent_dream_log` под реальную сигнатуру (сейчас тест не моделирует
  `chat_id` и потому баг не ловит).

### F3 — [Medium] R16: смешение скоупов и неаддитивная смена семантики `paradigms[]`
- **Файл:** `web/api/memory_agi.py:508-518` (`paradigms` скоупится, счётчики — нет)
- **Проблема:** `list_recent_beliefs(chat_id=chat_id, …)` теперь чат-скоуп, а
  `count_paradigms()`, `last_deep_run()`, `count_dream_log(0, kind="deep_run")`
  остались глобальными. Изменение семантики **существующего** поля `paradigms[]`
  не является аддитивным (spec §4/§5.2 — «аддитивно, R16»).
- **Почему это важно:** Потребитель, ожидавший глобальный список, получит
  чат-скоуп (breaking change под видом аддитивного). Дашборд может показать
  `paradigms_total>0` при `paradigms_status="empty"`.
- **Как чинить:** привести счётчики к тому же скоупу
  (`count_paradigms(chat_id=chat_id)`, `last_deep_run(chat_id=chat_id)`,
  `count_dream_log(..., chat_id=chat_id)` — методы сигнатуру поддерживают) ИЛИ
  зафиксировать намеренный скоуп в spec §5.2/ADR и добавить
  `paradigms_total_scoped`. Решение обязательно задокументировать.

### F4 — [Low] Недостижимые коды причин для гейтов `cooldown`/`daily_limit`
- **Файл:** `web/api/memory_agi.py:459-468` (`_DEEP_REASON_MAP`), `database.py:3178` (`count_deep_attempts`)
- **Проблема:** `cooldown`/`daily_limit` присутствуют в маппинге, но эти гейты
  не пишут в `memory_dream_log` (только `_trace_deep`), поэтому в Empty State
  недостижимы. Пользователь не отличит «нет данных» от «прогон не запускался
  по лимиту/охлаждению».
- **Как чинить:** вычислять причину из состояния (`last_deep_attempt`/
  `count_deep_attempts`) без записи `deep_skip` (иначе сломается
  `count_deep_attempts`, который считает `deep_skip` со статусами
  `error/unchanged/duplicate`), либо явно зафиксировать ограничение в spec/ADR
  и не держать в маппинге мёртвые коды без комментария.

### F5 — [Low] Потеря per-chat override при сбое чтения гейта persona
- **Файл:** `services/dream_worker.py:1848-1853`
- **Проблема:** при исключении в `_persona_gate` fallback —
  `settings.PERSONA_ENABLED` (True), hot/chat-override игнорируется.
- **Как чинить:** в `except` писать trace `gate_read_error`; трактовать как OFF
  (`False`), т.к. `persona_enabled` — контентный гейт владельца. Минимум — не
  «повышать» молча выключенный для чата модуль до включённого.

---

## Контракт

### Чекбоксы `tasks.md`
| Задача | Статус | Комментарий ревьюера |
|---|---|---|
| T-2244 [x] | подтверждено | ADR-1024-5/spec на месте |
| T-2245 [ ] | **не закрыт** | live-диагностика прода (@DevOps) отсутствует |
| T-2246 [x] | подтверждено | `parse_bridge_answer` валидные элементы сохраняет (тест f); корень — traits-гейт |
| T-2247 [x] | подтверждено | без self-фактов LLM не вызывается, `no_self_facts` |
| T-2289 [x] | частично | Empty State есть, но причина искажается (F1/F2) |
| T-2248 [x] | подтверждено | API-поля и рендер лент добавлены |
| T-2249 [x] | подтверждено | дедуп парадигм и traits идемпотентны |
| T-2250 [x] | частично | нет тестов на маппинг `unchanged` и chat-скоуп причины |
| T-2251 [x] | подтверждено | `trace_step` на этапах, R17-safe |
| T-2252 [ ] | это ревью | — |
| T-2253 [ ] | **не закрыт** | live-приёмка (@DevOps) отсутствует |

### Инварианты
- `imported-history-immutable` — **OK** (записи в импорт-историю нет).
- `manual-overrides-immutable` — **OK** (только чтение через `get_chat_param`).
- `physical-two-call` — **OK** (изменён только фон `dream_worker`).
- `egress` — **OK** (новых сетевых вызовов/провайдеров нет).
- `R16` — **частично (F3)**: смена семантики `paradigms[]` не аддитивна.
- `R17` — **OK** (коды/счётчики; `trace_step` через `safe_text`).
- `R18` — **OK** (секретов в диффе нет).
- `parse_mode=None` — **OK** (handlers не менялись).
- `Δ DDL = 0` — **OK** (нет DDL; `last_trait_status` — существующее TEXT-поле).
- `tma-menu-freeze` — **OK** (меню не менялось, Empty State внутри лент).

### Тесты
- Полный прогон: `.venv/Scripts/python.exe -m pytest -q` → **7591 passed**,
  1 warning (deprecation starlette) — соответствует заявленному.
- `node --check web/app.js` → OK.
- Тесты (a)/(b)/(c)/(d)/(e)/(f)/(g) и kill-switch присутствуют, **не
  тавтологичны**: `test_traits_run_on_no_anchors`/`test_traits_run_on_unchanged`
  на старом коде падали бы (traits пропускались ранним return).
- **Пробелы:** (1) нет теста на `unchanged` → код причины (F1);
  (2) `_ApiDb.recent_dream_log` не принимает `chat_id` → F2 не покрыт;
  (3) нет теста на согласованность скоупов `paradigms[]` vs `paradigms_total`
  (F3).

---

## Точный список на исправление

1. `web/api/memory_agi.py:465` — `"unchanged"` не маппить в `duplicate`;
   → `empty` либо новый код `unchanged` + подпись в `web/app.js`. Тест обязателен.
2. `web/api/memory_agi.py:518` + `_last_deep_reason` — запрашивать лог строго
   `chat_id=chat_id` при заданном чате; убрать fallback на чужие строки;
   обновить мок `_ApiDb` и добавить тест «чужой чат не влияет».
3. `web/api/memory_agi.py:515-517` (и при необходимости spec §5.2/ADR) —
   выровнять скоуп `paradigms_total`/`runs_total`/`last_run_at` со списком
   `paradigms[]` либо задокументировать расхождение.
4. `web/api/memory_agi.py:459-468` — либо сделать причины `cooldown`/
   `daily_limit` достижимыми, либо зафиксировать ограничение (F4).
5. `services/dream_worker.py:1848-1853` — при сбое чтения гейта persona не
   повышать его до ON, писать trace-причину (F5).

**Верни исправленную версию. Текущий код отклонён.**

---

# Итерация 2 — ревью коммита `297d2ac`

- **Статус:** **Approved**
- **Объём коммита:** `git show 297d2ac --stat` → 4 файла:
  `services/dream_worker.py`, `web/api/memory_agi.py`,
  `tests/test_dead_extractor_paradigms_round1024.py`,
  `tests/test_settings_worker_sync_round1018.py`. Родитель — `ea04be9` (F12);
  изменения F12 **не приписываются** F8 (в диффа F8 не попадают).
- **Прогоны:**
  - полный `.venv/Scripts/python.exe -m pytest -q` → **7617 passed / 0 failed**;
  - целевые (`test_dead_extractor_paradigms_round1024`,
    `test_settings_worker_sync_round1018`, `test_memory_consolidation_round1021`,
    `test_dream_persona_traits`, `test_deep_sleep`) → **137 passed**;
  - `node --check web/app.js` → OK.

## Закрытие findings итерации 1

- **[High] F1 (`unchanged` → `duplicate`)** — исправлено по существу:
  `web/api/memory_agi.py:472` → `"unchanged": "empty"`, `duplicate` оставлен
  только за реальным «всё записано». Тесты `test_unchanged_maps_to_empty_not_duplicate`
  и `test_duplicate_reason_kept` — **не тавтологичны** (на прежнем маппинге
  первый падал бы). ✔
- **[Medium] F2 (чужая причина)** — `recent_dream_log(limit=50, chat_id=chat_id)`
  строго (`:526-527`), `_last_deep_reason(log)` без fallback (`:480-493`).
  Мок `_ApiDb` теперь моделирует реальные сигнатуры (`chat_id`, `kind`),
  добавлен `test_foreign_chat_log_not_used` (на старом коде вернул бы `error`
  чужого чата). ✔
- **[Medium] F3 (смешение скоупов, R16)** — все счётчики выровнены по чату:
  `count_paradigms(chat_id)`, `last_deep_run(chat_id)`,
  `count_dream_log(0, kind="deep_run", chat_id=chat_id)` (`:522-525`);
  `test_counters_chat_scoped` проверяет и чат-, и глобальный режим; скоуп
  зафиксирован в `spec.md` §5.2 (UPD review iter1). ✔
- **[Low] F4 (недостижимые коды)** — ограничение задокументировано в коде
  (`:462-464`) и в `spec.md` §5.1; запись `deep_skip` для пре-LLM гейтов
  намеренно не добавлена (иначе сломала бы `last_deep_attempt`/cooldown). ✔
- **[Low] F5 (override при сбое гейта)** — fail-closed OFF + trace
  `gate_read_error` (`services/dream_worker.py:1848-1861`);
  `test_gate_read_error_is_fail_closed_off` (на старом коде был бы ON). ✔

## Инварианты

`imported-history-immutable` OK · `manual-overrides-immutable` OK ·
`physical-two-call` OK (только фон `dream_worker` + read-only API) ·
`egress` OK (новых внешних вызовов нет) · `R16` OK (скоуп задокументирован,
поля аддитивны, смена семантики `paradigms[]`/`log[]` зафиксирована) ·
`R17` OK (коды/счётчики) · `R18` OK (секретов нет) · `parse_mode=None` OK ·
`Δ DDL = 0` OK · `tma-menu-freeze` OK (меню не менялось).

## Неблокирующие замечания

1. Рабочее дерево **грязное** относительно `297d2ac`: незакоммиченные правки
   F12 (`config/settings.py`, `services/image_generation.py`, `web/app.js`,
   `tests/test_summary_cover_model_compat_round1024.py`). К F8 не относятся;
   перед деплоем развести/закоммитить, чтобы приёмка шла с чистого дерева.
2. `plans/features/dead-extractor-paradigms-round1024/` не в git (конвенция
   репозитория: весь `plans/` untracked) — UPD-фиксация spec §5.1/§5.2 живёт
   только на диске.
3. T-2245/T-2253 (live-диагностика/приёмка @DevOps) остаются открытыми —
   приёмка F8 на живом стенде за DevOps; кодом не блокируется.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
