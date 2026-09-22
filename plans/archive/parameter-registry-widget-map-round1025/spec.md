# F8 — `parameter-registry-widget-map-round1025` — Spec (read-only enabler)

> **Шаг 2 @Architect.** Источники ТЗ: `plans/current_task.md` §1, §2, §3, §117 п.1–4. Задачи: `tasks.md` (T-2964…T-3023). Решения: `adr-1025-21-parameter-registry-and-config-diff.md` (**Accepted**).
> **Baseline:** HEAD `a40f244`, `APP_VERSION` 2.58.15, каталог **459/98/96/21/418**, pytest **8374/0**, JS **38/38**.
> **Тип:** аудит + сохранность данных. F8 **не меняет** рантайм, каталог, UI, БД. Не дублирует аудиты F4–F7/10.14/prod — они **источник**; реестр их агрегирует ссылками.
> **Инварианты:** **Δ DDL = 0**, **Δ каталога = 0**, CSP/zero-build, read-only, R17 (секреты не выводить), R18.

## 1. Scope

**Входит:** полный реестр параметров (459) с 12 полями §2; карта «Старый экран → Параметр → Новый экран → API»; карта виджетов; безопасный снапшот+diff «до/после» по 8 срезам §3; read-only инструменты в `tools/`; отчёты и результаты §117 п.1–4.

**Исключено (явно):** перенос UI, изменение `services/param_catalog.py`, изменения `web/**`/`handlers/**`/`services/**`, новые рантайм-эндпоинты, миграции/DDL, правки §52–§66/F0–F7, §117 п.5–12 (F9/F10/F11), повторная инвентаризация F4–F7/10.14/prod (только ссылки).

## 2. Трассируемость (REQ → §ТЗ → артефакт)

| REQ | §ТЗ | Артефакт |
|---|---|---|
| FR-01 источники | §2.1–§2.15 | разделы карт (ссылки на F4–F7/prod) |
| FR-02 реестр 12 полей | §2 | `plans/docs/param-registry-round1025.tsv` |
| FR-03 секреты без значения | §2, R17 | маскирование во всех артефактах |
| FR-04 карта экранов | §2 | `plans/docs/screen-map-round1025.md` |
| FR-05 нет параметра без места | §1/§2 | инвариант полноты карты |
| FR-06 неизвестный → в реестр | §1 | секция `registry-only` |
| FR-07 карта виджетов | §2 | `plans/docs/widget-map-round1025.md` |
| FR-08 API-но-нет-UI ≠ сохранено | §2 | флаг `ui_visibility` |
| FR-09 бэкап | §3 | переиспользование `manage.py`/`var/backups/` |
| FR-10 diff по 8 срезам | §3 | `plans/reports/round1025_f8_config_diff.md` |
| FR-11 нет скрытых миграций | §3 | Δ DDL=0 подтверждение |
| FR-12 §117 п.1–4 | §117 | `plans/reports/round1025_f8_results.md` |

## 3. Артефакты и контракты (D1/D2/D3)

### 3.1. Storage — committed-артефакты (D1)
Канонические артефакты — **файлы в репозитории**, не эндпоинт:
- `plans/docs/param-registry-round1025.tsv` — реестр 459 (машиночитаемый, TSV);
- `plans/docs/param-registry-round1025.meta.md` — провенанс (HEAD/`APP_VERSION`/счётчики каталога/команда генерации), **вне** TSV (чтобы TSV был байт-идемпотентен);
- `plans/docs/screen-map-round1025.md`, `plans/docs/widget-map-round1025.md`.
Эндпоинт **не создаётся** (новый рантайм-код/риск/CSP → против «не создавать ненужную инфраструктуру», §117 требует артефакты, а не live-API). `plans/docs/canon/` **не используется** (это эталоны промптов «НЕ редактировать»). Файлы — короткие навигационные, не логи (граница рост-риска: Low).

### 3.2. Реестр — 12 полей §2 (можно >12, если аддитивно)
`internal_key | display_name | description | data_type | current_value | default_value | scope | inheritance | read_api | write_api | validation | permissions`
Плюс производные: `category | group | per_chat | secret | widget | storage | runtime_consumer | read_fn | status`.
- `internal_key` = `ParamSpec.pg_key`; `display_name` = `title_ru`; `data_type` = `ParamSpec.type`; `group` = `ParamSpec.group`; `description` = `ParamSpec.description`.
- `current_value`/`default_value`: для `secret=True` и категории `keys` — **только** `{configured,last4}` (формат `_mask_secret`), значение никогда (R17); остальные — из read-API/каталога, без утечек.
- `read_api`/`write_api`: реальные маршруты блока A (`/api/config` GET/POST, `/api/config/params-meta`, `/keys/own` GET/PUT/DELETE, `/keys/status`, `/api/config/chat/{key}` DELETE, `/api/debug/config`) либо явное «нет API».
- `scope`/`inheritance`: global / chat / ЛС / PERMsoc; приоритеты global→chat override.
- **Контракт полноты:** множество `internal_key` реестра == ключи `REGISTRY` == **459**. Пустых ячеек нет; отсутствующие документированы.

### 3.3. Генератор (D2) — `tools/gen_param_registry_round1025.py`
Read-only, вне рантайма, только stdlib + импорт `services.param_catalog`; **без БД, сети, секретов, записи вне `plans/docs/`**.
- Вход: `param_catalog.REGISTRY/GROUPS/_TAB_BY_GROUP/TAB_RULES` + `plans/archive/settings-persistence-audit-round1014/inventory.tsv` (сверка/дельта).
- Выход: детерминированный TSV (сортировка по `pg_key`), **без timestamp** → байт-идемпотентность.
- `--check`: выход не совпал с committed-артефактом → exit≠0 (защита от устаревания; используется маркер-тестом T-3011).
- **Дельта 411→459 = 48**: скрипт перечисляет ключи каталога, отсутствующие в `inventory.tsv`, и явно кладёт их в реестр (`status=new`). При будущих фичах реестр обновляется повторным запуском `--check`/генерацией (не «застывает»).

### 3.4. Карта экранов (D3) — `screen-map-round1025.md`
Строка: `old_screen → param_key → new_screen (IA §4: Статус/Справка/Модули/ИИ/Память/Доступы/PERMsoc) → read_api → write_api → ui_visibility`.
- Старые экраны/формы/виджеты берутся из блока A (маршруты/компоненты), не переизобретаются.
- **Правило «ни один параметр не остался без места»:** `set(map.param_key) ⊇ REGISTRY(459)`; контроль-сверка с реестром → **0 «без места»**. Неизвестный (нет в каталоге, но есть в API/БД) → секция `registry-only` реестра (`status=unknown`).
- **`ui_visibility ∈ {visible, hidden, api-only}`:** `hidden` — из `ParamSpec.hidden`; `api-only` — есть в API/каталоге, но нет в UI → **≠ сохранено** (REQ-F8-08): фиксируется отдельным списком с сохранностью ключа.

### 3.5. Карта виджетов (D3) — `widget-map-round1025.md`
Строка: `old_widget → data_source (endpoint/service) → new_location → preserved_actions → ui_visibility`.
Покрыть виджеты §11/§12–§21 (сон, граф, мониторинг интеллекта, лента досье, логи, превью карты и т.д.). Для каждого — откуда данные и где отображаются; api-only виджеты помечены.

## 4. Бэкап + diff по 8 срезам (D4)

- **Механизм не строим заново.** Точка отката: git-тег `pre-round1025-f8` на `a40f244` + `var/backups/f8-round1025-<ts>/` + `.env.bak.round1025-f8`. Переиспользовать `flags.memory_backup_enabled`/`limits.memory_backup_hour`, `manage.py --backup-dir`/`db_backup`. R18: ничего не удалять.
- **Форма снимка:** JSON-на-b2b срез, ключ — стабильный идентификатор (**`pg_key`/`chat_id`**, не display-name). 8 срезов §3: глобальная, чаты, ЛС, PERMsoc, промпты, модели, подключения, роли/разрешения.
- **R17-safe:** секреты (`secret=True`, `category==keys`) → только `{configured,last4}`; сырые значения не пишутся ни в снимок, ни в отчёт. Снимки — в `var/backups/` (вне git); в коммит идёт только **отчёт-статусы**.
- **Инструмент diff** `tools/config_snapshot_diff.py` (read-only, вне рантайма): классификация `added/removed/changed/unchanged` **по ключам**; помечает только реальные изменения. **Ожидание F8 = 0 незапланированных изменений** (F8 ничего не меняет). Метод переиспользуется в **F10** (финальная приёмка Эпика 1).
- Отчёт: `plans/reports/round1025_f8_config_diff.md` (статусы, без сырых секретов).

## 5. Инварианты и тесты (D6)

| Инвариант | Проверка |
|---|---|
| Δ DDL = 0 | diff миграций/alembic/schema пуст; SQLite `user_version=12` |
| Δ каталога = 0 | `param_catalog.py` не в диффе; счётчики 459/98/96/21/418 |
| CSP/zero-build | нет правок `web/**`, новых внешних ресурсов |
| read-only | нет новых рантайм-эндпоинтов/импортов `/tools` из `services`/`web`/`handlers` |
| R17 | ни одного открытого секрета в артефактах (`{configured,last4}`) |
| Без скрытых миграций | снапшот «до» == «после» по 8 срезам |

Тесты (T-3011/T-3012): полнота 459/459; дельта 411→459=48 перечислена; отсутствие открытых секретов; идемпотентность генератора (`--check`); diff без реальных изменений; неизменность множества роутов и `APP_VERSION`. Плюс полный pytest (baseline 8374/0) + JS 38/38.
**§117 п.1–4** = 4 артефакта: карта экранов, реестр, карта виджетов, подтверждение сохранности конфигурации → `plans/reports/round1025_f8_results.md`.

## 6. Deploy / версия (D5/D7)

- **Вердикт deploy: NOT_APPLICABLE.** F8 = аудит/доки + read-only `tools/`-скрипты (не импортируются рантаймом, не отдаются web). Нет изменений `services/**`/`web/**`/`handlers/**`, БД, каталога, ассетов → рестарт/миграция/cache-bust не нужны. Даже если прод сделает `git pull`, поведение не меняется. → **T-3019 = NOT_APPLICABLE** с этим обоснованием в `deployment.md`.
- **`APP_VERSION` не бампается:** бамп нужен только для инвалидации отдаваемых ассетов (cache-bust), а F8 ассеты не меняет. Остаётся **2.58.15**.
- **Совместимость:** §52–§66/F0–F7 не трогаются; артефакты аддитивны и стабильны для F9 (читает реестр/секреты-UI), F10 (метод snapshot+diff), F11 (карта виджетов/токенов); ADR-1025-21 Accepted.

## 7. Приёмка (acceptance scenarios)

1. Реестр покрывает 459/459; 48 новых ключей явно помечены.
2. Карта экранов: 0 параметров «без нового места»; api-only помечены.
3. Карта виджетов: 0 потерянных виджетов; api-only отдельно.
4. В артефактах/отчётах нет открытых секретов.
5. `tools/gen_param_registry_round1025.py --check` идемпотентен.
6. Diff по 8 срезам: 0 незапланированных изменений; Δ DDL=0; Δ каталога=0.
7. §117 п.1–4 закрыты; п.5–12 — вне F8.

## 8. Риски

- Потеря параметра при переносе (**Critical**) → контракт полноты реестр↔карта.
- Утечка секрета в артефакт (**Critical, R17**) → маскирование + Scanner-проверка (T-3006).
- Скрытая миграция/подмена дефолта (**High**) → snapshot+diff + Δ DDL=0.
- Устаревание реестра (**Low**) → `--check`-маркер в тестах.
- Разрастание `plans/docs/` (**Low**) → короткие навигационные файлы, не логи.
