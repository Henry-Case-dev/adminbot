# Round 10.25 F11 `status-showcase-dashboard-round1025` — focused diff-based аудит (Step 6 @Scanner, T-3092)

> **НЕ ЗАКОММИЧЕНО.** Baseline (HEAD) — `25cc19c61ef4b02e887c04ecbffea21e7dc9b46b` (`25cc19c`, == `origin/master`).
> Вход: `spec.md` + `adr-1025-23-status-grid-composition.md` + `evidence.md` + `review.md` + `tasks.md` + `plans/reports/round1025_f11_verification.md` / `round1025_f11_ui_report.md`.
> Тип: UI-композиция (`web/**`) + bump + тесты + один обратно-совместимый серверный дифф (corrective H-F11S-1).

**Вердикт (итер.2, финал): К ДЕПЛОЮ — ДА. Блокеров нет.** Итерация 1 (High 1 + Medium 1 + Low 3) закрыта, воспроизведена @Scanner.

---

## Severity (итер.2)

| Severity | Кол-во | Статус |
|---|---|---|
| Critical | 0 | — |
| High | 0 | H-F11S-1 RESOLVED |
| Medium | 0 | M-F11S-1 RESOLVED (док-реконсиляция) |
| Low | 0 | L-F11S-1/2/3 RESOLVED |
| Info | 2 | I-F11S-1 RESOLVED; I-F11S-3 live-гейт PENDING OWNER (T-3097) |

---

## Ключевой фикс — H-F11S-1 (счётчики §20)

**Было (итер.1):** UI читал `count` из `GET /api/status/logs?level=ERROR|WARNING&limit=1`, а сервер отдавал `count = len(entries[-limit:][::-1])` → `count ≤ limit`, т.е. счётчик «залипал» на 0/1.

**Стало (итер.2, проверено):**
- `services/log_ring.py:185-199` — новый read-only `level_counts()`: агрегация по ВСЕМУ буферу под тем же локом, `{"ERROR": n, "WARNING": m, ...}`; `get_entries` не изменён.
- `web/api/routes.py:1675-1685` — **аддитивно** `"counts": ring.level_counts()` в существующем ответе; `count` и `logs` сохранены без изменений.
- `web/app.js:9308-9318` (`loadLogCounts`) — **один** запрос `level=ALL&limit=1`, читает `counts.ERROR`/`counts.WARNING`; нет `counts` или ошибка сети → `null` → «—» (не выдуманный 0).
- Семантика раздельная: «Ошибки» — только `ERROR`, «Предупреждения» — только `WARNING` (не «warn и выше»).

**Доказательство:**
- `py -3 -m pytest tests/test_log_ring.py tests/test_webapp_status_control.py` → `test_level_counts_exact` (7×ERROR / 3×WARNING → `ERROR=7, WARNING=3`, `CRITICAL=None`), `test_level_counts_not_capped_by_limit` (`get_entries(limit=1)=1`, `level_counts()["ERROR"]=5>1`), `test_logs_counts_not_capped_by_limit` (API: `count=1`, `counts.ERROR=5>1`, `counts.WARNING=2>1`, `CRITICAL` отсутствует) — **PASSED**.
- `node tests/js/round1025_f11_log_counts_test.js` → `F11-LOG-COUNTS-OK` (реальные числа, WARNING не вбирает ERROR, нет `counts`→«—», сеть→«—»).
- **Обратная совместимость:** `loadLogs` (`web/app.js:9280-9291`) по-прежнему читает `data.logs`/`data.count`; поле `count` не менялось. Существующие потребители не сломаны.

## M-F11S-1 (kill-switch) — RESOLVED

`UI_STATUS_GRID_V2=OFF` = **одноколоночный безопасный режим** (`.status-grid--legacy`), а не byte-identical legacy-DOM. Формулировка приведена к фактическому поведению: `spec.md:70/149`, `adr-1025-23…:48/52/59/73` (альтернатива с legacy-DOM отклонена осознанно), `.env.example` (новый блок документирует soft-откат и полный откат через `git revert`+тег). Код не менялся (по-прежнему одна колонка) — расхождения «обещание/реализация» больше нет.

## L / I — RESOLVED

- **L-F11S-1 RESOLVED:** строгий byte-freeze `web/api/routes.py` восстановлен через `ROUTES_SHA256_F11` (`tests/test_round1025_f8_registry.py:39-49/97-105`); независимо вычислил SHA-256 файла — совпадает с константой (`76bcab3c…3306`), тест PASSED. Набор endpoint'ов по-прежнему заморожен.
- **L-F11S-2 RESOLVED:** `.env.example` документирует `UI_STATUS_GRID_V2` (default ON, доставка через `/api/me.ui_flags`, OFF = soft-откат, полный откат = revert+тег).
- **L-F11S-3 RESOLVED:** `ref="graphFullPanel" tabindex="-1"` + `_focusGraphFull()` (initial focus, `preventScroll`); Esc закрывает полноэкранный граф первым (`escClose` → `closeGraphFull`, `web/app.js:4876-4879`). Остаточно (Info): полного focus-trap нет, тач-цели чипов/счётчиков < 44px — не блокер для mobile-fallback.
- **I-F11S-1 RESOLVED:** мёртвая ветка `$refs.statusLogs` удалена из `scrollToLogs` (работает `getElementById('status-logs')`).
- **I-F11S-2:** поведение принято (один лёгкий запрос вместо двух; новых таймеров нет).

---

## Независимые прогоны @Scanner (итер.2)

- `node --check web/app.js` → rc=0.
- `tests/js/*.js` → **42/42 PASS** (в т.ч. новый `round1025_f11_log_counts_test.js`).
- `py -3 -m pytest -q` → **8457 passed / 5 failed / 1 skipped** (117 s). 5 падений — **предсуществующие env** (`test_outgoing_guard_round1022.py` ×2 + `test_summary_cover_round1023.py` ×3, причина `ImportError` aiogram rich-типы; `services/**` вне scope F11, кроме добавленного read-only `level_counts`). Не-ENV падений нет.
- `py -3 -m pytest tests/test_webapp_f11_round1025.py` → **33 passed**; целевые (`test_log_ring`/`test_webapp_status_control`/`test_round1025_f8_registry`/F11) → **104 passed**.
- `git diff --check` → 0.

## Инварианты

| Инвариант | Статус | Доказательство |
|---|---|---|
| Δ DDL = 0 | ✔ | `git diff --name-only -- services/ migrations/ alembic/` → только `services/log_ring.py` (in-memory `level_counts()`, без схемы/DDL); `web/api/routes.py` — аддитивно (`ui_flags` bool + `counts`) |
| Δ каталога = 0 | ✔ | Импорт `param_catalog`: REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21; `UI_STATUS_GRID_V2` в каталоге отсутствует |
| CSP `script-src 'self'` / zero-build | ✔ | `node --check` OK; в диффе 0 `v-html`/`innerHTML`/`onclick`/`eval`/`new Function`/CDN |
| `APP_VERSION` 2.58.17 | ✔ | settings + README + `?v=__APP_VERSION__` + строгие пины тестов |
| Флаг env-only вне каталога | ✔ | `ClassVar[bool]` → `bool()` в `/api/me.ui_flags` |
| Маркер-тесты не ослаблены | ✔ | byte-freeze `routes.py` восстановлен (L-F11S-1); пины версий строгие; новый регресс-гейт `count>1` |
| R17 (секреты) | ✔ | `counts` отдаёт только имена уровней; секретов в диффе/тестах нет |
| R18 (тег/бэкап/stash) | ✔ | `pre-round1025-f11` (annotated → `25cc19c`, в origin); `stash@{0}` на месте; `.env.bak.round1025-f11`/`var/backups` gitignored |
| Гигиена индекса | ✔ | `git diff --check`=0; `.env`/`plans/current_task.md`/zip/скриншоты/`tools/_ui_*`/`var/backups` отсутствуют; `ARCHITECTURE.md`/`MEMORY.md`/`metrics.md` не тронуты |
| §52–§68 / F0–F9 / §15 / §18 / §20 viewer / F6 | ✔ | `web/static/execution_graph.js`/`/analytics/*` не тронуты; `.status-block` контракт, `hb-canvas`/`ekg-trace`, `log-panel scroll-thin`/`copyLogRow`/`ERROR+WARNING`/`log.expanded && log.exc_text`, §18-ленты — сохранены |

## Изменённые файлы (относительно `25cc19c`)

- **Код:** `services/log_ring.py` (+`level_counts()`), `web/api/routes.py` (аддитивно `counts` + `ui_flags`), `web/app.js`, `web/index.html`, `web/static/app.css`, `config/settings.py`, `README.md`, `.env.example`.
- **Инструмент:** `tools/ui_round1025_matrix.py`.
- **Тесты:** `tests/js/round1025_f11_status_grid_test.js`, `tests/js/round1025_f11_log_counts_test.js`, `tests/test_webapp_f11_round1025.py`, `tests/test_log_ring.py`, `tests/test_webapp_status_control.py`, `tests/test_round1025_f8_registry.py` + пины.
- **Plans:** `spec.md`, `adr-1025-23…`, `evidence.md`, `review.md`, `tasks.md`, отчёты (Scanner/UI/verification).

## Handoff

**RESULT: SCANNED — Critical 0 / High 0 / Medium 0 / Low 0 / Info 2; к деплою ДА, блокеров нет.** @Orchestrator → Merge/деплой (bump 2.58.17). Live Telegram WebView/TMA — PENDING OWNER VERIFICATION (T-3097), workflow не останавливает.
