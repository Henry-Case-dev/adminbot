# REL-258180 — выкат VMQ-MEM retrieval fixes (2.58.180) на production

Дата: 10.11.2026, 06:07–06:37 UTC. Сервер `192.255.209.205` (`vps159032-gqg`),
каталог `/var/www/admin_bot`, unit `admin_bot`.
Результат: **VERIFIED** — обязательные постпроверки пройдены, откат готов.

## 1. DEPLOY_SOURCE

| Поле | Значение |
|---|---|
| Артефакт выкладки | `721bab1000a36c55b59794c36b6aefa6322a367c`, ветка `release/2.58.180` (в origin), tree `9b2706ae` |
| Одобренный кандидат | `7bc8545a` (tree `89c5ffbc`; `846a00c0` — тот же объект дерева, `git diff` пуст) |
| База выкладки | `32e018b9` (2.58.179, то, что реально работало на проде), **не** `integ/unify-release` |
| Предыдущий прод | `32e018b9…` / 2.58.179 (точка отката) |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — выкат из immutable-коммита по SHA |
| Write scope прода | checkout `/var/www/admin_bot` (ветка `release/2.58.180`) + рестарт unit; следы в `/root/deploy-258180/` |
| Схема | **остаётся v47**, миграций нет (`schema_migrations` 36 → 36) |

### Почему не `integ/unify-release`

`git merge-base 32e018b9 7bc8545a` = `adfd0d0c`; только в прод-линии — **34** коммита
(`2.58.173`…`2.58.179`), только в ветке кандидата — **27**. Выкат ветки кандидата
откатил бы содержимое пяти релизов. Фикс перенесён cherry-pick'ом на прод-линию.

### Cherry-pick

`32e018b9` → `1f792d85` (`cherry-pick -x 7bc8545a`), затем релизная обвязка
`1f792d85` → `721bab10`. Конфликтов не было; `services/tool_router.py` слился
автоматически, потому что прод-линия держит более старый `execute_tool`
(без SELF-DIAG-01 D2). Проверено адресно:

* `git diff 32e018b9:services/tool_router.py HEAD:…` = **только** два хунка VMQ-MEM
  (`order="time"` в dig + `_dig_coverage`);
* `git diff 7bc8545a:… HEAD:…` показывает **только** отсутствующий блок
  SELF-DIAG-01 D2, который в прод и не должен попадать;
* остальные 5 продуктовых файлов и новый тест — **байт-идентичны** кандидату
  (`git rev-parse HEAD:<f>` == `git rev-parse 7bc8545a:<f>`).

## 2. Дельта `32e018b9 → 721bab10` (33 файла)

Продукт (6): `services/database.py`, `direct_chat_service.py`,
`direct_context_composer.py`, `mca_retrieval_context.py`, `summary_memory.py`,
`tool_router.py`.
Тест (1): `tests/test_vmq_mem_retrieval_fixes.py` (новый, 12 тестов).
Версии (26): `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`,
24 файла тестов-пинов версии — 27 строк заменены 1:1, ни одна не добавлена/удалена.

`services/database.py` — только аддитивная SQL/query-работа (73+/7−, 5 хунков,
все внутри `get_messages_around` и `search_messages_fts`):
keyword-only `target_row_id` (якорь по `smart_messages.id`), keyword-only
`order` + одна новая ветка bounded-плана. **DDL нет, шага миграции нет**,
блок миграций (`semantic_schedule_v47` — последняя) байт-в-байт с базой.
Чужих полос в дельте нет: список файлов выше исчерпывающий.

## 3. Прогоны тестов на релизном дереве

| Группа | Итог |
|---|---|
| `test_vmq_mem_retrieval_fixes` (новый) | **12 passed** |
| `test_mca07_retrieval_context_round1027`, `test_memory_unified_retrieval_06`, `test_memory_communities_retrieval` | **101 passed** |
| `test_direct_context_{composer,capacity,scenarios}_asap3` | **69 passed** |
| `test_tool_router`, `test_direct_chat`, `test_summary_memory`, `test_tool_schemas`, `test_mca14_schema_additive_round1027` | **312 passed** |
| Запрошенная батарея целиком (одним прогоном) | **494 passed, 0 failed** |
| Смежные швы: `test_direct_chat_{lore_inject,prompts,handlers,concurrency}` | **133 passed** |
| Пины версии (24 файла) | 630 passed, **2 failed** — см. ниже |

Классификация падений против `32e018b9` (единственные два):
`test_tool_coordinator_round1026::test_forbidden_paths_out_of_diff` и
`test_unified_image_request_round1026::test_forbidden_paths_out_of_diff_vs_baseline`.
Оба берут `git diff --name-only pre-round1026-a1` (baseline от 02.11) и падают на
**18 путях `web/`**; тот же список из 18 путей получен **на самой базе
`32e018b9`**, а срез добавляет в этот diff ровно один файл —
`tests/test_vmq_mem_retrieval_fixes.py`, и ни одного `web/`/`db/`. То есть
падения предсуществующие и срезом не внесены.

## 4. Снапшот и схема

`/root/deploy-258180/predeploy-258180.db`, 2 009 239 552 Б,
`sha256 d6db0909e740bd5bf371bd10b28dbb32d806dedbd1de32beea3594e5b7d531aa`.
Read-back совпал с живой БД полностью:

| | живая | снапшот |
|---|---|---|
| `user_version` | 47 | 47 |
| `schema_migrations` | 36 | 36 |
| `smart_messages` | 2 077 120 | 2 077 120 |
| `nodes` / `edges` / `graph_facts` | 33 772 / 66 002 / 24 258 | то же |
| `quick_check` | ok | ok |

После выката: `user_version` 47, `schema_migrations` 36 — **шага миграции не было**.

## 5. Health

| Проверка | Значение |
|---|---|
| `/healthz` loopback | 200 `{"status":"ok","version":"2.58.180"}` |
| `/healthz` публично | 200 `{"status":"ok","version":"2.58.180"}` |
| unit | `active`/`running`, MainPID 3640633, `NRestarts=0`, старт 06:09:30 UTC |
| подъём | healthz с новой версией через **6 с** после рестарта |
| дерево прода | `HEAD=721bab10`, tracked-dirty 0 |
| журнал | traceback/CRITICAL за окно выката — **0** |

## 6. Постпроверки (read-only, in-process, на живых данных)

Ни одного сообщения в чаты, ни одной записи: `DatabaseService.initialize_readonly()`
открывает БД как `?mode=ro`; `user_version`/`schema_migrations`/`smart_messages`/
размер файла до и после пробега **совпали побайтово**. Код при этом пытался писать
(в stderr видны `attempt to write a readonly database`), и SQLite отказал — это и
есть работающая гарантия read-only.

1. **`<Old_Episode>` больше не пуст.** Чат `-1002661910336`, запрос — последнее
   реальное сообщение чата. Блок **непустой**: 3 144 симв., 2 эпизода, 31 сообщение
   (второй прогон: 6 120 симв., 2 эпизода, 58 сообщений). Годы в блоке: **2026**.
   В логе видно оба пути одновременно:
   `hit=tg:1208683 … reason=gap+reply_links+cap_applied` (tg-путь цел) и
   `hit=tg:None hit_row=534 … rows=6` — принят эпизод по **`msg:<row>`**-якорю.
2. **`direct_old_episode_empty_total`.** До выката: за всё время журнала **0**
   событий `direct: old episode empty` при **272** успешных блоках
   (`direct: old episode | …`). После: в прогоне на живых данных
   `direct_old_episode_empty_total = 0`,
   `direct_old_episode_retrieval_total = 1`; за окно после рестарта —
   `EMPTY_SINCE=0`. Честная оговорка: строка
   `direct: old episode empty | pool=… ref_unresolved=…` в живом трафике прода не
   наблюдалась ни до, ни после — срабатывал tg-путь. Дефект «пул непустой, а блок
   пуст» воспроизведён контролируемым измерением ревьюера, а не живым трафиком.
3. **`dig_into_lore(year=2023)` end-to-end** через `ToolRouter.dispatch`:
   **0.385 с**, `status="ok"`, `coverage.sampling="window_scan_by_time"`,
   `coverage.truncated=true`, `coverage.messages_total=31 213`,
   `messages_shown=8`, `first_seen="2023-01-01 05:58"`,
   `last_seen="2023-12-31 23:48"`. Раньше этот путь не завершался в бюджет.
4. **`msg:<row>` доходит до payload с реальными датой и автором.**
   `msg:528`: в блоке строка
   `[15.08.2026 21:34 | <SPEAKER> [529151103] | msg:528]: …`;
   дата `15.08.2026` совпала с `smart_messages.timestamp`, имя — резолвнутое
   каскадом алиасов (`aliases.resolve(uid, author_name, None)`), совпало.
   До фикса такая ссылка отбрасывалась как `tg id unresolved`.

## 7. Откат

- Код: `cd /var/www/admin_bot && git checkout -B release/2.58.179 32e018b9 && systemctl restart admin_bot`
  (коммит на сервере присутствует — `git cat-file -e` ok).
- Данные: `/root/deploy-258180/predeploy-258180.db` (v47, `quick_check ok`, sha256 §4).
  Схема не менялась, поэтому снапшот нужен только на случай порчи данных.
- Диск после выката: 45 ГБ свободно.

## 8. Открытые находки (не блокируют выкат)

1. **Нет внутреннего timeout/fail-fast у `dig_into_lore`.** Год-окно теперь
   укладывается в доли секунды, но защита от «патологического» запроса
   (очень широкий FTS-токен + окно) отсутствует: зависание снова возможно на
   другом входе. Нужен бюджет запроса внутри инструмента.
2. **План запроса зависит от статистики.** `order="time"` выбирается
   вызывающим, а фактический план строит планировщик SQLite по
   `sqlite_stat1`; после большой миграции/`ANALYZE` форма плана может измениться,
   и стоимость снова станет пропорциональна match-set. Нужна проверка плана на
   реальном объёме после каждого крупного изменения данных.
3. **Тест формы плана держится только на крошечной БД.**
   `test_windowed_plan_driven_by_time_index` смотрит `EXPLAIN QUERY PLAN` на
   маленьком наборе; там планировщик ведёт себя иначе, чем на 2,07 млн строк,
   поэтому тест подтверждает намерение, но не боевую стоимость.
4. Предсуществующее, вне среза: два ERROR `anticliche_worker` (wikipedia
   `sources_unavailable`) в окне выката — известный дефект, к срезу не относится.
