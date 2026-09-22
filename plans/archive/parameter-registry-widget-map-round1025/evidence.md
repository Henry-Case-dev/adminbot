# F8 `parameter-registry-widget-map-round1025` — Evidence (@Builder, Шаг 4)

- **Фича:** F8 (Эпик 1, read-only enabler). **ADR:** `adr-1025-21-parameter-registry-and-config-diff.md` (Accepted).
- **Baseline:** HEAD `a40f244`, `APP_VERSION` 2.58.15, каталог **459/98/96/21/418**, pytest baseline **8374/0**, JS **38/38**.
- **Тип изменений:** additive (артефакты + read-only инструменты + тесты). Рантайм/каталог/БД/UI не менялись.

## Что реализовано (блоки A–H)

| Блок | Задачи | Результат |
|---|---|---|
| A — аудит §2 (15 источников) | T-2968…T-2982 | Таблица 15 источников → `plans/reports/round1025_f8_results.md` §2 (ссылки на F4–F7/10.14/prod, без дублирования). |
| B — реестр 12 полей | T-2983…T-2987 | `plans/docs/param-registry-round1025.tsv` (459 строк, 23 колонки, 0 пустых) + генератор + `meta.md`. |
| C — карта экранов | T-2990…T-2992 | `plans/docs/screen-map-round1025.md` (459 строк; «без места» = 0; `registry-only` = 0). |
| D — карта виджетов | T-2994, T-2995 | `plans/docs/widget-map-round1025.md` (Статус/Аналитика/Память/ИИ/Доступы; `api-only` выделен). |
| E — бэкап+diff 8 срезов | T-2999, T-3001 | `tools/config_snapshot_diff.py` + `plans/reports/round1025_f8_config_diff.md` (0 изменений). |
| F — hidden/secret-контроль | T-3004, T-3005 | Реестр: поля `secret`/`hidden`/`ui_visibility` (28 секретов, 1 hidden, 25 api-only). |
| G — результаты §117 п.1–4 | T-3008 | `plans/reports/round1025_f8_results.md` (4 артефакта). |
| H — регресс/инварианты/маркеры | T-3011, T-3012 | `tests/test_round1025_f8_registry.py` (29 тестов) + freeze-фикстура. |

## Новые/изменённые файлы

**Новые (additive):**
- `tools/gen_param_registry_round1025.py` — read-only генератор (stdlib + `param_catalog`); `--check` → exit≠0 при расхождении.
- `tools/config_snapshot_diff.py` — read-only snapshot-diff по 8 срезам (переиспользуемый в F10).
- `plans/docs/param-registry-round1025.tsv` — реестр 459 (байт-идемпотентный, без timestamp).
- `plans/docs/param-registry-round1025.meta.md` — провенанс (HEAD/APP_VERSION/счётчики/дельта 48).
- `plans/docs/screen-map-round1025.md` — карта экранов.
- `plans/docs/widget-map-round1025.md` — карта виджетов.
- `plans/reports/round1025_f8_config_diff.md` — diff-отчёт (8 срезов).
- `plans/reports/round1025_f8_results.md` — §117 п.1–4.
- `tests/test_round1025_f8_registry.py` — маркер-тесты.
- `tests/fixtures/round1025/f8_baseline.json` — freeze-hashes/routes/счётчики.
- `var/backups/f8-round1025-config/{before,after}/` — offline-снимки 8 срезов (вне git, `var/` в `.gitignore`).

**Изменённые:** `plans/features/parameter-registry-widget-map-round1025/tasks.md` (чекбоксы @Builder).

**НЕ изменялись (инварианты):** `services/param_catalog.py`, `services/pg_db.py`, `web/api/routes.py`, `web/**`, `handlers/**`, `services/**`, `plans/current_task.md`.

## Прогоны и факты

| Проверка | Команда | Результат |
|---|---|---|
| Генератор (идемпотентность) | `python tools/gen_param_registry_round1025.py --check` | exit **0**; реестр 459 == REGISTRY, карта полна, R17-чисто |
| Искусственное расхождение | тесты `test_check_detects_tsv_mismatch` / `..._screen_mismatch` | run_check() **≠ 0** ✅ |
| Полный pytest | `python -m pytest -q` | **8403 passed**, 0 failed (baseline 8374 + 29 новых) |
| Тесты F8 | `python -m pytest tests/test_round1025_f8_registry.py -q` | **29 passed** |
| JS (node) | в составе pytest (`tests/js/*`) | зелёные (JS-файлы F8 не менял) |
| Snapshot-diff | `config_snapshot_diff.py --diff before after` | **0 незапланированных изменений**; 8 срезов |
| Selftest diff | `config_snapshot_diff.py --selftest` | OK (классификатор + R17-маска) |
| `git diff --check` | — | чисто (без whitespace-ошибок) |
| Δ DDL | `services/pg_db.py` freeze-hash | не менялся ✅ |
| Δ каталога | `services/param_catalog.py` freeze-hash + счётчики 459/98/96/21/418 | не менялся ✅ |
| Роуты | `web/api/routes.py` freeze-hash + freeze-множество 31 маршрута | не менялись ✅ |
| `APP_VERSION` | — | **2.58.15** (без бампа) |

## Приёмочные сценарии (spec §7)

1. Реестр 459/459; 48 новых ключей `status=new` (перечислены в `.meta.md`). ✅
2. Карта экранов: 0 «без места»; `api-only` (25) помечены. ✅
3. Карта виджетов: 0 потерянных; `api-only` отдельно. ✅
4. Отсутствие открытых секретов в артефактах (`scan_for_open_secrets` = []; 19 кандидатов из Settings/.env/env сверено). ✅
5. `--check` идемпотентен (+ детект искусственного расхождения). ✅
6. Diff по 8 срезам: 0 изменений; Δ DDL=0; Δ каталога=0. ✅
7. §117 п.1–4 закрыты; п.5–12 — вне F8. ✅

## Не выполнено / ограничения (для Reviewer/Scanner)

- **Живой PG-снимок недоступен** в песочнице сборки (PostgreSQL не отвечает): diff-отчёт построен на детерминированном offline-baseline из каталога; снятие живых снимков «до/после» существующим контуром — задачи @DevOps **T-2998/T-3000**, метод тот же (`--diff`). Поскольку F8 не меняет рантайм/БД, ожидаемый результат = 0 изменений.
- **Deploy:** NOT_APPLICABLE (D5) — оформление `deployment.md` на T-3019 @DevOps.
- **Независимая проверка** (Reviewer T-2988/2993/2996/3009/3015, Scanner T-2997/3002/3006/3014/3016) — не выполнена этим шагом.
- JS `node --check` не требовался: JS-файлы не менялись.

## Как воспроизвести

```
python tools/gen_param_registry_round1025.py          # emit артефактов
python tools/gen_param_registry_round1025.py --check  # маркер устаревания
python tools/config_snapshot_diff.py --selftest
python tools/config_snapshot_diff.py --emit-baseline var/backups/f8-round1025-config/before
python tools/config_snapshot_diff.py --emit-baseline var/backups/f8-round1025-config/after
python tools/config_snapshot_diff.py --diff var/backups/f8-round1025-config/before var/backups/f8-round1025-config/after --out plans/reports/round1025_f8_config_diff.md
python -m pytest tests/test_round1025_f8_registry.py -q
```
