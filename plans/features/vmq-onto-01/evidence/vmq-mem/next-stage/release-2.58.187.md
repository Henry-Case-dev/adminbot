# Release 2.58.187 — VMQ-MEM next stage (векторная нога периодного добора)

**Выкачено:** `952b9ebd4ceb113bbd687401fa8d2cb53b93a3a9` (`release/2.58.187`, APP_VERSION `2.58.187`).
**База и откат:** `d96b24abac2ae988dd675e1347bf116767be7f16` (2.58.186).
**Одобренный кандидат:** `c698618a0c812ec51f5ffd9bcb3f5e179e3cc990` (`vmq/next-stage`, база `77a63bc5`).
**Схема:** `user_version=47`, DDL=0, миграций нет (константа `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47` на выкаченном дереве).

## 1. Как портирован

Два `git cherry-pick -x` поверх `d96b24ab`:

| # | SHA на линии релиза | Источник | Смысл |
|---|---|---|---|
| 1 | `e347b517` | `eca808c6` | векторная нога периодного добора, год-окно в FTS, порог §2, пустой вердикт, guard поколения |
| 2 | `2fc1cac0` | `c698618a` | одна периодная нога на ход, честный `period_kept` |
| 3 | `95cc5d37` | — (адаптация порта) | убран стаб `_cp_g -> None` в новом тест-файле, см. §1.2 |
| 4 | `952b9ebd` | — | bump версии и запись релиза |

### 1.1. Конфликт и разрешение (аддитивно, оба изменения сохранены)

`services/direct_chat_service.py`, два хунка:

1. **Гейт реранка.** 2.58.186 перевёл гейт на per-chat цепочку
   `if await _cp_g(chat_id, "flags.chat_rag_rerank_enabled", settings.CHAT_RAG_RERANK_ENABLED)`;
   кандидат в этой же точке вводит `period_kept_despite_empty = 0` и `protected_keys`.
   Оставлено **и** то, и другое: счётчики объявлены до гейта, гейт — версия 2.58.186.
   Второго (старого) варианта `hot.get(...)` в дереве нет — проверено grep'ом.
2. **Строка лога `direct: rag block`.** Взята расширенная версия кандидата
   (`period_kept`, `period_rejected_subject`, `period_kept_despite_empty`,
   `vector_pool_miss`, `period_vector_knn`, `period_vector_leg`, `subject_proxy`),
   плюс сохранён `out_memory`-блок инспектора UR-F из 2.58.185 ниже того же места.

### 1.2. Адаптация теста порта (утверждения не менялись)

`tests/test_memory_period_vector_leg.py` ставил `monkeypatch.setattr(dcs, "_cp_g", ... -> None)`
в двух местах. Под per-chat гейтом 2.58.186 этот стаб превращал флаг ON в OFF, реранк не
вызывался и два теста телеметрии падали (`period_kept_despite_empty=1` ожидался, приходил 0).
Стаб убран — тот же приём, что применил сам 2.58.186 в `tests/test_mem_time_policy.py`.
На собственной базе кандидата файл даёт 18/18, на линии релиза тоже 18/18.

## 2. Дельта и доказательства неизменности

Дельта `d96b24ab..952b9ebd` — **36 файлов**:

* 6 файлов среза: `services/database.py` (+28/−2), `services/direct_chat_service.py` (+281/−46),
  `services/mca_retrieval_context.py` (+177/−34), `services/summary_memory.py` (+155/−0),
  `tests/test_mem_time_policy.py` (+47/−11), `tests/test_memory_period_vector_leg.py` (+708, новый);
* `config/settings.py` (APP_VERSION + описание релиза), `plans/docs/param-registry-round1025.meta.md`;
* 24 python-пина и 4 JS-пина версии.

Проверки:

| Проверка | Результат |
|---|---|
| Список файлов `diff(c698618a, 952b9ebd)` == список файлов `diff(77a63bc5, d96b24ab)` | 67 == 67, различий нет — порт добавил только 6 файлов среза к дереву 2.58.186 |
| Непересекающиеся файлы среза (`database.py`, `mca_retrieval_context.py`, `summary_memory.py`, новый тест) | побайтово равны кандидату (0 строк diff) |
| Гейт реранка | `_cp_g`, ровно одно вхождение, идентично 2.58.186 |
| Security-блобы | `web/api/avatars.py` `3b8be940`, `web/api/deps.py` `509b387d`, `services/permissions.py` `e20d46eb` — равны базе и кандидату |
| Содержимое релиза инспектора | `web/api/routes.py` `532fda00`, `web/app.js` `118d5eae`, `web/index.html` `0e665210`, `services/turn_trace.py` `cca4233a`, `tests/test_ur_f_inspector_step3_ui.py` `2f16a999` — равны базе |
| DDL в дельте | 0 (`CREATE`/`ALTER`/`DROP` в `services/database.py` нет) |
| Схема | 47 на выкаченном дереве, 47 в БД после рестарта |

Замечание о bump'е: 24 python-пина были перезаписаны целиком со сменой переводов строк
(CRLF → LF). Смысловое изменение — одна строка версии на файл; доказано сравнением AST
базы с выкаченным деревом после обратной замены версии: `AST_EQUAL=24/24`. Функционального
эффекта нет; 858 пин-тестов зелёные.

## 3. Прогоны на точном дереве релиза

| Набор | Результат | Классификация |
|---|---|---|
| Четыре VMQ-TIME (`test_mem_time_asof/l1_scope/policy/profile`) | 78 passed | ожидаемо 78 |
| Новый `test_memory_period_vector_leg.py` | 18 passed (16 + 2 после §1.2) | 18/18 и на собственной базе кандидата |
| direct/memory/recall/summary/retrieval (121 файл) | **3129 passed, 15 failed** | те же 15 падают на `d96b24ab` (3110 passed) — все pre-existing |
| Версионные пины (24 python + 4 JS) | 858 passed, **2 failed** | оба — структурные diff-vs-baseline guard'ы (`test_tool_coordinator_round1026`, `test_unified_image_request_round1026`), красные и на базе |

Список 15 pre-existing отказов (идентичен на базе): `test_direct_fallback_recompose_asap32` (5),
`test_graphrag_rebuild_asap32` (1), `test_nostalgia_layer_a` (2),
`test_summary_coverage_ledger_asap41` (1), `test_summary_generator` (2),
`test_summary_source_window_asap41` (1), `test_summary_two_call_round1022` (3).

Release-gate `requirements_gate.py --stage release` по карте `vmq-onto-01`
(владелец — основная линия): `errors=68`, все — PENDING-строки эпика плюс один
`candidate mismatch` (в карте пока нет строки/кандидата этой ступени). Ни одного
slice-дефекта по `952b9ebd`. Привязка карты — шаг PM, здесь не выполнялась.

## 4. Выкладка

| Шаг | Факт |
|---|---|
| Снимок БД | `backups/predeploy-258187-20261111T082439Z.db`, 2 315 640 832 байта, `sha256 5569ac51eddec4dc9e8a0d86c1b38f78da6c32fd3e570cdbe3a1079f8e5543cf` |
| Read-back снимка | `integrity_check=ok`, `user_version=47`, таблиц 130, `graph_facts=25539`, `mca_events` max rowid 262701 |
| Checkout | `git fetch` → `git checkout --detach 952b9ebd`, HEAD подтверждён, трекаемых локальных правок не было |
| Рестарт | `systemctl restart admin_bot` → `active`, `NRestarts=0` |
| `/healthz` | `{"status":"ok","version":"2.58.187"}` |
| ADR-1019 на выкаченном дереве | `1 passed` |
| Ошибки после рестарта | 2 строки, обе `anticliche_worker` (fetch wikipedia) — фон, тот же рисунок до выкладки (07:36 UTC); в путях памяти/recall — ноль |

## 5. Значения после выкладки (с источником)

| Показатель | Значение | Источник |
|---|---|---|
| Версия | 2.58.187 | `/healthz`, `config.settings.APP_VERSION` на дереве |
| SHA | 952b9ebd | `git rev-parse HEAD` на сервере |
| Фабричный дефолт реранка | `True` | `settings.CHAT_RAG_RERANK_ENABLED` (модуль) |
| Переменная окружения | отсутствует | `os.environ.get("CHAT_RAG_RERANK_ENABLED")` → None |
| Глобальная настройка | `true`, `2026-09-06 14:48:01.866578+00`, категория `flags` | `bot_settings` (Postgres) |
| Чатовые override | нет ни в одном из 3 профилей | `chat_profiles.chat_params` → `rerank_override=False` ×3 |
| Эффективное значение | `True` | `services.chat_params.get_chat_param(...)` для `-1002661910336` |
| Состояние индекса (как его видит код) | `state=insufficient`, `reason_code=compat_not_proven`, `action=retry_canary`, `class=COMPATIBILITY_UNKNOWN`, `needs_probe=true`, `rows=1` | `embedding_control_plane.resolve_index_compat(..., current_fp=<live MSI>, current_dims=3072)` |
| Активное поколение | gen 1, `gemini-embedding-001`, dims 3072, `status=active`, fingerprint `96f80838…` | `mca_embedding_index_generations` |
| Причина | space совпадает (`e540d4ad890e121d`), но `conn` сейчас `d2e6314e3586c547`, а в admission — `a93485483697c3c3` | тот же compat-ответ |
| Guard ступени | **векторная нога НЕ принимается** | по правилу guard: `state == compatible` не выполнено |

**Следствие:** периодный добор в проде сейчас идёт **лексическим путём**, векторная нога
штатно деградирована с записанной причиной `compat_not_proven`. Это ровно то поведение,
которое требует дизайн ступени («пока поколение индекса `compat_not_proven`, нога
UNVERIFIED и ступень не принимается»), а не дефект кода релиза.

## 6. Реальный трафик (окно 08:24 → 09:04 UTC, после рестарта)

| Что искали | Наблюдение |
|---|---|
| События retrieval | 4 (одно `skipped/embedding_generation_changed` от фонового пути, три `success`, все `policy=auto`) |
| События с `period_fill` | **0** |
| Строки `direct: rag block` | **0** после рестарта (последняя — 10.11 21:52) |
| Турновые события | 0 |

**Честно:** реального хода direct-чата в окне не было, поэтому «одна векторная нога на ход,
k=32, ноль на operative-проходе», честный `period_kept`/`subject_proxy` и p50/p95 сборки
блока **не измерены** — вместо подстановки чисел здесь фиксируется их отсутствие.
Триггер: первый реальный ход direct-чата в одном из трёх чатов; после него read-only проба
(`mca_events` + `journalctl 'direct: rag block'`) даёт эти значения без новых изменений.

Даже при таком ходе ожидаемое наблюдаемое значение `period_vector_leg` — `compat_not_proven`
(см. §5), а не `ok`: semantic-нога не активируется до доказанной совместимости индекса.

## 7. Откат

`cd /var/www/admin_bot && git checkout --detach d96b24ab && systemctl restart admin_bot`.
Коммит отката на сервере есть (`git cat-file -e` → ok). Снимок БД — §4. Схема и данные
не менялись (v47, DDL=0), поэтому откат — только код и рестарт.
