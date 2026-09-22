# Evidence — T-3100 [@DevOps] (F10 `epic1-verification-round1025`)

Deploy F10 — **NOT_APPLICABLE** (verification-гейт; только `tools/**`/`tests/**`/`plans/**`, код не пишется).

## Точка отката

- `git rev-parse pre-round1025-f10` → `26929443eead390eebc3dff6efd22e0e4fc85cea` (annotated tag object)
- `git rev-parse pre-round1025-f10^{commit}` → `57b325c217d84e9fe8ff98906c90c9e7e52e6090`
- `APP_VERSION` → **2.58.17** (bump не требуется)
- Тег запушен: `origin/refs/tags/pre-round1025-f10`

**Команда rollback:**
```
git fetch --tags origin
git reset --hard pre-round1025-f10
```

## Бэкап и baseline

- Бэкап HEAD (`git archive`): `var/backups/f10-round1025-20260923-091131/`
  (`tools/ui_round1025_matrix.py`, `web/index.html`, `web/app.js`, `web/static/app.css`, `BASELINE.md`, `snapshot-before/`).
- `.env.bak.round1025-f10` — размер 7131, SHA-256 совпадает с `.env`.
- pytest 8463/0/0; JS 42/42; `database is locked`=0; Δ DDL=0; Δ каталога=0 (459/98/96/21/418).
- R18 соблюдён; в git не коммичено; `deploy_commands.txt` не изменялся.

---

# Evidence — F10 Step 4 [@Builder] (T-3103…T-3120, блоки A–G)

Baseline прогонов: HEAD `57b325c`, `APP_VERSION` 2.58.17. Deploy F10 — **NOT_APPLICABLE** (D1).
Изменены только `tools/**` + `plans/**` (рантайм `services/**`/`web/**`/`config/**`/миграции — не тронуты).

## Код/инструменты (изменено/добавлено)

- `tools/ui_round1025_matrix.py` — аддитивно: `LOW_TG_WINDOW = {1280×400, offset 120}`,
  `_low_tg_failures()`, отдельный low-window проход (базовые 10 вьюпортов × 5 режимов не изменены).
- `tools/ui_round1025_e2e.py` — **новый** E2E §72/§73/§74 (переиспользует сервер/стабы матрицы).
- `tools/ui_round1025_secrets_ui.py` — **новый** UI-прогон §78 (перехват сети).
- `tools/.gitignore` — игнор локальных JSON-артефактов прогонов.

## Прогоны (фактические результаты)

| Проверка | Команда | Результат |
|---|---|---|
| §71 матрица | `.venv/Scripts/python.exe tools/ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов × 19 маршрутов + low-tg 1280×400 failures=0) |
| E2E §72–§74 | `.venv/Scripts/python.exe tools/ui_round1025_e2e.py` | **failures: 0** (s72 writes=1; s73 B стабилен; s74 override сохранён) |
| §78 UI-секреты | `.venv/Scripts/python.exe tools/ui_round1025_secrets_ui.py` | **failures: 0** (маска/композит → 0 write; замена → 1 write) |
| pytest (full) | `.venv/Scripts/python.exe -m pytest -q` | **8463 passed** (104.8s) |
| pytest §79 subset | 9 summary/image-файлов | **300 passed** |
| JS-юниты | `pytest tests/test_webapp_js_unit.py -q` | **29 passed** |
| `node --check` | `web/app.js`, `web/static/*.js` | OK |
| `git diff --check` | — | чисто (только CRLF-warnings) |

## Артефакты

- `tools/_ui_round1025_raw.json` (gitignored), `tools/_ui_round1025_e2e.json` (gitignored),
  `tools/_ui_round1025_secrets_ui.json` (gitignored), `tools/_ui_round1025_shots/` (gitignored).
- Отчёты: `plans/reports/round1025_f10_playwright.md`, `_f10_e2e.md`, `_f10_map_monitoring.md`,
  `_f10_heartbeat.md`, `_f10_secrets_ui.md`, `_f10_epic2_gate.md`, `_f10_acceptance.md`.
- Скриншоты: `plans/reports/round1025_f10_shots/` (8 PNG).

## Инварианты

- Δ DDL=0, Δ каталога=0 — подтверждено `git status` (рантайм не тронут).
- CSP/zero-build — новых библиотек нет. R17/R18 — секреты только `{configured,last4}`.

## Не выполнено / PENDING

- Live-гейты владельца (T-3097/T-3059/T-3021/T-2961/T-2917/T-2862/…) — **PENDING**.
- Живая приёмка Telegram WebView (Chromium ≠ WebView) — **PENDING**.
- T-3121…T-3128 (Reviewer/Scanner/merge/archive/deploy/metrics) — **не выполнялись** (вне F10 Step 4).
