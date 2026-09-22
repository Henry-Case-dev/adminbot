# F6 `memory-analytics-reorg-round1025` — review (Step 5, T-2911) @Reviewer

- **Feature-ID:** `memory-analytics-reorg-round1025` (F6, round 10.25)
- **Status (итерация 2):** **Approved** — блокеры iter1 закрыты; остаётся non-blocking техдолг.
- **Base:** тег `pre-round1025-f6` = HEAD `f103992`; рабочее дерево без commit. `APP_VERSION` 2.58.14.
- **Артефакты:** `spec.md` D6 (**AMEND-1**), `adr-1025-19`, `adr-1025-19a-memory-section-52-amend.md`, `evidence.md`, `plans/reports/round1025_f6_scanner_audit.md`.

## Закрытие находок iter1 (независимо подтверждено)
| Находка | Статус | Доказательство |
|---|---|---|
| H1 §52 (5 vs 3 раздела) | **Закрыта (решение @Architect)** | `adr-1025-19a` AMEND-1 вариант A (3 карточки приняты; «Досье/Факты» — существующие поверхности: `openDossier` `app.js:4719`, dossier-modal `index.html:4039`; карта §52 в `spec.md:134-152`). Код = 3 карточки (`app.js:425-446`), соответствует обновлённому spec D6 |
| H2 §27 (поиск + фильтр «статус») | **Закрыта** | `index.html:2025-2043` — `<input type="search" v-model="execFilterQuery">` и `<select v-model="execFilterStatus">`; adapter `filter` расширен `query` (подстрока без регистра по label/stage/module/model/tool). Live-проба: поиск «web_search» 3→1 узел |
| M-F6S-1 (утечка фильтров в агрегат) | **Закрыта** | `setExecMode` → `resetExecFilters()` при смене режима (`app.js:3894-3901`); `execAggregate` применяет только `{module}` (`app.js:2303-2310`). Live-проба: после «День» фильтр пуст, агрегат показывает 2 модуля |
| L-F6S-3 (статус-селект) | **Закрыта** | вместе с H2 (опция «нет данных» присутствует, `execStatusOptions`) |
| L-F6S-4 (модалка/backdrop/Esc) | **Закрыта** | `index.html:4013-4016` — `.exec-detail-backdrop` `@click.self`, `role="dialog" aria-modal="true"`; `escClose` первым закрывает detail (`app.js:4540-4542`). Live-проба: Esc и backdrop закрывают |
| L-F6S-5 (мёртвый memorySubgroup-шов) | **Закрыта** | `openHubCard` больше не читает `card.memorySubgroup`, сбрасывает `memorySubgroup=''` (`app.js:5951-5957`); hub `:key` без `memorySubgroup` (`index.html:277`) |

## Воспроизведённые проверки
| Проверка | Результат |
|---|---|
| `node --check app.js` / `execution_graph.js` | OK |
| JS-тесты (37 файлов) | **37/37 PASS** |
| `py -3 -m pytest -q` | **8334 passed, 1 skipped, 5 failed** — те же 5 env (`ImportError` rich-fallback; `services/**` вне диффа) |
| Playwright F6-проба (поиск/статус/сброс/Esc/backdrop) | **failures: 0**, console/pageerror: 0 |
| Playwright-матрица | **failures: 0** (10 вьюпортов) |
| `git diff --check` | чисто |
| Δ DDL / Δ каталога | **0 / 0** (`services/param_catalog.py`, `web/api/analytics.py` не тронуты) |
| R17/R18 | `current_task.md` не изменён (gitignored); секретов нет; тег/stash на месте |

Маркер-тесты не ослаблены: pytest F6 13→19, adapter-тест расширен query/status, аналитические тесты — поиск/сброс/Esc; routing-тесты атомарно обновлены под AMEND-1.

## Non-blocking (остаточный)
- **L-F6S-2 (R16):** `fromSummary` всегда `priceKnown:true`, агрегатная цена неполна при `price_known=false` — контракт API не выражает; follow-up.
- **Low:** регресс-кейс round1024 «смешанный набор / дубликат `stage1`» не перенесён в новые тесты (не блокер, adapter — 1:1-маппинг).

## Unavailable
- **PENDING OWNER VERIFICATION (T-2917):** живой Telegram WebView + реальный PG-пайплайн `/analytics/*` (Playwright — на стабах).

## Handoff
RESULT: **Approved** @Orchestrator, `plans/features/memory-analytics-reorg-round1025/review.md` — H1/H2/M-F6S-1/L-F6S-3/4/5 закрыты; воспроизведено: JS 37/37, pytest 8334/0/5-env, matrix 0, F6-probe 0, Δ DDL=0, Δ каталога=0. PENDING OWNER: WebView/PG (T-2917).
