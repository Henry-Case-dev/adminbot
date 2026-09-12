# Spec F8 — `cognition-irony-dossier-round1013` («Ирония и Досье Персонажей»)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; спека Step 2 @Architect, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §2. Tasks: T-1468…T-1476. Backend (промпт-канон + досье). P1.
> Зависимости: F1 (инфраструктура PREV/байт-тестов, метки). ADR: `../cognition-4d-memory-round1013/adr-1013-3-prompt-canon-policy.md`.

## 0. Цель

LLM перестаёт принимать локальные мемы/постиронию за реальную биографию.
Воркер досье получает «Иронический фильтр» и раскладывает титулы по корзинам
`real_facts` / `chat_memes`; в контекст досье подаётся блоками `[Факты]` и
`[Локальные мемы/Ярлыки]`.

## 1. Объём

### In scope
- «Иронический фильтр» в канон воркера досье + дословная инструкция ТЗ.
- Классификация (LLM + keyword fail-safe) → запись `chat_memes`.
- Два блока в контексте досье; обратная совместимость.
- Флаг `flags.irony_filter_enabled` (OFF); телеметрия/API (опц.).

### Out of scope
- Ручное редактирование мемов в TMA (F8-Q5: только авто).
- Новый воркер/таблица/DDL; UI.

## 2. Что такое «Досье» и кто его собирает (F8-Q1 — РЕШЕНО)

В коде нет отдельного dossier-воркера (greenfield, подтверждено grep).
**Досье персонажа = агрегация карточки человека** (`direct_chat_service.build_persona_card`
→ `database.get_persona_card`), а **«воркер, собирающий досье» = существующий
`LoreWorker`** (архивариус): он дистиллирует окно в факты/лор и теперь дополняется
шагом классификации `_classify_dossier`. Новый воркер НЕ вводим.

## 3. Схема данных (F8-Q2/Q3 — РЕШЕНО, без DDL)

**`real_facts`** = существующие строки `graph_facts`:
`status='confirmed' AND kind='fact' AND target_user=<canon-имя>`.

**`chat_memes`** = строки той же таблицы с **`status='chat_meme'`** (`status`
не имеет CHECK — сверено `database.py:863`), `kind='fact'`, `origin='chat_history'`,
`target_user=<canon-имя>`, `weight=0.4`, `belief_meta` JSON:
```json
{"meme":true,"source":"dossier","classified_by":"llm|keyword","confidence":0.8,
 "created_at":...}
```

Почему так (не JSONB `chat_profiles.relations`, не `kind`):
- `kind` имеет `CHECK(kind IN ('fact','belief'))` → новый kind = DDL (запрещено).
- Новый `status`-value не требует DDL и **автоматически** исключает мемы из всех
  читающих путей с `status='confirmed'` (FTS RAG, KNN, `get_persona_card`,
  `get_dream_candidates`, `/persona list`) — «real vs meme» разделение бесплатно.
- JSONB `relations` — ручные админ-данные с optimistic-lock; писать туда из
  LLM-воркера = конфликт жизненных циклов. **Отклонено** (см. §12).

## 4. Канон «Иронического фильтра»

### 4.1. Новый `services/dossier_prompts.py`
- `DOSSIER_SYSTEM_PROMPT` — канон-константа с **дословной** инструкцией ТЗ:
  «Пользователи часто шутят и используют сарказм. Оскорбительные или абсурдные
  титулы (например, 'мегачмо', 'повелитель грибов') записывать в отдельный
  массив `chat_memes`, а не в `real_facts`.» + строгий JSON-контракт:
  ```json
  {"real_facts":[{"target":"Имя","text":"..."}],
   "chat_memes":[{"target":"Имя","text":"..."}]}
  ```
- `PREV_DOSSIER_SYSTEM_PROMPT` — слепок (для greenfield — пустая строка/прежний
  отсутствующий канон; тест фиксирует отсутствие исторического значения).
- `parse_dossier_answer(raw)` — чистый парсер (по образцу `parse_distill_answer`):
  UNCHANGED/пусто → пустые массивы; кривой JSON → `ValueError` (1 retry у воркера);
  элементы не-dict/без `text` — отброшены; `target` — через `aliases.canon_name`.
- `KEYWORD_MEME_HINTS` — fail-safe список (`мегачмо`, `повелитель грибов`, `лорд`,
  `король`, `бог`, `повелитель`, ...). Если фраза матчит — гарантированно в memes
  даже при сбое LLM-классификации.

### 4.2. Правка `services/lore_prompts.py`
Аддитивная заметка про иронию в `LORE_MERGE_SYSTEM_PROMPT` и
`LORE_INIT_SYSTEM_PROMPT` (мемы/саркастичные титулы — не биография). PREV-слепки
`PREV_LORE_MERGE_SYSTEM_PROMPT`/`PREV_LORE_INIT_SYSTEM_PROMPT` + байт-тесты.
`PROMPT_MIGRATIONS` — **без изменений** (каноны не PG-сид; ADR-1013-3).

## 5. Алгоритм классификации и записи

```
# в LoreWorker после _run_generation (best-effort, под флагом)
if not hot.get("flags.irony_filter_enabled", False): return
window = последние N сообщений (тот же window воркера)
names  = roster участников (aliases.canon)
raw    = await llm.generate_worker(
           "background",                       # фоновые проверки (см. ADR-1013-1)
           [{"role":"system","content": DOSSIER_SYSTEM_PROMPT},
            {"role":"user","content": build_dossier_user(window, names)}],
           temperature=0.2)
items = parse_dossier_answer(raw)              # ValueError → 1 retry → skip
for m in items.chat_memes:
    if not m.text or not m.target: continue
    if meme_exists(chat_id, m.target, m.text): continue    # анти-дубль/уникальность
    fact_id = await db.insert_graph_fact(
        chat_id, m.text, "chat_history", None, target_user=m.target,
        weight=0.4, status="chat_meme", kind="fact",
        belief_meta=json.dumps({"meme":True,"source":"dossier",...}))
# real_facts НЕ дублируем: они уже факты/создаются обычным GraphRAG-путём
```
`KEYWORD_MEME_HINTS` — pre-filter: совпавшие фразы принудительно в memes.
Идемпотентность: `meme_exists` по `(chat_id, target_user, fact, status='chat_meme')`.
Инвалидация кэша: если затрагивается PG-лор (`lore_cache`), `lore_cache.invalidate()`.

## 6. Чтение/рендер (F8-Q4 — РЕШЕНО)

- `database.get_persona_card` (`:3118`) — без изменений (status='confirmed'
  исключает memes).
- Новый `database.list_chat_memes(chat_id, target_user=None, limit=50)`
  (`status='chat_meme'`, ORDER BY created_at DESC).
- Новый чистый хелпер `format_dossier_block(facts, memes, cap_chars)`:
  ```
  [Факты]
  <строки>
  [Локальные мемы/Ярлыки]
  <строки>
  ```
  Пустой блок **не рендерится**; бюджет — общий
  (`_PERSONA_MAX_ITEMS`/кап символов), **мемы урезаются первыми**. Старое досье
  без memes → только `[Факты]` (обратная совместимость).
- `direct_chat_service.build_persona_card` (`:1443`): собрать `facts`/`memes`,
  отрендерить через `format_dossier_block` (вместо плоского списка) при
  `flags.irony_filter_enabled`; при OFF — байт-в-байт прежний вывод.
- Сборка прочих досье-блоков (`summary_memory` person-aggregation) — memes
  не подмешиваются в RAG (status-фильтр), отдельного блока не требует.

## 7. Файлы и точки изменения

| Файл | Что |
|---|---|
| `services/dossier_prompts.py` | **новый**: канон+парсер+keyword-hints |
| `services/lore_prompts.py` | ироническая заметка + PREV-слепки |
| `services/lore_worker.py` | `_run_generation` :408 → hook `_classify_dossier` (flag-gated) |
| `services/database.py` | `list_chat_memes`, `meme_exists`; SELECT без изменений |
| `services/direct_chat_service.py` | `build_persona_card` :1443 → два блока |
| `services/summary_memory.py` | (если есть досье-блок) memes через хелпер; RAG не трогаем |
| `services/param_catalog.py` | `_FLAGS` += `flags.irony_filter_enabled` (группа `flags_relations`) |
| `config/settings.py` | `IRONY_FILTER_ENABLED = False` |
| `services/prompt_migrations.py` | **не трогаем** (ADR-1013-3) |
| `tests/test_chat_lore*`, `test_direct_chat*`, `test_database.py`, `test_param_catalog*` | тесты |

## 8. Каталог-Δ

| Ключ | Кат. | Группа | Тип/дефолт | Settings-поле | per_chat |
|---|---|---|---|---|---|
| `flags.irony_filter_enabled` | flags | `flags_relations` | bool / **False** | `IRONY_FILTER_ENABLED` | true |

Итог F8: **REGISTRY +1**, Settings +1, GROUPS 90, mapped 88, TAB_RULES 19.

## 9. Feature flag / progressive delivery

- `flags.irony_filter_enabled` (default **OFF**); при OFF — поведение 10.12 без изменений.
- Rollout: internal (тест-чат) → 10% (`--chat-id`) → 50% → 100%.
- Критерии отката: мемы просачиваются в `real_facts`/RAG, жалобы на «биографию по шуткам».
- Rollback: флаг OFF (мгновенно) + `git revert`; memes остаются в существующей структуре.

## 10. Тест-план

1. Классификация: `мегачмо`/`повелитель грибов` → `chat_memes` (LLM-mock и keyword-hint);
   реальный факт («Толян живёт в Москве») → остаётся `real_facts`.
2. `parse_dossier_answer`: UNCHANGED/пусто → пусто; кривой JSON → ValueError;
   не-dict/без text — отброшены; `target` канон-алиас.
3. Изоляция: memes (`status='chat_meme'`) не видны в RAG (FTS/KNN), `get_persona_card`,
   `get_dream_candidates`, `/persona list`.
4. Рендер: два блока `[Факты]`/`[Локальные мемы/Ярлыки]`; пустой блок не рендерится;
   мемы урезаются первыми; старое досье → только `[Факты]`.
5. Идемпотентность: повторная классификация не плодит memes.
6. Байт-канон: `DOSSIER_SYSTEM_PROMPT` reference == код; `PREV_LORE_*` == прежний текст.
7. Флаг OFF → байт-в-байт прежний вывод досье.
8. Регресс `test_chat_lore*`/`test_direct_chat*`/`test_database`; каталог Settings/REGISTRY.

## 11. Риски

| Риск | Митигация |
|---|---|
| LLM кладёт мемы в real_facts | keyword fail-safe + строгий JSON + тест-кейсы |
| Мемы просачиваются в RAG | `status='chat_meme'` вне всех `status='confirmed'`-путей |
| Дубли memes при повторных прогонах | `meme_exists` (идемпотентность) |
| Досье раздувается | общий кап; memes урезаются первыми |
| Ломаем канон лора | PREV-слепки + байт-тесты; флаг OFF по умолчанию |

## 12. Разрешение open questions (F8)

- **F8-Q1** — отдельного dossier-воркера нет; досье агрегирует `build_persona_card`, собирает `LoreWorker` + шаг `_classify_dossier`. Новый воркер не вводим.
- **F8-Q2** — `chat_memes` хранится в `graph_facts` со `status='chat_meme'` (нулевой DDL). JSONB `relations` отклонён (ручной optimistic-lock lifecycle).
- **F8-Q3** — `real_facts` = `graph_facts` `status='confirmed' AND kind='fact' AND target_user`.
- **F8-Q4** — блоки `[Факты]`/`[Локальные мемы/Ярлыки]` в `build_persona_card`; пустой не рендерится; общий кап; memes режутся первыми; совместимость со `<Protected_Facts>`/`<user_relations>` не нарушается (отдельные блоки).
- **F8-Q5** — v1 только авто-сбор; ручное редактирование memes в TMA — вне скоупа; memes видны в карточке `/persona`.
- **F8-Q6** — LLM-классификация (канон досье) + keyword fail-safe (оба).
