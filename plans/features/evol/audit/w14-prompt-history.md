# W14 — История версий промптов (P0-2): отчёт полосы Builder

Фича: `ASAP-SUMMARY-COVER-INTEGRITY-01` v2.1, §2 (P0-2) и §9.A сценарии 1–8.
Ветка: `evol/impl` @ `00ab8d4c` (prod 2.58.145), worktree
`…/worktrees/c742e4de9e92c489/evol-71536a366a11-c63f6f44`.
Режим: только чтение/правки файлов и `pytest`; никаких `git reset/checkout/stash/
clean/restore` и коммитов. Рабочее дерево содержит незакоммиченные правки
соседних полос (`cover_style_jobs.py`, `direct_chat_service.py`,
`evidence_policy.py`, `tool_router.py`, `web_content_extractor.py`,
`test_evol_evidence_*`) — они не мои и не изменялись.

Мой scope: `services/prompt_release_policy.py`, `web/api/routes.py`,
`tests/test_asap_prompt_history_integrity.py` (новый), `tests/test_evol017_prompt_history_ui.py`
(одно утверждение контракта), `tests/test_round1025_f8_registry.py` (re-pin
hash по инструкции самого теста). `web/app.js`/`index.html` (UI) — НЕ трогал.

---

## 1. Root cause продового HTTP 500 «История версий» (доказано)

**Дефект:** `services/prompt_release_policy.py`, функция `_revision_chars()`
вызывала **async** метод стора без `await`:

```python
full = store.get_revision(revision.revision_id)   # coroutine, без await
return len(full.body) if full is not None else 0  # AttributeError
```

**Трасса (реальный запуск, воспроизведено):**

```
list_versions → "chars": _revision_chars(store, r)
_revision_chars → len(full.body)
AttributeError: 'coroutine' object has no attribute 'body'
+ RuntimeWarning: coroutine '…get_revision' was never awaited
→ FastAPI 500 (не перехватывалось маршрутом)
```

**Почему падало только на реальных данных:** `PgPromptJournal.list_revisions()`
намеренно **не** отдаёт тела ревизий (`body=""`, тела — только через
`get_revision`/`/source`). Тогда `revision.body` пуст → управление уходит в
сломанную ветку. `MemoryPromptJournal.list_revisions()` отдавал полные тела,
поэтому `tests/test_evol016*`, `test_evol017*` и «успешный тест на чистой БД»
оставались зелёными. Это ровно тот случай, который §1.1/§2.2 ТЗ называет
«успешный кодовый тест не заменяет проверку существующих записей».

**Корреляция с 500 у владельца:** ошибка возникает при **наличии хотя бы одной
ревизии** в PG-журнале (`prompt_revisions`), т.е. у любого промпта, прошедшего
cutover/правку, — включая `prompts.summary_cover_style`. У промпта без истории
ответ был 200 с пустым списком (это и маскировало системность дефекта).
Проверено на живом PostgreSQL (см. §7): старая формула падает с точно той же
ошибкой на реальных строках журнала.

**Исправление (минимальное, на нижнем слое):**

| Файл | Изменение |
| --- | --- |
| `services/prompt_release_policy.py` | `_LIST_REVISIONS_SQL` += `length(body) AS char_count` (длина без пересылки тела; список больше не грузит полные тексты), `RevisionRow.chars`, `PgPromptJournal.list_revisions` заполняет `chars`, `MemoryPromptJournal.list_revisions` тоже (`len(body)`) — форма строк у стора и у двойника теперь совпадает |
| `services/prompt_release_policy.py` | `_revision_chars(revision)` стал чистым (без I/O и без `await`-ловушки): `chars` из стора либо `len(body)` |
| `services/prompt_release_policy.py` | `list_versions()` собирает строки циклом (а не списковым включением с вызовом стора) |

Побочный плюс: страница истории больше не вытягивает тела всех ревизий из БД
(большие Core/Summary-промпты грузятся только по `/source`).

---

## 2. Честные отказы: 503 вместо `200: []` (§2.2, сценарий 5)

До правки было **два** способа спрятать отказ:

1. `list_versions()` глотал любое исключение чтения журнала
   (`except Exception: … pass`-стиль) и возвращал `revisions: []` — история
   выглядела «пустой», хотя она есть.
2. Маршрут при `store is None` (PG/журнал недоступен) отдавал `200` с пустым
   списком и `journal_available: false`.

Теперь:

* сервис поднимает `JournalUnavailable` при сбое чтения журнала;
* `GET /api/prompts/{key}/versions` → **503** `«журнал версий недоступен …»`
  (нет PG / ошибка чтения), **403** — права (без изменений), **404** — ключ вне
  реестра, **200** — только реально прочитанная история;
* `GET /api/prompts/revisions/{id}/source` и `/revisions/diff` уже отдавали 503
  при недоступном журнале — поведение сохранено;
* `journal_available` теперь `True` только когда история действительно
  прочитана.

UI-контракт: `web/app.js::loadPromptHistory` пишет ошибку в
`promptHistory.error` и **не трогает** состояние редактора (`workspacePromptFocus`,
черновик текста) — несохранённая правка при неудачной загрузке истории не
теряется. Это проверено чтением кода; визуальная проверка — за UI-полосой
(`web/app.js`/`index.html` в этой полосе не менялись).

---

## 3. Аудит активаций: даты и адресат (§2.2, сценарии 2 и 8)

`prompt_activations.created_at` существовал в DDL и выбирался в SQL, но
отбрасывался при сборке `ActivationRow` — события включения были без даты.

* `ActivationRow.created_at` (аддитивное поле), заполняется PG-стором и
  memory-стором (`_utc_now()` при вставке);
* `list_versions()` отдаёт `activations[].created_at`;
* маршрут: `activation_time_available` = `True` только если у событий реально
  есть время (старые/частичные строки не превращаются в выдуманные часы);
* строка ревизии теперь несёт `scope` и `chat_id` — в истории видно
  `global`/`chat` и адресат, а не только глобальный контекст запроса.

Зависимость для UI-полосы: `web/index.html` блок «События включения» пока не
выводит дату — нужно добавить `phWhen(ev.created_at)` рядом с
`phEventLabel(ev)`. API-поле уже есть, деплой UI не обязателен для этой правки.

---

## 4. Concurrent/stale write (§2.2, сценарий 5)

`activate_revision()` читал активное состояние (`read_applied`) **до**
транзакции, хотя транзакция PG берёт advisory-лок (`pg_advisory_xact_lock`) —
две параллельные активации могли классифицировать выбор (`manual_rollback` /
`manual_forward`) и записать `factory_revision_applied` по устаревшему
состоянию.

Теперь `read_applied` + `revision_precedes` выполняются **внутри** транзакции
под тем же локом: классификация и записанный `factory_revision_applied`
соответствуют состоянию, на котором реально сериализованы активации.
Поведение откат/вперёд, гейты `retired`/`schema_incompatible`, «история не
удаляется» не менялись.

---

## 5. Версия-целостность: кто вообще может записать `prompts.summary_cover_style`

Протрассированы **все** пути записи (grep по `summary_cover_style`,
`bot_settings`, `cache.set`, `write_versioned_value`, `record_manual_activation`,
`apply_release`, `_seed_settings`, UI `saveConfigItem`/`persistItems`):

| Путь | Пишет значение? | Условие |
| --- | --- | --- |
| `POST /api/config` (редактор промптов) | да, только переданный ключ | явное сохранение; `persistItems` отправляет лишь изменённые элементы; сервер пишет только `items` и журналирует только их |
| `apply_release` (старт/деплой, `release_id=evol-016-cutover`) | да, **только при новой заводской МЕТКЕ** или первом cutover | `activation_plan`: та же метка → `no_op` (ни строки, ни записи); целостность печати сломана → `integrity_reject` (fail-closed) |
| cutover (первый запуск механизма) | да: снимок текущего текста `origin=legacy` → активация заводской ревизии | `has_import=False` |
| `POST /api/prompts/{key}/activate` | да | явный откат/вперёд владельца |
| CLI `prompt_factory` (`reset`, `restore`) | да | явная команда владельца |
| `pg_db._seed_settings` | **нет** для существующего ключа | `INSERT … ON CONFLICT (key) DO NOTHING` (только создаёт отсутствующий ключ, дефолт из кода) |
| seed/migrations (`prompt_migrations.py`) | **нет** | в файле больше нет прямых записей значений; только `apply_release` |
| `web/api/speech.py`, `cover_styles.py`, `summary_generator.py` | **нет** этого ключа | пишут свои ключи (`prompts.direct_chat_verbalizer_system_prompt`, `prompts.summary_cover_style_id` и пр.) |
| изменение другого поля/чата | **нет** | `_prompt_record_saved_snapshots` вызывается только по `updated`-ключам пакета |

**Объяснение наблюдения владельца (`photorealistic, cinematic light` вместо
comic-book):** строка в редакторе — это ровно кодовая заводская константа
`services/summary_prompts.py:268 SUMMARY_COVER_STYLE_DEFAULT = "photorealistic,
cinematic light"` (печать блока `summary.cover.style` = `cover-style-default`,
sha12 `19d2dd88086e`). Значит, в ключ легла **заводская** ревизия, а не
произвольная UI-запись: механизм журнала (EVOL-016) при первом применении
(cutover, `release_id=evol-016-cutover`) снимает снимок текущего текста как
`origin=legacy`, а затем активирует заводской текст — это разрешённый §2.1(2)
сценарий «новая заводская ревизия активна поверх ручной правки», но выглядит
как непрошеная подмена, и до этой правки историю нельзя было открыть (500),
т.е. снимок был недоступен для просмотра и откат невозможен.

Аудит-трасса до появления журнала (до 2.58.x) отсутствует — механизма записи не
существовало; это фиксируется прямо, без выдуманных версий. После cutover все
активации пишутся в `prompt_activations` и теперь читаются через исправленный
endpoint (`legacy_import` / `deploy_activate` / `manual_edit` … с датой,
scope, актором).

Проверено тестом `test_restart_keeps_manual_cover_style`: cutover → ручная
правка `prompts.summary_cover_style` → повторный `apply_release` с тем же
релизом (`restart/redeploy`) → `changed=0`, результат `skipped_same` /
`restart_same_revision`, текст остался ручным, новых ревизий нет, активная —
ручная. И `test_editing_other_prompt_does_not_write_cover_style`: сохранение
другого промпта не делает ни одного upsert по cover-ключу и не добавляет
ревизий блока.

---

## 6. Единый реестр/история для Summary L1/L2/Cover (§9.A сценарий 6)

Read-only снимок идентичностей (реестр этого worktree, без текстов):

| block_id | pg_key | scope | заводская метка | sha12 | factory revision | hidden |
| --- | --- | --- | --- | --- | --- | --- |
| summary.base.single | prompts.summary_system_prompt | global | summary-cfg07a | e66c40b6acdf | fac:e66c40b6acdf | нет |
| summary.base.editor | prompts.summary_editor_system_prompt | global | summary-editor-r1025-hotfix4 | cbd95e5e2489 | fac:cbd95e5e2489 | нет |
| summary.base.narrator | prompts.summary_narrator_system_prompt | global | summary-narrator-legfix | 497732fb2f71 | fac:497732fb2f71 | нет |
| summary.base.l1_clusterizer (L1) | prompts.summary_l1_clusterizer_system_prompt | global | summary-l1-clusterizer-asap41 | 45117539651c | fac:45117539651c | нет |
| summary.base.l2_writer (L2) | prompts.summary_l2_writer_system_prompt | global | summary-l2-writer-p0-factual | 3fce4bcd6370 | fac:3fce4bcd6370 | нет |
| summary.cover.style | prompts.summary_cover_style | global_chat | cover-style-default | 19d2dd88086e | fac:19d2dd88086e | нет |
| summary.cover.style_id | prompts.summary_cover_style_id | global_chat | — (код-блок без текста) | — | — | **да** |
| summary.l1.anchors / summary.l2.reviewer / summary.l2.reviser | — (код) | code | summary-*-w2a | … | fac:… | нет |
| cover.scene_verify / internal.image_stage / internal.image_probe | — (код) | code | *-w2a | … | fac:… | нет |

Вывод по сценарию 6: L1, L2 (и clusterizer/anchors/reviewer/reviser), Cover Style
и профиль `summary.cover.style` идут через **тот же** единый реестр
(`prompt_registry`) и тот же `/api/prompts/{key}/versions` + `/source` + `/diff`
+ `/activate`; в редакторе промптов «Стиль обложки» виден сразу (не спрятан в
advanced). Расхождения (не блокеры этой полосы):

* `prompts.summary_cover_style_id` — `hidden`-ключ (выбор профиля обложки):
  история/просмотр доступны, но активация из админки = 422
  (`manageable=false`) по действующему правилу «один источник правды —
  модуль Cover Style». Это задумано, не дефект;
* кодовые блоки (`summary.l1.anchors`, `summary.l2.reviewer/reviser`,
  `cover.scene_verify`, `internal.image_*`) — `scope=code`: история и diff
  доступны, активация 422 «нет переключаемого значения» (по контракту §1.5);
* блок «События включения» пока без даты (см. §3) — требуется строка UI-полосы.

Снимок прод-БД **не читался**: у этой полосы нет авторизованного канала к
прод-PostgreSQL (SSH-доступ к проду ограничен правилами fail2ban, и запись/чтение
прод-БД не входит в задачу Builder). Read-only запрос для владельца деплоя
(без тел промптов):

```sql
SELECT block_id, scope, chat_id, origin, content_sha12, factory_revision,
       release_id, actor, reason, retired, created_at
FROM prompt_revisions
WHERE block_id IN ('summary.cover.style','summary.base.l1_clusterizer',
                   'summary.base.l2_writer','summary.base.single')
ORDER BY block_id, created_at;

SELECT block_id, scope, chat_id, kind, outcome, revision_id,
       factory_revision_applied, release_id, actor, detail_code, created_at
FROM prompt_activations
WHERE block_id = 'summary.cover.style'
ORDER BY activation_id DESC LIMIT 50;
```

---

## 7. Тесты и доказательства

Новый файл `tests/test_asap_prompt_history_integrity.py` (10 тестов; один
гейтится `ADMINBOT_TEST_PG_DSN`):

| Тест | Что доказывает |
| --- | --- |
| `test_versions_ok_on_pg_shaped_journal` | HTTP 200 + `chars` на PG-форме строк (регрессия 500), тел в ответе нет, `scope`/`chat_id` есть |
| `test_list_versions_service_on_pg_shape_keeps_origin_scope` | manual/factory/legacy, автор, даты ревизий и события |
| `test_versions_503_when_journal_is_missing` | нет журнала/PG → 503, не `200 []` |
| `test_versions_503_on_journal_read_error` | сбой чтения → 503, пустого списка нет |
| `test_list_versions_raises_journal_unavailable` | сервисный контракт отказа |
| `test_activation_events_carry_time` | `activations[].created_at`, `activation_time_available=true` |
| `test_rollback_and_forward_keep_previous_versions` | откат/вперёд: набор ревизий неизменен, события обоих видов |
| `test_restart_keeps_manual_cover_style` | рестарт без новой метки не переписывает cover-промпт |
| `test_editing_other_prompt_does_not_write_cover_style` | нет upsert/ревизий cover-ключа при правке другого промпта |
| `test_history_on_live_postgres_has_chars_and_dates` (skip без DSN) | реальный SQL `length(body) AS char_count`, дата активации, отдельная схема, `DROP SCHEMA` в finally |

Изменения в существующих тестах (осознанные, не «подгонка»):
`test_evol017_prompt_history_ui.py::test_versions_have_no_bodies_or_secrets` —
`activation_time_available` теперь `True` (время события реально есть; прежнее
`False` утверждало отсутствие даты, что противоречит новому контракту аудита);
`test_round1025_f8_registry.py` — переутверждён `ROUTES_SHA256_F11` с
комментарием-обоснованием (тест сам требует осознанного re-pin; новых
endpoint'ов нет, RBAC/маскировка не менялись).

Прогоны (локально, venv `C:\Code\Python\adminbot\.venv`):

```
tests/test_asap_prompt_history_integrity.py                       10 passed (с DSN; 9 passed + 1 skip без DSN)
tests/test_evol016_prompt_activation.py (ADMINBOT_TEST_PG_DSN)     23 passed (живой PG-тест не skipped)
+ test_evol017_prompt_history_ui, test_evol016_prompt_journal_v39,
  test_round1025_f8_registry                                        75 passed, 2 skipped
+ test_webapp_api, test_evol018_prompt_audit, test_prompt_migrations,
  test_evol012_barrier_retired, test_webapp_evol_w11_controls,
  test_p0_prompts_core, test_summary_asap21_prompt_migrations,
  test_soul1_factory_defaults, test_soul1_core_registry_api         318 passed
```

**Живой PostgreSQL (одноразовый контейнер `postgres:17-alpine`, порт 55432,
удалён после проверки), фактический вывод:**

```
PG list_revisions: [('rev-legacy-real', 59, True), ('rev-factory-real', 31, True),
                    ('rev-manual-real', 50, True)]          # (id, chars, body=="")
OLD-CODE on real PG -> AttributeError : 'coroutine' object has no attribute 'body'
list_versions OK | revisions: [('legacy',59,'global'), ('factory',31,'global'), ('manual',50,'global')]
active: {'revision_id': 'rev-manual-real', 'origin': 'manual', 'chars': 50, 'created_at': '2026-10-31 20:21:47.428579+00:00', ...}
activations: [('manual_edit', '2026-10-31 20:21:47.432671+00:00')]
OK: rollback/forward сохраняют все версии
```

Первая строка — доказательство исходного дефекта на реальных данных, вторая
часть — доказательство исправления (длина, дата, scope, откат/вперёд) на живом
PG, а не на двойнике.

**Классификация посторонних падений (не мои, pre-existing):**

```
tests/test_soul1_w6_speech_ui.py — 3 failed
  test_entry_lives_inside_ai_without_reworking_navigation
  test_screen_has_required_sections_and_single_screen_mode
  test_long_lines_scroll_inside_components_and_oauth_targets
причина: в web/index.html HEAD нет анкоров data-speech-entry / data-speech-*
(экрана «Речь и характер» в разметке нет). Файлы web/index.html и web/app.js
этой полосой не изменялись (git diff по ним пуст) → дефект другой полосы.
```

---

## 8. Остаточные риски и что осталось

1. **Прод-снимок ревизий не снят** (нет авторизованного канала к прод-PG).
   Форма снимка и read-only SQL даны в §6; после деплоя история открывается
   штатно, прошлые редакции восстанавливаются откатом.
2. **UI «События включения»** пока не показывает дату события (API-поле
   `created_at` готово) — задача UI-полосы (`web/index.html`).
3. **Нет оптимистичного токена у активации**: два одновременных клика дают две
   записи событий и «последний побеждает». Данные не теряются, всё аудируется;
   явный 409 потребовал бы нового контракта API+UI — не вводил самовольно.
4. Тела ревизий больше не попадают в ответ списка; `chars` приходит из SQL.
   Если у стора нет `chars` (сторонний двойник), длина считается по `body` —
   деградация безопасная, не 500.

---

## 9. Итог (3 строки)

История версий падала с 500 из-за `_revision_chars`, где async `get_revision`
вызывался без `await`: на PG список ревизий не отдаёт тело, поэтому ошибку
видели только реальные данные, а тесты на memory-сторе её скрывали.
Исправлено: длина берётся из SQL (`length(body)`), сбой журнала отдаёт честный
503 вместо пустого массива, события активации получили дату и scope, активация
читает состояние под транзакционным локом; рестарт без новой заводской метки
по-прежнему ничего не переписывает — доказано на живом PostgreSQL.
Осталось за UI-полосой: показать дату события включения и визуально подтвердить
историю на реальной записи `prompts.summary_cover_style`.
