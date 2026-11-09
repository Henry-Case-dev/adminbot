# MOD-ACL-UX-01 — M0 Baseline Audit
<!-- read-only probe; no product code changed -->
<!-- branch: integ/unify-release | date: 2026-11-09 -->

---
## 1. Каталог модулей (module_registry.py)

| # | name | classification | runtime_gate | master_param |
|---|------|----------------|--------------|--------------|
| 1 | cognitive | core | global | `cognitive_enabled` |
| 2 | learning | core | global | `learning_enabled` |
| 3 | memory | core | global | `memory_enabled` |
| 4 | search | core | global | `search_enabled` |
| 5 | analysis | core | global | `analysis_enabled` |
| 6 | generation | core | global | `generation_enabled` |
| 7 | dialogue | core | global | `dialogue_enabled` |
| 8 | initiative | core | global | `initiative_enabled` |
| 9 | meme | core | global | `meme_enabled` |
| 10 | experience | core | **per_chat** | `experience_enabled` |
| 11 | embeddings | infrastructure | global | *(пусто — нет master_param)* |

Итог: 10 глобальных + 1 per_chat; 1 infrastructure-модуль без master_param (embeddings отображается
в UI без toggle). JS-реестр (app.js L691-696) использует ModuleSpec как аддитивный fallback к
hardcoded MODULES — расхождение возможно при добавлении нового модуля только в Python.

---
## 2. Effective-state sources (chat_params / feature_gates)

```
capability ON/OFF
│
├─ product params  →  chat_params.overrides[chat_id][key]
│                       └─ hot.get(key)           ← глобальный fallback
│
├─ heavy features  →  chat_params.gates[chat_id][feature]   (ALL_GATED_FEATURES)
│                       └─ hot.get("gates." + feature)      ← глобальный fallback
│
└─ env kill-switch →  mca_gates.<feature>                   ← поверх всего
```

Два независимых домена (`params` и `gates`) без унифицированного ридера.
Один capability (например, `experience`) может читаться из разных слоёв разными сервисами —
источник EXP-FIX-08.

---
## 3. ACL false-403 — root cause

**Файл:** `web/api/memory_agi.py` L174-188 — `_is_global_admin()`

```python
# memory_agi.py — ЛОКАЛЬНАЯ копия, НЕ использует role_type_of()
def _is_global_admin(user) -> bool:
    role = cache.get_role(user.telegram_id)
    return (
        user.telegram_id == ADMIN_USER_ID
        or role == "admin"          # строковое сравнение — не role_type
        or role == "*"
    )
```

**Каноничная версия:** `web/api/deps.py` L198-213 — `user_is_global_admin()` вызывает
`role_type_of()` из `services/roles.py` и корректно распознаёт `role_type="global_admin"`.

**Масштаб:** все 15+ endpoints `/api/memory/*` используют локальный `_require_global_admin`
вместо `requires_global_admin()` из deps.py. Пользователь с `role_type="global_admin"`, но без
строки `role=="admin"` получает 403 на всех memory-endpoints.

**Fix:** заменить `_is_global_admin` / `_require_global_admin` в `memory_agi.py` на импорт
`requires_global_admin` из `web.api.deps`. Файл `memory_agi.py` — в `M`-статусе MEMORY-08 →
координация с MEMORY-08 обязательна.
---
## 4. EXP-FIX-01..10 — owner contract и verdict deployed line

Ниже сохранены определения из owner TZ §7.1. Указанные в TZ примерные строки уже
сдвинулись; рядом приведены текущие координаты и короткие цитаты deployed line.
Вердикты: **present** — дефект воспроизводится по коду; **partial** — часть контракта
уже выполнена; **absent/fixed** — дефект в текущей линии не найден.

| ID / P | Owner definition | Current evidence / quote | Verdict |
|---|---|---|---|
| EXP-FIX-01 / P0 | `_load_payload()`/`_inherit_cursor()` не наследуют `semantic_watermark`, per-chat `semantic_cursor:*`, `semantic_pending`, `semantic_last_ts`; новый job может начать semantic pass с начала. | `mca_experience_jobs.py:787-842`: `_load_payload` задаёт watermark/pending только defaults (L800-801), а `_inherit_cursor` копирует лишь `cursor_feedback_rowid`, `cursor_event_rowid`, detector и link cursor (L827-838). | **present** |
| EXP-FIX-02 / P0 | `DEFAULT_CADENCE="daily"` и максимум 10 строк/chat за review смешивают product interval и backlog drain rate; их надо разделить в существующем job. | `mca_experience_jobs.py:67`, `661-702`, `1199-1205`: `DEFAULT_CADENCE = "daily"`; tick enqueue-ит due job по cadence; semantic extractor ограничивает проход `≤SEMANTIC_PER_CHAT_MAX` (текущая константа/планка — до 10). | **present** |
| EXP-FIX-03 / P0 | Если все строки окна ineligible, chat cursor движется, `semantic_pending` не уменьшается и `drained=True` не обновляет `semantic_last_ts`; возникают phantom pending/repeated selection. | `mca_experience_jobs.py:1327-1335`: `if not eligible` делает `payload[key] = last_id; return [], True`; `mca_experience_jobs.py:1233-1237`: `drained` сразу `continue`, без pending/last_ts update. | **present** |
| EXP-FIX-04 / P0 | Ошибка durable write возвращает False, но batch всё равно продвигает cursor; candidate может быть потерян. | `mca_experience_jobs.py:1393-1457`: write exception → `return False` (L1448-1451), затем `_semantic_extract` безусловно вызывает `_advance_semantic_cursors` (L1261-1262). | **present** |
| EXP-FIX-05 / P1 | Bad JSON и valid `[]` оба превращаются в empty list; cursor продвигается после unparsed answer, `semantic_extracted=0`. | `mca_experience_jobs.py:426-469`: `parse_semantic_candidates` возвращает `[]` и при отсутствии JSON (L433-434), и при `json.loads` error (L435-438), после чего extractor считает результатом `len(candidates)` и двигает checkpoint (L1246-1262). | **present** |
| EXP-FIX-06 / P1 | Регистрация `experience_review_tick` зависит от `_experience_review_tick_enabled()` при startup; hot-ON позже не регистрирует job до restart. | `memory_maintenance.py:344-379`: `start()` вызывает `_experience_review_tick_enabled()` только в условии L375, затем `add_job` (L376-379). | **present** |
| EXP-FIX-07 / P1 | `_resume_incomplete()` выбирает candidate/validated через `ORDER BY created_at LIMIT batch_max` без cursor; старые invalid candidates могут занимать окно навсегда. | `mca_experience_jobs.py:1464-1483`: SQL содержит `ORDER BY l.created_at, l.lesson_id LIMIT ?` (L1480-1482), durable cursor/rotation отсутствует. | **present** |
| EXP-FIX-08 / P0 | Global OFF полностью запрещает chat ON; `review_enabled` блокирует shared job до chat selection, противореча GLOBAL-default → CHAT-override. | `mca_experience_jobs.py:552-565`: `if not _learning_enabled(): return False`; `592-600`: `review_enabled()` возвращает `_learning_enabled()` после gates. `tick` L671-672 возвращает `disabled` до выбора чатов. | **present** |
| EXP-FIX-09 / P0 | `dedup_key = SHA(source_kind, chat_id, ref_type, msg_id)` может слить разные semantic signal kinds одного сообщения; второй сигнал не попадёт в experience. | `mca_experience.py:1737-1763`: `dedup_key = _sha1_16(source_kind, chat_id, ref_type, ref_id)`; semantic writer `mca_experience_jobs.py:1437-1438` передаёт один `source_kind` и `primary_id`, без semantic kind/signal identity. | **present** |
| EXP-FIX-10 / P0 | `_semantic_discover()` при `len(pending)>64` удаляет ожидающие chat keys после продвижения discovery watermark; сообщения могут быть потеряны. | `mca_experience_jobs.py:1279-1303`: watermark продвигается L1295, затем при `len(pending)>64` ключи удаляются L1299-1302 (`pending.pop(key, None)`). | **present** |
**Сводка verdict:** confirmed present — **EXP-FIX-01..10 (10/10)**; already fixed — **0**;
partial — **0**. В текущей линии нет доказательства, что какой-либо owner-дефект уже
исправлен. Отдельный ACL false-403 остаётся архитектурным finding MOD-ACL, но не входит
в EXP-FIX-01..10.
---
## 5. UI-поверхности — статус
### 5a. Roles & Permissions (Роли и права)
- **Расположение:** `index.html` L9829-9988 — два `modal-card` (`roles-permissions-modal`,
  `roles-modal`), **не** самостоятельные страницы/маршруты.
- Открываются по кнопкам в Settings; не интегрированы в модульную таблицу.
- Отображают статичные данные; нет live-эффектов от module_registry.

### 5b. Module Toggles
- Модули рендерятся через JS (app.js L691) из hardcoded MODULES + ModuleSpec fallback.
- `embeddings` (infrastructure, master_param="") появляется без toggle — корректно.
- `experience` (per_chat) требует per-chat UI, которого сейчас нет — только глобальный toggle.

### 5c. Status Feeds (пять лент)
- `index.html` L13785-13801: dossierFeed, beliefs, paradigms, character + отдельное досье.
- Все реализованы через Vue-директиву `v-sfeed` (app.js L38452).
- API: `/api/oversight/dossier_feed` (dossierFeed), остальные через `statusData` / `cognitionParadigms`.
- Досье отображается внизу страницы отдельно от остальных лент, несмотря на общий источник данных.
## 6. Cross-epic конфликты

| Файл | Git-статус | Владелец | Конфликт с MOD-ACL |
|------|-----------|----------|--------------------|
| `services/mca_gates.py` | M (modified) | MEMORY-08 | effective-state читается обоими |
| `services/config_cache.py` | M | MEMORY-08 | shared cache layer |
| `services/param_catalog.py` | M | MEMORY-08 | параметры модулей |
| `web/app.js` | M | MEMORY-08 | JS-реестр модулей, UI logic |
| `web/api/memory_agi.py` | M | MEMORY-08 | ACL false-403 fix target |
| `web/api/cognitive_map.py` | M | MEMORY-08 | смежный API |

**SERIALIZE:** MOD-ACL не может параллельно писать в эти 6 файлов.
MOD-ACL-UX-01 должен стартовать Builder только после merge/close MEMORY-08 в `integ/unify-release`,
или строго скоординировать патч через PM-arbitration.

Дополнительные зависимости (untracked в worktree):
- `plans/features/self-diag-01/` — SELF-DIAG-01 (новая директория, не merged)
- `plans/features/vmq-onto-01/` — VMQ-ONTO-01 (новая директория, not merged)

---
## 7. План вех M0–M6

| Веха | Содержание | Предусловие |
|------|-----------|------------|
| **M0** | Baseline audit (этот файл) | — |
| **M1** | ACL fix: заменить `_is_global_admin` в `memory_agi.py` на `requires_global_admin` из deps | MEMORY-08 merge или координация |
| **M2** | EXP-FIX-01..04: полный semantic checkpoint; разделить cadence и backlog drain; исправить phantom pending; не двигать cursor после write failure | M1 done + MEMORY-08 coordination |
| **M3** | EXP-FIX-05..07: typed parse result и deferred retry; fair resume pagination; EXP-FIX-08..10: GLOBAL→CHAT resolver, shared-job gating, signal-aware dedup и durable discovery overflow | M2 done |
| **M4** | UI: per-chat toggle для experience, убрать embeddings-toggle, роли живые (не статика) | M3 done |
| **M5** | UI: интеграция Status-лент с module effective-state; досье — унификация расположения | M4 done |
| **M6** | Regression/E2E: два последовательных batch, restart/checkpoint, filtered window, write failure, invalid JSON vs `[]`, OFF→ON, backlog >64 чатов; Playwright + Reviewer accept | M5 done |

---
## Резюме (русский, 10 строк)

Аудит подтвердил root cause false-403: `memory_agi.py` содержит локальную копию проверки
администратора, которая не вызывает `role_type_of()`, — все 15+ memory-endpoints недоступны
пользователям с `role_type="global_admin"`. Два критических дефекта EXP-FIX-06/08 блокируют
работу experience-модуля при типичном production-сценарии (global OFF + per_chat ON). Каталог
содержит 11 модулей: 10 global, 1 per_chat (experience), 1 infrastructure без toggle (embeddings).
Effective-state раздроблен на два независимых домена (params + gates) без унифицированного ридера.
UI Roles & Permissions реализован как модальные окна, не как страницы; per-chat UI для experience
отсутствует. Шесть ключевых файлов заняты in-flight MEMORY-08 — MOD-ACL Builder должен ждать
merge или явной координации. Пять Status-лент работают через v-sfeed, досье отображается отдельно.
Все 10 EXP-FIX дефектов локализованы с приоритетами; M1-M6 план готов для PM-леджера.

MOD-ACL READY FOR PM LEDGER
