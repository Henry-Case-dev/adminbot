# deployment.md — F8 `parameter-registry-widget-map-round1025`

> **Статус:** **`NOT_APPLICABLE`** (Шаг 9 / T-3019 [@DevOps]; обоснование @Architect — ADR-1025-21 D5, подтверждено Merge §67 и @Scanner).
> **Причина:** F8 — **read-only enabler**: аудит + артефакты (`plans/docs/**`) + read-only инструменты (`tools/**`) + тесты. **Изменений рантайма, БД, ассетов и каталога параметров нет** → деплой не применим.

## Вердикт и предусловия

| Поле | Значение |
|---|---|
| Вердикт | **NOT_APPLICABLE** (деплой не выполняется, рестарт/cache-bust не требуются) |
| @Reviewer | **Approved** (`review.md`, T-3015) |
| @Scanner | **Critical 0 / High 0 / Medium 0** / Low 3 / Info 4 → «к приёмке ДА» (`plans/reports/round1025_f8_scanner_audit.md`, T-3016) |
| Merge | `plans/ARCHITECTURE.md` **§67** (@Architect, T-3017) |
| Архивация | `plans/features/parameter-registry-widget-map-round1025/` → `plans/archive/parameter-registry-widget-map-round1025/` (Шаг 8 @PM, T-3018) |
| Baseline | HEAD `a40f244` (тег `pre-round1025-f8`), `APP_VERSION` **2.58.15** |

## Обоснование NOT_APPLICABLE (почему деплой не нужен)

| Срез | Δ | Доказательство |
|---|---|---|
| Рантайм `services/**` | **0** | `git diff a40f244 -- services/` = 0 файлов (в т.ч. `services/param_catalog.py`, `services/pg_db.py`) |
| Web `web/**` (+ CSP/zero-build) | **0** | правок `web/**` нет; CSP `script-src 'self'` не менялся |
| Handlers `handlers/**` | **0** | правок нет |
| Схема БД | **Δ DDL = 0** | `migrations/`/`alembic/`/`services/pg_db.py` не тронуты; миграции не запускались |
| Каталог параметров | **Δ каталога = 0** | 459/98/96/21/418 без изменений; `param_catalog.py` не менялся |
| Ассеты/версия | **0** | `APP_VERSION` **2.58.15 без bump**; ассеты не менялись → cache-bust не требуется |
| Роуты/эндпоинты | **0** | `web/api/routes.py` не менялся; 31 роут без изменений |
| Инструменты `tools/*` | вне рантайма | `tools/{gen_param_registry_round1025,config_snapshot_diff}.py` рантаймом не импортируются (маркер-тест `test_tools_not_imported_by_runtime`) |

**Вывод:** нет кода/данных/ассетов, влияющих на прод, → `systemctl restart`, `git pull`, cache-bust `?v=` и миграции **не выполняются**. «Поставка» F8 — сами артефакты в репозитории (реестр/карты/diff) и прочитанные из них выводы.

## Что НЕ выполнялось (осознанно)

- Нет `git push`/`git pull` на прод в рамках F8 (изменений кода нет).
- Нет `systemctl restart admin_bot`, нет bump `APP_VERSION`, нет обновления `?v=`.
- Нет миграций/DDL, нет изменений в `plans/current_task.md` (R17/R18).

## Схема данных и инварианты

- **Δ DDL = 0**, **Δ каталога = 0** (459/98/96/21/418); CSP/zero-build сохранены.
- **R17:** секреты в артефактах только в виде `{configured,last4}` (28 записей; открытых значений нет — подтверждено @Scanner и @Reviewer).
- **R18:** тег `pre-round1025-f8` → `a40f244`; бэкапы `var/backups/f8-round1025-20260923-044606/` + `f8-round1025-config/`; `.env.bak.round1025-f8`; `stash@{0}` — **не удалять**.

## Откат (готовность)

- **Не требуется для прода** (прод не менялся).
- **Репозиторный откат:** `git revert` docs/plans-коммита (артефакты F8 + Merge §67 + архивация) либо удаление ADD-only артефактов `plans/docs/{param-registry-round1025.tsv,.meta.md,screen-map-round1025.md,widget-map-round1025.md}` + `tools/*` + `tests/test_round1025_f8_registry.py`.

## Границы доказательств (важно)

- Так как деплой N/A, прод-проверки (health/`?v=`/логи) **не проводились и не применимы**; корректность F8 подтверждена Reviewer/Scanner на уровне артефактов и инвариантов.
- **Живой PG-снимок «до/после» (8 срезов §3) не снят** — построен детерминированный **offline-baseline** (`plans/reports/round1025_f8_config_diff.md`; срезы `chats`/`dm`/`permsoc` пусты). **PENDING OWNER VERIFICATION** (T-3021; задачи T-2998/T-3000/T-3002). Поскольку F8 рантайм/БД не меняет, ожидаемый результат = 0 изменений.
- Остаточный техдолг (не блокеры): Low **L-F8S-1** (аннотировать пустые срезы), **L-F8S-2** (`--fail-on-changes` для гейта F10), **L-F8S-3** (расширить R17-скан на `results.md`) — owned follow-up; см. `review.md` / `plans/reports/round1025_f8_scanner_audit.md`.

## Handoff

**RESULT: NOT_APPLICABLE @Orchestrator** — F8 `parameter-registry-widget-map-round1025` не требует деплоя: read-only enabler, **Δ рантайма/БД/ассетов/каталога = 0**, `APP_VERSION` 2.58.15 без bump; `tools/*` рантаймом не импортируются; рестарт/cache-bust не нужны. Предусловия закрыты (@Reviewer Approved, @Scanner C0/H0/M0, Merge §67, архивация). Открыт **только** живой PG-снимок «до/после» (**PENDING OWNER VERIFICATION**, T-3021). Далее: @Memory — метрики/KG (Шаг 10, T-3020); затем следующая фича — **F9 `secrets-and-save-states-round1025`**.
