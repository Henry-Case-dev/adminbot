# F11 `status-showcase-dashboard-round1025` — Review (T-3091, Step 5 @Reviewer) — Итерация 2

- **Feature-ID:** status-showcase-dashboard-round1025 (F11, Эпик 1). **Дата:** 23.09.2026.
- **Base:** `25cc19c` + рабочее дерево F11 (вкл. rework итер.2). **Скоуп:** `web/index.html`, `web/static/app.css`, `web/app.js`, `web/api/routes.py` (аддитивно), `services/log_ring.py` (аддитивно read-only), `config/settings.py`, `.env.example`, `README.md`, `tests/**`, `tools/ui_round1025_matrix.py`.
- **Status: Approved.** Итерация 1 (Changes requested, 1× High §20) закрыта: счётчики теперь точные (N, а не 0/1). Блокеров нет; остаются только неблокирующие заметки и живой гейт владельца.

## Находки итерации 1 → статус (итерация 2)
| # | Sev (итер.1) | Статус | Доказательство (проверено заново) |
|---|---|---|---|
| H-F11S-1 §20 счётчики занижены до 0/1 | High | **Закрыто** | `services/log_ring.py:185` `level_counts()` — read-only агрегация всего буфера под локом; `web/api/routes.py:1684` возвращает `{"count", "counts": ring.level_counts(), "logs"}`; `web/app.js:9308` `loadLogCounts` — **один** запрос `?level=ALL&limit=1`, читает `counts.ERROR`/`counts.WARNING`, нет `counts`/ошибка → `null` («—»). Эксперимент: 5 ERROR + 2 WARNING + 1 CRITICAL → `get_entries(level=ERROR,limit=1)=1`, `level_counts={ERROR:5,WARNING:2,CRITICAL:1,INFO:1}`; UI = 5/2. Тесты: `tests/test_log_ring.py` (`level_counts` 7/3), `tests/test_webapp_status_control.py` (route: `count==1`, `counts.ERROR==5`, `counts.WARNING==2`), `tests/js/round1025_f11_log_counts_test.js` (`count>1`, WARN≠7, fail-open→null). |
| M-F11S-1 OFF не byte-identical | Medium | **Закрыто** | Формулировки исправлены на «одноколоночный безопасный режим (`.status-grid--legacy`), НЕ byte-identical»: `spec.md:70`, `adr-1025-23:48/52/59/73`, `config/settings.py:780`, `.env.example`. |
| L-F11S-1 byte-freeze ослаблен | Medium | **Закрыто** | `tests/test_round1025_f8_registry.py` — восстановлен строгий SHA256-пин `ROUTES_SHA256_F11`; вычисленный sha256 `web/api/routes.py` = `76bcab3c…53306` **совпадает** с константой; исторический `f8_baseline.json` не тронут. |
| L-F11S-2 флаг не в .env.example | Low | **Закрыто** | `.env.example` — секция F11 с `#UI_STATUS_GRID_V2=true` и описанием семантики OFF. |
| L-F11S-3 a11y полного экрана графа | Low | **Закрыто** | `index.html:3998` `role="dialog" aria-modal="true" tabindex="-1" ref="graphFullPanel"`; `app.js` `_focusGraphFull()` (initial focus, watch `graphFullVisible`) + `escClose()` закрывает граф первым; CSS `.status-graph-full .btn-ghost/.badge { min-height:44px }`. Focus-trap нет — осознанно Low. |
| I мёртвая ветка `$refs.statusLogs` | Info | **Закрыто** | `web/app.js:9321` `scrollToLogs` читает только `document.getElementById('status-logs')`. |

## Воспроизведённые цифры (итерация 2)
- `node --check web/app.js` — OK; JS-тесты `tests/js/*.js` — **42/42 PASS** (вкл. `F11-LOG-COUNTS-OK`, `F11-STATUS-GRID-OK`, `F11-HEARTBEAT-OK`).
- `py -3 -m pytest -q` — **8457 passed, 5 failed, 1 skipped** (118.3 c). 5 fail — те же предсуществующие env-модули (`test_outgoing_guard_round1022` 2×, `test_summary_cover_round1023` 3×; ImportError rich-типов `aiogram`), к F11 не относятся.
- Таргет: `test_log_ring.py + test_webapp_status_control.py + test_webapp_f11_round1025.py + test_round1025_f8_registry.py` — **104 passed**.
- Δ каталога = 0 (459/98/96/21/418); Δ DDL = 0; `git diff --check` — чисто; `APP_VERSION` = 2.58.17 + README `v2.58.17`.
- R18: тег `pre-round1025-f11` на месте; `.env.bak.round1025-f11` и `var/backups/f11-round1025-20260923-071210/` на месте; `stash@{0}` (F1 WIP) сохранён.
- `level_counts` семантика: «Ошибки» = точный `ERROR`, «Предупреждения» = точный `WARNING` (без «warn и выше»); совпадает со `spec.md:63`. CRITICAL в «Ошибки» не входит, но продовый код CRITICAL не эмитит (только тесты) — заметка, не дефект.

## Новые находки
- Блокирующих нет. Информационно: аддитивная правка `services/log_ring.py` (read-only `level_counts`) — единственный разрешённый corrective; `spec.md §1/§7/D5`, `ADR-1025-23` и `evidence.md` приведены в соответствие (Δ DDL=0, новых endpoint'ов/каталога нет). Маркер-тесты усилены (byte-freeze восстановлен, пин `counts`), не ослаблены.
- Playwright-матрица (`tools/_ui_round1025_raw.json`: `failures: []`, 10 вьюпортов) — артефакт-верификация; сам прогон не воспроизводился (Playwright в окружении не установлен).

## Unavailable / live
- Живой Telegram WebView/TMA (§117/§77) — **PENDING OWNER VERIFICATION** (T-3097): HTTP/Playwright ≠ корректный UI в клиенте.
- `F11-FU-DOSSIER-TS` (время/тип `dossier_feed`) и `F11-FU-GRAPH-ALIAS` — осознанные follow-up вне F11.

## Handoff
RESULT: Approved @Orchestrator — F11 (T-3091) итер.2: H-F11S-1 закрыт по факту (счётчики §20 = реальные N, проверено экспериментом и тестами), M/L/I закрыты, новых блокеров нет; инварианты (Δ DDL=0/Δ каталога=0/CSP/R18/2.58.17/env-флаг) подтверждены, маркер-тесты не ослаблены. Дальше — Step 6 @Scanner (T-3092), затем Merge/Deploy; живой TMA — PENDING OWNER VERIFICATION. Артефакт: `plans/archive/status-showcase-dashboard-round1025/review.md`.
