# VMQ-MEM / VMQ-MEM-TIME — корпусный прогон Slice C (15.11.2026)

Read-only проверка кода Slice C `16931216` (ветка `vmq/mem-c`, tip `8bc2bcf7`)
против кода Slice B `d159ea8a` (ветка `vmq/mem-b`, tip `182fcbf9`) на копии
прод-архива. Деплоя не было: до и после прогона `HEAD=c97c06e4…`, ветка
`release/smart-corrective-01`, `healthz` `200 / 2.58.203`, `NRestarts=0`,
`ActiveEnterTimestamp: Sat 2026-11-14 18:56:49 UTC`. Сообщений в чат не
отправлялось, живые данные не писались, сервис не перезапускался.

Свидетельство для Reviewer/PM. Приёмка строк карты этим файлом не объявляется.

## 1. Что прогонялось и на чём

| параметр | значение |
|---|---|
| baseline (Slice B) | `d159ea8ad8362616ec78b43cb64a3e54ec7de2e6` (tree `c0d93fb9…`) |
| candidate (Slice C) | `16931216ab0015b4a3001c9947768305517e46eb` (tree `7fc79ec9…`) |
| merge-base | `d159ea8a…` (Slice C — один код-коммит поверх Slice B) |
| прод (не менялся) | `c97c06e4` / 2.58.203 |
| корпус | чат `-1002661910336`, 2 075 744 сообщения; эпизоды 83 (2023) / 92 (2024) / 9 (2025) / 16 (2026) |
| эпизоды всего | 200 — ровно на кап view (200), т.е. окно покрытия = весь набор эпизодов копии |
| БД-копия | `sqlite3 .backup` из read-only соединения; sha256 `4e644e52…afdd`, 3 279 290 368 байт |
| пояс чата | `Asia/Yekaterinburg` (`global_legacy`) |
| конфиг (effective) | frozen, 13 ключей; `graph_rag_facts_limit=10`; `chat_rag_rerank_enabled=true`; гейты `evidence_bundle=true`, `episodes=true` |
| интерпретатор | `/var/www/admin_bot/venv/bin/python`, Python 3.12.3 |

Копия снята в этой сессии; `USER_VERSION`/размер/sha зафиксированы
(`out/dbcopy.sha256`). Живой архив вырос с Slice B (было 2 075 717), поэтому
счётчики сообщений отличаются — числа выше относятся к копии, а не к «сейчас».

## 2. Метод

Взят закоммиченный харнесс `evidence/vmq-mem/harness-2026-11-15/`
(`entities.py`, `cfg_probe.py` — залиты на хост без изменений) и probe Slice B
как метод. Добавлен только invocation-слой Slice C (`probe_slice_c.py`):

* тот же набор запросов, что в Slice B: `A1` точный owner-запрос, `A1P`
  обычный двойник, `D` 2023, `T2` без сигнала, `T3` «что сейчас», `P1`
  profile/reply, `E` отношения;
* каждый `_build_rag_block` идёт через реальный шов, `retrieve` обёрнут
  spy: для каждого вызова записаны `include_overview`, `period_intent`,
  поля результата и **полный bounded overview** того же `RetrievalResult`;
* проверяется идентичность объекта: `_rag_overview_result is <первый
  retrieve этого блока>` (`overview_result_is_first_retrieve`);
* строится **настоящий** `EvidenceBundle` тем же вызовом
  `_build_evidence_bundle(..., retrieval_result=_rag_overview_result)`;
  записаны `coverage`/`independent_periods`/`counterexamples`/`limitations`;
* чтения эпизодов (`list_episode_views`, `subject_longitudinal_view`)
  считаются только вокруг сборки блока памяти;
* покрытие overview сверено независимой SQL-проекцией того же документированного
  окна (`ORDER BY updated_at DESC LIMIT 200`, год = `COALESCE(event_end_ts,
  event_start_ts)` в поясе чата) и существованием каждого `episode_ref`.

Один конфиг (frozen, паритет с `corpus-run-2026-11-15`); route-конфиг с
ключами эмбеддингов не прогонялся — векторная нога и так остаётся
отдельной/UNVERIFIED.

## 3. Триггер: базовая эвристика → структурный intent

| запрос | baseline `is_history_query` | candidate `PeriodIntent` (`auto`) | overview в candidate |
|---|---|---|---|
| `A1` «напиши юмористический рассказ об основных шизах конфы» | **false** | `historical` / `query_marker` | **да** |
| `A1P` «что за шизы были на конфе?» | false | `none` | нет |
| `D` «…в 2023 году» | false | `explicit_year` / `query_year` (2023) | да |
| `T2` событие без года | false | `none` | нет |
| `T3` «что сейчас происходит с …?» | false | `none` | нет |
| `P1` «что ты знаешь про …?» | false | `none` | нет |
| `E` «как менялись отношения и взгляды за эти годы» | false | `historical` / `query_marker` | да |

## 4. Обязательные случаи

| # | случай | статус | основание |
|---|---|---|---|
| 1 | точный owner-запрос: candidate запрашивает overview, Writer/bundle получает слоты из ТОГО ЖЕ результата | **PASS** | baseline: `include_overview=false`, 0 чтений эпизодов, overview нет, слоты bundle пусты. Candidate: `include_overview=true` только на базовом вызове (флаги `[true,false]`), overview на первом результате (`is_first_retrieve=true`), bundle получил `["2023: эпизодов 83","2024: эпизодов 92","2025: эпизодов 9","2026: эпизодов 16","границы: 01.02.2023 — 01.09.2026"]`, `independent_periods=["2023","2024","2025","2026"]`, 5 контрпримеров, 8 ограничений |
| 2 | «что сейчас»/non-history: нет overview, нет лишних чтений эпизодов, блок памяти не изменился | **PASS** | 1 retrieve в обеих ветвях, `include_overview=false`, overview нет, чтений эпизодов 0/0, те же 10 id, те же годы (10/10 2026), тот же размер блока (321 символ) |
| 3 | один retrieve/один bundle: overview питается тем же результатом | **PASS** | retrieve-вызовов столько же, сколько в baseline (A1 2/2, T3 1/1, D/E 2/2); overview только на первом (базовом) вызове; `_rag_overview_result` — это объект первого вызова; второго чтения ради обзора нет |
| 4 | покрытие не выдумано | **PASS с границей** | независимая SQL-проекция: `periods_match=true`, лишних периодов 0, непокрытых 0, `episode_refs` 20/20 существуют, `unknown_time=0`; `complete=false`, `complete_reason=archive_bounds_unknown` — полнота архива не объявляется |
| 5 | вектор — отдельно | **UNVERIFIED (как и было)** | во время прогона живой провайдер дал `EMBED_API_FAILED provider_unavailable`; `vec.available=true`, но живого KNN-участия нет |

## 5. Что именно попало в Writer-bundle (candidate, A1)

* `coverage`: 4 строки периодов + границы (01.02.2023 — 01.09.2026), это
  ровно SQL-подтверждённые 83/92/9/16;
* `independent_periods`: 2023, 2024, 2025, 2026 (внутри заявленного покрытия);
* `counterexamples`: 5 пар (bounded), `limitations`: 8 кодов, среди них
  `coverage_complete_unknown_until_archive_bounds_proven`,
  `missing_period_means_no_episode_not_no_event`,
  `periods_are_calendar_buckets_not_entities`,
  `episode_source_integrity_partial`, `episodes_stale`, `repeated_claims_present`;
* `episode_refs` 20, `support_source_refs` 20, `independent_support_count=956`,
  `repeated_claims=9`;
* текст ответа не смотрелся и не нужен: проверены только поля и доставка.

Память (`<RAG_Memory>`) при этом не изменилась: те же 10 id
(2023:1, 2024:1, 2026:8), тот же размер блока 1220 символов, как в baseline.

## 6. Наблюдения и границы

1. `D` (2023) и `E` («за эти годы») тоже получают overview в candidate, хотя
   baseline не запрашивал: это следствие структурного сигнала (явный год,
   повествовательная форма), а не нового списка слов. Блок памяти в обоих
   случаях совпал с baseline по id/годам.
2. `T3 + historical_recall` (явный план): candidate запрашивает overview и
   делает 2 чтения эпизодов; baseline — нет. Это решение плана L1, а не
   словарь потребителя; обязательный негатив (без сигнала) выполнен.
3. Ограничение харнесса: per-class SQL-сверка покрытия записалась как
   `no_overview` (поле читалось по неверному пути `item.overview_on_result`
   вместо `item.rag.overview_on_result`). Сверка выполнена на двух
   plan-flow строках с тем же chat-scope окном: `periods_match=true`,
   refs 20/20; у `A1`/`D`/`E` в overview те же самые 2023:83/2024:92/9/16.
4. `episodes_total == 200 == кап view` — на этой копии окно покрытия равно
   всему набору эпизодов; усечения сверх капа нет. При росте архива окно
   останется bounded, и это будет видно как неполнота, а не как полное покрытие.
5. Копия ≠ живой процесс: `Global_Context`, hot-cache, реранк/LLM и генерация
   ответа не участвовали. Один чат, одна формулировка на класс, один прогон
   на вариант — статистики нет.

## 7. Воспроизведение

* этот отчёт;
* `corpus-run-slice-c-2026-11-15.json` — идентичности, конфиг, триггеры,
  классы baseline/candidate, overview-поля, слоты bundle, равенство id/блоков,
  SQL-сверка покрытия, хеши сырых артефактов; sha256 файла
  `d5ace2a5…` (см. `git show` фиксации);
* харнесс: `harness-2026-11-15/probe_slice_c.py`, `driver_slice_c.sh`
  (probe — производный от `probe_slice_b.py`: добавлен только invocation-слой).

Сырые артефакты (на хосте удалены после переноса):

| файл | sha256 |
|---|---|
| `base_frozen.json` | `4e351d164cbb199b75c15f66f221cbac4524c69fb578e513e4b36bfbe66ec808` |
| `cand_frozen.json` | `85ea4301de2fb8112c653c26dbb4ebe5dc657a96a19d3e18d01dbba38f55c8e9` |
| `cfg_frozen.json` | `b7bf1e977b99052cea196312001e87ed16edf01b01b325e82196f0429abfe4e7` |
| `entities.json` | `5d0890d0495a4a7cb98aa9081381898b83d05ada69a9a76cb73f630353840fc3` |

Порядок (одна SSH-сессия): клоны `--shared` из `/var/www/admin_bot` →
`fetch origin vmq/mem-b vmq/mem-c` → checkout `d159ea8a` / `16931216` →
свежая `.backup`-копия → `entities.py` → `cfg_probe.py` → `probe_slice_c.py`
для базы и кандидата → sha256 и base64+gzip-перенос в той же сессии →
удаление каталога прогона → повторная проверка `HEAD`/`NRestarts`.

## 8. Housekeeping

* на сервере удалён `/root/vmqC` целиком (клоны, копия БД, скрипты, логи);
  `pgrep` не находит probe; свободно 20,3 ГБ после удаления;
* первая попытка прогона была прервана ошибкой самого опросчика (строка
  команды содержала маркер `DONE`, очистка сработала раньше сбора); данные
  не пострадали, прод не менялся, прогон повторён целиком с исправленным
  опросом — это зафиксировано, чтобы числа выше не путались с первой попыткой;
* бэкапы и прод-ассеты не трогались; прод-дерево до и после — `dirty=1`
  (существующая запись, прогон её не менял);
* локальный run-каталог закрывается после переноса доказательств.

## 9. Что остаётся открытым

1. Живая векторная нога (KNN с рабочим провайдером) — **UNVERIFIED**;
   в этом прогоне провайдер отвечал `provider_unavailable`.
2. Приёмка строк карты (MEM-03/04, TIME-01/02/03/04/06) — за PM/Reviewer;
   этот отчёт даёт корпусные числа, но не приговор.
3. Live-доставка overview в реальном ходе (после деплоя) — не проверялась:
   деплоя не было.
