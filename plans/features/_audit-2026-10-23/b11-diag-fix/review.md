# B11-DIAG-FIX — независимое ревью `3334141a`

**Вердикт: PASS (можно в поезд 2.58.112).** Блокирующих замечаний нет.
`REQ-B11-E2E` остаётся `READY_FOR_LIVE`: нужен один post-deploy read-only прогон
исправленного инструмента по прод-БД. Этот коммит сам по себе не закрывает
live-требование и не даёт права помечать его `VERIFIED`.

Кандидат: `3334141a5ba2f57323a1e974df607e668a83e0da`.
Файлы инструмента и теста на HEAD `5877810d` идентичны кандидату
(`git diff 3334141a HEAD -- tools/v63_b11_mechanisms_report.py
tests/test_asap8_v63_b11_report.py` — пусто), поэтому проверки ниже привязаны
и к коммиту, и к текущему рабочему дереву.

## 1. Приёмка по пунктам

| # | Пункт | Итог | Чем подтверждено |
|---|---|---|---|
| 1 | Регистронезависимая классификация статусов | **закрыто** | свой прогон матрицы 19 значений + код |
| 2 | Провал публикации при успешном state → `attention` | **закрыто** | прямой вызов `diagnose` (в т.ч. `publication_status="FAILED"`) |
| 3 | Backlog: `backlog_status`/`backlog_reason`, честное число, без `0`-подмены | **закрыто** | независимый прогон probe на реальной vec0 + пустая БД |
| 4 | Скоуп: только инструмент/тест/evidence | **закрыто** | `git show --name-only 3334141a` |
| 5 | Независимые прогоны 22 / 103 / RED | **закрыто, с уточнением к формулировке RED** | см. §2 |
| 6 | Риски из отчёта | **не блокируют поезд**, один требует follow-up | см. §3 |

### 1.1 Регистр (пункт 1)
Моя матрица (`diagnose`, вход `last_attempt`):

`DONE|done|OK|ok|Completed` → `ok`; `FAILED|failed|CANCELLED|cancelled|CANCELED|INTERRUPTED|ERROR|error|"  FAILED  "` → `attention`;
`DEGRADED|degraded|PARTIAL` → `degraded`; `""|ARCHIVED_LEGACY` → `unknown`.
Плюс `status_semantics="classification"` (`self_model`, `self/ambiguous`) → не `unknown`.
Ни один провал не стал зелёным.

### 1.2 Публикация (пункт 2)
`DONE + publication=failed` → `attention`; `DONE + publication=FAILED` → `attention`;
`DEGRADED + publication=failed` → `attention`; `DONE + publication=published` → `ok`.

### 1.3 Backlog (пункт 3)
- vec0 есть (реальная `vec0`-таблица, 3 факта / 2 вектора): `backlog_missing_embedding=1`,
  `backlog_status="ok"`, `backlog_reason=null`. Независимо повторил probe — число честное.
- vec0 нет: `null` + `backlog_status="unknown"` + причина `no such table: graph_facts_vec`.
- `not_instrumented` реализован (spec без `backlog_sql`), но для текущих 10 механизмов
  недостижим: `backlog_sql` есть только у `graph_memory`/`embeddings`. Это защитный код, не дефект.
- Подмены `unknown` на `0` нет; «запись: …» в человекочитаемом выводе больше не молчит —
  добавлена строка `backlog (без эмбеддинга): …`.

## 2. Независимые числа

| Прогон | Результат |
|---|---|
| `tests/test_asap8_v63_b11_report.py` на кандидате | **22 passed** (6.97 s) |
| 5 смежных наборов (analytics_viz, pipeline_analytics, webapp_analytics_api, memory_health, memory_health_round1019) | **103 passed** |
| Probe (FAILED/DEGRADED/DONE + vec0) | `attention / degraded / ok`, backlog `1` + `ok` — воспроизведено мной |
| RED на родителе | см. ниже |

**Уточнение к RED (не блокирует).** На чистом родителе `b1525b60` новый тест-файл
**не импортируется**: `ImportError: cannot import name 'DIAG_DEGRADED'` — новых
констант там нет. Поэтому заявленные в отчёте «5 failed / 17 passed на исходном коде»
буквально не воспроизводятся. Если добавить в родительский инструмент **только две
константы** (`DIAG_DEGRADED`, `DIAG_UNKNOWN`, без логики), получается ровно
**5 failed / 17 passed** — совпадает с отчётом, падают именно 5 новых регрессионных тестов.
Сам дефект я подтвердил отдельно: старая логика на `state='FAILED', publication='failed'`
возвращает `ok` (`assert 'ok' == 'attention'`). То есть суть RED верна, формулировка
«на исходном коде» — неточная. Рекомендация: в отчёте писать «RED при откате логики
(константы на месте)».

## 3. Оценка рисков из отчёта

1. **`sqlite_vec` в venv инструмента — не блокирует.** В `.venv` стоит `sqlite-vec 0.1.9`;
   в `requirements.txt:18` — `sqlite-vec>=0.1.2`. Проверил колесо 0.1.2: `loadable_path()`
   в нём уже есть, то есть нижняя граница требований совместима с кодом. Если на проде
   пакета всё же нет — инструмент честно отдаст `unknown` + причину, а не `null`/`0`.
2. **`job cancelled` → `never_run` — формулировка в отчёте неточна, и случай шире.**
   Job-ветка `diagnose` (`tools/v63_b11_mechanisms_report.py:703,718,723`) по-прежнему
   сравнивает `task_jobs.status` **регистрозависимо** и знает только
   `queued/running/failed/interrupted/completed`. Реальные прод-значения шире:
   `paused_rate_limit`, `validation_failed` (`prod-checks/raw/main.txt:176,201`),
   `cancelled`, `finished`. Мой прогон: job `cancelled`/`paused_rate_limit`/`finished`/
   `validation_failed` + более ранняя успешная попытка → **`ok`**, а не `never_run`
   (job `FAILED` в верхнем регистре → тоже `ok`). Это **pre-existing** и не влияет на
   разобранный дефект Summary (у Summary `last_job=None`), поэтому поезд не блокирую,
   но рекомендую отдельным маленьким патчем: `casefold` для job-статуса + явный
   не-зелёный код для `cancelled/paused_*/validation_failed/finished`, 1 тест.
3. **`analytics_viz._effective_status` для `unknown` — не блокирует.** Новые коды
   `degraded/unknown` живут только в этом инструменте; `analytics_viz` читает
   `mca_events.outcome`, а не `diagnosis.code`. Пересечения нет, W4-UI не задет.

## 4. Замечания (все nonblocking)

- **N1 (medium, pre-existing).** См. §3.2: зелёный `ok` при последнем job
  `cancelled/validation_failed` и старой успешной попытке. Точное место — job-ветка
  `diagnose`. Минимальная правка и один тест; на текущий аудит не влияет.
- **N2 (low).** В отчёте §5 утверждение «`summary_run_stages.status` … пишется в нижнем
  регистре» неверно: в проде есть `LEGACY_FALLBACK` (верхний) и `degraded_map_fallback`.
  На инструмент не влияет (он эту таблицу не читает), на выводы `pipeline_analytics`
  по equality-сравнениям `failed/degraded` — тоже нет. Поправить формулировку.
- **N3 (low).** Словарь не покрывает `mca_events.outcome` `silent/skipped/pending_external/start`
  и `mca_experience.outcome_kind='unknown'` — они дадут жёлтый `unknown`, а не отдельный
  код. Это консервативно и не создаёт ложного зелёного; можно уточнить позже.
- **N4 (low).** `local-db-human.txt` — прогон по непригодной локальной БД
  (`no such table: graph_facts`, все секции `unavailable`), поэтому прод-форму графа он
  не доказывает. Сильнейшее доказательство — `probe_fixed.py` с настоящей `vec0`
  (воспроизвёл). Реальные 4162 на проде этим коммитом не проверены.

## 5. Скоуп

`git show --name-only 3334141a`: `tools/v63_b11_mechanisms_report.py`,
`tests/test_asap8_v63_b11_report.py` и 8 файлов evidence в
`plans/features/_audit-2026-10-23/b11-diag-fix/`. Ни `services/`, ни `web/`,
ни `database.py`, ни конфигов. Runtime-поведение прод-бота не меняется — риск выката
нулевой, откат не требует миграций.

## 6. Обязательный follow-up (вне write-scope лейна)

1. После деплоя — **один read-only прогон** на проде:
   `python tools/v63_b11_mechanisms_report.py --db <prod local_database.db>`.
   Ожидается: `Summary scheduler — attention`, реальное число backlog (на момент аудита
   было 4162) либо честный `unknown` с причиной.
2. В карте `asap8-v6-3-live-correction` evidence для `REQ-B11-E2E` —
   `"8 ok / 2 never_run"` (candidate `c2775a54`) — это и есть **ложный** прод-отчёт.
   Его нельзя оставлять как доказательство: заменить результатом прогона из п.1.
   Статус оставить `READY_FOR_LIVE` до этого прогона.

## 7. Ограничения ревью

Прод/SSH не трогал (запрещено брифом); реальные прод-значения backlog и фактический
вывод исправленного инструмента на прод-БД не наблюдал. Вывод об успехе опирается на
код, тесты и локальное воспроизведение прод-строки.
