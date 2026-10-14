# Scanner-аудит F10 — `epic1-verification-round1025` (Step 6, T-3122)

> **Дата:** 23.09.2026. **Аудитор:** @Scanner (независимо, focused diff-based).
> **Baseline:** HEAD `57b325c` (== `origin/master`; тег `pre-round1025-f10` → `57b325c`).
> **Правки НЕ закоммичены** — аудит рабочего дерева относительно HEAD (5 M + 18 ??).
> **Тип фичи:** verification-гейт (код не пишет; аддитивные `tools/**`).
> Вход: `spec.md`, `adr-1025-24`, `evidence.md`, `deployment.md`, `tasks.md`,
> `round1025_f10_{playwright,e2e,map_monitoring,heartbeat,secrets_ui,epic2_gate,acceptance}.md`.

## Вердикт

**Приёмка Эпика 1 (авто) готова — `SCANNED`, блокеров нет.**
Critical 0 / High 0 / Medium 0 / Low 2 / Info 4. Возвратов @Builder нет.
Эпик 1 **не объявляется завершённым/принятым владельцем** — live-гейт Telegram WebView
**PENDING** (честно помечен в отчётности; workflow не блокирует независимые задачи, Эпик 2
разрешён к старту по D4, но существующий паблиш-пайплайн менять нельзя до live-приёмки).

## 1. Read-only инвариант (проверено программно)

- Изменённые (tracked): `plans/MEMORY.md`, `plans/backlog.md`,
  `plans/features/epic1-verification-round1025/tasks.md`, `plans/workflow_state.md`,
  `tools/ui_round1025_matrix.py`.
- Новые (untracked): `plans/features/epic1-verification-round1025/{adr-1025-24,deployment,evidence,spec}.md`,
  7 отчётов `plans/reports/round1025_f10_*.md`, `plans/reports/round1025_f10_shots/*.png` (8),
  `tools/.gitignore`, `tools/ui_round1025_e2e.py`, `tools/ui_round1025_secrets_ui.py`.
- **Рантайм не тронут:** `git diff --name-only HEAD -- services web handlers config migrations param_catalog.py web/api` → **пусто**;
  untracked в этих путях — **нет**. Все изменения — `tools/**` + `plans/**` (тесты `tests/**` в F10 не менялись).
- `deploy_commands.txt` / `plans/current_task.md` — в индексе/диффе **нет** (`current_task.md` gitignored, не изменён).

## 2. Честность приёмки (ложное «зелёное»?)

- **§72 «ровно 1 write» — поведенческий, не тавтологичный.** `ui_round1025_e2e.py:206-236` считает
  реальные `POST /api/config`; утверждение `writes != 1` краснеет и при 0, и при >1. Три
  представления (быстрая панель/карточка/store) сверяются между собой и с серверным значением после
  reload (`:265-269`, `:289-291`). Артефакт: `writes=1, quick=card=store=false`.
- **§73 «stale не применяется» — ловит целевой дефект.** Поздний ответ A (`route`-defer) не должен
  менять B; при регрессии «ответ применяется к активному scope» `b_after != b_before` → FAIL
  (`:348-350`). Артефакт: `deferred_captured=true, b_before=b_during=b_after=false, a_server_value=true`.
  Остаточный риск — при НЕотправленной мутации проверка вакуумна (нет assert на `deferred_captured`) →
  **L-F10S-1** (не блокер: §72 отдельно ловит 0-write; в текущем прогоне captured=true).
- **§78 секреты UI — поведенческий.** `ui_round1025_secrets_ui.py:147-183` вызывает реальный
  `saveKeyItem`: маска/композит → **0 write**, реальный ключ → **ровно 1 write**, payload без маски;
  поле ввода секрета пусто, маска — display-бейдж.
- **§79-стоп-гейт — не заглушка, но тонкий.** `round1025_f10_epic2_gate.md`: реальный прогон
  подмножества пайплайнов Саммари/image (**300 passed**), плюс инвариант «рантайм не изменён»
  (`git diff` пуст). Для `sendRichMessage` evidence — grep-присутствие (I-F10S-1).
- **Проверка «мысленно сломать»:** §72/§73/§78 при поломке соответствующей логики краснеют;
  «§79-стоп-гейт» не «дорисовывает» зелёное (алгоритмы не менялись — доказано пустым рантайм-диффом).

## 3. §117 п.1–12 — полнота (пропусков нет)

| # | Артефакт | Существует |
|---|---|---|
| 1 | `plans/docs/screen-map-round1025.md` (F8) | ✔ |
| 2 | `plans/docs/param-registry-round1025.tsv` (459) | ✔ |
| 3 | `plans/docs/widget-map-round1025.md` | ✔ |
| 4 | `round1025_f8_results.md`, `round1025_f8_config_diff.md`, `tools/config_snapshot_diff.py` | ✔ |
| 5 | `round1025_f9_secrets_checklist.md` (28=20+8) + `round1025_f10_secrets_ui.md` | ✔ |
| 6 | `round1025_f10_e2e.md` (§72/§73) | ✔ |
| 7 | `plans/reports/round1025_f10_shots/` (8 PNG) | ✔ |
| 8 | `round1025_f2_report.md`, `round1025_f11_ui_report.md` | ✔ |
| 9 | `round1025_f10_heartbeat.md` | ✔ |
| 10 | `round1025_f10_map_monitoring.md` (F6) | ✔ |
| 11 | `round1025_f10_playwright.md` (10+низкое × 5, `failures: 0`) | ✔ |
| 12 | annotated-тег `pre-round1025-f10` → `57b325c` (проверено `git rev-parse`) | ✔ |

Все 12 пунктов закрыты ссылками; пропущенных нет.

## 4. Инварианты

- **Δ DDL=0** — рантайм/миграции/alembic не тронуты (см. §1).
- **Δ каталога=0** — `services/param_catalog.py` не тронут; независимый импорт:
  `REGISTRY=459`, `GROUPS=98`, `_TAB_BY_GROUP=96`, `TAB_RULES=TAB_NAV=CONFIG_TAB_TITLES=21`.
- **CSP/zero-build** — новых библиотек нет (stdlib + уже установленный Playwright).
- **R17** — regex-скан F10-артефактов на `sk-*`/bot-token/PEM → **0 совпадений**; секретов наружу нет
  (синтетический probe-литерал — I-F10S-3).
- **R18** — annotated-тег `pre-round1025-f10` (2692944 → commit `57b325c`), запушен (`refs/tags/pre-round1025-f10`
  на origin); бэкап `var/backups/f10-round1025-20260923-091131/`; `.env.bak.round1025-f10`; `stash@{0}` цел.
- **`APP_VERSION` = 2.58.17** — bump не делался (соответствует deploy **NOT_APPLICABLE**, ADR-1025-24 D1).
- **Маркер-тесты не ослаблены** — `tests/**` в F10 не менялись (`git status -- tests` пуст).

## 5. Гигиена

- `git diff --check` → **exit 0** (только CRLF-warnings).
- Скриншоты/сырые артефакты вне индекса: `tools/_ui_round1025_shots/`, `_ui_round1025_raw.json`
  (root `.gitignore:101-102`), `_ui_round1025_e2e.json`/`_ui_round1025_secrets_ui.json` (`tools/.gitignore`).
- `.env`/`.zip`/`tools/_ui_*`/`var/backups` в индексе **отсутствуют** (`git ls-files` пуст по паттернам).

## 6. Независимое воспроизведение

| Команда | Результат @Scanner |
|---|---|
| `node --check web/app.js` | OK |
| `node tests/js/*.js` | **42/42 OK** |
| `py -3 -m pytest -q` (system, aiogram 3.29.1) | **8457 passed / 5 failed / 1 skipped** (5 — env pre-existing `rich`/`InputRichMessageMedia`, вне диффа F10) |
| `.venv\Scripts\python.exe -m pytest -q` (aiogram 3.31.0) | **8463 passed** (совпадает с приёмочным отчётом) |
| `git diff --check` | exit 0 |

## 7. Находки

| ID | Sev | Статус | Локация | Суть |
|---|---|---|---|---|
| L-F10S-1 | Low | OPEN (follow-up) | `tools/ui_round1025_e2e.py:320,346-350` | §73 не assert'ит `deferred_captured`/положительный эффект A → при неотправленной мутации проверка вакуумна (текущий прогон валиден: `deferred_captured=true`). Fix: assert `deferred_captured is True` + `a_server_value` == цель. |
| L-F10S-2 | Low | OPEN (follow-up) | `tools/ui_round1025_matrix.py:1451-1481,2610-2690`; `round1025_f10_playwright.md:36-37` | Low-TG окно `1280×400`: `.bottom-nav`/`minTouch` на desktop-ширине отсутствуют → клаузы «нижние панели в stableHeight / touch ≥44» неактивны; фактическое покрытие low-TG = h-scroll + bounds sidebar. Формулировка отчёта шире факта. |
| I-F10S-1 | Info | OPEN | `round1025_f10_epic2_gate.md:29-32` | Evidence `sendRichMessage` — grep-присутствие; поведенческий тест (`tests/test_outgoing_guard_round1022.py`, проходит в `.venv`) в 300-test subset не включён. Не блокер (рантайм не менялся). |
| I-F10S-2 | Info | OPEN | `round1025_f10_acceptance.md:142`, `evidence.md:48`, `round1025_f10_map_monitoring.md:22` | «pytest 8463 passed» воспроизводится только в `.venv` (aiogram 3.31.0); system `py -3` → 8457/5env/1. Рекомендация: указывать интерпретатор рядом с числом. |
| I-F10S-3 | Info | OPEN | `tools/ui_round1025_secrets_ui.py:35` | Синтетический `NEW_KEY = "sk-ui-round1025-f10-probe"` — не реальный секрет, но может триггерить секрет-сканеры. |
| I-F10S-4 | Info | OPEN | `round1025_f10_epic2_gate.md:9`, `evidence.md:31` | Формулировка «изменены только `tools/**`, `plans/**`, `tests/**`» — фактически `tests/**` не менялись (nit). |

Блокирующих (Critical/High/requirement-blocking Medium) находок нет.

## 8. Handoff

`RESULT: SCANNED @Orchestrator` — приёмка Эпика 1 (авто) готова; live-гейт Telegram WebView
**PENDING OWNER VERIFICATION**; EPIC 1 не объявляется завершённым. Артефакты: этот отчёт,
`full_audit_results.md`, `global_map.md`, `audit_backlog.md`.
