# MCA Wave 1 (round 10.27) — сводка независимого Reviewer gate — итерация 2 (re-review после rework)

> **Дата:** 26.09.2026. **Гейт:** единый @Reviewer (обе линзы; Scanner отсутствует — прецедент Эпик 3 / волны 0).
> **Baseline:** HEAD `05bc870` (код-анкер `7165ff7`); все изменения **НЕ закоммичены** (DEFERRED_TO_RELEASE). Ревьюировалось рабочее дерево.
> **Working-Tree-Hash (обе фичи, итер. 2):** `09f2d9e942909a4240d4ef3c9e25b458e08eb9d1d83da562477d917286e1f8e0` (рецепт — в `review.md` фич: tracked-diff + untracked-не-`node_modules` без review-артефактов; wave-0-конвенция). **Supersedes** `c871625b…` (итер. 1) и Builder-reported `bae421c5…` (не воспроизводится — L-W1-1).
> **Tracked-Diff-SHA256:** `72b00db0025e7cb14dc655ef484305a5e23644134dda62a4d97acb48a607c8eb`.
> **Continuity-нота:** Re-review выполнен general-сессией в роли @Reviewer (named Reviewer недоступен: provider 400 ×3); независимость сохранена — сессия не участвовала в реализации mca-03/mca-02.

## Финальная таблица вердиктов

| Фича | Risk | Вердикт (итер. 2) | Закрытые findings | Открытые findings |
|---|---|---|---|---|
| `mca-03-message-identity` | R3 | 🟩 **Approved** | B-MCA03-1 (High), B-MCA03-2 (High), M-MCA03-3, M-MCA03-4, M-MCA03-5 | L-MCA03-8 (Low, residual), L-W1-1 (Low, общий) |
| `mca-02-safe-fetch-cookies` | R3 | 🟩 **Approved** | B-MCA02-1 (High), M-MCA02-2, M-MCA02-3 (путь+carry-over), L-MCA02-4 | L-W1-1 (Low, общий) |

Binding (обе фичи): Reviewed-Commit `05bc8704c2de5e7de1d5d04ac34df763d35219aa`; Spec-Hash mca-03 `aa377d3b…` (не менялся; implemented per-import namespace соответствует D2 «батч/экспорт»), mca-02 `d31f6929…` (не менялся); Tasks-Hash mca-03 `9217abd3…`, mca-02 `4f914807…` (Блок I rework); ADR-1027-4 `053ce84f…`, ADR-1027-5 `1c9936a4…` (не менялись).

**Независимо воспроизведено (итер. 2, обе фичи):** полный pytest `.venv` — **9678 passed / 0 failed** (192.24s; итер. 1: 9667 + 11 новых тестов); focused mca-03 = **25**, mca-02 = **63** (сумма 88); JS vm-харнесс — **47/47 ok** + `node --check web/app.js` exit 0; `git diff --check` = 0; httpx 0.28.1; Δ каталога = 0; `param_catalog.py`/F8-fixture не изменены; `APP_VERSION` 2.58.31 не менялся; `git ls-files` чист от cookies/профиля. Числа совпали с заявленными Builder (9667 → 9678, +11 тестов rework — расхождений нет).

## Перепроверка исходных 3 High (независимо, по коду и прогонам)

1. **B-MCA03-1 (namespace) → CLOSED.** `_dataset_namespace(path) = import:<export_id>:<sha256(abspath|size)[:16]>`; per-file по умолчанию; явный override сохранён; legacy-backfill `legacy_import_v1` не переприсваивается. Мои пробы: два файла с одинаковой шапкой/record-id и **одинаковым размером** → 4 smart_messages / 4 source records / 2 namespace; повторный импорт идемпотентен; **реальные** `migrate_history/10.2024.json` (export `2417005237`) × `10.08.2025.json` (export `2661910336`) → namespace'ы различны, пересечение id-пространств **независимо пересчитано = 316 547** (335 765 ∩ 339 672). Регресс-тест осмыслен.
2. **B-MCA03-2 (две даты live) → CLOSED.** observer: `sent_at=_sent_at_of(message)`, `ingested_at=now`, legacy `timestamp`=время записи, значения не приравнены; строгие тесты на позднюю доставку (2022→сегодня) без ослабленных assert'ов; import-путь (дата события из `date_unixtime`, `ingested_at`≠`sent_at`) не сломан; A11/SC-06 выполнен.
3. **B-MCA02-1 (timeout) → CLOSED.** `build_request(..., timeout=prof.timeout)` + общий deadline `asyncio.timeout(prof.timeout)` в `fetch`/`stream_to_file`; таймауты пробрасываются, не маскируются; тесты: 0.2 c ≤0.6 c (stage `stream`), `stream_to_file` + удаление частичного файла, html baseline 10 c/video 240 c сохранены. Ранее мёртвые `SAFE_FETCH_*_TIMEOUT_SECONDS` действуют.

## Новые findings (итер. 2)

- **L-MCA03-8 (Low, residual, non-blocking):** отпечаток namespace (`abspath|size`) совпадёт при in-place регенерации файла с тем же размером → возможен пропуск source record для новой canonical-строки (`INSERT OR IGNORE`), без порчи данных. Экзотика; follow-up при следующем касании loader'а.
- **L-W1-1 (Low, doc/binding, non-blocking):** Builder-reported `wt bae421c5…` не воспроизводится на текущем дереве (ни полным манифестом `2ac636a7…`, ни wave-0-style вариантами); вероятно, вычислен до поздних правок доков. Авторитетный binding — пересчитанный Reviewer'ом (`09f2d9e9…`).

## Dispositions Medium/Low (законность подтверждена)

- mca-03: M-MCA03-3 (wiring `chat_id_migrations` в `on_chat_migrated` через DI `db`, fail-open), M-MCA03-4 (вхождение на canonical при импорт↔live), M-MCA03-5 (`COALESCE(sent_at)` в changed-ветке) — **исправлены и покрыты тестами**; L-MCA03-6/-7 — подтверждённые границы (версии только через `record_edit`; bot-edit вне revision). Побочных поломок в `bot.py`/`chat_lifecycle.py`/`loader.py` нет (все вызовы совместимы, `db` в scope).
- mca-02: M-MCA02-2 (trusted IP-литерал → `resolved` канонизирован), M-MCA02-3 (официальный trusted-HTTP путь + carry-over потребителей в `mca-11`/`mca-19` по границам spec §1), L-MCA02-4 (unlink частичного файла) — **исправлены и покрыты тестами**.
- Законные residual'ы без изменений: Cobalt egress вне процесса; live-проверка авторизованного видео (deferred); отсутствие producer'а `unavailable/deleted` (санкция spec §4.4); deep retrieval-интеграция — границы `mca-07`/`mca-04a`.

## Рекомендация

**@Orchestrator:**
- Обе фичи — **Approved**; маршрут `review → release-подготовка` (без нового build). Зафиксировать в state: статусы Approved; binding итер. 2 (Reviewed-Commit `05bc870`, Working-Tree-Hash `09f2d9e9…`; Spec/Tasks/ADR/Evidence-хэши — в `review.md` фич). **Использовать хэш Reviewer'а, а не `bae421c5…`** (L-W1-1).
- Carry-over (non-blocking): L-MCA03-8, L-W1-1 — как watch-items; Medium/Low не блокируют.

**@Architect:**
- Условие итер. 1 («Merge §96+ / ADR Accepted — только при Approved») **выполнено**: рекомендую **Merge §96** (`mca-03`) и **§97** (`mca-02`) + **ADR-1027-4 → Accepted**, **ADR-1027-5 → Accepted**.
- Уточнения по spec не требуются: per-import namespace соответствует D2 («идентификатор импортной партии/экспорта»); trusted-HTTP — путь реализован, границы потребителей зарегистрированы в `tasks.md`.
- Открытый вопрос итер. 1 о семантике legacy-колонки `timestamp` разрешён реализацией и покрыт тестами: live `timestamp` = время записи, импорт `timestamp` = дата события (историческое поведение), `sent_at`/`ingested_at` — независимые поля.

**@Builder:** блокирующих фиксов не требуется.

## MEMORY_DELTA (для @Orchestrator)

- Подтверждено независимо: pytest **9678/0**, JS **47/47**, focused 25/63, `git diff --check` 0, Δ каталога 0, httpx 0.28.1 на `05bc870`+worktree (WT `09f2d9e9…`).
- Durable-факты волны 1 (закрытие): namespace импорта теперь per-dataset (`import:<export_id>:<fingerprint>`) — коллизия provenance при ≥2 экспортах устранена, реальное пересечение 316 547 подтверждено; live `sent_at`/`ingested_at` — независимые часы (A11/SC-06); профильный timeout SafeFetcher действует (html 10 c baseline сохранён). `ADR-1027-4`/`ADR-1027-5` можно принимать; Deploy — `DEFERRED_TO_RELEASE`.
