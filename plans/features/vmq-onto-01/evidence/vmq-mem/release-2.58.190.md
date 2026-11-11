# Release 2.58.190 — VMQ-MEM основания решений (структурная проверяемость)

**Кандидат:** `c4c01a1f47481e77ec369fcbf350f7d0b2f4b3ac` (`fix/memory-grounds-provenance`,
три цикла ревью: `fef3b23b` → `cbec7f02` → `c4c01a1f`).
**База:** `edd7d47255c36ec5ce4504a086c5db87798518cf` (2.58.189).
**Задеплоено:** `7c3c01b23ae8e5510229cdc531ebd529f5b1ddbe` (`release/2.58.190`),
HEAD на сервере прочитан обратно = `7c3c01b2…`.
**Схема:** `user_version=47`, DDL=0, миграций нет, файлов миграций не добавлено.

## 1. Сборка среза

`release/2.58.190` создана от `edd7d472`; коммиты кандидата черри-пикнуты по порядку
(`-x`): `581a1ef4` (fef3b23b), `add8f3ff` (cbec7f02), `cd4a54a8` (c4c01a1f) — без конфликтов.
Затем bump версии `7c3c01b2` (30 файлов, 31/31 строка — только версия).

Аддитивность проверена механически по двум общим файлам (`direct_chat_service.py`,
`turn_trace.py`): множества добавленных/удалённых строк кандидата применены дословно,
изменения 2.58.186–189 не потеряны и не откатаны.

**Диффстат `edd7d472..7c3c01b2`: 39 файлов, +2220/−48**
= 9 файлов кандидата (+2189/−17) + 30 файлов пинов (+31/−31).

| Проверка | Результат |
|---|---|
| `services/permissions.py` | `e20d46ebf159` — байт-в-байт как в `edd7d472` |
| `web/api/avatars.py` | `3b8be940b539` — байт-в-байт |
| `web/api/deps.py` | `509b387d4894` — байт-в-байт |
| `web/api/routes.py` | `de3d57d656db` — байт-в-байт (дайджест F11 не переутверждается) |
| `f8_baseline.json` | `2ae1a9b6b5ee` — байт-в-байт |

Файл `services/mca_experience_jobs.py` входит в дельту: он часть отревьюенного кандидата
(правки в `cbec7f02` и `c4c01a1f`), 50 строк — проброс происхождения в job-слое.

## 2. Проверки до выката

| Набор | Результат |
|---|---|
| `tests/test_evidence_grounds_persistence.py` (новый) | **23 passed** |
| потребители `evidence_independent_count`: `test_mca04a_provenance_round1027`, `test_graphrag_memory`, `test_memory_attribution` | **281 passed** |
| `test_ur_f_inspector_step1` | **59 passed** |
| `test_ur_f_inspector_step2` | **19 passed** |
| `test_ur_f_inspector_step3_ui` | **44 passed** |
| `tests/js/ur_f_inspector_step3_test.js` | **UR-F-STEP3-OK** |

Release-gate `requirements_gate.py check --stage release` на карте `vmq-onto-01`
(strict_evidence, 380 строк):

```
FAIL: candidate mismatch; map candidate_commit must match --candidate
FAIL: VMQ-A-01: mandatory not ['VERIFIED'] (got PENDING)
...
stage=release inventory=380 manual=69 scoped=70 errors=73
```

Ненулевой результат — состояние карты, а не кода: `candidate_commit` в карте указывает на
`709865f6` (2.58.183), а все 380 строк остаются `PENDING`. Тот же класс, что записан для
2.58.187 (`errors=68`). Привязка карты — работа PM; этот релиз ею не сертифицируется.

## 3. Выкат

| Шаг | Значение |
|---|---|
| Преддеплойный снимок БД | `backups/predeploy-258190-20261111T145101Z.db` |
| Размер / sha256 | 2 368 585 728 байт / `c66fcf3947e1c68269936b1b11de45420042ae2e8524c8af9abcfa2697c50e23` |
| Read-back снимка | `integrity_check=ok`, `user_version=47`, таблиц 130, `graph_facts=25665`, `mca_lessons=663`, `mca_events` max rowid 268184 |
| Checkout | `git fetch` → `git checkout --detach 7c3c01b2`, HEAD прочитан обратно = цель |
| Перезапуск | `systemctl restart admin_bot` → `active`, `NRestarts=0`, active since 14:51:45 UTC |
| `/healthz` | `{"status":"ok","version":"2.58.190"}` |
| Логи 20 мин | `TRACEBACK=0`, `CRITICAL=0`, `ERROR=0` |
| Живая БД после выката | `integrity_check=ok`, `user_version=47`, `mca_lessons=663`, `graph_facts=25665` — данные не менялись |

## 4. Проверка фикса на реальных данных (read-only, копия живой БД)

Чат `-1002661910336` (450 уроков, из них 5 с пустым `independent_sources`):
`learning_analytics.lessons.items[]` несут `grounds[]` с первичными id источника и
происхождением, `independent_grounds` посчитан, `stems_shared` — `null` с причиной:

```
LESSON_ITEM_0={"lesson_id":"07d4dea4704142deb28f6a6df406c71c","version":1,"status":"active",
 "type":"social_preference","scope_chat_id":-1002661910336,"confirmation_count":1,
 "grounds_total":1,"grounds_truncated":false,"distinct_ground_roots":1,
 "independent_grounds":0,"grounds_state":"complete",
 "gaps":["author_unknown","origin_unknown"],"confirmation_count_mismatch":false}
GROUND_0_0={"provenance_root":"sqlite:message:9767:-1002661910336","source_ref_id":42854,
 "entity_type":"message","entity_id":"9767","chat_id":-1002661910336,
 "tg_message_id":1024497,"author_id":null,"origin":null,"independence":"unknown",
 "resolution":"resolved","verification":"verified","supports_kind":"lesson",
 "supports_id":"07d4dea4704142deb28f6a6df406c71c","channel":"evidence_link",
 "stems_shared":null,"stems_shared_reason":"not_lexical_path"}
CONSISTENCY_VIOLATIONS=[]
```

`entity_id` — значение из хранилища (row id сообщения), `tg_message_id` — разрешённый
telegram-id: row id больше не выдаётся за telegram-id. Независимость основания в этих
записях честно `unknown` (`origin` в БД `NULL`), `stems_shared` честно `null` +
`not_lexical_path` — у основания-урока нет лексического пути. Публикация `memory_grounds[]`
в событии выбора после выката не наблюдалась: **0 ходов** с момента рестарта
(всего 21 событие `direct_turn_selection`, все до выката) — ждёт реального хода.

## 5. Ремонтный инструмент — ТОЛЬКО dry-run

`tools/mca_lesson_grounds_repair.py` на копии живой БД **без `--apply`**:

```
DRY_RUN= True
SCANNED= 6
REPAIRED_COUNT= 6
REFUSED_COUNT= 0
UNCHANGED= 0
```

**Расхождение с аудитом.** Ожидание «production has zero affected rows» не подтвердилось:
в проде 6 уроков с пустым/`NULL` `independent_sources`, у всех шести сохранённые
evidence-связи есть (`would_restore` 18/1/1/1/1/3), `refused=0`. Все шесть имеют
`confirmation_count=0`; пять в статусе `suspended`/`superseded`, один `active`
(`9c97344e…`, `source_ref_id=33524`, `failure_pattern`). `--apply` не выполнялся и не
должен выполняться до решения Builder/PM о причине расхождения аудита.

## 6. Откат

```
cd /var/www/admin_bot && git checkout --detach edd7d472 && systemctl restart admin_bot
```

Объект `edd7d472` на сервере есть. Схема и данные не менялись (`v47`, DDL=0), поэтому
откат данных не требуется: снимок `predeploy-258190-20261111T145101Z.db` остаётся
страховкой, а не необходимостью.
