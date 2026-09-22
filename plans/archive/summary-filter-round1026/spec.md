# spec.md — S1 `summary-filter-round1026` (Эпик 2, этап 0: алгоритмический префильтр)

> **Раунд 10.26 · Эпик 2 («Summary Hybrid Pipeline») · Приоритет P0 · Тип: backend/алгоритм (0 LLM-вызовов)**
> **Step 2 @Architect (23.09.2026):** спека + **ADR-1026-1** (санкция Δ каталога + форма алгоритма).
> **Задачи:** `tasks.md` (T-3129…T-3159, блоки 0/A–G). **ТЗ:** `plans/current_task.md` §80, §82–§83, §87–§89, §91–§93, §107–§109.
> **Зависит от:** Эпик 1 (авто-приёмка ✅ §70; live-гейт ⏳ PENDING OWNER, не блокирует независимые задачи — ADR-1025-24 D4).
> **Baseline:** HEAD `01f3c57`, `APP_VERSION` 2.58.17, pytest `.venv` **8463/0**, JS **42/42**,
> каталог **459/418/434/98/96/21**, SQLite `user_version=12`.
> **Продолжают:** S2 `summary-context-restore` (§90–§92), S3 L1 Кластеризатор (§93–§95), S7 `summary-logging-runid`.

---

## 1. Область / вне области

**В области S1 (этап 0 «подготовка сообщений»):**
- Новый чистый модуль `services/summary_filter.py`: балльный алгоритм §88 + порог §87 + режим всплеска по плотности §89.
- Оценка токенного объёма отфильтрованного окна + механические перекрывающиеся фрагменты §93 (для S3).
- Интеграция как **участок входа** в `services/summary_generator.py::_run` (вход L1/Редактора) без изменения двухвызовности.
- Каталоговые параметры `summary.filter.*` (§87/§89, блок `flags/limits`) + UI-вкладка «Подготовка сообщений» (`mod_summary`).
- Аддитивные логи `FILTER_START/COMPLETE/ERROR` §108–§109 + `run_id`-совместимость с S7.

**ВНЕ области S1 (не реализуется здесь):**
- Восстановление контекста (§90) — **S2**; S1 только отдаёт `dropped`/`fragments` и заводит ключи §89.
- Восстановление переплетённых тредов и «объединение тем / устранение семантических дублей» — **S3** (L1 LLM).
- Пакет фактов (§96) — S4; Писатель/статьи (§97–§99) — S5; публикация (§100–§105) — S6 (гейт).
- ExecutionGraph-узлы `algorithm` (§111) — **S8** (S1 только отдаёт метрики в структуру); log viewer §110 — S7.
- Любое изменение публикационного пути (`generate_image*`, `sendRichMessage`, `build_cover_media`, `send_rich_message`, fallback `sendMessage`) — **запрещено (D4)**.

---

## 2. Факты аудита кода (перепроверено Step 2)

| Факт | Точка в коде |
|---|---|
| Пайплайн `_run` | `services/summary_generator.py:312-451` |
| Чтение окна (вход) | `get_window_messages` → `services/summary_memory.py:1686-1725` → `DatabaseService.get_smart_window` (`services/database.py:1864-1875`) |
| Поля строки окна | `id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, is_forward, forward_source, tg_message_id` |
| Сборка XML-истории (вход L1) | `services/summary_xml.py:57-118` (`build`, `_build_element`) |
| Точка врезки | между `rows = get_window_messages(...)` (`:318`) и `xml_context = self.xml.build(rows, …)` (`:327`) |
| 2 LLM-вызова (Редактор→Рассказчик) | `_run:403-418`, ADR-1022-3/4/5 |
| `truncate_to_tokens`/`count_tokens` | `services/token_counter.py` (импорт `:76-81`) |
| Публикация | `_deliver_rich:824`, `_deliver_plain:793`, `generate_image_verbose`, `build_cover_media`/`send_rich_message` |
| Каталог: `pg_key` | `services/param_catalog.py:111-115` → `{category}.{field_lower}` |
| Группы вкладки `mod_summary` | `services/param_catalog.py:2080-2084`; `TAB_MOD_SUMMARY="mod_summary"` (`:1973`) |

**Критично для алгоритма (установлено по коду):**
1. `smart_messages.reply_to_id` хранит **Telegram** `message_id` ответа-родителя (`handlers/summary.py:181-183`), а `smart_messages.id` — **DB** id, `tg_message_id` — Telegram id. Поэтому критерий 2 («на сообщение кто-то ответил») индексируется по **`tg_message_id`**, а не по `id`.
2. В строке окна **нет поля `mentions`** (§92 «использовать реальные поля, не выдумывать»). «Адресное упоминание» для критерия 1 детектируется детерминированно по тексту (`@token`); `reply_to_id` — основной сигнал. Без текстовых `@` упоминание не определяется (ограничение, фиксируется).
3. `tg_message_id` может быть `None` (импорт) — в индексе reply-родителей `None` игнорируется (нет ложных склеек).
4. Бот-сообщения/прошлые Саммари — по `user_id == bot_id` (передаётся вызывающим как `self.bot.id`); при `bot_id is None` исключение не применяется (fail-open).

---

## 3. Трассируемость REQ → сценарии

| REQ | Сценарий спеки |
|---|---|
| REQ-S1-01 (§80) | SC-01, SC-02 |
| REQ-S1-02 (§87 тумблер default ON) | SC-03 |
| REQ-S1-03 (§87 min_weight/min_words/burst_window) | SC-04 |
| REQ-S1-04 (§87 ключи, без параллельного хранилища) | §6 (каталог), SC-05 |
| REQ-S1-05 (§88 4 критерия) | SC-06 |
| REQ-S1-06 (§88 максимум 1 балл/критерий) | SC-07 |
| REQ-S1-07 (§88 всплеск по плотности) | SC-08 |
| REQ-S1-08 (§89 тонкая настройка, «короткий тред не бесполезен») | SC-09, SC-10 |
| REQ-S1-09 (§93 токены/фрагменты/дубли/связи) | SC-11, SC-12 |
| REQ-S1-10 (§108/§109 логи + run_id) | SC-13 |
| REQ-S1-11 (§107 default ON + минимальные тесты) | SC-03, SC-14 |
| REQ-S1-12 (§83 сохранность/дефолты) | SC-05, SC-15 |
| REQ-S1-13 (§85/§87 маршрут UI) | SC-16 |

---

## 4. Наблюдаемое поведение

### 4.1. Главный поток (ON, дефолт)
```
rows = get_window_messages(chat_id)                 # неизменно
  ├─ RAG/graph/memorize ключи и контекст             # используют ИСХОДНЫЕ rows (без регресса recall)
  └─ result = summary_filter.filter_window(rows, params, bot_id, trigger_message_id)
        xml_context = summary_xml.build(result.kept, aliases, trigger_message_id)   # ← фильтруется только это
xml_context + RAG/graph → _compose_user_content → Редактор → Рассказчик → публикация (НЕ тронута)
```

### 4.2. Режимы
- **ON (по умолчанию):** `flags.summary_filter_enabled=true` → вход XML = `result.kept`.
- **OFF:** флаг `false` → фильтр не вызывается, `xml.build(rows)` — **байт-в-байт** прежний путь (никаких побочных записей/логов счёта). Переключение — hot (без рестарта).
- **Fail-open:** любое исключение внутри фильтра → WARNING `event=FILTER_ERROR`, `kept=rows` (нефильтрованное окно), Саммари работает. Тихая потеря недопустима.

### 4.3. Гарантии «фильтр не теряет важное»
1. Ответ (`reply_to_id != None`) → балл ≥1 → сохранён при `min_weight=1`.
2. Родитель, на который ответили (в окне), → балл ≥1 → сохранён.
3. `dropped` сохраняется полностью (строка + `score` + побочные `reason`) и передаётся дальше — S2 восстанавливает обратимо; ничего не выбрасывается безвозвратно.
4. `trigger_message_id` (маркер /summary, ADR-1023-1) **принудительно сохраняется** (иначе маркер теряется).
5. Если после фильтра `kept` пуст, а `rows` не пуст → fail-open: `kept = rows` + WARNING `event=FILTER_EMPTY_FALLBACK`.
6. Ровно-пороговое поведение — сохранять (`score >= min_weight`).

---

## 5. Контракт данных `FilterResult` (`services/summary_filter.py`)

```python
@dataclasses.dataclass(frozen=True)
class FilterParams:
    min_weight: int = 1
    min_words_for_bonus: int = 5
    burst_window_seconds: int = 120
    min_burst_density: int = 4
    reply_context_enabled: bool = True

@dataclasses.dataclass(frozen=True)
class Fragment:
    index: int                       # 0-based
    message_ids: tuple[int, ...]     # tg/id-стабильные id строк окна (row["id"]) в хронологии
    overlap_message_ids: tuple[int, ...]   # повтор предыдущего фрагмента (перекрытие), [] у первого
    reason: str                      # "token_budget"

@dataclasses.dataclass(frozen=True)
class FilterResult:
    kept: list                       # АСК-хронология, тот же тип строк, что вход
    dropped: list                    # АСК-хронология (для S2), полные строки
    fragments: list | None           # None если «влезает»; иначе []-безопасный список Fragment
    source_count: int
    saved_count: int
    restored_count: int              # 0 в S1 (заполняет S2); поле зарезервировано
    drop_percent: float              # 0..100, округление до 1 знака
    counts: dict[str, int]           # 'mention_or_reply','answered','burst','long','bot_excluded'
    scores: dict[int, int]           # row-id -> балл (kept и dropped)
    budget: dict                     # {'fits': bool, 'estimated_tokens': int, 'limit': int, 'kind': 'tokens'|'chars'}
    status: str                      # 'ok' | 'disabled' | 'empty_fallback' | 'error'
    duration_ms: float
```

Публичные функции (чистые, без LLM/сети/БД/часов):
- `score_message(row, *, children_by_tg, burst_ids, params, bot_id) -> int` — 0..4.
- `filter_window(rows, params, *, bot_id=None, trigger_message_id=None, token_limit=None, char_limit=None) -> FilterResult`.
- `estimate_and_split(kept, *, token_limit, char_limit) -> tuple[list[Fragment] | None, dict]` — §93 (переиспользует `count_tokens`).

---

## 6. Каталог: `summary.filter.*` (санкция ADR-1026-1 D1)

Хранилище — **существующий** каталог (`param_catalog` → `chat_params`/PG-конфиг, `hot.get`), параллельное хранилище запрещено. Ключи — канон `{category}.{field_lower}`; «предлагаемые» `summary.filter.*` из §87 транслируются в `flags.*`/`limits.*`.

| Ключ (PG) | Settings-поле | Кат. | Группа | Тип | Дефолт |
|---|---|---|---|---|---|
| `flags.summary_filter_enabled` | `SUMMARY_FILTER_ENABLED` | flags | `flags_summary_filter` | bool | **True (ON)** |
| `flags.summary_filter_reply_context_enabled` | `SUMMARY_FILTER_REPLY_CONTEXT_ENABLED` | flags | `flags_summary_filter` | bool | True |
| `limits.summary_filter_min_weight` | `SUMMARY_FILTER_MIN_WEIGHT` | limits | `limits_summary_filter` | int | 1 |
| `limits.summary_filter_min_words_for_bonus` | `SUMMARY_FILTER_MIN_WORDS_FOR_BONUS` | limits | `limits_summary_filter` | int | 5 |
| `limits.summary_filter_burst_window_seconds` | `SUMMARY_FILTER_BURST_WINDOW_SECONDS` | limits | `limits_summary_filter` | int | 120 |
| `limits.summary_filter_min_burst_density` | `SUMMARY_FILTER_MIN_BURST_DENSITY` | limits | `limits_summary_filter` | int | 4 |
| `limits.summary_filter_context_neighbors` | `SUMMARY_FILTER_CONTEXT_NEIGHBORS` | limits | `limits_summary_filter` | int | 1 |
| `limits.summary_filter_context_max_messages` | `SUMMARY_FILTER_CONTEXT_MAX_MESSAGES` | limits | `limits_summary_filter` | int | 50 |

- **Новые группы:** `flags_summary_filter` («Предфильтрация»), `limits_summary_filter` («Тонкая настройка»). Обе добавляются в `TAB_RULES[TAB_MOD_SUMMARY]`; новая вкладка **не** создаётся.
- **Δ каталога (санкционировано):** REGISTRY 459→**467**, Settings 418→**426**, categorized 434→**442**, GROUPS 98→**100**, `_TAB_BY_GROUP` 96→**98**, `TAB_RULES`/`TAB_NAV`/`CONFIG_TAB_TITLES` 21 (без изменений). JS `MODULES` — **без изменений**.
- **Резолвинг:** `hot.get(key, settings.FIELD)` → каскад **global → per-chat override → код-дефолт** через существующий механизм (`_chat_limit`/`get_chat_param`). `per_chat` — да, для всех 8 ключей (чат A ≠ чат B). Значения соседних ключей/чатов не подменяются (§83).
- `context_neighbors`/`context_max_messages`/`reply_context_enabled` — заводит S1 (UI/персистентность), **потребляет S2**; семантика восстановления — зона S2.

### 6.1. Решение Step 2b по M-1 — главный тумблер **per-chat** (обязательно к исполнению)

`flags.summary_filter_enabled` резолвится **per-chat**, как остальные 7 ключей (каталог `per_chat=True`, SC-05, §5/§38/§43: «не использовать один глобальный boolean для всех чатов»; §89 «тонкая настройка»). Текущее чтение в `services/summary_generator.py:336-337` (`hot.get` без chat-скоупа) — **дефект реализации**, а не намерение; spec/каталог не меняются.

**Точная формулировка для @Builder:** в `SummaryGenerator._run` заменить глобальное чтение на `bool(await _chat_limit(chat_id, "flags.summary_filter_enabled", hot.get("flags.summary_filter_enabled", settings.SUMMARY_FILTER_ENABLED)))` — симметрично `flags.summary_filter_reply_context_enabled` (`:495-498`). Fail-open и OFF-байт-в-байт сохраняются.

### 6.2. Решение Step 2b по B-1 — санкция переиздания frozen-артефактов F8

Δ каталога D1 (459→467) делает переиздание артефактов round1025 F8 (**AMEND ADR-1025-21 D6**, см. **ADR-1026-2**) штатной процедурой. **Санкция выдана; откат не требуется.** Procedure = repin `sha256` + регенерация TSV/screen-map/meta + recount/дельта (411→467=56) + обновление `f8_baseline.json`/ассертов; байтфризы (`pg_db.py`/`routes.py`) и строгие пины остаются; 459/48 сохраняются как исторический baseline.

---

## 7. Алгоритм веса (ADR-1026-1 D4) — детерминированный

Вход отсортирован АСК по `(timestamp, id)`. Один проход. Никакого чтения системных часов.

**Индексы (O(n)):**
- `children_by_tg`: `tg_message_id` → число строк окна с `reply_to_id == tg_message_id` (строки с `tg_message_id is None` пропускаются).
- `burst_ids`: множество id в «всплеске по плотности».

**Всплеск по плотности (критерий 3):** trailing-окно `[t_i − burst_window_seconds, t_i]`; сообщение в всплеске, если число строк окна в этом интервале (включая само) **≥ `min_burst_density`** (`==` порога → всплеск). Два соседних сообщения при дефолте `density=4` всплеском **не** считаются (§88). Асимметрия trailing-окна допустима (fail-open в сторону сохранения более поздних; ранние добираются S2).

**Балл сообщения `m` (0..4, максимум 1 за критерий):**
1. `+1` если `reply_to_id != None` **или** текст содержит адресное упоминание (`@[A-Za-z0-9_]{3,}`; множество упоминаний = **1 балл**).
2. `+1` если `children_by_tg.get(m.tg_message_id, 0) > 0`, **и** `reply_context_enabled` (иначе критерий не начисляется).
3. `+1` если `m.id ∈ burst_ids`.
4. `+1` если число слов в тексте (split по whitespace) **> `min_words_for_bonus`** (строго; `==` порога → нет балла).

**Исключение «не-событий»:** если `bot_id is not None` и `m.user_id == bot_id` → `score = 0` (сообщения бота/прошлые Саммари не начисляют баллы и не идут в `children_by_tg`/`burst_ids`, §91). При `bot_id is None` — правило не применяется.

**Порог:** `kept = {m : score(m) >= clamp(min_weight, 0, 4)}`. `min_weight ≤ 0` → keep-all; `min_weight > 4` → клэмп до 4 (не «удалить всё молча»).

**Детерминизм:** одинаковый вход (+ `bot_id`/`trigger_message_id`) → байт-идентичный `kept`/`dropped`/`scores`; тай-брейки — по `(timestamp, id)`; сложность O(n log n) только на сортировку (вход уже отсортирован) — практически O(n).

---

## 8. Лимит контекста §93 (механическая часть S1; семантика — S3)

- **Оценка:** `estimate_and_split` считает токены по существующим потолкам `limits.summary_max_context_tokens`/`summary_max_context_chars` (новых ключей нет). Результат — `budget.fits` + статус, без сети/LLM.
- **«Не влезает»:** детерминированное разбиение `kept` на **перекрывающиеся** фрагменты по границам сообщений (overlap — хвост предыдущего фрагмента, по умолчанию код-константа `overlap = 1` сообщение); **последний фрагмент всегда заканчивается последним `kept`** — «не отрезать последние сообщения молча».
- **Дубли/связи:** дедуп в S1 — только по `id` (механический); `reply_to_id`/`tg_message_id` сохраняются. Семантическое «объединить темы/устранить дубли» — **S3** (см. D5).
- Контракт для S3: `result.fragments` (список `Fragment`) либо `None`; `kept`/`dropped` доступны всегда.

---

## 9. Интеграция в `_run` (ADR-1026-1 D6)

- Врезка **строго** после `rows = await self.memory.get_window_messages(chat_id)` и до `self.xml.build(...)`. Порядок этапов/публикация не меняются.
- `xml.build` получает `kept`; **все прочие потребители `rows`** (`_extract_keywords`, `search_long_term`, `vector_search`, `get_graph_facts`, `memorize_facts`, `_ensure_shiz_postfix`) остаются на **исходных** `rows` (нет регресса RAG/памяти).
- **Двухвызовность:** фильтр — алгоритмический, **0 LLM-вызовов**; `SYSTEM2_SUMMARY_ENABLED`-ветка Редактор→Рассказчик и `truncate_to_tokens` не меняются (ADR-1022-3/4/5 сохраняются).
- `trigger_message_id` передаётся в фильтр как forced-keep (маркер ADR-1023-1).
- Fail-open и OFF — см. §4.2.

---

## 10. UI (ADR-1026-1 D6)

- Маршрут §85/§87: **Модули → Сводки чатов → Подготовка сообщений** (вкладка `mod_summary`, каркас F5). Группы `flags_summary_filter`+`limits_summary_filter` рендерятся существующим config-items-механизмом; метаданные — в JS `MODULES` (Δ JS-каталога = 0).
- Главный тумблер «Алгоритмическая предфильтрация» — **default ON**, описание из §87. Мобильный layout — вертикально, без h-scroll; touch ≥44 px.
- Сохранение — **одна серверная мутация** на операцию через `persistItems` (F0, `saveState`/409-контракт). Новых API/таблиц нет.

---

## 11. Логирование и `run_id` (ADR-1026-1 D6)

- `run_id` = существующий `correlation_id` (`usage_events.new_correlation_id()`, `_run:315`). S1 логирует с ним; S7 формализует без переделки контура.
- События: `FILTER_START`, `FILTER_COMPLETE`, `FILTER_ERROR`. Поля COMPLETE (§109): `source_count`, `saved_count`, `restored_count` (=0), `drop_percent`, `duration_ms`, `status`, `run_id`, `chat_id`.
- Метрики фильтра кладутся в аддитивную внутреннюю структуру для §111/§112 (S8) — **без** создания узлов ExecutionGraph (kind `algorithm` эмитит S8).
- **R17/R18:** только числа/коды/id; никаких текстов сообщений, имён, API-ключей.

---

## 12. Инварианты (нарушение = НЕ принято)

1. **Публикация не тронута** (D4/ADR-1025-24): `generate_image*`, `sendRichMessage`, `build_cover_media`, `send_rich_message`, fallback `sendMessage` — вне диффа.
2. **Ровно 2 LLM-вызова** System-2 (ADR-1022-3/4/5); фильтр — 0 LLM-вызовов.
3. **Δ DDL = 0** (SQLite `user_version=12`; PG без новых таблиц/колонок; хранение — существующие `chat_params`/каталог).
4. **Δ каталога = санкция §6** (ровно +8 записей / +2 группы). Любое отклонение — блокер. Переиздание frozen-артефактов round1025 F8 — санкционировано (ADR-1026-2, AMEND ADR-1025-21 D6); откат не требуется.
5. **OFF — байт-в-байт** прежний вход; hot-переключение без рестарта.
6. Fail-open: ошибка фильтра не роняет Саммари и не теряет окно молча.
7. **CSP/zero-build**, **R17/R18**; порядок роутеров `bot.py` не тронут.
8. Промпт-каноны **не меняются** (`services/summary_prompts.py` вне диффа) → `PREV_*`/`PROMPT_MIGRATIONS`/эталон не требуются (ADR-1013-3 не задействован).
9. S6/S10 — отдельный гейт (после live-приёмки Эпика 1); S1 их не открывает.

---

## 13. Сценарии приёмки

- **SC-01** ON: мусор без адреса/ответов/всплеска/длины отсеян; XML-история = `kept`.
- **SC-02** вход L1 = `kept`; RAG/память по-прежнему на исходных `rows` (регресс-тест).
- **SC-03** дефолт ON; OFF → байт-в-байт; переключение без рестарта.
- **SC-04** дефолты 1/5/120; границы (`==` порога) корректны.
- **SC-05** значения резолвятся global→chat→дефолт; чат A ≠ чат B; соседние ключи не изменены.
- **SC-06** каждый критерий даёт свой балл; итог 0..4.
- **SC-07** «много упоминаний → 1 балл»; «ответ на сообщение бота» не считает бота событием.
- **SC-08** «всплеск» ≠ «два сообщения рядом»; плотность учитывается.
- **SC-09** короткий важный тред (ответ + родитель) сохраняется; «короткий тред не бесполезен».
- **SC-10** параллельные разговоры; почти пустой лог; одно сообщение.
- **SC-11** оценка токенов детерминирована; границы.
- **SC-12** фрагменты перекрываются; последние сообщения не отрезаны; reply-связи целы.
- **SC-13** `FILTER_*` в логе с полями §109 + `run_id`, без секретов/содержимого.
- **SC-14** минимальные функциональные тесты §114 до деплоя.
- **SC-15** первый запуск без ручного заполнения (дефолты).
- **SC-16** сохранение/перечитывание UI одной мутацией; reload сохраняет; изоляция чатов; CSP/zero-build.

---

## 14. Зависимости / тесты / деплой / откат

- **Зависимости:** Эпик 1 (F0 save-path, F5 workspace, F6 ExecutionGraph-адаптер — только REUSE); `services/summary_generator.py`/`summary_xml.py`/`summary_memory.py`/`token_counter.py` — reuse. Новых внешних зависимостей нет.
- **Тесты (блок F):** `tests/test_summary_filter.py` — матрица критериев, «максимум 1 балл», границы порога, детерминизм (двойной прогон), перф ~10k; регресс: существующие тесты Саммари зелёные, ровно 2 LLM-вызова, OFF байт-в-байт, fail-open, публикация вне диффа; обновить числа-инварианты `test_param_catalog` под санкцию §6. Полный pytest ≥ 8463/0, JS 42/42.
- **Deploy = VERIFIED (да):** S1 меняет рантайм `services/**` + `config/settings.py` + `services/param_catalog.py` + `web/app.js` → нужны поставка и cache-bust ассетов. **Bump `APP_VERSION` 2.58.17 → 2.58.18**, синхронизация `README.md` (тест `test_app_version_matches_readme`), `?v=` для трёх ассетов.
- **Откат:** kill-switch OFF (флаг каталога) → байт-в-байт; `git revert` + annotated-тег `pre-round1026-s1` (T-3129).
- **Гейт S6/S10:** публикация/hybrid-пайплайн — только после live-приёмки Эпика 1 (ADR-1025-24 D4). S1 их не открывает.

---

## 15. Риски / митигации

| Риск | Ур. | Митигация |
|---|---|---|
| Потеря важного фильтром | High | гарантии §4.3, fail-open, `dropped` для S2, SC-09/10 |
| Δ каталога сверх санкции | Medium | T-3130 санкция §6; Scanner T-3153 сверяет точные числа |
| Случайный заход в публикацию (D4) | High | инвариант 1 + аудит `git diff` по публикационным модулям |
| Эвристика упоминаний (нет поля `mentions`) | Medium | детерминированный regex; `reply_to_id` — основной сигнал; ограничение задокументировано |
| Ложное закрытие по «зелёной сборке» | High | приёмка только по артефактам/evidence (прецедент 10.20/10.22) |
| Live-гейт Эпика 1 PENDING | Medium | S1 безопасен (вход/алгоритм); S6/S10 за отдельным гейтом |
