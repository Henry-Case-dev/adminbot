# Deployment — A0 `agentic-audit-round1026` (Шаг delivery @DevOps, read-only аудит)

> **Статус:** **`NOT_APPLICABLE`** (обосновано). Деплой не выполняется: рестарт, `git pull` на прод, cache-bust `?v=`, миграции — **неприменимы**.
> **Тип:** research/audit, **read-only** — аудит + durable-артефакт; **0 изменений product code/рантайма/ассетов/каталога/DDL/env**.
> **Основание:** `spec.md` §4 «Deploy — вердикт», `tasks.md` (блок 0 / блок F), **ADR-1026-13** (последствия: deploy NOT_APPLICABLE); подтверждено единым Reviewer gate (T-3498).
> **Дата:** 24.09.2026. **Агент:** @DevOps. **Прод не трогался.**

## 1. Вердикт и предусловия

| Поле | Значение |
|---|---|
| Вердикт | **NOT_APPLICABLE** (деплой/рестарт/cache-bust/миграции не выполняются) |
| @Reviewer | **Approved** — единый gate, обе линзы; **Critical 0 / High 0**, requirement-/architecture-блокирующих Medium 0 (`review.md`, T-3498) |
| @Scanner | **не создаётся** — Scanner удалён намеренно (24.09.2026), обязанности в линзе 2 Reviewer |
| Reviewed-Commit | `e8065e9257077098476e5bf3892ccaeefe775717` (HEAD == `origin/master`) |
| Working-Tree-Hash | `805c46805201716ce0fd9e1e893a5c48f278655a190d19727a0e5b227752bf76` |
| Spec-Hash | `1B2AE779BB3AF9A69A4B18237F5A7417D753AF5CC8D644F103A7FC781A835261` |
| Baseline / версия | HEAD `e8065e9`; `APP_VERSION` **2.58.29** (bump не выполнялся) |
| Прецедент | F8 `parameter-registry-widget-map-round1025` — `plans/ARCHITECTURE.md` **§67** (deploy NOT_APPLICABLE); F10 `epic1-verification-round1025` — **§70** |

## 2. Обоснование NOT_APPLICABLE (почему деплой не нужен)

| Срез | Δ | Доказательство (@DevOps, перепроверено) |
|---|---|---|
| Product code `services/**`/`web/**`/`handlers/**`/`config/**` | **0** | `git diff e8065e9 -- . ":(exclude)plans"` — **пусто** (0 строк) |
| Тесты / конфиги / lockfiles | **0** | вне diff; untracked-файлов вне `plans/**` — **нет** |
| Схема БД | **Δ DDL = 0** | `db/**` и `database.py` вне diff; SQLite остаётся v12; миграции не запускались |
| Каталог параметров | **Δ каталога = 0** | `param_catalog.py` вне diff; каталог **REGISTRY 469 / Settings 426 / categorized 444 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21** (без изменений) |
| Канон инструментов | **0** | `TOOL_CALLING_TOOLS` = **10** (`services/tool_schemas.py:337–348`); состав/порядок сохранены; `get_user_context` отсутствует |
| Ассеты / версия | **0** | `APP_VERSION` **2.58.29 без bump**; ассеты не менялись → cache-bust не требуется |
| Env / новые ключи | **0** | новых переменных/ключей нет; `.env` не менялся |

**Вывод:** нет кода, данных или ассетов, влияющих на прод → поставка в рантайм отсутствует; «поставка» A0 — это сами документы (durable-аудит `plans/docs/agentic-audit-round1026.md`, спека/ADR/evidence/review) в репозитории.

**Что НЕ выполнялось (осознанно):** нет `git push`/`git pull` на прод, нет `systemctl restart admin_bot`, нет bump `APP_VERSION`, нет обновления `?v=`, нет миграций/DDL, нет коммита (closing-коммит — отдельно, по решению оркестратора), нет правок `plans/current_task.md` и машинного блока `OPENCODE_WORKFLOW_STATE_V1`.

## 3. Проверка binding ревью (release inputs)

Пересчитано @DevOps независимо (SHA-256):

| Артефакт | Хэш @DevOps | Совпадение с ревью |
|---|---|---|
| `spec.md` (Spec-Hash) | `1B2AE779…A835261` | ✅ == `1B2AE779…` |
| `plans/docs/agentic-audit-round1026.md` (durable) | `9F438422…B30D6975` | ✅ |
| `adr-1026-13-…-discipline.md` | `CA9BC9EA…5D5CBEF3` | ✅ |

**Наблюдение (не блокер, вне scope инвалидации).** Композитный `Working-Tree-Hash` включает `git diff e8065e9`, а этот diff содержит **машинный блок** `plans/workflow_state.md`, которым управляет @Orchestrator. После gate (mtime `review.md` 12:16:07) оркестратор продвинул блок с rev 52 / `phase="review"` на **rev 53 / `phase="delivery"`** (mtime 12:16:50) — это и есть источник байтового сдвига композитного WTH. Все **субстантивные release-входы** (product code, `spec.md`, durable-артефакт, ADR) **байт-идентичны** состоянию на момент ревью; `review.md` явно **не включает** `workflow_state.md` в список инвалидирующих правок (там только product code / relevant untracked / `spec.md` / `plans/backlog.md` / `plans/MEMORY.md`). Дрейфа release-входов нет → **approval актуален**, пересчёт не требуется.

**R17 (секреты):** скан изменённых и untracked A0-файлов на `sk-…`/`api_key=`/`Bearer …`/`eyJ…`/`-----BEGIN` — **0 совпадений**; в артефактах только числа/коды/id/`file:line`. `git diff --check` = **0** whitespace-ошибок.

## 4. Схема данных и инварианты

- **Δ DDL = 0**, **Δ каталога = 0** (469/426/444/100/98/21); CSP/zero-build не затрагивались.
- **Read-only:** diff вне `plans/**` пуст; untracked вне `plans/**` нет.
- **R17:** секретов/ключей/сырых промптов/сырых ответов LLM в изменённых и новых файлах нет.
- **R18:** annotated-тег **`pre-round1026-a0`** (tag-obj `afe14278`) → commit `e8065e9` — **цел**; бэкап `var/backups/a0-round1026-20260924-114354/` (+ `BASELINE.md`, `files/`) — **на месте**; `stash@{0}` (`wip(f1): IA v2 round1025 …`) — **цел**. Теги/бэкапы/`stash@{0}` **не удалять**.

## 5. Откат (готовность)

- **Для прода — не требуется** (прод не менялся).
- **Точка отката read-only-инварианта:** annotated-тег **`pre-round1026-a0`** → `e8065e9` (T-3481). Жёсткий откат: `git fetch --tags origin && git reset --hard pre-round1026-a0`.
- **Мягкий откат репозитория:** `git revert` docs/plans-коммита A0 (при его появлении) — рантайм не затрагивается.
- **Страховка:** бэкап `var/backups/a0-round1026-20260924-114354/` и `stash@{0}` сохранены (R18).

## 6. Границы доказательств

- Так как деплой **N/A**, прод-проверки (health/`?v=`/логи/`database is locked`) **не проводились и не применимы**; корректность A0 подтверждена Reviewer на уровне артефактов и read-only-инвариантов.
- **Живой прогон провайдера** (реальная генерация / LLM tool-probe) и разбор прод-логов — вне A0 (read-only, ADR-1026-13 D2); кандидаты HY-01…HY-06 остаются **HYPOTHESIS** с планами проверки для волн **A3/A4**.
- **Машинный блок** `plans/workflow_state.md` (rev 53) содержит `deployment.required=true` / `status="pending"` — оркестратор-managed; @DevOps его **не менял**. Согласно `review.md` L-R1026A0-1, приведение к `required=false` / `status="not_applicable"` — за @Orchestrator через `workflow_checkpoint` (не через этот артефакт).

## 7. Non-blocking debt (из `review.md`, без изменений)

- **[L-R1026A0-1] [info]** — машинный блок: `deployment.required=true` при deploy NOT_APPLICABLE → fix @Orchestrator через `workflow_checkpoint`.
- **[L-R1026A0-2] [info, docs]** — шапка durable-отчёта читается как «ожидает T-3497/T-3498» → обновление AMEND-записью после Verified (или на архивации T-3499).
- **[L-R1026A0-3] [low, coverage]** — часть `file:line` в отчёте без полного пути → точка роста для машинного переиспользования A1–A10.

## 8. Handoff

**RESULT: NOT_APPLICABLE @Orchestrator** — A0 `agentic-audit-round1026` **не требует деплоя**: read-only аудит, **Δ рантайма/ассетов/каталога/DDL/env = 0**, `APP_VERSION` **2.58.29** без bump, прод не трогался; тег `pre-round1026-a0` → `e8065e9` и бэкап целы (R18). Предусловия закрыты: @Reviewer **Approved** (C0/H0; binding `e8065e9` / WTH `805c4680…` / Spec-Hash `1B2AE779…`); binding release-входов подтверждён @DevOps (см. §3). Далее: **T-3499 @PM** — архивация фичи (`plans/archive/agentic-audit-round1026/`; durable-артефакт `plans/docs/agentic-audit-round1026.md` остаётся на месте) → handoff к **A1 `tool-coordinator`**.
