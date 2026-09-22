# F8 `parameter-registry-widget-map-round1025` — Scanner-аудит (Шаг 6, T-3016)

> **Фича:** F8 (Эпик 1, Wave 0, read-only enabler). **ADR:** `adr-1025-21-parameter-registry-and-config-diff.md` (Accepted).
> **Baseline/дерево:** HEAD `a40f244` (== `origin/master`, тег `pre-round1025-f8`), `APP_VERSION` **2.58.15**. Правки **НЕ закоммичены** — аудировано рабочее дерево относительно `a40f244` (focused diff-based).
> **Метод:** только чтение; независимая программная сверка артефактов инструментами @Scanner (не доверял `--check` как единственному источнику). R17/R18 соблюдены.

## Вердикт

**БЛОКЕРОВ НЕТ. К приёмке — ДА.** Critical 0 / High 0 / Medium 0 / Low 3 / Info 4. Открытых секретов, изменений рантайма, Δ DDL/каталога, ослабления маркеров и утечек R17/R18 не найдено.

## Таблица severity

| Severity | Кол-во | Статус релиза |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 0 | — |
| Low | 3 | не блокируют, owned follow-up |
| Info | 4 | наблюдательные |

## Находки (с доказательствами)

### L-F8S-1 — [Low, new, honesty] Пустые срезы выглядят как «проверено — изменений нет»
- **Где:** `plans/reports/round1025_f8_config_diff.md:12–14` (строки `chats`/`dm`/`permsoc` → `unchanged=0`, вердикт `OK (без изменений)`).
- **Доказательство:** `tools/config_snapshot_diff.py::build_offline_snapshot` (стр. 106) оставляет `chats`/`dm`/`permsoc` пустыми: «при отсутствии живых данных — пустые». Классификация по 0 записям даёт `unchanged=0` — «0 изменений» **вакуумно** и не является доказательством сохранности конфигурации чатов.
- **Влияние:** читатель может принять «OK» за подтверждённую неизменность. Живые снимки осознанно отложены на @DevOps (T-2998/T-3000) и раскрыты в `evidence.md:68`.
- **Ремедиация:** в отчёте заменить для пустых срезов вердикт на `н/д (нет живых данных; T-2998/T-3000)`; в `results.md` §5 явно указать, что подтверждены 5 непустых срезов (global/prompts/models/connections/roles), а chats/dm/permsoc — ожидают живого снимка.
- **Статус:** OPEN (следующим @Builder, до F10).

### L-F8S-2 — [Low, new, regression-gate] `config_snapshot_diff.py --diff` не падает при реальных изменениях
- **Где:** `tools/config_snapshot_diff.py:299–302` — при `added/removed/changed > 0` печатается число, но `return 0`.
- **Доказательство:** `main()` возвращает 0 всегда (кроме R17-ветки `return 1` на стр. 291). `gen_param_registry_round1025.py --check` для контраста делает `exit≠0` при расхождении.
- **Влияние:** метод заявлен как переиспользуемый гейт в **F10** (spec §4); позитивный diff не провалит автоматический шаг → риск ложного «зелёного» на финальной приёмке.
- **Ремедиация:** добавить `--fail-on-changes` (exit≠0 при любых added/removed/changed) и использовать его в F10.
- **Статус:** OPEN (follow-up, не блокирует F8 — на F8 реальных изменений нет).

### L-F8S-3 — [Low, new, R17-coverage] R17-скан автоматики шире/уже, чем кажется
- **Где:** `tools/gen_param_registry_round1025.py:505–513` (`run_check` сканирует 4 артефакта: TSV/meta/screen/widget) и `tests/test_round1025_f8_registry.py:156–158` (сканирует `ARTIFACTS` из фикстуры — 5 файлов, включая `config_diff.md`, но **без** `round1025_f8_results.md`).
- **Доказательство:** `f8_baseline.json:3–9` — список из 5 артефактов, `results.md` отсутствует; `--check` не читает `round1025_f8_config_diff.md`.
- **Влияние:** секрет, попавший в `round1025_f8_results.md`, автоматикой не будет пойман. Ручной скан @Scanner (bot-token/`sk-`/hex32/DSN-паттерны по всем 14 артефактам и отчётам) — **чисто**.
- **Ремедиация:** расширить `run_check`/фикстуру на `results.md` и `config_diff.md`.
- **Статус:** OPEN (Low, hardening).

### I-F8S-1 — `tools/` не полностью изолирован от рантайма (pre-existing)
`services/tool_router.py:74`, `services/tool_schemas.py:49`, `handlers/{video_download,youtube}.py` импортируют `tools.video_downloader`/`tools.video_download_phrases` (легаси, вне F8). **F8-инструменты рантаймом не импортируются** — подтверждено grep и маркер-тестом `test_tools_not_imported_by_runtime` (запрещает токены `gen_param_registry_round1025`/`config_snapshot_diff`). Info.

### I-F8S-2 — Мёртвый хелпер
`tools/gen_param_registry_round1025.py:446–448` `scan_for_secret_patterns()` определён, но нигде не вызывается (в CLI не используется) → значения не логируются. Безвредно. Info.

### I-F8S-3 — Неточная формулировка контракта полноты в spec
`spec.md:47` — «множество `internal_key` реестра == ключи `REGISTRY`». Фактически `pc.REGISTRY` индексирован по env-именам (UPPER), а `internal_key = ParamSpec.pg_key` (lower). **Проверено:** `{s.pg_key}` = 459, биективен (дублей нет), TSV-набор == pg_key-набор. Артефакты корректны; текст spec стоит уточнить на `{s.pg_key}`. Info.

### I-F8S-4 — Живой diff отложен
Живые PG-снимки «до/после» не сняты в этой сессии (T-2998/T-3000 @DevOps); diff построен на детерминированном offline-baseline. Раскрыто в `evidence.md:68` и шапке отчёта. Info.

## Инварианты (независимая проверка @Scanner)

| Инвариант | Результат |
|---|---|
| Реестр: строк / колонок / пустых ячеек | **459 / 23 / 0** ✅ |
| `set(internal_key)` == `{pg_key}` каталога | **равны, 459, биекция** ✅ |
| Счётчики каталога | **459 / 98 / 96 / 21** ✅ |
| Дельта 411→459 | **48**, набор `status=new` == `pg_keys − inventory(411)`, список в `.meta.md` совпадает полностью ✅ |
| Карта экранов | **459** ключей ⊇ каталог, «без места» = **0**, `registry-only` = 0 ✅ |
| Карта виджетов | маркер + обязательные виджеты, `api-only`-секция (`≠ сохранено`) ✅ |
| Секреты (R17) | **28** записей, все `current_value`/`default_value` = `{configured,last4}` ✅; открытых значений нет (ручной скан всех артефактов) |
| `ui_visibility` | visible **433** / hidden **1** (`limits.factcheck_context_messages`) / api-only **25** ✅ |
| Генератор `--check` | exit **0**; при искусственном расхождении exit≠0 (тесты) ✅ |
| `config_snapshot_diff --selftest` | OK ✅ |
| Маркер-тесты F8 | **29 passed** ✅ |
| Δ DDL / Δ каталога | `git diff a40f244 -- migrations alembic services/pg_db.py services/param_catalog.py` = **0 файлов** ✅ |
| Рантайм/эндпоинты | нет изменений `services/**`,`web/**`,`handlers/**`,`config/settings.py`,`web/api/routes.py`; 31 роут без изменений ✅ |
| `plans/docs/canon/` | не затронут ✅ |
| `tools/*` не импортируются рантаймом | ✅ (F8-токены отсутствуют в `services/web/handlers`) |
| CSP/zero-build | правок `web/**` нет ✅ |
| `APP_VERSION` | **2.58.15** без бампа ✅ |
| deploy | **NOT_APPLICABLE** — обоснованно ✅ |
| R18 | тег `pre-round1025-f8`@`a40f244`; бэкапы `f8-round1025-20260923-044606` + `f8-round1025-config`; `.env.bak.round1025-f8`; `stash@{0}` на месте; `var/` не в индексе ✅ |
| R17/R18 `current_task.md` | не изменён (gitignored, `.gitignore:70`) ✅ |
| Гигиена / `git diff --check` | `.env`/zip/скриншотов/`tools/_ui_*`/`var/backups` в индексе нет; `check` exit 0 ✅ |
| Полный pytest (заявлено @Builder) | **8403 / 0** (baseline 8374 + 29 F8); выборочно подтверждён F8-набор ✅ |

## Изменённые файлы (аудит относительно `a40f244`)

**Tracked (только планы, не код):** `plans/MEMORY.md`, `plans/backlog.md`, `plans/workflow_state.md`, `plans/features/parameter-registry-widget-map-round1025/tasks.md` (чекбоксы/нарратив).
**Untracked (additive):** `plans/docs/{param-registry-round1025.tsv,.meta.md,screen-map-round1025.md,widget-map-round1025.md}`, `plans/features/.../{spec.md,evidence.md,adr-1025-21-...}`, `plans/reports/round1025_f8_{config_diff,results}.md`, `tests/test_round1025_f8_registry.py`, `tests/fixtures/round1025/f8_baseline.json`, `tools/{gen_param_registry_round1025,config_snapshot_diff}.py`.
**Вне git:** `var/backups/f8-round1025-config/`, `.env.bak.round1025-f8`.

## Handoff

**RESULT: SCANNED @Orchestrator** — F8 `parameter-registry-widget-map-round1025`, T-3016. Critical 0 / High 0 / Medium 0 / Low 3 / Info 4 → **к приёмке ДА**, блокеров нет. Low (L-F8S-1 honesty-аннотация пустых срезов; L-F8S-2 `--fail-on-changes` для F10-гейта; L-F8S-3 расширить R17-скан) — owned follow-up. Отчёты обновлены: `plans/reports/round1025_f8_scanner_audit.md`, `full_audit_results.md`, `audit_backlog.md`, `global_map.md`. Deploy — NOT_APPLICABLE.
