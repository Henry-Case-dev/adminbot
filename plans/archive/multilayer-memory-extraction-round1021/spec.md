# Spec F1 — Многослойная экстракция памяти (Слой А / Слой Б) — раунд 10.21

> **Автор:** @Architect (Step 2), 18.09.2026. **Статус:** 🟢 ACCEPTED (UPD владельца после Human Gate).
> **UPD Human Gate:** фича **включена по умолчанию** (строка 117), раскатки нет, каталожного флага нет (Δ=0);
> аварийный kill-switch — env-only ClassVar, default **ON**. Д3: портрет не перезаписывает ручные overrides.
> **Фича:** `multilayer-memory-extraction-round1021` (T-1943…T-1952), **P0**.
> **ADR:** `ADR-1021-1.md` (двухслойный пайплайн: контракт, стоимость, fallback).
> **Baseline:** HEAD `21cd54c`; pytest **6574/0**; SQLite **v12**; APP_VERSION 2.57.0.
> **R17/R18:** `plans/current_task.md` — untracked, значения SSH-кредов НЕ цитируются и файл НЕ коммитится.

---

## 1. Проблема и цель

**Симптом (ТЗ):** Entity Resolution Failure — в досье попадают копипасты про Тяньаньмэнь и «Кирилла»
у юзера «Никита», шуточные «инструкции по сокрытию трупа» у «Васи». Воркеры не отличают личностные
черты от цитат, мемов и спама.

**Цель:** заменить однопроходную классификацию окна воркера на **двухэтапный пайплайн**:
Слой А (Scratchpad/Мыслитель) явно рассуждает и классифицирует кандидатов, Слой Б (Синтезатор)
получает **только** отфильтрованные `person_fact` и формирует **портрет и паттерны поведения**,
а не вырванные из контекста цитаты.

---

## 2. Аудит кода (факты, а не посылки ТЗ)

### 2.1 Что есть на самом деле
| Утверждение ТЗ | Факт в коде |
|---|---|
| Класс `PersonalityExtractor` | **НЕ существует.** Реальная точка — `LoreWorker` (`services/lore_worker.py:178`), методы `_classify_dossier_safe` (`:483`) и `_classify_dossier` (`:526`). |
| `DreamWorker` «однопроходный воркер» | **Есть** — `services/dream_worker.py:274`; синтез убеждений/парадигм, отдельный контур (F4). |
| Таблица `user_dossier` | **НЕ существует.** Досье = `graph_facts` (`services/database.py:318-341`) + `persona_dossier_overrides` (`:428`). |
| Reasoning-тегов нет | Парсинг `reasoning_content`→`reasoning`→`thinking` уже есть (`services/llm_client.py:1012-1020`); срез тегов `thought/scratchpad/analysis/thinking/reasoning` — `services/reply_postprocess.py:29,39`. |

### 2.2 Как работает текущая классификация (`_classify_dossier`)
1. Собирается окно `lines` (`_format_window`, `:594`) и роster имён `_window_names` (`:511`, канон-алиасы).
2. Один вызов LLM (`_dossier_llm`, `:590`) с `DOSSIER_SYSTEM_PROMPT` (`services/dossier_prompts.py:21`) и
   `build_dossier_user` (`:80`).
3. `parse_dossier_answer` (`:95`) → `{real_facts, chat_memes}`; keyword-фильтр `matches_meme_hint` (`:61`).
4. Пишутся **только** `chat_memes` → `graph_facts.status='chat_meme'`, `kind='fact'`, `weight=0.4`
   (`lore_worker.py:560-567`), идемпотентность `db.meme_exists` (`:558`). `real_facts` воркером НЕ дублируется.
5. Кривой JSON → ровно 1 retry (`:537-550`); ошибка → fail-open (`_classify_dossier_safe`, `:487`).
6. Лор пишется **до** классификации (`:475` vs `:478`) — падение классификации лор не ломает.

**Вывод:** «двухслойность» встраивается внутрь `_classify_dossier`, не меняя точку записи
`chat_memes` и не вводя DDL. Гейт уже существует: `flags.irony_filter_enabled`
(`config/settings.py:1071`, каталог `services/param_catalog.py:860`, группа `flags_relations`).

---

## 3. Целевая архитектура (Слой А → Слой Б)

```
окно (lines, names)
   │
   ▼
[СЛОЙ А — Thinker / Scratchpad]  LLM-вызов #1 (temp 0.2)
   │  назначение: скрининг и Entity Resolution
   │  выход: строгий JSON (intermediate artifact)
   ▼
фильтр kind == "person_fact" + валидатор evidence
   │
   ▼
[СЛОЙ Б — Synthesizer]           LLM-вызов #2 (temp 0.2)
   │  назначение: портрет/паттерны БЕЗ цитат
   │  выход: строгий JSON (portrait/patterns/themes/memes)
   ▼
запись: chat_memes → graph_facts (как в 10.20); профиль → потребляется досье
```

### 3.1 Контракт промежуточного артефакта (Слой А)
```json
{
  "candidates": [
    {"target": "Никита", "kind": "person_fact",
     "text": "живёт в Питере, работает в IT",
     "evidence": [12, 14], "confidence": 0.8,
     "reason": "устойчивый факт о самом участнике, подтверждён двумя репликами"}
  ],
  "discarded": [
    {"text": "площадь Тяньаньмэнь ...", "kind": "copypasta",
     "reason": "энциклопедическая копипаста, к Никите не относится"},
    {"text": "инструкция по сокрытию трупа", "kind": "joke",
     "reason": "шуточная инструкция, не факт биографии"}
  ]
}
```
- `kind` ∈ `{person_fact, meme, quote, copypasta, other_person, noise}`.
- `evidence` — номера строк окна (1..N), обязательны для `person_fact`; иначе кандидат отбрасывается.
- `reason` — обязателен (для логов, R17: без содержимого сообщений).

### 3.2 Контракт Слоя Б (Синтезатор) — **per-target** (UPD раунд 10.21, Issue 1)
```json
{"portraits": [
    {"target": "Имя",
     "portrait": "сухой текст до 600 символов",
     "patterns": ["поведенческий паттерн", "..."],
     "themes": ["тема, к которой человек возвращается"]}],
 "memes": [{"target": "Имя", "text": "локальный мем/ярлык"}]}
```
- На вход Слоя Б идут **только** `kind=person_fact` + `memes`-кандидаты Слоя А.
- **Атрибуция обязательна:** досье — персональное (кейс ТЗ «у Никиты мусор про Кирилла»), поэтому Слой Б
  обязан вернуть портрет/паттерны/темы **отдельно по каждому `target`** из ростера. Прежняя схема
  (один безадресный `portrait` на всё окно) физически не позволяет положить портрет в персональное досье.
  `parse_layer_b` дополнительно принимает legacy-поля `portrait`/`patterns`/`themes` (обратная совместимость
  парсера), но они **не персистятся** — запись идёт только из `portraits`.
- **Запрет цитат:** валидатор Слоя Б отклоняет дословные подстроки исходного окна длиной > 6 слов
  **в каждом** `portrait`/`patterns`/`themes` (анти-«вырванные цитаты»). Причина отклонения — в лог
  (`field`/`reason`, R17: без текстов).
- `real_facts` в `graph_facts` по-прежнему **не дублируем** (обычный GraphRAG); Слой Б повышает качество
  портрета/`chat_memes`, а не создаёт новую таблицу.

### 3.2.1 Контракт персистенции портрета (UPD раунд 10.21, Issue 1 High)
> Закрывает разрыв: `validate_layer_b` вычислял `portrait`/`patterns`/`themes`, но они **нигде не
> сохранялись и никем не читались**; F5 `rebuild_dossier_for_chat` их тоже не персистил. Владелец требует:
> «Досье содержит психологический портрет и паттерны поведения».

**Где пишем.** `services/lore_worker.py::_classify_dossier_multilayer` — после `validate_layer_b`, для каждого
элемента `validated["portraits"]` с `target` из ростера: `db.upsert_generated_dossier(...)`.

**Хранилище (нулевой DDL, `user_version` остаётся 12).** Одна производная строка `graph_facts` на
`(chat_id, target_user)`:

| Поле | Значение | Почему |
|---|---|---|
| `status` | `'dossier_portrait'` | Свободный TEXT без CHECK (прецедент `chat_meme`/`archived_belief`) → **Δ DDL = 0**. Статус `≠ 'confirmed'` автоматически отсекает строку от **всех** читателей: FTS-RAG (`status='confirmed'`), KNN (`_knn_graph_facts` → `confirmed`/`archived_belief`), `get_persona_card`, `get_persona_names`, `get_dream_candidates`, `list_chat_memes`, `_list_orphan_facts`. |
| `kind` | `'fact'` | CHECK колонки допускает только `fact`/`belief`; `insert_graph_fact` нормализует. |
| `origin` | `'chat_history'` | Разрешён CHECK origin; портрет — производная истории чата. |
| `target_user` | канон-имя участника | Ключ «chat+target»; согласуется с `get_persona_card(chat_id, name)`. |
| `fact` | текст портрета (≤ `LAYER_B_PORTRAIT_MAX_CHARS`); если пуст — детерминированный рендер `patterns`/`themes` | NOT NULL; человекочитаемое содержимое для досье. Все поля прошли анти-цитатный валидатор. |
| `weight` | `0.3` | Низкий приоритет производной (мемы — `0.4`). |
| `belief_meta` | JSON `{"generated": true, "generator": "layer_b", "contract_version": 1, "patterns": [...], "themes": [...], "updated_at": ts}` | Пометка «сгенерировано» + структурированные паттерны/темы. `kind='fact'` → парсеры beliefs не задействованы. |

**Кто читает (конкретные потребители).**
1. `services/database.py::get_generated_dossier(chat_id, target_user)` — новый read-хелпер (fail-open → `None`).
2. `web/api/chat_lore.py::_dossier_payload` — модалка «Досье» мини-аппа (`GET/PUT /api/chat_lore/{chat_id}/dossier/{user_id}`):
   в ответ добавляются `portrait`, `patterns`, `themes`, `generated_updated_at`, `portrait_source`.
3. `services/direct_chat_service.py::build_persona_card` (`/persona`, LLM-facing) — аддитивные блоки
   `[Психологический портрет]` / `[Паттерны]` / `[Темы]`.
4. `web/index.html` — отдельный блок «(сгенерировано автоматически · Слой Б)» в модалке досье.

**Merge с ручными `persona_dossier_overrides` (инвариант `manual-overrides-immutable`).**
- Writer пишет **только** в `graph_facts` и НИКОГДА не вызывает `set_dossier_override`/`delete_dossier_override`.
- Ручные правки — отдельная таблица, ключ `user_id`; сгенерированный портрет — `graph_facts`, ключ `target_user`.
  Конфликта записи нет по построению.
- При чтении (`_dossier_payload`) приоритет отдаётся ручной правке: `portrait_source = "manual"`, если
  `manual_traits` непуст (тогда `effective_portrait = manual_traits`); иначе `"generated"`
  (`effective_portrait = generated.portrait`); иначе `"none"`. Сгенерированный портрет всё равно отдаётся
  отдельным полем с пометкой «авто (Слой Б)» — прозрачность, но не перекрытие. `patterns`/`themes` ручной
  правкой не перекрываются (их в override нет) и отдаются всегда.

**Обновление / идемпотентность.** `upsert_generated_dossier`:
1. `SELECT id FROM graph_facts WHERE chat_id=? AND target_user=? AND status='dossier_portrait' LIMIT 1`.
2. Есть → **FTS-safe UPDATE**: `DELETE FROM graph_facts_fts WHERE rowid=?` → `UPDATE graph_facts SET
   fact=?, belief_meta=?, weight=?, created_at=? WHERE id=?` → `INSERT INTO graph_facts_fts(rowid, fact)
   VALUES(?,?)` (внешний контент FTS5, паттерн `delete_generated_facts`/`insert_graph_fact`).
   Нет → `insert_graph_fact(..., status='dossier_portrait', kind='fact', origin='chat_history',
   target_user=..., weight=0.3, belief_meta=json)`.
3. Ровно одна строка на `(chat, target)`; повторный прогон → UPDATE, дублей нет. Vec-строку не создаём
   (backfill может эмбеддить — безвредно: статусный фильтр KNN исключает `dossier_portrait`).

**Удаление при rebuild (F5).** `memory_rebuild.rebuild_dossiers` расширяется: в шаге сброса, помимо
`status='chat_meme'`, архивирует и удаляет `status='dossier_portrait'` того же чата (тот же авто-бэкап,
JSONL-архив, guard allowlist `graph_facts`, сверка `candidates == archived`) — иначе после пересборки
останутся устаревшие персональные портреты. `--dry-run` учитывает их в счётчике. `sanitize_beliefs`
портреты **не трогает** (не мемы, не убеждения).

**R17:** логи — только `chat_id`, counts, число портретов, `field`/`reason` отклонений; без текста портрета
и без текстов сообщений.

**Откат:** `DELETE FROM graph_facts WHERE status='dossier_portrait'` (+ FTS/vec) — производная, схема не
меняется; ручные overrides не затрагиваются.

### 3.3 Entity Resolution (ядро анти-мусора)
- Ростер имён окна — существующий `_window_names` (канон-алиасы). Слой А ОБЯЗАН привязывать `person_fact`
  только к имени из ростера.
- Различение «упоминание имени» vs «факт о человеке»: если субъект действия — не участник
  (например, «Кирилл» упомянут, но говорит Никита) → `kind=other_person`.
- Коллизии имён (Никита/Кирилл): привязка по автору строки-источника (`evidence`), а не по упоминанию;
  при конфликте — отбрасывать кандидат с reason `ambiguous_entity`.

---

## 4. Точки интеграции (что именно меняется)

| Файл | Изменение |
|---|---|
| `services/dossier_prompts.py` | Новые канон-константы Слоя А/Б + парсеры `parse_layer_a`/`parse_layer_b` рядом с `parse_dossier_answer`. `DOSSIER_SYSTEM_PROMPT` сохраняется как ветка OFF (байт-совместимость). **UPD Issue 1:** `LAYER_B_SYSTEM_PROMPT`/`parse_layer_b`/`validate_layer_b` — per-target `portraits[]` (§3.2). |
| `services/lore_worker.py` | `_classify_dossier` по умолчанию выполняет A→фильтр→B (безусловно, UPD). Только аварийный env-kill-switch OFF возвращает ровно путь 10.20. Бюджет: единый прогноз токенов A+B через `_budget_ok`/`worker_budget` (`:461-467`). **UPD Issue 1:** после `validate_layer_b` — запись портретов per-target через `db.upsert_generated_dossier` (§3.2.1). |
| `services/database.py` | **UPD Issue 1:** аддитивные read/write-хелперы `get_generated_dossier` / `upsert_generated_dossier` над `graph_facts.status='dossier_portrait'`. **Схема/DDL НЕ меняется (v12).** |
| `services/direct_chat_service.py` | **UPD Issue 1:** `build_persona_card` — аддитивные блоки `[Психологический портрет]`/`[Паттерны]`/`[Темы]` (fail-open; нет портрета → байт-в-байт прежний вывод). |
| `web/api/chat_lore.py`, `web/index.html` | **UPD Issue 1:** `_dossier_payload` отдаёт `portrait/patterns/themes/portrait_source`; модалка «Досье» рендерит портрет и паттерны, ручная правка — с приоритетом. |
| `services/memory_rebuild.py` | **UPD Issue 1 (F5):** в `rebuild_dossiers` сброс `status='dossier_portrait'` вместе с `chat_meme` (архив+guard, отчёт `reset_portraits`). |
| `config/settings.py` | **Каталожный флаг НЕ вводится.** Только env-only ClassVar kill-switch `MULTILAYER_EXTRACTION_ENABLED = _env_bool("MULTILAYER_EXTRACTION_ENABLED", True)` — default **ON**, вне каталога (прецедент retention-гейтов, `settings.py:483-497`). |
| `services/param_catalog.py` | **Без изменений:** новых REGISTRY-записей нет, Δ каталога = 0 (см. §7). |
| `plans/docs/canon/**` | Если Слой А/Б выносится в PG-сид-канон — синхронно; при модульных константах (прецедент `dossier_prompts.py:1-15`) канон-миграция НЕ требуется. **Решение: модульные константы, `prompt_migrations.py` не трогаем** (как `DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT`). |

**Не трогаем:** `reply_postprocess.strip_reasoning_tags` (не дублировать), `parse_dossier_answer` (переиспользовать),
`db.meme_exists`, `graph_facts`-схему (v12), `persona_dossier_overrides`.

### 4.1 Границы F1 (descope DreamWorker — решение по Issue 7 @Reviewer, Low)
T-1949 упоминал «интеграцию в `LoreWorker`/`DreamWorker`», фактически тронут только `LoreWorker`.
**Решение: двухслойность в `DreamWorker` — ВНЕ периметра F1 (descope в F4).** Обоснование:
- `DreamWorker` (`services/dream_worker.py:274`) — отдельный контур **синтеза убеждений/парадигм** («сон»),
  его вход/выход — `kind='belief'`/`belief_meta`, а не персональное досье. Наложение Слоя А/Б на убеждения
  меняет семантику и пороги F4 (консолидация порогов/санитария убеждений) и пересекается с санитайзом F5.
- ТЗ и цель F1 (spec §1) — устранение мусора в **персональном досье**; точка `LoreWorker._classify_dossier`
  закрывает кейсы «Никита/Кирилл», «Вася/инструкция».
- Формулировка T-1949 в tasks.md исправлена на «Интеграция в `LoreWorker` (DreamWorker — вне периметра F1,
  относится к F4)». Отдельная задача в F4, если владелец решит распространить фильтр на убеждения.

---

## 5. Активация и аварийный kill-switch (UPD Human Gate)

- **ВКЛЮЧЕНО по умолчанию (строка 117 UPD):** двухслойный пайплайн работает безусловно, без флага
  и без процентов. Поэтапной раскатки 10/50/100% **нет** (прецедент прошлого раунда — отказ от поэтапности).
- **Каталожного флага нет.** Для F1 допускается аварийный **env-only ClassVar kill-switch**
  `MULTILAYER_EXTRACTION_ENABLED` (default **ON**) — на время дорогой операции; при значении `false`
  воркер откатывается на путь 10.20. Поле — ClassVar, в `param_catalog.py` не регистрируется → Δ каталога = 0.
- **Развязка от irony-флага (UPD fix-round 2).** Запуск двухслойного пайплайна и персистенция
  портретов/мемов **не зависят** от исторического `flags.irony_filter_enabled` (каталожный флаг
  `IRONY_FILTER_ENABLED`, default `False`). Irony-фильтр остаётся отдельной функцией и гейтит только
  legacy-путь 10.20 при `MULTILAYER_EXTRACTION_ENABLED=False`; его историческое поведение не меняется.
  Без этой развязки при дефолтном `IRONY_FILTER_ENABLED=False` портреты/мемы в рантайме не писались бы,
  что противоречит указанию владельца «включено по умолчанию». Тесты: `IRONY_FILTER_ENABLED=False` +
  `MULTILAYER_EXTRACTION_ENABLED=True` → портрет/мемы пишутся; kill-switch OFF + irony OFF → не пишутся.
- **Д3 (решение владельца):** портрет F1 **не перезаписывает** ручные `persona_dossier_overrides` —
  обновляются только генерируемые производные; ручные правки главнее.
- Kill-switch OFF-путь обязан быть **байт-совместим** с 10.20: те же вызовы, тот же промпт, те же записи.

## 6. Fallback / отказоустойчивость

1. Слой А упал/невалидный JSON после 1 retry → **fail-open**: логируем WARNING и идём по пути 10.20 (single-pass).
2. Слой Б упал → сохраняем `chat_memes` Слоя А; портрет не пишем (без потери мусора-фильтрации).
   Запись портрета — fail-open: ошибка `upsert_generated_dossier` логируется (WARNING, R17) и не роняет прогон.
   Портрет с отклонённым анти-цитатным валидатором полем не пишется по этому полю (пустой `portrait` →
   рендер из `patterns`/`themes`; всё пусто → строку не создаём).
3. `asyncio.CancelledError` пробрасывается (как сейчас).
4. R17: логи — только `chat_id`, counts, `kind`, длины; **без текстов сообщений**.

## 7. Δ каталога (флаги)

**Целевое состояние (UPD владельца): Δ каталога = 0 по всем фичам F1–F6.**

| Ось | Было | Δ | Стало |
|---|---|---|---|
| REGISTRY | 439 | **0** | **439** |
| Settings полей | 409 | **0** | **409** |
| categorized | 414 | **0** | **414** |
| GROUPS | 92 | **0** | **92** |
| mapped | 90 | **0** | **90** |
| TAB_RULES | 20 | **0** | **20** |

> Никаких новых REGISTRY-записей: F1 kill-switch — env-only ClassVar; F2 CoVe — безусловный блок канона;
> F3 — правка канона; F4 — значение существующего лимита; F5 — env-only гейты (вне каталога); F6 — frontend.
> Точные счётчики подтверждаются тестом-интроспекцией (`tests/test_param_catalog.py`) при реализации;
> расхождение с таблицей — стоп и эскалация @Architect.

## 8. План тестов

1. **Парсеры:** `parse_layer_a`/`parse_layer_b` — валидный JSON, code-fence, битый JSON → `ValueError`,
   отброс кандидатов без `evidence`/с `kind=noise`.
2. **Двухслойность:** mock LLM возвращает A-JSON, затем B-JSON → ровно 2 вызова, в `graph_facts` только
   прошедшие мемы, портрет без цитат.
3. **Кейсы ТЗ:** Тяньаньмэнь/копипаста → `discarded`; «Кирилл» у Никиты → `other_person`;
   «инструкция по сокрытию трупа» → `joke`; шутливый титул → `chat_memes`.
4. **Fallback:** A бросает/отдаёт мусор → путь 10.20, запись лора цела.
5. **Флаг OFF:** байт-в-байт поведение 10.20 (снапшот вызовов/промпта).
6. **Стоимость/бюджет:** прогноз считается по A+B; при превышении — skip с reason.
7. **Детерминизм:** одинаковый вход + mock → одинаковый промежуточный артефакт.
8. **Персистенция портрета (UPD Issue 1):** per-target `portraits` → ровно одна строка
   `graph_facts.status='dossier_portrait'` на (chat, target), `belief_meta.generated=true`, `patterns`/`themes`
   читаются `get_generated_dossier`; повторный прогон → UPDATE (idempotent, дублей нет); отклонённый
   verbatim-портрет не пишется; `user_version` = 12 и `sqlite_master` не меняются (тест-интроспекция).
9. **Изоляция портрета:** строка `dossier_portrait` не видна в `get_persona_card`/`get_persona_names`/FTS-RAG/
   KNN/`get_dream_candidates`/`list_chat_memes`/`_list_orphan_facts`.
10. **Приоритет ручных overrides:** при непустом `manual_traits` API-ответ отдаёт `portrait_source='manual'`;
    генератор никогда не вызывает `set_dossier_override`/`delete_dossier_override`.
11. **Потребители:** `_dossier_payload` и `build_persona_card` возвращают портрет/паттерны/темы; при отсутствии
    строки — байт-в-байт прежний вывод (регресс-инвариант).

## 9. Риски и откат

- **R1 × 2 стоимость LLM** — бюджет воркера, кап окна; аварийный env-kill-switch (default ON) на время операции.
- **R2 потеря полезных фактов** — `discarded` логируется, метрика доли отсева, откат kill-switch/`git revert`.
- **R3 пересечение файлов с F2/F3** — `services/**` + `*_prompts.py`; вливать ступенями (F1 → F2+F3).
- **R4 дублирование стриппера** — запрещено, переиспользуем существующие.
- **R5 невалидный intermediate** — 1 retry + fail-open на путь 10.20 (аварийно — kill-switch OFF).
- **Откат:** аварийно — env-kill-switch (default ON); штатно — `git revert` (раскатки нет; схема БД не меняется, v12).

## 10. Research references

- **Mem0 + LangGraph (production agent):** https://mem0.ai/blog/how-to-build-a-production-ai-agent-with-langgraph-and-mem0 —
  память как отдельные узлы `memory_retrieval` / `memory_update`; для прода рекомендуется отдельный
  классификатор «что вообще достойно памяти», а не сохранение каждого хода.
- **Mem0 paper:** https://arxiv.org/pdf/2504.19413.pdf — пайплайн из двух фаз (extraction → update),
  реконсиляция кандидатов через ADD/UPDATE/DELETE/NOOP; графовая память с entity extraction.
- **Mem0 docs (memory-evaluation):** https://docs.mem0.ai/core-concepts/memory-evaluation — этапы
  контекст-лукап, дистилляция, дедуп, entity linking, temporal reasoning; hash-дедуп.
- **LangMem:** https://github.com/langchain-ai/langmem — background memory manager: extract, consolidate, update.
- **MemR3 (reflective retrieval, LangGraph):** https://arxiv.org/pdf/2512.20237 — router/retrieve/reflect/answer
  + evidence-gap tracker; рефлексия итеративна и завершается по достаточности улик.
- **Talker-Reasoner (System 1/System 2):** https://arxiv.org/pdf/2410.08328v1 — Reasoner (медленный)
  формирует beliefs/паттерны, Talker лишь вербализует; асинхронность и «деградация к старому состоянию»
  как осознанный трейд-офф.
- **PLaT (decouple reasoning from verbalization):** https://www.alphaxiv.org/overview/2601.21358 —
  Planner (лаконично рассуждает) отдельно от Decoder (вербализует) — прямой аналог Слоя А/Б.
