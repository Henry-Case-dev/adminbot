# `mca-03-message-identity` — независимый Reviewer gate (T-3796, round 10.27 / Wave 1) — итерация 2

> **Статус:** 🟩 **Approved** (0 Critical, 0 High, 0 блокирующих Medium; 2 Low watch-item).
> **Итерация:** 2 — точечный re-review после rework (T-3796-R1…R6). Итерация 1 — 🟥 `Needs Fixes` (B-MCA03-1 High, B-MCA03-2 High).
> **Единый gate:** обе линзы (requirements/correctness + focused change audit); Scanner отсутствует (прецедент Эпик 3 / волны 0).
> **Risk-Level:** **R3** (ратифицировано). `threat-failure-analysis.md` присутствует и проверен.
> **Deploy:** `DEFERRED_TO_RELEASE` (§20). Пер-фичевого деплоя/тега/bump нет.

## Binding (точное ревьюируемое состояние, итер. 2)

| Параметр | Значение |
|---|---|
| `Reviewed-Commit` | `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (HEAD; код-анкер `7165ff7`) |
| `Working-Tree-Hash` | `09f2d9e942909a4240d4ef3c9e25b458e08eb9d1d83da562477d917286e1f8e0` |
| `Tracked-Diff-SHA256` (`git diff --no-color`) | `72b00db0025e7cb14dc655ef484305a5e23644134dda62a4d97acb48a607c8eb` |
| `Spec-Hash` (не менялся rework'ом) | `aa377d3b679b4d21f20d04acdfdcb053362a962d9fa331a0b46b77d65513647b` |
| `ADR-Hash` (не менялся) | `053ce84fb9eadb65e3e9febfa2aeb0caf1bd990d08351ba93b0d31d656644224` |
| `Tasks-Hash` (обновлён: Блок I rework) | `9217abd3c2af3dc0612a231ae732f4d8b885987b7aad46bd2832170dc0448363` |
| `Evidence-Hash` | `c5b4bb1db3448a8c9024170251958fe6e06dc65655b9d0168b1527ec4cbf6b28` |
| `Threat-Hash` | `182bf43e5524fa5b42482203e3bb12e3786e1cfba7f189269867f3242cdd212d` |
| Git base | `05bc870` → рабочее дерево (изменения **НЕ закоммичены**, DEFERRED_TO_RELEASE); staged-контент отсутствует |
| Diff scope | `services/message_identity.py` (NEW), `services/database.py` (v16), `handlers/summary.py`, `handlers/chat_lifecycle.py` (wiring), `bot.py` (DI), `tools/history_import/{parser,loader}.py`, `config/settings.py`, `services/mca_gates.py`, `services/mca_events.py`, `tests/test_mca03_*` |

**Рецепт Working-Tree-Hash (итер. 2; wave-0-конвенция):** `sha256( "HEAD <rev>" + "\n" + "TRACKED_DIFF_SHA256 <sha256(git diff --no-color)>" + "\n" + по строкам "U <path> <sha256(content)>" для всех untracked-не-`node_modules` файлов, отсортированных по path, **исключая review-артефакты** (`mca-03/review.md`, `mca-02/review.md`, `mca-wave1-review.md`) — они являются выходом самого ревью и иначе делали бы запись хэша самоссылочной). Хэш воспроизводим на финальном дереве после записи вердиктов.

**Сверка с Builder:** (справочно) полный манифест, включая review-артефакты в состоянии итер. 1, даёт `2ac636a733c2dee2b7cdf27ef94b28176a278c14aaaf53a41c7ccee9d63f6846`; заявленный Builder `wt `bae421c5…`` **не воспроизводится** ни полным, ни wave-0-style манифестом на текущем дереве (вероятно, вычислен до поздних правок доков; зарегистрировано как L-W1-1, non-blocking). Авторитетным является хэш, пересчитанный Reviewer'ом.

## Checks performed (независимо, итер. 2)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`, Python 3.12.0) | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **9678 passed / 0 failed** (192.24s) ✔ совпало с заявленным |
| Focused mca-03 | `pytest tests/test_mca03_message_identity_round1027.py -q` | **25 passed** ✔ |
| Focused mca-03+mca-02 | `pytest tests/test_mca03_* tests/test_mca02_* -q` | **88 passed** ✔ (25+63) |
| JS vm-харнесс | 47 файлов `tests/js/*.js` + `node --check web/app.js` | **47/47 ok**; app.js check exit 0 ✔ |
| Whitespace | `git diff --check` | exit 0 ✔ |
| Δ каталога | `git status services/param_catalog.py tests/fixtures/round1025/f8_baseline.json` | не изменены ✔ (F8 NOT_APPLICABLE) |
| `APP_VERSION` | `config/settings.py` | 2.58.31 ✔ (не менялся) |
| httpx | импорт | **0.28.1** ✔ |
| Cookies/профиль | `git ls-files | rg -i "cookie|profile"` | только `tools/cookies_export.py`, `tests/test_cookies_export.py` ✔ |

## Re-check блокирующих findings (итер. 1 → итер. 2)

### [B-MCA03-1] High → **CLOSED** — namespace per-import

- **Код:** `tools/history_import/loader.py:49–67` — `_dataset_namespace(path) = "import:<export_id>:<sha256(abspath|size)[:16]>"` (`detect_export_id` из шапки, `os.path.abspath` + size — различает и файлы с одинаковой шапкой); `load_file:205,218–219` — `namespace=None` → per-dataset namespace файла (явный namespace — override); `import_history_fts:316,341–343` — проброс per-file; `_INSERT_SQL_IDENTITY:76–92` + `_SOURCE_RECORD_SQL:88–92`; `services/database.py:265–275` — сохранённый `UNIQUE(namespace, local_record_id)`.
- **Legacy-backfill не сломан:** `services/database.py:1299–1337` (`_migrate_message_identity_v16_backfill`) по-прежнему пишет `namespace='legacy_import_v1'`/`source_record_id='k:'||import_key`; переприсвоения старых строк нет.
- **Воспроизведение (мой независимый прогон, не тест Builder'а):**
  - два файла с **одинаковой шапкой** (`-1005001`), одинаковыми record-id `1/2`, разным текстом и **принудительно одинаковым размером** (287=287) → `inserted=4`, `message_source_records=4`, `distinct(namespace)=2`; ✔
  - повторный импорт того же файла → `inserted=0`, число source records не растёт (идемпотентность `INSERT OR IGNORE`); ✔
  - **реальные файлы:** `migrate_history/10.2024.json` (`export_id=2417005237`, ns `import:2417005237:25659129b077863c`) × `10.08.2025.json` (`export_id=2661910336`, ns `import:2661910336:b3ff1c301de6516a`) — namespace'ы различны; пересечение id-пространств **независимо пересчитано: 335 765 ∩ 339 672 = 316 547** (совпало с итер. 1). ✔
- **Регресс-тест осмыслен:** `tests/test_mca03_message_identity_round1027.py:642–686` — проверяет `smart_messages=4`, `source_records=4`, `len(namespaces)==2`, оба `local_record_id ∈ {1,2}`, `ns.startswith("import:")`. До фикса этот кейс давал 2 source records (итер. 1). ✔
- **Вердикт:** требование spec §4.1 D2/§4.6/SC-03 («namespace/dataset ID») теперь выполняется; finding закрыт.

### [B-MCA03-2] High → **CLOSED** — `sent_at` ≠ `ingested_at` на живом пути

- **Код:** `handlers/summary.py:238–244` — `sent_at = _sent_at_of(message)` (Telegram-дата, `message.date`), `ingested_at = int(time.time())`, legacy `timestamp=ingested_at`; значения вычисляются независимо и **не приравниваются**. `services/message_identity.py:183–199` — `sent_at_source='telegram_date'` при наличии даты, иначе честный `unknown`; приём независимых `sent_at`/`ingested_at`.
- **Строгий тест (ослабленный assert убран):** `test_observer_sent_at_is_telegram_date_not_ingest_time:542–567` — событие 2022 → `sent_at == date.timestamp()`, `before ≤ ingested_at ≤ after`, `sent_at < ingested_at`, `timestamp == ingested_at != sent_at`; `test_observer_live_writes_identity:519–538` — строгий (`row["sent_at"] < row["ingested_at"]`, без `or sent_at > 0`). Grep по `tests/test_mca03_*` не находит ослабленной формы. ✔
- **Import-путь не сломан:** `test_a11_import_via_loader_two_dates:595–638` — `sent_at=1640995300` (дата события из `date_unixtime`), `timestamp` там же (историческое поведение импорта), `ingested_at != sent_at` (момент записи). ✔
- **A11/SC-06:** «дата события ≠ дата записи» достижима и проверена как на live (поздняя доставка), так и на импорте. Равенство при нормальной доставке (`date ≈ now`) — физически корректное совпадение двух независимых часов, а не схлопывание.
- **Вердикт:** finding закрыт.

## Dispositions Medium/Low (итер. 2)

| ID | Итер.1 | Итог итер. 2 | Ссылки / тест |
|---|---|---|---|
| M-MCA03-4 (связывание импорт↔live, SC-03) | OPEN | **CLOSED** — `_record_occurrence` вызывается и на существующей canonical-строке (`services/database.py:2815–2831,2880`); live-наблюдение импортной копии при общем `(chat_id, tg)` добавляет live-вхождение к тому же canonical source | `test_import_and_live_share_one_canonical_source:690–711` (1 canonical, `{import, live}`) |
| M-MCA03-5 (`sent_at` в changed-ветке) | OPEN | **CLOSED** — changed-UPDATE содержит `sent_at=COALESCE(sent_at, ?)` / `ingested_at=COALESCE(ingested_at, ?)` (`services/database.py:2855–2865`) | `test_existing_row_backfills_sent_at_on_changed_update:715–733` |
| M-MCA03-3 (wiring `chat_id_migrations`, REQ-MCA03-06) | OPEN | **CLOSED** — DI `db` (`bot.py:606`, `handlers/chat_lifecycle.py:39–49`), запись в `on_chat_migrated:166–180` по подтверждённому `migrate_to_chat_id` (`evidence='telegram:migrate_to_chat_id'`, fail-open) | `test_chat_migrated_wiring_records_chat_id_mapping:737–770`; другие вызовы `setup_chat_lifecycle` совместимы (db default None) |
| L-MCA03-6 (re-observation без revision) | boundary | **подтверждено границей** (версии — только `record_edit`/edited-хендлер; согласуется с D5) | — |
| L-MCA03-7 (bot-edit вне revision) | boundary | **подтверждено границей**; порядок роутеров и UNHANDLED сохраняют чужие edited-хендлеры | `handlers/summary.py:272–298`, `bot.py:761 vs 790` |

Побочных поломок в `bot.py`/`handlers/chat_lifecycle.py`/`tools/history_import/loader.py` не найдено: `db` в `on_startup` определён до вызова DI (bot.py:279, 606); регистрация миграции fail-open и не меняет PG-ветку `chat_links`; `load_file`/`import_history_fts` — только новый keyword-параметр (все вызовы, включая `manage.py:243` и `tests/test_history_loader.py`, сохраняют сигнатуру).

## Новые findings (итер. 2)

- **[L-MCA03-8] Low (residual, non-blocking) — чувствительность fingerprint namespace к in-place регенерации файла.** `_dataset_namespace` (`loader.py:49–67`) выводит отпечаток из `abspath|size`. Если экспорт перегенерирован **по тому же пути с тем же размером** (но другим содержимым/record-id), namespace совпадёт; `INSERT OR IGNORE` по `(namespace, local_record_id)` может пропустить source record для новой canonical-строки (provenance-пробел, не порча данных). Влияние экзотично (реальные `migrate_history/*.json` различаются export-id; копии — путём). Follow-up: опционально добавить mtime/content-хэш в отпечаток (`mca-release`/@Architect решением). Не блокирует.
- **[L-W1-1] Low (doc/binding, общий для волны 1) — Builder-reported wt `bae421c5…` не воспроизводится.** Заявленный в `workflow_state`/evidence хэш не совпадает ни с полным манифестом итер. 1 (`2ac636a7…`), ни с wave-0-style вариантами; вероятно, вычислен до поздних правок доков. Reviewer пересчитал binding (см. выше); Orchestrator должен использовать хэш Reviewer'а. Не блокирует.

## OFF-паритет kill-switch

- `MCA_MESSAGE_IDENTITY_ENABLED=false` → observer legacy `save_smart_message` (без новых полей) и loader legacy-INSERT (namespace/source records не пишутся): `test_observer_identity_off_parity`, `test_loader_identity_off_parity` — passed.
- `MCA_MESSAGE_REVISION_TRACKING_ENABLED=false` → правки без версий: `test_revision_tracking_off_parity` — passed.
- Переключение per-call через `mca_gates`; полный pytest 9678/0 на ON-дефолтах.

## Counterexamples checked

1. Два экспорта с одинаковой шапкой/record-id/**одинаковым размером** → 4/4, 2 namespace (мой прогон). ✔
2. Повторный импорт того же файла → 0 дублей/source records. ✔
3. Реальные `10.2024.json`×`10.08.2025.json`: export-id и namespace различны; пересечение 316 547 воспроизведено. ✔
4. Поздняя доставка live (2022 → сегодня): `sent_at < ingested_at`, legacy `timestamp`=время записи. ✔
5. Legacy-дубли: partial UNIQUE не создаётся, WARN, строки целы (тест итер. 1). ✔
6. OFF-паритет обоих рубильников. ✔
7. `unknown` вместо выдуманных значений (`sent_at=None` → `sent_at_source='unknown'`; пустой content → `content_hash=None`). ✔

## Unavailable checks

- Live Telegram edited-update — offline (покрыт aiogram unit/integration).
- Полный migration smoke v1→v16 на реальной legacy-БД — за `mca-release`.
- Реальный deploy — `DEFERRED_TO_RELEASE`.

## Вывод

**Status: Approved** (B-MCA03-1/B-MCA03-2 закрыты; M-MCA03-3/-4/-5 закрыты; L-MCA03-6/-7 — границы; L-MCA03-8/L-W1-1 — Low watch-item). Условие итер. 1 выполнено; binding итер. 2 зафиксирован Reviewer'ом. Разблокировано: **Merge §96** и `ADR-1027-4 → Accepted` (решение @Architect; Reviewer хэши не редактирует). Follow-up: L-MCA03-8 — при следующем касании loader'а.
