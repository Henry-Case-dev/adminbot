# spec.md — F1 `urgent-rebuild-dossiers-target-chat-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: data-migration / CLI + ops
> **ADR:** `ADR-1022-1.md` (**Accepted — решение владельца UPD3, 18.09.2026**). **Задачи:** `tasks.md` (T-2019…T-2027 + T-2090/T-2091).
> **ТЗ:** `plans/current_task.md`, UPD3 §1 «По Досье и фактам (В1)» (строки **247–249**); ранее «Проблема 1» (175–178).
> **R17/R18:** `plans/current_task.md` untracked; SSH-креды не цитировать и не коммитить.
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION 2.57.0; прод `a923310`.
> **Карта решений гейта:** `plans/features/round1022-human-gate-map.md` (Д-1/Д-2/Д-3 закрыты).

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде | Комментарий |
|---|---|---|
| CLI `memory` и подкоманда `rebuild-dossiers` | `manage.py:635-719`, парсер `:944-1020` | Дефолт — боевой прогон; `--dry-run` опционален |
| Guard целевого чата | `manage.py:848-869` | **Не жёсткий блокер**: `--chat <target> --allow-target-chat` разрешён (`:858-863`); `--all` целевой исключает (`:864-865`) |
| Инвариант сырой истории | `services/memory_rebuild.py:55-62` (`RAW_HISTORY_TABLES`), `:72-82` (`assert_derived_table`), `:85-92` (`_guarded_delete`) | **Не снимается.** Единственный путь DELETE |
| Allowlist сгенерированных | `services/memory_rebuild.py:46-53` (`DERIVED_TABLES_ALLOWLIST`) | `graph_facts`(+FTS/vec), `edges`, `nodes`, `graph_fact_compressions` |
| Оркестрация rebuild | `services/memory_rebuild.py:400-484` | **СНАЧАЛА** archive+DELETE, **ПОТОМ** pipeline (`:445-483`) |
| Выборки мемов/портретов | `services/memory_rebuild.py:234-250` | Только `status IN ('chat_meme','dossier_portrait')` |
| JSONL-архив + fail-closed | `services/memory_rebuild.py:175-229` | `candidates == archived` иначе delete отменён |
| Авто-бэкап БД | `services/memory_rebuild.py:130-172` (`create_safety_backup`) | Backup API + fsync; fail-closed без `db_path` |
| Pipeline | `manage.py:872-890` → `services/lore_worker.py:691-717` (`rebuild_dossier_for_chat`) | Читает окно `now − window_hours` (дефолт 168ч) и `max_msgs` (дефолт 300); **только чтение** `smart_messages` |
| Слои A/B (двухслойная экстракция) | `services/lore_worker.py:562-689` | Уже bounded-retry (1 повтор на невалидном JSON) |
| **Что показывает «Досье»** | `services/database.py:4410-4437` (`get_persona_card`) + `web/api/chat_lore.py:838-902` (`_dossier_payload`) | Факты карточки = `graph_facts WHERE target_user = name AND status = 'confirmed'`; плюс `links` (edges) и `dossier_portrait` |
| `graph_facts` схема/колонки | `services/database.py:318-335` + миграции (`kind`, `status`, `target_user`, `source_ids`) | `kind ∈ {fact, belief}`; beliefs хранят `source_ids` (JSON) |
| `busy_timeout` | `services/database.py:48` (`_BUSY_TIMEOUT_MS = 5000`) | 5 с |
| Диагностика прода | `dossier_portrait=0`, `chat_meme=0` для `-1002661910336` | Прогон не запускался |

### 0.1. Критический риск over-delete (R1b) — сохраняется

`rebuild_dossiers` удаляет `chat_meme`/`dossier_portrait` целевого чата (`:445-462`), затем
пере-собирает их **только из окна** `now − window_hours`. Если мусорные досье старше окна
(кейс Никиты/Тяньаньмэнь — исторические), их **удалят, но не пере-соберут**. В UPD3 окно
расширено до **180 дней**, но инвариант полностью не снимается: `effective_window ≥ возраста
удаляемых строк` + `rebuild_empty` (ненулевой exit) остаются обязательными.

### 0.2. Расширение скоупа по решению UPD3 (новое)

До этой итерации rebuild чистил **только** `status IN ('chat_meme','dossier_portrait')`.
UPD3 §1 требует дополнительно **жёстко вычистить подтверждённый (`status='confirmed'`)
сгенерированный мусор, привязанный к участникам**, — именно он питает «Досье»
(`get_persona_card` фильтрует `target_user = name AND status = 'confirmed'`). См. точный
скоуп и границы — §2.5.

---

## 1. Цель

Получить **реальный результат в БД** для целевого чата `-1002661910336`: (1) вычистить
подтверждённый мусор `graph_facts` с **предварительным JSONL-архивом**; (2) пере-собрать
досье двухслойным пайплайном по **180-дневному окну**; **без** удаления сырой истории,
**без** over-delete валидных производных и **без** потери ручных `persona_dossier_overrides`;
с отчётом counts «до/после» и документированным откатом.

## 2. Архитектура

### 2.1. Снятие операционного трения (не инвариантов)

1. `_memory_scope` (`manage.py:848-869`) **сохраняет** запрет на неявный целевой чат.
2. Добавляется явный операторский shortcut `--target-chat` (равнозначен `--chat <LEGACY_TARGET_CHAT_ID> --allow-target-chat`). Он **не** делает целевой чат доступным через `--all` и **не** трогает `RAW_HISTORY_TABLES`.
3. `help`/комментарий CLI прямо сообщает: «сырая история (`smart_messages`) не мутируется ни при каких флагах».

### 2.2. Окно прогона = 180 дней (решение Д-3)

1. Боевой дефолт `--window-hours` для целевого прогона — **4320** (180 дней); прежний дефолт 168 ч отвергнут владельцем.
2. `effective_window = max(args.window_hours, ceil((now − oldest_created_at)/3600) + 24)` (R1b-защита сохраняется); `--window-hours 0` = «всё в пределах `max_msgs`».
3. В отчёте — `window_hours_used`, `source_age_days` (возраст самого старого удаляемого ряда), `max_msgs`.

### 2.3. Устойчивость к `database is locked` и таймаутам

1. **Чтение через снапшот** SQLite (Backup API, прецедент `manage.py:730-752`); запись — в живую БД (WAL/`busy_timeout`).
2. **Bounded-ретраи записи** на `locked` (≤3 попытки, экспоненциальный бэкофф); при исчерпании — reason `db_locked`, частичная деградация.
3. **LLM-таймауты**: `rebuild_dossier_for_chat` → 1 повтор (уже есть), затем `rebuild_error` для чата; цикл продолжает остальные чаты.
4. **Fail-closed**: без успешного `create_safety_backup` и `candidates == archived` DELETE не выполняется.

### 2.4. Порядок и безопасность

```
[dry-run?] → snapshot-read → counts до (scanned/reset/portraits/confirmed)
           → safety backup (БД) + JSONL archive мемов/портретов (до DELETE)
           → guarded DELETE (chat_meme, dossier_portrait)
           → confirmed-cleanup (§2.5): JSONL archive → сверка → guarded DELETE confirmed-фактов
           → pipeline(chat) [окно = 180 дней / effective_window]
           → counts после (rebuilt) + window_used + source_age_days
           → post-check: smart_messages/FTS/vec НЕ изменены
```

### 2.5. Точный скоуп confirmed-cleanup (критично; UPD3 §1)

**Что удаляется (ровно это):**

```sql
-- chat-wide (F1 CLI):
SELECT id, fact, target_user, weight, created_at, status, kind
FROM graph_facts
WHERE chat_id = :chat
  AND kind = 'fact'                 -- убеждения/парадигмы (kind='belief') НЕ трогаются
  AND status = 'confirmed'          -- «сгенерированный мусор со статусом confirmed» (UPD3)
  AND target_user IS NOT NULL
  AND target_user != '';            -- только привязанные к участнику (питает get_persona_card)
```

- **user-scoped (для F8 UI-job):** тот же фильтр + `AND target_user = :resolved_name`.
- **Обоснование выбора:** `get_persona_card` (`database.py:4416-4421`) показывает карточку
  строго по `target_user = name AND status='confirmed'`. `kind='fact'` и непустой `target_user`
  отделяют «личностные» строки от чат-мемов/непривязанных и от beliefs. Это минимальный скоуп,
  дающий видимый эффект в «Досье», при этом не задевающий мета-слой.
- **НЕ удаляется:**
  - `kind='belief'` (beliefs/paradigms) — мета-слой неприкосновенен;
  - факты с `target_user IS NULL/''` — чат-уровневые, в карточку не попадают;
  - `persona_dossier_overrides` — ручные правки (инвариант `manual-overrides-immutable`);
  - `nodes`/`edges` — **не мутируются** в этом проходе (см. ниже);
  - `smart_messages` + FTS/vec + `import_checkpoints` — инвариант `imported-history-immutable`.
- **Защита провенанса убеждений:** факты, чей `id` встречается в `source_ids` любой строки
  `kind='belief'` чата, **исключаются** из удаления (иначе belief-валидатор получит
  `missing_sources`). Считается в `protected_belief_sources`; реализация — Python-набор из
  `_parse_source_ids` (`memory_rebuild.py:357-372`), bounded.
- **`nodes`/`edges`:** намеренно не трогаются. Удаление confirmed-фактов не каскадируется
  (FK нет); «висячий» `edges.fact_id` не влияет на карточку (она джойнит `edges→nodes`).
  Сбор orphaned edges — вне этого раунда (не переоткрывать N10.21-2).
- **Страховка:** `_archive_generated_rows` (JSONL, fsync) + сверка `candidates == archived`
  (`memory_rebuild.py:175-229`) → **только потом** `delete_generated_facts` (guard+allowlist).
  Добавляется reason `confirmed_cleanup_archive_mismatch` при рассинхроне (delete отменяется).

### 2.6. Защита от over-delete (R1b)

1. Перед сбросом — `_list_generated_memes`/`_list_generated_portraits` + выборка confirmed-кандидатов.
2. `oldest_created_at` → `needed_window_hours`; `effective_window = max(...)`.
3. Инвариант успеха: если `reset > 0`, но `rebuilt == 0` → reason `rebuild_empty`, `WARNING`,
   **ненулевой exit-код**. Молчаливый «успех» запрещён.

---

## 3. Контракты

- **CLI:** `python manage.py memory rebuild-dossiers --target-chat [--window-hours 4320] [--dry-run] [--limit N] [--batch N] [--backup-dir P]`.
  `--window-hours 0` = без ограничения по времени (в пределах `max_msgs`). Дефолт боевого прогона — **4320 ч**.
- **Отчёт (R17-safe, только числа/коды):** `mode, chats, scanned, reset, reset_portraits,
  confirmed_candidates, confirmed_cleaned, confirmed_protected_belief_sources,
  rebuilt, skipped, window_hours_used, source_age_days, reasons, backup`.
- **Инвариант:** `smart_messages`, `smart_messages_fts`, `smart_messages_vec`,
  `smart_messages_archive`, `import_checkpoints` — байт-в-байт неизменны (тест + post-check).
- **`persona_dossier_overrides`** — не трогается без `--include-overrides`.
- **Новый общий примитив (владелец — F1):** `cleanup_confirmed_dossier_facts(db, *, chat_ids,
  target_user=None, dry_run=False, db_path=None, backup_dir=None, batch=2000) -> dict` в
  `services/memory_rebuild.py`. Возврат `{candidates, cleaned, protected_belief_sources,
  archived, reasons}`. F8 (UI-job) вызывает его read/write из job-раннера (reuse, не дублировать).

---

## 4. Feature Flags / Progressive Delivery

- Флагов **нет** (F1 — CLI, под контролем оператора). Δ каталога = **0**.
- Поэтапная раскатка % не применима. `DOSSIER_REBUILD_UI_ENABLED` (F8) на CLI не влияет.

## 5. Kill-switch / fallback / откат

- **Kill-switch:** не запускать команду (авто-кронов/HTTP-триггеров нет).
- **Fallback:** `--dry-run` (read-only counts) — рекомендованный маркер перед боевым прогоном.
- **Откат данных:** `MEMORY_BACKUP_DIR/memory_rebuild_*.db` (полный снапшот) **+** JSONL-архивы
  удалённых строк (мемы, портреты, **confirmed-факты**); инвариант «overrides не тронуты» упрощает откат.
- **Откат кода:** `git revert`.

## 6. Стоимость / латентность

- LLM: двухслойный пайплайн на чат × сообщения 180-дневного окна; линейна по `max_msgs`. Ограничивается `--limit`/`window_hours_used`.
- Время: десятки минут; бэкап БД ~724 МБ — учесть диск. Запуск осознанно (Д-1 закрыт: запускаем).

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | Critical | Снятие guard → удаление сырой истории | Инвариант `RAW_HISTORY_TABLES`/`assert_derived_table`/`_guarded_delete` **не снят**; post-check `smart_messages` неизменен |
| R1b | Critical | Over-delete: производные удалены, но не пере-собраны | `effective_window` ≥ возраста удаляемых строк; `--window-hours 4320`; reason `rebuild_empty` → ненулевой exit |
| R7 | Critical | confirmed-cleanup удалит валидные/нужные факты участников (принято владельцем, вариант «а») | JSONL-архив + сверка `candidates==archived`; защита `source_ids` beliefs; F8 — rollback-снапшот; beliefs/nodes/edges не тронуты |
| R2 | High | `database is locked` роняет прогон/бота | Снапшот чтения + bounded-бэкофф записи + `busy_timeout` |
| R3 | High | LLM-таймауты → неполный ребилд/аборт | Bounded-ретраи + частичная деградация на чат |
| R4 | High | Боевой прогон без бэкапа | Авто-бэкап **до** DELETE, fail-closed |
| R5 | Medium | Неполный ростер (`roster_incomplete`, N10.21-2) | Вывод `roster_size`; класс «галлюцинация» не применяется при неполном ростере |
| R6 | R17/R18 | SSH-креды | Не цитировать/не коммитить |

## 8. Расхождения ТЗ и открытые вопросы

- ТЗ «снять любые инварианты» → **частично отклонено** (§0.2/§2.1), владелец подтвердил (Д-2).
- Открытые вопросы Д-1/Д-2/Д-3 **закрыты** UPD3 — см. `round1022-human-gate-map.md`.
- Открыто: **точная формулировка «валидный confirmed-факт»** для будущих проходов (сейчас
  скоуп формальный — см. §2.5); при необходимости — отдельный follow-up.

## 9. Задачи

См. `tasks.md` (T-2019…T-2027 + **T-2090** confirmed-cleanup primitive, **T-2091** тесты/постчек).
Настоящий spec **дополняет** их: вариант (а), окно 180 дней, точный скоуп confirmed-cleanup,
R1b, `--target-chat`, `effective_window`, `rebuild_empty`.
