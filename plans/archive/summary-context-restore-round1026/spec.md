# spec.md — S2 `summary-context-restore-round1026` (Эпик 2, шаг 2: детерминированное восстановление контекста)

> **Раунд 10.26 · Эпик 2 («Summary Hybrid Pipeline») · Приоритет P0 · Тип: backend/алгоритм (0 LLM-вызовов)**
> **Step 2 @Architect (23.09.2026):** спека + **ADR-1026-4** (контракт восстановления, границы S2↔S3, лимиты, интеграция/логи, деплой).
> **Задачи:** `tasks.md` (T-3224…T-3252, блоки 0/A–I). **ТЗ:** `plans/current_task.md` §80, §89–§92, §93, §96, §107–§109, §114, §17.
> **Зависит от:** **S1 `summary-filter-round1026`** (✅ COMPLETED + MERGED §71 + DEPLOYED 2.58.18) — потребляет `FilterResult.kept`/`dropped`.
> **Baseline (Step 0 @Memory, HEAD `7895e77`):** `APP_VERSION` **2.58.20**, pytest `.venv` **8525/0**, JS **43/43**, каталог **467/426/442/100/98/21**, **Δ DDL=0**, CSP/zero-build, R17/R18.
> **Продолжают:** S3 L1 Кластеризатор (§93–§95) — «объединить темы/устранить дубли»; S4 Пакет фактов (§96); S7 логи; S8 узлы `algorithm`.

---

## 1. Область / вне области

**В области S2 (этап «Восстановление контекста», §80/§90–§92):**
- Новый модуль `services/summary_context_restore.py`: **чистая** функция `restore_context(...) -> RestoreResult` — достраивание контекста вокруг `kept` за счёт обратимого `dropped` и полного окна: reply-родители (транзитивно, включая проход **сквозь бот-ответы** через `thread_chain`), ограниченный ближайший контекст, единая хронология, дедуп, сохранение исходных id.
- Асинхронный адаптер в `services/summary_generator.py` (`_apply_filter`-контур): резолв §89-ключей, вызов pure-core, подтяжка родителей **вне окна** через существующий `services/thread_chain.collect_thread_chain`, логи `RESTORE_*`.
- Заполнение `restored_count` (§108/§109) фактическим числом добавленных сообщений.

**ВНЕ области S2 (не реализуется здесь):**
- **Семантическая** кластеризация, «выделить темы / восстановить переплетённые разговоры / объединить темы / устранить семантические дубли» — **S3** (§93–§95, ADR-1026-1 D5).
- Пакет фактов (§96) — S4; L2 Писатель (§97–§99) — S5; публикация (§100–§106) — S6 (гейт); узлы ExecutionGraph `algorithm` (§111) — S8; log viewer §110 — S7.
- Любое изменение `services/summary_xml.py`, `services/summary_prompts.py`, публикационного пути (`generate_image*`, `sendRichMessage`, `build_cover_media`, `send_rich_message`, fallback `sendMessage`) — **запрещено (D4/ADR-1025-24)**.
- Новые параметры каталога/DDL/UI — **нет** (см. D4/D6/D7).

---

## 2. Факты аудита кода (перепроверено Step 2)

| Факт | Точка в коде |
|---|---|
| Пайплайн | `services/summary_generator.py::_run:323-476`, врезка S1 `:338-351` |
| S1-фильтр и его контракт | `services/summary_filter.py` (`FilterParams`/`Fragment`/`FilterResult`, `filter_window:299`) |
| S1-вызов + метрики/логи | `services/summary_generator.py::_apply_filter:478-569` |
| Поля строки окна | `services/database.py::get_smart_window:1864-1875` → `id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, is_forward, forward_source, tg_message_id` |
| Родитель вне окна (та же схема полей) | `services/database.py::get_smart_message_by_tg_id:1984-1993` |
| `reply_to_id` = **Telegram** `message_id` родителя | `handlers/summary.py:181-183` |
| Готовый проход цепочки реплаев **сквозь бот-ответы** | `services/thread_chain.py::collect_thread_chain:94`, `ChainItem:30` (`bot_replies`/`bot_reply_parents`) |
| Бот-хендл и БД | `SummaryGenerator.bot:290`, `SummaryGenerator.memory:287` → `SummaryMemory.db:1186` |
| Единый потолок контекста (без новых ключей) | `services/token_counter.py::resolve_context_tokens:131`, `resolve_chat_limit:157`; ключи `limits.summary_max_context_tokens`/`_chars` |
| §89-ключи S2 (уже заведены S1) | `config/settings.py:955-958`; `services/param_catalog.py:1069-1071`, группы `limits_summary_filter`/`flags_summary_filter` |
| XML-модуль (вне diff) | `services/summary_xml.py::build:57` (читает `row["id"|"timestamp"|"author_name"|"user_id"|"media_type"|"text"|"reply_to_id"]`) |

**Критично (установлено по коду):**
1. `collect_thread_chain` **async и читает БД** (`get_smart_message_by_tg_id`, `get_bot_reply`, `get_bot_reply_parent`) — это единственный канонический обход reply-цепочки. Pure-core S2 не делает I/O: он получает `window` (все строки) и `extra_parents` (строки вне окна, добытые адаптером) как данные.
2. Родитель, **уже присутствующий в окне**, восстанавливается **чисто** (индекс `tg_message_id → row` над `window`). Обращение к БД нужно только для родителя **вне окна / сквозь бот-ответ** — там переиспользуется `collect_thread_chain`.
3. Строки вне окна имеют **тот же набор полей**, поэтому `summary_xml.build` принимает смешанный набор **без изменений**.
4. Поля `mentions` в строке нет (как в S1) — не выдумывать (§92).
5. `FilterResult.fragments` рассчитаны по `kept` S1 и адресованы **S3**; S2 их **не потребляет** (см. §6).

---

## 3. Трассируемость REQ → сценарии

| REQ | Источник (verbatim) | Сценарии |
|---|---|---|
| REQ-S2-01 | §80 «Восстановление контекста» в пайплайне | SC-01, SC-02, SC-13 |
| REQ-S2-02 | §90 «Определить reply_to. Добавить необходимые родительские сообщения» | SC-02, SC-03 |
| REQ-S2-03 | §90 «Добавить ограниченный ближайший контекст» | SC-04 |
| REQ-S2-04 | §90 «Сохранить хронологию. Удалить дубли. Сохранить исходные message_id» | SC-05, SC-06 |
| REQ-S2-05 | §90 «Нельзя вернуть весь шестичасовой лог. Контекст должен быть ограничен» | SC-04, SC-07, SC-08 |
| REQ-S2-06 | §91 спец-случаи (треды/длинные/параллельные/упоминания/reply/медиа/подписи/транскрипты/бот) | SC-09, SC-10, SC-11 |
| REQ-S2-07 | §91 «Не включать предыдущие Саммари как новые события» | SC-12 |
| REQ-S2-08 | §92 «структурированные сообщения… только реальные поля… корректная идентификация авторов» | SC-06, SC-14 |
| REQ-S2-09 | §89 «Сохранение контекста ответов / Количество ближайших / Лимит восстановленного» | SC-03, SC-04, SC-07 |
| REQ-S2-10 | §93 «оценивать токенный объём… не отрезать последние сообщения молча» | SC-07, SC-08 |
| REQ-S2-11 | §107 «включено по умолчанию… минимальные тесты перед деплоем» | SC-15, SC-16 |
| REQ-S2-12 | §108/§109 «FILTER_COMPLETE: Восстановленные из контекста» | SC-13 |
| REQ-S2-13 | §85/§87 «Модули → Сводки чатов → Подготовка сообщений» | SC-17 (NOT_APPLICABLE) |

---

## 4. Наблюдаемое поведение

### 4.1. Главный поток (ON, дефолт)
```
rows = get_window_messages(chat_id)                       # полное окно (6ч) — неизменно
  ├─ RAG/graph/memorize/постфикс                           # ИСХОДНЫЕ rows (как в S1)
  └─ result   = filter_window(rows, …)                     # S1: kept/dropped/fragments
        restore = restore_context(result.kept, result.dropped, window=rows, …)   # S2 (pure)
        xml_context = summary_xml.build(restore.kept, aliases, trigger)          # БЕЗ изменений XML
  → Редактор → Рассказчик → публикация (НЕ тронута, ровно 2 LLM-вызова)
```

### 4.2. Режимы
- **ON (дефолт):** `flags.summary_filter_enabled=true` **и** `flags.summary_filter_reply_context_enabled=true` → XML-вход = `RestoreResult.kept` (S1 `kept` ∪ добавленные, ASC, без дублей).
- **OFF по `flags.summary_filter_reply_context_enabled=false`:** S2 **не вызывается**, XML-вход = `FilterResult.kept` — **байт-в-байт** поведение S1 (T-3242). Переключение hot.
- **OFF по мастер-тумблеру `flags.summary_filter_enabled=false`:** фильтр и восстановление не вызываются, XML-вход = `rows` (как в S1).
- **Fail-open:** любое исключение S2 → WARNING `event=RESTORE_ERROR`, XML-вход = `FilterResult.kept` (S1-выход). Тихая потеря недопустима.

### 4.3. Гарантии
1. S2 **никогда не удаляет** ни одного элемента `kept` — только добавляет (усечение возможно лишь для *добавляемых* кандидатов, и оно всегда логируется).
2. Добавляемое множество ограничено `context_max_messages` (cap) **и** существующим потолком токенов/символов.
3. Хронология единая ASC `(timestamp, id)`; тай-брейк детерминирован.
4. Исходные `id`/`tg_message_id`/`reply_to_id` не подменяются (§92).
5. Двойной прогон при одном входе → байт-идентичный `RestoreResult`.

---

## 5. Контракт данных S2 (`services/summary_context_restore.py`) — D1

```python
@dataclasses.dataclass(frozen=True)
class RestoreParams:
    context_neighbors: int = 1          # §89: ближайших контекстных сообщений (с каждой стороны)
    context_max_messages: int = 50      # §89: лимит ВОССТАНОВЛЕННЫХ (добавляемых) сообщений

@dataclasses.dataclass(frozen=True)
class RestoreResult:
    kept: list                # ФИНАЛ для xml.build: S1.kept ∪ restored, ASC (timestamp,id), без дублей
    restored: list            # только ДОБАВЛЕННЫЕ строки (родители + соседи), ASC
    restored_count: int       # len(restored) — заполняет §109
    parent_count: int         # из них reply-родителей
    neighbor_count: int       # из них соседей
    restored_tg_ids: tuple    # tg_message_id добавленных (только числа/id — R17)
    skipped_ids: tuple        # DB-id кандидатов, не добавленных из-за cap/бюджета (для логов)
    budget: dict              # {'fits':bool,'estimated_tokens':int,'limit':int,'kind':'tokens'|'chars'}
    status: str               # 'ok' | 'no_candidates' | 'truncated' | 'error'
    duration_ms: float
```

**Публичная чистая функция:**
```python
def restore_context(kept, dropped, window, params, *, extra_parents=(),
                    token_limit=None, char_limit=None, bot_id=None) -> RestoreResult
```
- Без LLM, без сети, **без БД**, без системных часов; входные списки не мутируются.
- `window` — полное окно (`rows`); `extra_parents` — строки **вне окна**, добытые async-адаптером (та же схема полей).

**Контракт S1 → S2 → XML (D1):**
- S2 **не меняет** `summary_xml.py` и его подпись: `_run`/`_apply_filter` передаёт в `xml.build` **`RestoreResult.kept`** — набор строк того же типа, что и `FilterResult.kept`.
- Новый объект `RestoreResult` — **самостоятельная** аддитивная структура (не расширяет `FilterResult`). `FilterResult` не ломается: в `_apply_filter` его поля `kept`/`restored_count` обновляются по результату S2 (`dataclasses.replace`) только для метрик/логов; `dropped`/`fragments` остаются доступны.
- **Обратимость:** S2 детерминирован и неразрушающ — `dropped` и `window` неизменны, результат воспроизводим.
- **Fail-open:** исключение внутри core или адаптера → `status='error'`, `kept = FilterResult.kept`.

---

## 6. Границы §93: S2 ↔ S3 — D2

- **S2 = только детерминированное достраивание контекста** (родители + соседи). Семантика тем, кластеризация, «объединить темы / устранить семантические дубли» — **S3** (L1 LLM, §94–§95).
- **`FilterResult.fragments`:** контракт **не меняется** (`Fragment{index, message_ids, overlap_message_ids, reason}` | `None`); S2 их **не потребляет** и не пересчитывает — фрагменты остаются входом S3. S2 оперирует полным окном и `kept`/`dropped`, а не фрагментами `kept`.
- Механический дедуп по `id` (как в S1) — S2 сохраняет; `reply_to_id`/`tg_message_id` сохраняются для L1 (§92).

---

## 7. `restored_count` — семантика и логи — D3

- **Семантика:** `restored_count = len(restored)` — число **добавленных** сообщений (reply-родители + соседи), **после** дедупа с `kept`, cap и бюджета. Дедуплицированные пересечения **не** считаются. `saved_count` остаётся числом `kept` S1; итоговый размер XML-входа = `saved_count + restored_count`.
- **Где считается:** в pure-core (`RestoreResult.restored_count`), переносится в `FilterResult.restored_count` (`dataclasses.replace`) — §109/§108/S7 читают единый источник.
- **Логи:** `FILTER_COMPLETE` заполняет `restored_count` фактическим значением (было `0`); дополнительно — события `RESTORE_START`/`RESTORE_COMPLETE`/`RESTORE_ERROR` (аддитивно, `event=`-стиль S1) с `run_id = correlation_id` (R17: только числа/коды/id).

---

## 8. Лимиты и порядок применения §89/§93 — D4

**Ключи (уже существуют, потребляются S2; новых нет):**

| Ключ | Роль S2 | Дефолт |
|---|---|---|
| `limits.summary_filter_context_neighbors` | число ближайших соседей **с каждой стороны** от якоря | 1 |
| `limits.summary_filter_context_max_messages` | жёсткий cap на число **добавленных** сообщений | 50 |
| `flags.summary_filter_reply_context_enabled` | мастер-гейт всего S2 (OFF → без восстановления) | True |
| `limits.summary_max_context_tokens`/`_chars` | общий бюджет (через `resolve_context_tokens`/`resolve_chat_limit`) | как в S1 |

Резолв — **per-chat** (`_chat_limit`: global → chat → код-дефолт), симметрично S1.

**Порядок применения (детерминированный):**
1. **Reply-родители** (высший приоритет): для каждого якоря `kept` идти по `reply_to_id` транзитивно по окну (пример §90: 100→101→102); родитель **вне окна / сквозь бот-ответ** — через `collect_thread_chain` (адаптер, глубина ≤ код-константы `RESTORE_CHAIN_DEPTH=10`), только не-бот элементы (§91).
2. **Соседи:** для каждого якоря (`kept` + восстановленные родители) — до `context_neighbors` предшествующих и до `context_neighbors` последующих строк окна по хронологии (только из `dropped`).
3. **Cap:** если добавлений > `context_max_messages` → приоритет родители → соседи по близости; тай-брейк `(timestamp, id)`; отброшенные → `skipped_ids`.
4. **Бюджет:** оценка `count_tokens` (или chars-fallback, `resolve_chat_limit`) по `kept ∪ restored`; при превышении — отбрасывать добавляемые с низшим приоритетом до влезания; `kept` не трогать.

**«Не резать молча» (§93):** любое усечение (cap или бюджет) → `status='truncated'`, лог `RESTORE_COMPLETE` (`skipped_count`) и `skipped_ids`; последние `kept`-сообщения не теряются **никогда** (S2 не удаляет из `kept`). Жёсткий cap символов в `summary_xml.build` остаётся последней страховкой (вне diff).

---

## 9. Спец-случаи §91 — D5

- **Короткие важные треды:** родитель+ответ восстанавливаются целиком (приоритет родителей).
- **Длинные бессодержательные:** не раздувают контекст — соседи ограничены `context_neighbors`, добавления — cap.
- **Параллельные разговоры:** связанность только по `reply_to_id`/соседству по хронологии; несвязанные ветки **не** склеиваются (нет глобального «объединения»).
- **Упоминания:** поля `mentions` в окне нет — не выдумывать (ограничение наследуется от S1).
- **Медиа / подписи / транскрипты:** строка с `media_type != 'text'` и пустым `text` **не отбрасывается** (медиа — валидный родитель/сосед); подпись/транскрипт сохраняются как есть.
- **Ответы бота и предыдущие Саммари — не события:** элементы `collect_thread_chain` с `is_bot=True` и любые строки с `user_id == bot_id` **не восстанавливаются** как контекст (согласованно с семантикой S1 §91/T-3237); сквозь бот-ответ проходим, но сам бот-ход в набор не попадает.
- **Идентификация авторов §92:** `author_id ← user_id`, `display_name ← author_name`, `message_id ← tg_message_id`, `reply_to_id`, `message_type ← media_type`, `timestamp`; `chat_id` — из контекста запуска; отсутствующие поля **не фабрикуются**.

---

## 10. Интеграция, логи, UI — D6

- **Место врезки:** внутри `_apply_filter` **после** `filter_window` и **до** `xml.build` (строго между `get_window_messages` и XML, как S1). `_run` и порядок этапов не меняются; RAG/память/граф/memorize — на **исходных** `rows`.
- **0 новых LLM-вызовов**; двухвызовность (ADR-1022-4) сохранена.
- **Логи:** `RESTORE_START` / `RESTORE_COMPLETE` / `RESTORE_ERROR` (+ `status=truncated`), `run_id=correlation_id`; поля только числа/коды/id (R17/R18). Метрики — аддитивно в `self._filter_metrics[chat_id]` (`restored_count`, `parent_count`, `neighbor_count`, `skipped_count`, `status`) для S8; узлы `algorithm` не создаются.
- **UI (блок H):** **NOT_APPLICABLE.** S2 не вводит новых параметров; §89-ключи `SUMMARY_FILTER_CONTEXT_NEIGHBORS`/`SUMMARY_FILTER_CONTEXT_MAX_MESSAGES` уже рендерятся в существующей группе «Тонкая настройка» вкладки «Подготовка сообщений» (`mod_summary`). Δ каталога = 0, Δ JS `MODULES` = 0, новых API нет.

---

## 11. Инварианты / деплой — D7

1. **Δ DDL = 0**; **Δ каталога = 0** (новых параметров нет → переиздание frozen-артефактов F8 **не требуется**, в отличие от S1). Любой новый параметр — только по письменной санкции @Architect.
2. `summary_xml.py`/`summary_prompts.py`/публикация — **вне diff** (D4-гейт S6/S10 закрыт).
3. **Ровно 2 LLM-вызова**; **0** новых LLM-вызовов в S2.
4. Не ломать §57–§72/F0–F11/S1, IA, сердцебиение, zero-build/CSP; R17/R18.
5. **Переиспользовать** `services/thread_chain.py`; вторую реализацию обхода цепочки не создавать; `thread_chain.py` не модифицировать.
6. **Deploy = ДА:** новый рантайм `services/summary_context_restore.py` + правка `services/summary_generator.py` → **bump `APP_VERSION` 2.58.20 → 2.58.21** + синхронизация `README.md` (`test_app_version_matches_readme`) + cache-bust `?v=2.58.21`.
7. **Откат:** hot-OFF `flags.summary_filter_reply_context_enabled=false` (байт-в-байт S1) или полный `flags.summary_filter_enabled=false`; `git revert` + annotated-тег **`pre-round1026-s2`**.
8. **Форма приёмочного отчёта** (`evidence.md`): `git rev-parse pre-round1026-s2`, baseline-числа (8525/0, JS 43/43, каталог 467/…), per-block факты, пример `100→101→102`, значения `restored_count`, pytest/JS после, `git diff --stat` по публикационным/XML/промпт-модулям = пусто, маркеры **Δ DDL=0 / Δ каталога=0**, поля `RESTORE_*` без секретов.
9. **§17:** после деплоя workflow **не останавливать**; live-проверки Telegram — `PENDING OWNER VERIFICATION`; продолжить S3 `summary-l1-clusterizer`.

---

## 12. Сценарии приёмки

- **SC-01** ON: XML-история = `RestoreResult.kept`; RAG/память — на исходных `rows` (регресс-тест).
- **SC-02** §90 пример: `102` сохранён → `100` и `101` восстановлены, порядок `100,101,102`.
- **SC-03** OFF `reply_context_enabled=false` → XML-вход байт-в-байт = `FilterResult.kept`; родители не добавляются.
- **SC-04** всплеск → добавлены только ближайшие (`context_neighbors`), не весь 6-часовой лог.
- **SC-05** хронология ASC `(timestamp,id)`; двойной прогон байт-идентичен; дублей нет.
- **SC-06** исходные `id`/`tg_message_id`/`reply_to_id` не подменены; авторы корректны.
- **SC-07** cap=50 при 200 кандидатах; `context_neighbors` граница (0/1/N) соблюдена.
- **SC-08** усечение (cap/бюджет) → `status='truncated'` + лог + `skipped_ids`; последние не потеряны молча.
- **SC-09** короткий важный тред восстановлен; длинное бессодержательное не раздувает.
- **SC-10** два параллельных треда не перемешиваются.
- **SC-11** медиа-родитель без текста / подпись / транскрипт восстановлены.
- **SC-12** прошлое Саммари и бот-ответ **не** попадают восстановленным событием (сквозь бот-ответ проходим).
- **SC-13** `RESTORE_*` + `FILTER_COMPLETE.restored_count` в логе с `run_id`, без секретов/содержимого (R17/R18).
- **SC-14** `mentions`/иные отсутствующие поля не выдумываются; `chat_id` из запуска.
- **SC-15** дефолт ON; OFF hot; fail-open (инъекция ошибки → рабочее Саммари на S1-выходе).
- **SC-16** минимальные функциональные тесты §114 до деплоя.
- **SC-17** UI — NOT_APPLICABLE (обоснование §10); Δ каталога=0 подтверждён.

---

## 13. Зависимости / тесты / откат

- **Зависимости:** только reuse — `services/summary_filter.py`, `services/thread_chain.py`, `services/token_counter.py`, `services/summary_memory.py`/`database.py` (чтение), `services/summary_xml.py` (без изменений). Новых внешних библиотек нет.
- **Тесты (`tests/test_summary_context_restore.py` + интеграция):** матрица §12 (SC-01…SC-16), детерминизм (двойной прогон), fail-open, OFF байт-в-байт, границы cap/бюджета, «два треда», «бот/прошлое Саммари», «медиа без текста», «id не подменены», «ровно 2 LLM-вызова», публикация/XML/промпты вне diff. Полный pytest ≥ baseline **8525/0**, JS **43/43**.
- **Откат:** kill-switch `flags.summary_filter_reply_context_enabled=false` (hot) → байт-в-байт S1; `git revert` + тег `pre-round1026-s2` (T-3224).
- **Гейт S6/S10:** закрыт (ADR-1025-24 D4); S2 его не открывает.

---

## 14. Риски / митигации

| Риск | Ур. | Митигация |
|---|---|---|
| Потеря reply-контекста (родители вне окна / сквозь бот-ответы) | Critical | reuse `collect_thread_chain` (глубина ≤10), SC-02/SC-12 |
| Дубли/порядок | High | единая ASC-сортировка + дедуп по `id`, SC-05 |
| Выход за лимиты (cap/токены) | High | детерминированный приоритет + `truncated`-лог, SC-07/SC-08 |
| Случайный заход в XML/промпты/публикацию (D4) | High | инвариант §11.2 + `git diff`-аудит (T-3246) |
| Ложное закрытие по «зелёной сборке» | High | приёмка только по evidence (прецедент 10.20/10.22) |
| Необоснованный Δ каталога/DDL | Medium | инвариант §11.1; Scanner T-3246 |
| Невидимый проход цепочки через БД замедляет прогон | Low | один вызов на «открытый» якорь, cap, fail-open |

---

## 15. Карта решений Step 2 (@Architect)

| # | Решение | Где |
|---|---|---|
| **D1** | Контракт `RestoreResult` (аддитивный), в XML отдаётся `RestoreResult.kept`; XML/подпись не меняются; обратимость/fail-open | §5, ADR D1 |
| **D2** | S2 = только детерминированное достраивание; семантика тем/дубли — S3; `fragments` S2 не потребляет | §6, ADR D2 |
| **D3** | `restored_count` = число добавленных (родители+соседи) после дедупа/cap/бюджета; логи `RESTORE_*` + `FILTER_COMPLETE` | §7, ADR D3 |
| **D4** | `context_neighbors=1`/`context_max_messages=50` (per-chat, существующие ключи) + общий бюджет; порядок родители→соседи→cap→бюджет; «не резать молча» | §8, ADR D4 |
| **D5** | Спец-случаи §91; бот/прошлое Саммари — не события; идентификация авторов §92 только по реальным полям | §9, ADR D5 |
| **D6** | Врезка после `_apply_filter`, до `xml.build`; 0 LLM; `RESTORE_*`; UI = NOT_APPLICABLE | §10, ADR D6 |
| **D7** | Δ DDL=0, Δ каталога=0, CSP/zero-build, R17/R18, 2-вызовность, гейт S6/S10 закрыт; deploy=ДА, bump 2.58.20→2.58.21; §17 | §11, ADR D7 |
