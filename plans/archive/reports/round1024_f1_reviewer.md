# Отчёт @Reviewer — раунд 10.24, Фича F1 `core-llm-error-fixes-round1024`

> **Ревьюер:** @Reviewer (Senior Principal Engineer — качество / безопасность / архитектура / прод-готовность).
> **Дата:** 19.09.2026. **Шаг:** 5 (строгий аудит), **итерация 1**.
> **Коммит:** `2a5c694` — `fix(services,tests): раунд 10.24 F1 — устойчивость фонового graph-extract к таймауту (чанкование, отдельный deadline, метрика dropped)`.
> **Диапазон ревью:** `git diff 2a5c694^ 2a5c694` (8 файлов, +593/−50): `config/settings.py`, `services/llm_client.py`, `services/summary_memory.py`, `tests/test_graphrag_memory.py`, `tests/test_history_retention_toggle.py`, `tests/test_llm_client.py`, `tests/test_payload_builder.py`, `tests/test_summary_memory.py`.
> **Замечание о состоянии дерева:** во время аудита HEAD сдвинулся на `27296bb` (F2 review-iter1). Дифф F1 проверялся ровно по `2a5c694`; полный pytest запускался на текущем HEAD (`2a5c694`+`27296bb`). `services/llm_client.py` и `services/summary_memory.py` в `27296bb` не менялись.
> **Метод:** полный `git show`/`git diff`; чтение call-site; **сравнение блока `embed` байт-в-байт через хеш**; целевые прогоны; полный pytest (2 прогона).

---

## Status: **Changes Requested**

---

## Сводка (почему не готово)

Ядро F1 сделано правильно и аккуратно: фоновый канал `generate_background` отделён от общего `generate`, `_post` получил строго аддитивные `budget`/`max_retries` (`None` → прежнее поведение), extрирован→запись выполнена как «extract-then-write» (запись ровно один раз на батч), есть bounded-чанкование, отдельный дедлайн/попытки, явные исходы all-ok/partial/none-ok и явный `drop` со счётчиком, а embeddings-код **не тронут** (дифф по `embed`/`EMBEDDING` пуст, блок байт-в-байт идентичен). Δ каталога = 0, Δ DDL = 0, egress/`parse_mode`/R16 не затронуты.

Но **один пункт контракта нарушен**: ADR-1024-6 D4 и spec §3.4 требуют структурированное событие именно с `event=graph_extract_dropped` / `event=graph_extract_partial` / `event=graph_extract_failed` (греп/алерт Betterstack). Фактически события уходят через F2-хелпер как `event=dropped_metric reason=graph_extract_dropped` и `event=pipeline_step reason=graph_extract_failed|partial`. Литерала `event=graph_extract_dropped` в логах **нет**, тестами это не зафиксировано — то есть алерт по документированному ключу не сработает. Ровно та категория «почти по спеке», которую нельзя пропускать: фича целиком про наблюдаемость потери графа.

Плюс есть несколько не-блокирующих, но обязательных к устранению замечаний (kill-switch не байт-в-байт, отсутствие батч-капа по триплетам, глобальный счётчик фейлов, пробелы покрытия).

**Итог итерации 1: 0 Critical / 0 High / 1 Medium / 6 Low.**

---

## Findings

### [Severity: Medium] R1024F1-01 — Событие `event=graph_extract_dropped` не эмитится; алерт по документированному ключу мёртв
**File:** `services/summary_memory.py:3416-3422, 3441-3447, 3451-3455`; хелпер — `services/external_log.py:204-224` (`trace_step`) и `:227-240` (`log_dropped`).
**Location:** `trace_step(..., reason="graph_extract_partial"|"graph_extract_failed")` и `log_dropped(..., reason="graph_extract_dropped")`.
**Problem:** ADR-1024-6 D4: «Структурированное лог-событие `event=graph_extract_dropped` (греп/алерт Betterstack)»; spec §3.4 и `round1024-architecture.md` §3.4 перечисляют `event=graph_extract_failed` / `graph_extract_partial` / `graph_extract_dropped` как ключевые события. Реально в лог уходит `event=dropped_metric reason=graph_extract_dropped` и `event=pipeline_step ... reason=graph_extract_failed`. Подстроки `event=graph_extract_dropped` (и остальных) в логе нет.
**Why it matters:** Единственная защита от «тихой» потери графа по замыслу — это алерт на явное событие (R3, критерий приёмки «явный `graph_extract_dropped` с логом и счётчиком»). Оператор, настроивший grep/алерт строго по ADR (`event=graph_extract_dropped`), получит 0 совпадений — потеря графа снова станет невидимой. Плюс это ломает заявленный контракт наблюдаемости для F9/DevOps-шага (T-2195).
**Required fix (выбрать один, зафиксировать письменно и покрыть тестом):**
- (a) Расширить `log_dropped`/`trace_step` в `services/external_log.py` опциональным `event: str | None = None` (при задании — печатать его вместо `dropped_metric`/`pipeline_step`; `None` → прежнее поведение, т.е. F2 не ломается); F1 вызывает с `event="graph_extract_dropped"|"graph_extract_partial"|"graph_extract_failed"`; **или**
- (b) Явно изменить контракт в spec/ADR: зафиксировать, что ключ алерта — `reason=graph_extract_dropped` (и `reason=graph_extract_partial|failed`), синхронизировать §3.4/§D4 и настроить grep/алерт на `reason=`.
- В любом случае добавить регресс-тест, который **точным** regex/подстрокой проверяет согласованный ключ (сейчас тесты проверяют лишь `"graph_extract_dropped" in message`, что маскирует проблему).

---

### [Severity: Low] R1024F1-02 — Kill-switch не «байт-в-байт»: потеря INFO-строки и перестановка `trace_step`
**File:** `services/summary_memory.py:3367-3380` (kill-switch), `:3308-3343` (`_write_graph_triplets`).
**Problem:** ADR-1024-6 D2/spec §3.5 обещают при `GRAPH_EXTRACT_RETRY_ENABLED=False` «прежний одиночный вызов (байт-в-байт старое поведение)». Старый код **всегда** завершал метод строкой `logger.info("graph: triplets=%d | chat_id=%s", ...)`, включая `triplets=0`; новый kill-switch-путь при пустом результате делает `return` из `_log_graph_no_triplets`, и эта INFO-строка теряется. Дополнительно `trace_step(step="write", status="ok")` из начала метода переехал в конец `_write_graph_triplets` (после `logger.info`).
**Why it matters:** Формально это наблюдаемое расхождение «байт-в-байт», а тест `test_kill_switch_single_generate` проверяет только `bg_calls==0`/`legacy_calls==2`, то есть заявленное тождество не подтверждено. Ниже риск, но заявление в ADR ложное.
**Required fix:** Либо восстановить в kill-switch-ветке прежний финальный `logger.info("graph: triplets=0 ...")`, либо явно ослабить формулировку в ADR до «семантически прежнее поведение: тот же одиночный вызов/запись/mark, порядок лог-строк может отличаться». Тест дополнить проверкой, что в kill-switch-ветке `generate()` получает необрезанный `tail` (последние 8000 симв.).

### [Severity: Low] R1024F1-03 — Кап триплетов стал на батч до `N×50` (было ≤50)
**File:** `services/summary_memory.py:3401` (`triplets.extend(parse_triplets(raw))`), `:572` (`parse_triplets` режет на `GRAPH_EXTRACT_MAX_TRIPLETS`=50 **на вызов**).
**Problem:** Кап `limits.graph_extract_max_triplets` (default 50) применяется внутри каждого `parse_triplets`, а чанков до 2 (при дефолтах) → на батч теперь пишется до 100 рёбер вместо ≤50.
**Why it matters:** Скрытый рост объёма записи GraphRAG/стоимости; оператор, воспринимающий ключ как лимит на обработку батча, получает вдвое больше. Не покрыто тестом.
**Required fix:** После агрегации применить батч-кап (`triplets = triplets[:resolved_max]`) либо явно зафиксировать в spec/ADR, что лимит — на вызов; добавить тест на агрегированный кап.

### [Severity: Low] R1024F1-04 — Счётчик последовательных фейлов глобальный, а не per-chat/per-batch
**File:** `services/summary_memory.py:1188, 3414, 3431, 3435-3439` (`self._graph_batch_failures`); `:468-482` (`_GRAPH_DROPPED_TOTAL`).
**Problem:** Один счётчик на инстанс `MemoryManager` (не на `chat_id`/батч). При нескольких чатах 2 фейла чата A + 1 фейл чата B → батч B отбрасывается с `dropped` уже на первом собственном сбое, вопреки формулировке «после 3 подряд» для батча.
**Why it matters:** Граф чата B теряется раньше политики. Потеря логируется явно, поэтому не Critical, но семантика «3 подряд» не соблюдена.
**Required fix:** Сделать счётчик словарём `dict[int, int]` по `chat_id` (сброс на успехе/чате) или зафиксировать в ADR, что счётчик глобальный и это осознанно (бот — один чат). Добавить тест на изоляцию чатов, если делаем per-chat.

### [Severity: Low] R1024F1-05 — В чанковом канале потеряно различение `empty_list` vs `no_triplets` (F8-регресс наблюдаемости)
**File:** `services/summary_memory.py:3425-3432` vs `:3292-3306` (`_log_graph_no_triplets`).
**Problem:** При `chunks_failed == 0` и пустом результате всегда пишется `reason=empty_list`, даже если ответ был не `[]`, а валидный JSON без валидных триплетов (`parse_triplets` вернул `[]` после `_validate_triplet`). Старый код (и kill-switch-ветка) различают `[]` и «невалидный ответ».
**Why it matters:** Диагностика F8/ADR-1019-7 D5 в новом (штатном) канале деградирует; «пусто по делу» и «модель ответила мусором» сливаются.
**Required fix:** Агрегировать признак: если хотя бы один чанк дал не-`[]` пустой ответ — писать `reason=no_triplets` с `raw_len`; иначе `empty_list`.

### [Severity: Low] R1024F1-06 — Запись графа не транзакционна: остаточное окно инфляции весов
**File:** `services/summary_memory.py:3308-3343` (`_write_graph_triplets`), вызовы `:3379, 3413`.
**Problem:** `_write_graph_triplets` пишет `upsert_node`/`upsert_edge` циклом без транзакции. Ошибка БД в середине (реалистично в раунде «Disaster Recovery» про диск/место) оставит часть рёбер записанными; батч не помечен → повторный крон пере-запишет их, `MIN(weight+inc, cap)` нарастит вес. Заявление «запись ровно один раз на батч» этим не гарантируется.
**Why it matters:** R2/§5.3 — идемпотентность по весам; окно узкое и пре-существующее, но новая формулировка обещает больше, чем обеспечено.
**Required fix:** Обернуть фазу B в одну транзакцию БД (или идемпотентный per-batch ключ). Если это вне объёма — явно записать остаточный риск в ADR §Consequences и не утверждать «ровно один раз» без оговорки.

### [Severity: Low] R1024F1-07 — Пробелы тест-покрытия F1
**File:** `tests/test_graphrag_memory.py:377-529`, `tests/test_llm_client.py:1950-2056`.
**Problem:** Не покрыты: (1) env-override значений `CHUNK_CHARS`/`MAX_CHUNKS`/`TIMEOUT_SECONDS`/`MAX_ATTEMPTS`/`MAX_BATCH_FAILURES` (тест проверяет только дефолты); (2) mark после **partial** в extract-only-ветке; (3) drop-ветка System-2 (`summary_memory.py:3156-3160`, `pass`); (4) сохранение `_GRAPH_EXTRACT_MAX_CHARS` (хвост ≤8000) в чанковом режиме; (5) батч-кап триплетов (R1024F1-03); (6) отсутствие утечки чанк-текста в лог.
**Why it matters:** Контракт F1 шире того, что зафиксировано тестами; часть инвариантов держится «на чтении кода».
**Required fix:** Дополнить тестами (1)-(4); для (1) — monkeypatch `type(settings)` и проверка переданных `deadline`/`max_attempts`/числа чанков.

---

## Контракт: чекбоксы, инварианты, конфликт с F2

### Чекбоксы spec

| Требование | Статус |
|---|---|
| `generate_background(messages, *, purpose, deadline, max_attempts)` (§5.1) + глобальный ключ + `LLMError`-подкласс | ✅ (`llm_client.py:949-983`) |
| `_post(budget=None, max_retries=None)` — `None` = прежнее поведение | ✅ (`llm_client.py:618-769`; embed/worker вызывают без override) |
| Чанкование ≤4000, ≤3, хвост ≤8000 (§3.2) | ✅ (`_graph_split_chunks:506-511`) |
| Запись ровно один раз на батч, без инфляции (§3.3/§5.3) | ✅ для extract-пути (тест (f)); ⚠️ R1024F1-06 (DB-ошибка mid-write) |
| all-ok → запись+mark | ✅ (caller `:3271`) |
| partial → запись успешных + mark + WARNING | ✅ (`:3411-3423`); mark у caller `:3271`; ⚠️ тест не проверяет mark |
| none-ok → без записи/mark + ERROR | ✅ (`:3451-3458`; caller `:3257-3268` `break`, батч сохранён) |
| ≥3 подряд → mark + dropped + счётчик | ✅ (`:3435-3450`; caller mark `:3252`; `graph_extract_dropped_total()`) |
| Kill-switch OFF → прежнее одиночное поведение | ✅ по семантике; ⚠️ R1024F1-02 (не байт-в-байт) |
| Лог: причина, chunks ok/failed, chat_id; без секретов/URL | ✅ (`reason_class`, `chunks_ok/failed`, `chat_id`); ⚠️ R1024F1-01 (ключ события) |
| «Батч не терять»: ни один батч не теряет граф молча | ✅ (запись / явный повтор без mark / явный dropped+счётчик) |

### Инварианты

| Инвариант | Статус |
|---|---|
| `physical-two-call-pipeline` (фоновый extract — вне пользовательского пути) | ✅ `generate_background` не вызывает `_record_analytics`/`_record_global_usage` (код + тест) |
| R16 (аддитивность API) | ✅ |
| R17 (логи без секретов; тела/URL не логируются) | ✅ тип исключения/длины/`chat_id`; секретов в diff нет |
| R18 (секреты не коммитить/не цитировать) | ✅ |
| egress `SEND_POINTS`/`SEND_ALLOWLIST` | ✅ не тронуты |
| `parse_mode=None` plain-каналы | ✅ `handlers/**`,`web/**` не менялись |
| Δ каталога = 0 | ✅ (только env-only `ClassVar`; тесты 457/96/94 зелёные) |
| Δ DDL = 0 | ✅ `services/database.py` вне диффа |
| embeddings не трогаем (UPD3 №7 / п.0b) | ✅ блок `embed` идентичен по хешу; в диффе `llm_client.py` нет ни одной ± строки с `embed`/`EMBEDDING`; `_post` аддитивен |

### Конфликт с F2

- F1 использует F2-хелпер `external_log` (`trace_step` + `log_dropped`, import `summary_memory.py:55`) — конфликта нет; **F1 закрывает R1024F2-04** (первый прод-потребитель `log_dropped`).
- Единственная коллизия — семантика `event=` (R1024F1-01): F2-хелпер жёстко печатает `event=dropped_metric`/`pipeline_step`, а F1-docs обещают `event=graph_extract_*`. Требуется синхронизация либо кода хелпера, либо ADR/spec (см. R1024F1-01).
- F2 review-iter1 (`27296bb`) в рабочем дереве применён; пересечения по файлам с F1 нет.

---

## Тесты

- Целевые: `test_graphrag_memory` + `test_llm_client` + `test_summary_memory` — **355 passed** (6.1 c); F1-классы отдельно: 27 + 9 passed.
- Смежные изменённые: `test_history_retention_toggle` + `test_payload_builder` — **28 passed**.
- Полный pytest на текущем HEAD (`2a5c694`+`27296bb`): **7466 passed, 1 warning** (104.9 c). Первый прогон дал флейк teardown (`test_summary_memory` fixture `d.close()` → pytest-timeout 60 c, Windows IOCP); чистый повтор — зелёный. К F1 не относится.
- Заявка коммита «7459 passed» на момент ревью не воспроизводится в этой цифре (7466 на актуальном HEAD) — цифра устарела/не сверена с чистым коммитом.
- Тесты F1 не тавтологичны: проверяют реальные вызовы `generate_background`, число чанков, отсутствие записи при фейле, рост `weight==1`, `GraphExtractDropped`+счётчик, `bg_calls==0` при kill-switch. Пробелы — см. R1024F1-07.
- Дефект R1024F1-01 тестами **не ловится** (проверяется подстрока, а не ключ события).

---

## Точный список для @Builder

1. **[Medium] R1024F1-01.** Согласовать ключ события с ADR-1024-6 D4/spec §3.4. Рекомендуется: добавить в `services/external_log.py` опциональный `event` в `log_dropped`/`trace_step` (default → текущие `dropped_metric`/`pipeline_step`, F2 байт-в-байт) и вызывать F1 с `event="graph_extract_dropped"|"graph_extract_partial"|"graph_extract_failed"`. Альтернатива — письменно переопределить ключ алерта на `reason=...` в spec/ADR. Обязательный тест: точная проверка согласованного ключа `event=`/`reason=` в сообщении.
2. **[Low] R1024F1-02.** Восстановить прежнюю финальную INFO-строку `graph: triplets=N` в kill-switch-ветке (или ослабить формулировку «байт-в-байт» в ADR) + тест, что `generate()` получает полный `tail`.
3. **[Low] R1024F1-03.** Применить батч-кап триплетов после агрегации чанков (или зафиксировать «лимит на вызов» в spec/ADR) + тест.
4. **[Low] R1024F1-04.** Сделать счётчик фейлов per-`chat_id` (либо явно зафиксировать глобальность в ADR) + тест изоляции чатов.
5. **[Low] R1024F1-05.** Сохранить различение `empty_list` vs `no_triplets` в чанковом канале (агрегировать признак).
6. **[Low] R1024F1-06.** Обернуть `_write_graph_triplets` в транзакцию либо оговорить остаточный риск в ADR §Consequences.
7. **[Low] R1024F1-07.** Закрыть пробелы покрытия (env-override, partial-mark, System-2 drop, tail-cap в чанковом режиме, отсутствие чанк-текста в логе).

Верни исправленную версию. Текущий код отклонён.

---
---

# Итерация 2 — повторный аудит F1

> **Дата:** 19.09.2026. **Шаг:** 5 (повторный аудит). **Коммит:** `391f97d` — `fix(services,tests): раунд 10.24 F1 — событие graph_extract_*, per-chat счётчик, транзакция записи, тесты (review iter1)`.
> **Диапазон:** `git diff 391f97d^ 391f97d` (5 файлов, +354/−72): `services/database.py`, `services/external_log.py`, `services/summary_memory.py`, `tests/test_external_log_round1024.py`, `tests/test_graphrag_memory.py`.
> **Контекст дерева:** поверх F1 уже влит F2 review-iter1 (`27296bb`) — файлы `image_generation.py` и его тесты к F1 **не относятся** и в дифф `391f97d` не входят. `services/llm_client.py` в этом коммите **не менялся** (embeddings не тронуты).

## Status: **Approved**

## Проверка закрытия findings (по существу, а не по заявлению)

| ID | Заявление | Проверка | Итог |
|---|---|---|---|
| **R1024F1-01** (Medium) | опциональный `event` в `trace_step`/`log_dropped`; default не изменён; F1 эмитит `event=graph_extract_*`; тесты ужесточены | `external_log.py:207-221, 236-250`: `event_key = safe_text(event…, limit=64) if event else "pipeline_step"|"dropped_metric"`. Default-путь **байт-в-байт** (отдельный тест `test_default_events_unchanged`). F1: `summary_memory.py:3466-3469` (`event="graph_extract_partial"`), `:3485-3486` (`event="graph_extract_dropped"`), `:3500-3502` (`event="graph_extract_failed"`). Тесты теперь проверяют **точный** ключ: `"event=graph_extract_failed "`, `"event=graph_extract_partial "`, `"event=graph_extract_dropped "` | ✅ **Закрыт** |
| **R1024F1-02** (Low) | OFF-ветка вернула `graph: triplets=N`; тест полного tail | `summary_memory.py:3408-3411`: при пустом результате `_log_graph_no_triplets` + `logger.info("graph: triplets=0 …")`. Новый `test_kill_switch_receives_full_tail_and_final_info`: `captured["user"] == full[-8000:]`, `len==8000`, `graph: triplets=0` в логе | ✅ **Закрыт** |
| **R1024F1-03** (Low) | батч-кап триплетов после агрегации | `_graph_max_triplets()` (`:514-525`) + `triplets = triplets[:max_triplets]` (`:3453-3456`) ПОСЛЕ конкатенации чанков. `test_batch_triplet_cap_after_aggregation` (2 чанка × 1 триплет, кап=1 → 1 ребро) | ✅ **Закрыт** |
| **R1024F1-04** (Low) | per-chat счётчик фейлов | `self._graph_batch_failures: dict[int, int]` (`:1203`); `get/pop(chat_id)` на всех ветках (`:3459, 3479, 3489-3490, 3495`). `test_failure_counter_isolated_per_chat`: A=2, B=1, drop только у A | ✅ **Закрыт** |
| **R1024F1-05** (Low) | агрегирование `empty_list` vs `no_triplets` | `empty_valid` стартует True, сбрасывается в False при `parsed == [] and raw.strip() != "[]"` (`:3438-3444`); `_log_graph_empty_result(empty_valid=…)` (`:3306-3326`). `test_empty_valid_vs_no_triplets_aggregated`: оба `[]` → `empty_list`; мусорный JSON → `no_triplets`, `empty_list` отсутствует | ✅ **Закрыт** |
| **R1024F1-06** (Low) | `_write_graph_triplets` в транзакции; аддитивный `commit` в `upsert_node` | `summary_memory.py:3338-3372`: `BEGIN` → цикл `upsert_node(commit=False)` / `upsert_edge(commit=False)` → `commit()`; `except Exception: rollback(); raise`. `upsert_node(commit=True)` default (`database.py:2474-2494`) — прочие вызовы без изменений. `upsert_edge` уже имел `commit` (B3-5) — не дублируется. `test_write_transaction_rolls_back_midway`: сбой на 2-м ребре → `nodes=0`, `edges=0` (**реальный rollback, без частичной записи**) | ✅ **Закрыт** |
| **R1024F1-07** (Low) | закрыты пробелы покрытия | env-override (`test_env_overrides_chunking_deadline_attempts`), partial-mark в extract-only (`test_partial_marks_batch_in_extract_only`), System-2 drop (`test_dropped_batch_is_marked_by_caller`), tail-cap в чанковом режиме (`test_chunk_mode_tail_capped_to_8000`), чанк-текст не в логе (`test_chunk_text_not_leaked_to_log`), батч-кап (`test_batch_triplet_cap_after_aggregation`) | ✅ **Закрыт** |

## Инварианты и F2 (итерация 2)

| Инвариант / риск | Статус |
|---|---|
| embeddings не тронуты (UPD3 №7) | ✅ `services/llm_client.py` вне диффа `391f97d`; `EMBEDDING_BASE_URL`/каскад не менялись |
| F2 не сломан | ✅ default-события `pipeline_step`/`dropped_metric` сохранены (`test_default_events_unchanged`); `event` — keyword-only в конце сигнатур, все прочие call-site не затронуты |
| `physical-two-call-pipeline` | ✅ изменений в пуле аналитики нет; фон по-прежнему вне System-2 |
| R17 (логи без секретов) | ✅ `event` проходит через `safe_text`; тест `test_chunk_text_not_leaked_to_log` |
| egress / `parse_mode=None` / `bot.py` | ✅ не менялись |
| Δ каталога = 0 | ✅ `param_catalog` вне диффа; ClassVar-флаги + dataclass-поле `GRAPH_EXTRACT_MAX_TRIPLETS` не новое |
| Δ DDL = 0 | ✅ `database.py` — только Python-сигнатура `commit`, схемы/миграций нет |

## Тесты (итерация 2)

- Целевые (`test_graphrag_memory` + `test_llm_client` + `test_summary_memory` + `test_external_log_round1024`) — **394 passed** (6.2 c).
- F1-классы отдельно: 35 (graphrag) + 6 (external_log iter2) — passed.
- **Полный pytest: `7477 passed, 1 warning`** (99.5 c) — совпадает с заявленным числом.
- Транзакционный тест не тавтологичен: проверяет именно отсутствие строк в `nodes`/`edges` после сбоя (иначе вернул бы `>0`).

## Остаточные (неблокирующие) наблюдения — на будущее, не требуют rework

- **Info-1.** Порядок `trace_step(step="write", status="ok")` относительно `logger.info("graph: triplets=N")` в `_write_graph_triplets` (`:3373-3376`) отличается от старого (trace теперь после info). Семантика/вызовы идентичны; «байт-в-байт» по логам — только для OFF-ветки, где финальная INFO восстановлена.
- **Info-2.** Транзакция покрывает только запись триплетов; `mark_smart_messages_processed` (caller) — отдельным стейтментом. При сбое mark батч повторится и пере-запишет граф (инфляция ограничена `MIN(weight+inc, cap)`). Пре-существующее окно, не регресс.
- **Info-3.** `_write_graph_triplets` использует общий aiosqlite-connection с явным `BEGIN` (тот же паттерн, что B3-5). Теоретическая интерливинг-гонка при параллельных писателях — свойство существующей архитектуры, не внесено F1.
- **Info-4.** `_graph_max_triplets()==0` трактуется как «кап выключен», тогда как `parse_triplets` при значении 0 останавливается на 1-м триплете (`>= 0`). Значение `0` нестандартно (default 50); легаси-квирк `parse_triplets`, не влияет на дефолт.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.

