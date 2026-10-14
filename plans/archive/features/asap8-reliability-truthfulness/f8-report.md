# F8 — Embeddings: честная rotation-семантика и recovery (отчёт lane F8)

Базис: `master @ cbda23b` (на момент старта lane; к моменту отчёта HEAD продвинулся
параллельными лейнами — a12e6bf/F3, мой diff поверх, конфликтов нет). Режим writer.
Контракт: `architecture.md` §8, ТЗ §15 (owner-архитектура), §23 E1–E5, §28.18/§28.19/дефект п.50.

---

## 1. Что сделано

### 1.1. Auto-group семантика named slots (§15.2/§15.3, дефект п.50) — `embedding_control_plane.py`

* Новая лестница резолва группы: **label → auto → unknown**.
  `resolve_quota_group_full(alias, labels) -> (group_id, known, source)`:
  explicit label (`GROUP_SOURCE_EXPLICIT`) → named slot (`primary|fallback_1|fallback_2`)
  получает стабильный group id **= alias** (`GROUP_SOURCE_AUTO`) → остальное
  (только `extra_N`-алиасы) — общая unknown-группа (`GROUP_SOURCE_UNKNOWN`).
* `resolve_quota_group()` сохранён (2-tuple, обратная совместимость); docstring модуля
  обновлён под новую safe-default семантику («unknown — одна группа» теперь только для
  не-опознанных алиасов; named slots — независимые pools).
* `EmbeddingCredential` + поле `quota_group_source` (additive, default) — панель честно
  различает `explicit | auto | unknown`.
* Эффект рантайма (E2): 429 на primary больше не замораживает fallback_1/fallback_2 —
  cooldown принадлежит группе `primary`, ротация работает без конфигурации. Ручная
  группировка через labels полностью сохранена (приоритет лестницы).

### 1.2. Панель (без секретов) — `provider_panel()` / `group_state_lines()` / `index.html`

* `rotation`-блок: `warn` (banнер-флаг), `reason` (`unknown_group | single_group`), `hint`
  (без изменений) — закрытие §28.18/E1: «rotation=none · все N ключ. в одной группе unknown».
* `credential_rows[]` per-credential: alias, provider/model, quota group + provenance,
  health (healthy/cooldown/…), `cooldown_until` (новый `REGISTRY.credential_cooldown_until`).
* `groups[]` per-group: `health` (ok/cooling/exhausted по-русски), `next_allowed_at`,
  `last_429_at` (новый per-group last-429 в `REGISTRY.record_rate_limit(group_id)`),
  `keys`/`aliases` из текущего пула.
* Пересбор registry при runtime-добавлении labels: `visible_group_ids()` — панель показывает
  группы ТЕКУЩЕГО пула (+ группы с ещё активным cooldown); устаревшая группа исчезает из
  панели по истечении cooldown, без рестарта. Пул строится на вызов — labels подхватываются
  живьём, новая группа не blocked → пул размораживается (проверено тестом).
* UI (`index.html`, только Embeddings-панель): WARN-баннер `data-embeddings-rotation-warn`
  (показывается только при честно вырожденном пуле), per-credential таблица
  `data-embeddings-credentials`, обогащённые строки групп, блок backlog
  `data-embeddings-backlog` (скрыт, пока нет ни счётчиков, ни прогресса — fail-open API
  не рисует пустую витрину).

### 1.3. Re-probe/backfill без read-трафика (E4/§28.19) — `summary_memory.py` + `memory_maintenance.py`

* `MemoryManager.embed_recovery_tick()` — публичная точка тика:
  vec off по embed → та же `_ensure_vec_retry()` (реактивация + backfill);
  vec жив, но есть text-only backlog (деградация embed при живом vec) → bounded backfill
  (`_BACKFILL_MAX_FACTS` за вызов), каденция `_EMBED_BACKFILL_TICK_INTERVAL=600s`.
  Никогда не бросает; `_text_only_backlog_counts()` — честные счётчики БД (None, если
  vec-таблиц нет — «неизвестно», не 0).
* `memory_maintenance.py`: джоб `embed_recovery_tick` (600s, код-константа, Δ каталога = 0)
  в СУЩЕСТВУЮЩЕМ планировщике обслуживания; регистрируется ВСЕГДА (recovery памяти не
  зависит от флагов других джобов; при здоровом vec и пустом backlog тик почти бесплатен —
  cadence-гейт внутри). `_tick_embed_recovery()` — fail-open, лог INFO только при
  recovered/backfilled.
* Прогресс — в `ecp.BACKFILL_STATE` (`note_backfill_progress`, R17-safe: только
  счётчики/ts): пишут сам тик, `_ensure_vec_retry` (recovery-ts) и оба backfill-функции
  (processed — триггер-агностично, включая read-path). Панель:
  `embeddings_backlog_panel(db)` — живые COUNT'ы + прогресс; в `/api/memory/embeddings`
  добавлено поле `backlog` (additive, fail-open).

### 1.4. WARN-семантика (E5) — НЕ ухудшена

`_maybe_warn_degenerate_rotation` (1/10 мин) не тронут; WARN «facts saved text-only»
(1/batch, `summary_memory.py:3064-3081`) не тронут (аудит опроверг спам). Реальный спам
не обнаружен. Cooldown unchanged → повторные попытки не логируются (покрыто тестом E5).

---

## 2. Сверка с ТЗ/архитектурой — reconciliation

**E1 «3 credentials no groups → rotation none/unknown» vs §15.3 auto-groups** —
разрешено так: после §15.3 настроенные named slots НЕ могут быть unknown (это и есть
фикс дефекта п.50 — «configured slots remain in one unknown group»). E1 проверяет
честный баннер для **genuinely-unknown** пула (extra-алиасы без labels) + отдельный
контракт «named slots не unknown» (`test_e1_named_slots_are_not_unknown`). Это ровно
формулировка lane-брифа: баннер для «все ключи в одной группе unknown»; auto для
named slots; unknown для настроенного named slot — defect, не сваливать.

Противоречий с архитектурой не найдено; `STATUS`-семантика (F10) получает честные
поля готовыми (`rotation.reason`, `groups[].health`).

---

## 3. Обновлённые пины (намеренно — закрепляли дефект)

| тест | старый пин | новый контракт |
|---|---|---|
| `test_asap4::test_unknown_group_safe_default_single_group` | 3 named keys без labels → все unknown | named slots → auto-группы (§15.3); unknown-collapse только для extra_N |
| `test_asap4::test_retry_storm_same_group_no_burst` | same-group через unknown-default | same-group через явные labels (E3-семантика); storm-контракт сохранён |
| `test_asap4::test_parking_*` (×4) + `test_flag_matrix_parking_backoff` | `group_state(UNKNOWN)` | labels→`gA`, парковка-математика без изменений |
| `test_asap4::test_429_counted_once_per_real_hit` | unlabeled 3-key пул | labels (иначе после 429 пул бы ротировал — E2) |
| `test_asap4::test_degenerate_pool_hint` | 3 named keys → degenerate | named keys → grouped; extra-only → degenerate/unknown; + `warn`/`reason` |
| `test_asap4::test_parked_note_and_panel_honest`, `test_provider_panel_r17_safe` | `«не определены»`/known==1 | gA-строка; known==2 (auto-группа известна) |
| `test_asap44::test_24_unknown_groups_collapse_to_one_safe_group` | partial labels → fallbacks в unknown | partial labels → fallbacks auto; unknown-collapse для extra |

## 4. Тесты (новые, `tests/test_asap8_f8_embeddings.py`, `TEST-LIFECYCLE: CONTRACT owner=ASAP8/F8`)

10 тестов: E1 (баннер+WARN≤1/10мин; named-not-unknown), E2 (429 primary → ротация на
fallback_1, per-group last-429), E3 (gA cooldown блокирует оба ключа gA, gB работает),
E4 (backfill-probe без read + re-probe реактивация + maintenance-tick wiring + no-op
двойник), E5 (нет WARN-флуда при unchanged cooldown), пересбор registry при runtime
labels + фильтрация устаревших групп, R17-маскирование панели/backlog.

**Прогоны (финальные):**
- `pytest tests/test_asap8_f8_embeddings.py tests/test_embedding_control_plane_asap4.py -q`
  → **79 passed** (акцептанс-команда).
- Смежные: `test_asap44_graphrag_batch_breaker` 11 passed; `test_summary_memory` 79 passed;
  `test_memory_maintenance` 13 passed; `test_asap6_embedding_generations` 24 passed;
  `test_mca17c_oversight_api_round1047` + `test_memory_health` + `test_graphrag_memory` —
  206 passed (в общий прогон с asap6-генерациями). Подмножества с моим файлом:
  89/104/128/158/197 passed.
- JS-структурные: `asap6_wave2_ux_tabs`, `asap41_zone_g_inspector`,
  `round1030_pipeline_inspector`, `asap6_embedding_profiles_ui` — OK.

## 5. Live/UI evidence

Изменённая панель верифицирована двумя обязательными способами на вербатим-фрагменте
изменённого `web/index.html` (харнес собран на vendor `tailwind.css`; замеченное в харнесе
слипание заголовочных спанов — артефакт отсутствия в vendor утилит `gap-x-4`/`gap-y-1`,
детально см. §6.2) — Playwright (детерминированные флоу-чеки) и Browser Use (реальные
рендер-скриншоты):

1. **Playwright (детерминированные флоу-чеки)** — warn: баннер «⚠ rotation=none · все
   3 ключ. в одной группе unknown» + hint, cred-строки `(unknown)`, группа cooling/blocked,
   backlog 12/5; auto: баннера нет, `(auto)`, primary cooldown до, fallback_1/2 ok,
   прогресс backfill «(+17)»; explicit: gA (2 ключа) cooling/blocked, gB ok; degraded
   (provider `{}`): все новые блоки честно скрыты; mobile 390px: баннер виден, без
   горизонтального overflow, cardFits.
2. **Browser Use (реальный рендер)** — скриншоты warn/auto: стилистика панели
   (`rounded-lg border-white/10 text-xs`, amber-баннер) сохранена, секретов нет,
   блоки читаемы.

`LIVE_UNVERIFIED` (вне скоупа lane, требует прод-деплоя): фактический production-пул
(3 Gemini-ключа) после деплоя покажет rotation=grouped с auto-группами; фактический
re-probe тик в прод-сердцебиении.

## 6. Incidental findings

1. **`related-nonblocking` (pre-existing, воспроизведён на baseline)**: флаковый дедлок
   teardown `db`-фикстуры `tests/test_summary_memory.py` (`loop.run_until_complete(d.close())`
   в aiosqlite-close, Windows IOCP) в БОЛЬШИХ комбинированных прогонах (6 embedding/memory
   файлов). Воспроизведён на `git stash`-baseline (без моих изменений) → не привнесено F8.
   На одиночных файлах/подмножествах — стабильно зелено. Чинить вне скоупа lane не стал
   (owner — тест-каркас summary); рекомендация: loop-scoped fixture или
   `pytest-timeout`-устойчивый close.
2. **`related-nonblocking` (pre-existing CSS; формулировка исправлена по REV-F8)**:
   утилиты `gap-x-4`/`gap-y-1` отсутствуют НЕ только в vendor харнеса — их нет ни в
   `web/static/vendor/tailwind.css`, ни в `web/static/app.css`, ни в
   `web/static/tailwind.input.css` → заголовочные спаны панели слипаются и в проде
   (например, «gemini-embeddingКлючи: 3»). Классы существовали на HEAD (cbda23b, 2
   вхождения) — не регресс F8, новые блоки F8 эти утилиты не используют. CSS-чистка
   (вернуть 2 утилиты) — ближайший UI-лайн (F4).
3. `unrelated/pre-existing`: RuntimeWarning «start_resume_ticker._loop never awaited» —
   существующий fire-and-forget паттерн `_recover_runtime_jobs`, виден и без F8.

## 7. Файлы / отклонения от DO_NOT_TOUCH

Изменено: `services/embedding_control_plane.py`, `services/summary_memory.py`
(только `_ensure_vec_retry`-участок/backfill/панельные данные + `embed_recovery_tick`),
`services/memory_maintenance.py` (re-probe в существующем планировщике),
`web/api/memory_agi.py` (backlog в существующий ответ), `web/index.html`
(только Embeddings-панель), `tests/test_embedding_control_plane_asap4.py` +
`tests/test_asap44_graphrag_batch_breaker.py` (пины старой unknown-семантики),
НОВОЕ `tests/test_asap8_f8_embeddings.py`. DO_NOT_TOUCH не нарушены; коммитить не стал —
после Reviewer.
