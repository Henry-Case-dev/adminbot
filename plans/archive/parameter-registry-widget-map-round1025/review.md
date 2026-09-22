# F8 `parameter-registry-widget-map-round1025` — Review (@Reviewer, T-3015)

- **Feature-ID:** `parameter-registry-widget-map-round1025` (Эпик 1, read-only enabler)
- **Status:** Approved
- **База:** HEAD `a40f244`, `APP_VERSION` 2.58.15, каталог 459/98/96/21/418.
- **Артефакты:** `plans/docs/{param-registry-round1025.tsv,.meta.md,screen-map-round1025.md,widget-map-round1025.md}`, `plans/reports/round1025_f8_{config_diff,results}.md`, `tools/{gen_param_registry_round1025.py,config_snapshot_diff.py}`.

## Checks performed (воспроизведено независимо)

| Проверка | Команда/метод | Наблюдение |
|---|---|---|
| Полнота реестра | импорт `services.param_catalog`, сравнение `pg_key` | REGISTRY 459 == TSV 459; missing=0, extra=0 |
| Структура TSV | разбор файла | 459 строк, 23 колонки, пустых ячеек = 0 |
| Дельта | сверка с `inventory.tsv` | inventory 411, `status=new`=48, `OK`=411; пересечений нет |
| `--check` | `gen_param_registry_round1025.py --check` | exit **0** |
| Искусственное расхождение | подмена TSV на bogus | `run_check()` = **1** (exit≠0) |
| R17 | independent-скан 19 значений секретов по `plans/docs/**` + артефактам + отчётам | утечек 0; 28 secret-строк — маска `{configured,last4}` в current/default |
| hidden | сверка с каталогом | 1 hidden = `limits.factcheck_context_messages`, сохранён |
| Карта экранов | парсинг + сравнение ключей | 459 строк, missing=0, extra=0; `api-only`=25 |
| Карта виджетов | проверка `data_source` по `web/api/*`/`web/app.js` | реальные маршруты (`oversight/dossier_feed`, `oversight/summary`, `access/param_permissions` и др. подтверждены) |
| Diff | `config_snapshot_diff.py --diff before after`, `--selftest` | 8 срезов, изменений 0; selftest OK |
| Инварианты | git diff + freeze-hash | Δ каталога=0, Δ DDL=0, `web/**`/`handlers/**`/`services/**` не тронуты; `git diff --check` чисто |
| Версия | `config.settings.APP_VERSION` | 2.58.15 (без bump) |
| R18 | тег/бэкап/stash | `pre-round1025-f8`→`a40f244`; `var/backups/f8-round1025-20260923-044606`; `.env.bak.round1025-f8`; `stash@{0}` на месте |
| Тесты | `pytest -q` | **8403 passed, 0 failed** (baseline 8374 + 29 новых F8) |
| §117 п.1–4 | сверка 4 артефактов | закрыты 1–4; п.5–12 — вне F8 |

## Requirement/evidence coverage

- FR-01…FR-12 и §117 п.1–4 покрыты артефактами и маркер-тестами; 12 полей §2 присутствуют (`internal_key`=`pg_key`, `display_name`=`title_ru`, `data_type`=`type`, производные — из каталога), не выдуманы.
- Тесты не ослаблены: существующие тесты не менялись, `tests/test_round1025_f8_registry.py` независимо пересчитывает полноту, дельту, R17, `--check`, diff.

## Blocking findings

Нет (Critical/High отсутствуют).

## Non-blocking debt / ограничения

1. **[Medium, non-blocking; owner @DevOps T-2998/T-3000 + F10]** Diff «до/после» построен на детерминированном offline-baseline из каталога; срезы `chats`/`dm`/`permsoc` пусты (0 записей), `global` — каталог-производные. «0 изменений» структурно верно (F8 рантайм не меняет), но §117 п.4 в части живых пользовательских значений доказывается только после снятия живых PG-снимков. Builder это явно раскрыл в `evidence.md`.
2. **[Low]** `current_value` для не-секретов = плейсхолдер `runtime` (детерминизм ADR D2), не фактическое значение — задокументировано в `.meta.md`.
3. **[Low]** Формулировка «`internal_key==REGISTRY`» неточна: `internal_key`=`pg_key`, а `REGISTRY` индексирован по env/internal-ключу; фактически одна строка на запись каталога (459). Тесты трактуют корректно.
4. **[Low]** `--check` покрывает TSV и screen-map побайтно, но для `widget-map` проверяет только маркер, `meta.md` побайтно не сверяется.

## Unavailable checks (PENDING OWNER VERIFICATION)

- Живой PG-снимок «до/после» реальных значений конфигурации (T-2998/T-3000) — ожидает владельца/окружение.
- WebView/UI-рендер карт и виджетов — ожидает владельца.

## Вердикт

**Approved.** Все приёмочные сценарии F8 (spec §7) подтверждены независимо; блокеров нет. Ограничение по живым снапшотам закрывается T-2998/T-3000 и финальным гейтом F10.
