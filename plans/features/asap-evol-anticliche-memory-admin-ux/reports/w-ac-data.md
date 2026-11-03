# AC-DATA — источники, честные статусы, revisions/freshness, LKG

Пакет: `AC-DATA` (FINAL v8 §2.1, §2.2, §3.1, §3.2, §3.3; arch §1, §7).
Ветка: `feat/ac-data-sources`, база `a9f326f8`.
Автор: Builder (leaf-исполнитель, без fan-out — один писатель подсистемы).

## 1. Что сделано

| Требование | Где реализовано |
|---|---|
| Реестр источников со стабильными id §3.1 | `services/anticliche_sources.py` (`SOURCES`, `all_sources`, `get_source`, `select_sources`) |
| Adapter contract `check / fetch` + revision/ETag/checksum | `check_source`, `_check_github`, `_check_wiki`, `_check_http_documents`, `fetch_source_documents`, `raw_document_url` |
| Таксономия §3.2 (10 статусов) + `db_error` для локального | `STATUS_*`, `STATUS_LABELS`, `status_meta`, `classify_response`, `classify_exception` |
| Отдельная пометка свежести (`stale`) | `freshness_state`, `source_view.reachability.freshness` |
| Per-source retry policy, 403 без storm, `Retry-After` | `RetryPolicy`, `parse_retry_after`, `compute_backoff_seconds`, `compute_next_attempt`, `attempt_decision` |
| Независимость источников | `check_sources` (изоляция исключений + bounded параллелизм), `_due_sources` в воркере |
| Lineage (одна upstream-база ≠ два подтверждения) | `Source.origin_repo/upstream_bases/lineage_id`, `independent_confirmations` |
| Хранение последней проверки в PG | таблица `anticliche_source_state` (`services/pg_db.py`), `fetch_states`, `fetch_state`, `record_check`, `set_enabled` |
| История проверок — существующий журнал | `emit_check_event` → `mca_events` (`component='anticliche'`, `stage='source_check'`, `operation_id=check_id`), один терминальный outcome на попытку |
| LKG и отсутствие ложных нулей | `anticliche_cache.read_active_version`, воркер возвращает реальную `version`/`rules` при любой ошибке |
| Четыре независимых вида здоровья | `reachability_health`, `content_health`, `analysis_readiness`, `runtime_health`, `build_health` |
| Read-only API для вкладок | `web/api/anticliche.py`: `GET /api/anticliche/sources`, `GET /api/anticliche/sources/{id}`, `GET /api/anticliche/health` |
| Stage A в воркере (по источнику, независимо) | `AntiClicheWorker._refresh_impl`, `_due_sources`, `check_one` |

`anticliche_worker.fetch_source` сохранён как тонкая обёртка над
`anticliche_sources.fetch_source_text` — транспорт один, второй стек не создан.

## 2. Хранилище (ровно две таблицы архитектора)

`anticliche_source_state` (последняя проверка + включённость):

```
source_id PK | enabled | last_check_at | last_status | last_http | revision |
etag | checksum | content_status | docs_fetched | docs_parsed | bytes_fetched |
last_success_fetch_at | last_success_analysis_at | last_analysis_status |
next_attempt_at | last_error_code | last_error_detail | consecutive_failures |
paused_reason | last_check_id | updated_at
```

`anticliche_snapshot` (immutable опубликованные версии + одна mutable draft):

```
version PK | state | compiler_version | checksum | source_revisions JSONB |
parent_version | publisher | published_at | effective_rule_count | rules JSONB
```

DDL идемпотентный (`CREATE/INDEX IF NOT EXISTS`), Δ SQLite = 0. Обе таблицы
заведены в `pg_db.py` сразу: `pg_db.py` — сериализованный файл (AC-DATA →
AC-PIPE), и второй DDL-владелец дал бы дрейф колонок. **AC-PIPE пишет
строки, а не создаёт таблицы.**

История (полная, не «последняя») — существующий `mca_events`; новых таблиц
истории нет. `anticliche_cache.patterns` остаётся материализованным снимком
активной версии (совместимость `get_rules()`); в элементы набора аддитивно
добавляются `source`/`source_revision` (провенанс) без DDL.

## 3. LKG — «нет правил» ≠ «не загрузилось»

`anticliche_cache.read_active_version(pg)` возвращает `{status, version,
rules, published_at, checksum, compiler_version, publisher, bank_source,
reason}`:

| status | смысл |
|---|---|
| `ok` | есть опубликованный `anticliche_snapshot` (immutable, version>0) |
| `lkg` | snapshot недоступен/отсутствует → материализованный снимок `anticliche_cache` (предыдущая версия) |
| `none` | действующего набора реально нет («Нет опубликованных правил») |
| `unavailable` | PG недоступен: `version=None`, `rules=None` — **не 0** |

Воркер при любой ошибке источника/модели/PG не пишет 0: `version` =
реальная действующая версия, `rules` = фактическое число элементов набора.
Сбой записи не меняет активный набор (кэш не перезаписывается).

## 4. Честные статусы — решения, которые нельзя «упростить»

1. **403 без признака политики ≠ `policy_blocked`.** `classify_response`
   требует положительного доказательства robot-policy (тело/`x-robots-*`),
   иначе это `auth_failed` (тест 6 §9.2). Обратное превратило бы любую
   авторизационную ошибку в «политику» и наоборот.
2. **Rate-limit сильнее 403.** `x-ratelimit-remaining: 0` / `Retry-After` /
   «rate limit» в теле → `rate_limited` (GitHub отдаёт лимит кодом 403).
3. **`policy_blocked` не ретраится автоматически.** `next_attempt_at = NULL`,
   `paused_reason='policy_blocked'`; `attempt_decision` всегда `allowed=False`
   для авто-опроса. Ручная проверка («Проверить доступ») разрешена явным
   намерением (`manual=True`) и не меняет User-Agent/IP/прокси.
4. **429 уважает `Retry-After`** (секунды или HTTP-date), ограничивая его
   `max_retry_after_seconds`; без заголовка — bounded exponential backoff с
   jitter. 5xx/timeout — тот же bounded backoff.
5. **HTTP 200 при HTML/битом JSON — не «готово».** Транспорт фиксируется
   отдельно (`http_status=200`), контент получает `parse_error`; анализ не
   помечается состоявшимся (`docs_parsed=0`).
6. **`local/manual` вне HTTP.** `transport='local'`, `http_status=None`,
   `transport_code='local'`; единственный сбой — `db_error` («ошибка БД»),
   а не сетевая ошибка и не «HTTP 200».
7. **Библиография не опрашивается.** `bib-*` — `auto_check=False`,
   `permits_analysis=False`, `counts_as_live=False`; `check_source`
   возвращает `disabled/bibliography_only`, транспорт не вызывается.
8. **`stale` — отдельная пометка свежести** (порог = действующий
   `REFRESH_DAYS`, нового конфига нет); старая зелёная проверка не выдаётся
   за доступность «прямо сейчас».

## 5. Реестр источников (сверено на реальных ревизиях 03.11.2026)

| id | тип | ревизия (live) | лицензия | по умолчанию |
|---|---|---|---|---|
| `ru-repo-a` | github | `324b1555…` | MIT (LICENSE читается как NOASSERTION из-за вводной заметки; текст MIT) | выключен* |
| `ru-repo-b` | github | `17e91018…` | MIT | выключен* |
| `ru-repo-c` | github | `35ad747a…` | MIT | выключен* |
| `local/manual` | local | — | owner-authored | включён |
| `wikipedia` | wiki_api | — (403 policy) | CC BY-SA 4.0 | включён |
| `bib-tinkoff-journal`, `bib-gramota`, `bib-textru`, `bib-yurova` | bibliography | — | not permitted / unknown | не опрашиваются |

\* Выключены **не из-за лицензии** (она проверена), а потому что
детерминированный разбор документов (Stage B: пример клише ≠ пояснение)
принадлежит AC-PIPE. Иначе markdown-справочники пошли бы в модель сырыми,
что прямо запрещено §4.2 («неясная разметка → `parse_error`/карантин, а не
фальшивые кандидаты»). Причина видна в API (`activation_note`) и снимается
одним флагом `enabled` (существующий per-source control).

**Lineage записан по документу, а не по догадке.** LICENSE `ru-repo-a`
сообщает: «Adapted in structure from blader/humanizer … informed by
Wikipedia: Signs of AI writing». Поэтому `independent_confirmations(
['ru-repo-a','wikipedia']) == 1` — это одно подтверждение, а не два.
`ru-repo-b`/`ru-repo-c` происхождение не декларируют → попадают в
`unverified_lineage`, а не считаются «независимо подтверждёнными».
README `ru-repo-c` сравнивает `blader/humanizer` как конкурента в бенчмарке —
это не происхождение, и его статистика не выдаётся за измерения Adminbot.

## 6. Живая проверка (не фикстура)

Реальный прогон адаптера (`check_source(..., manual=True)`, честный
User-Agent `adminbot-anticliche/1.0`, без PG-записей):

| источник | статус | HTTP | ревизия | документы | что видно |
|---|---|---|---|---|---|
| `ru-repo-a` | `available` | 200 | `324b1555…` | 6/6 parsed, 26 530 chars | все ожидаемые `references/*.md` существуют |
| `ru-repo-b` | `available` | 200 | `17e91018…` | 1/1 parsed, 12 058 chars | файл `ai-markers-ru.md` доступен |
| `ru-repo-c` | `available` | 200 | `35ad747a…` | 3/3 parsed, 26 824 chars | `SKILL.md` + `references/patterns.md`/`examples.md` |
| `wikipedia` | `policy_blocked` | 403 | — | 0/0 | тело: «Please respect our robot policy https://w.wiki/4wJS…» |

Это важный продуктовый факт: **Wikipedia сегодня реально отдаёт 403 по
robot policy** для нашего честного User-Agent. Старый код классифицировал
это как `fetch_error` и продолжал долбить источник каждую неделю; теперь
это `policy_blocked` без автоматических попыток (ровно §3.2/§3.3).
Обхода нет: User-Agent/IP/прокси не меняются.

## 7. Четыре вида здоровья (§2.2) — не один `ok/error`

`build_health()` отдаёт четыре независимых блока:

* `reachability` — по последней **реальной** проверке (`ok|degraded|blocked|
  partial|unchecked` + статусы каждого источника);
* `content` — `ready|partial|failed|unknown` + `documents_fetched/parsed`;
* `analysis` — `completed|failed|not_run` + `last_success_at` (берётся из
  результата анализа, а не из доступности источника);
* `runtime` — `works|works_previous_version|no_published_rules|
  compiler_error|unavailable|disabled` + `active_version`, `bank_source`,
  `compiler{available,state,reason}`.

Честный экран возможен: все источники красные, при этом
`reachability=blocked`, `content=unknown`, `analysis=not_run`,
`runtime=works` (активный snapshot + компилятор). Обратное тоже: источники
зелёные, а `runtime=no_published_rules`.

Сейчас `runtime.status = compiler_error`, `compiler.state = not_installed`:
компилятор подсказок — пакет AC-COMPILER, в этой ветке его нет. Это не
маскируется зелёным; UI сможет показать «компилятор ещё не подключён»
(разделение `state`), а не «сбой».

## 8. API (read-only; UI — отдельный пакет)

* `GET /api/anticliche/sources` — `summary` (правильные знаменатели:
  `live_http=4`, `local=1`, `references=4`), `active_version` (LKG),
  `health` (4 вида), `sources`/`local_sources`/`references`, `lineage`.
  Строка источника — по §8.3: `source_id`, `enabled`, `reachability{status,
  checked_at, http_status, transport_code, revision, etag, freshness}`,
  `content{status, documents_fetched, documents_parsed, bytes, checksum}`,
  `analysis{status, last_success_at, documents_analyzed, model_ref, proposals,
  run_id}`, `last_success_fetch_at`, `next_attempt_at`, `last_error`,
  `licence`, `retry_policy`, `activation_note`.
* `GET /api/anticliche/sources/{source_id}` — детали (пути, лицензия, retry
  policy, свежесть); неизвестный id → 404.
* `GET /api/anticliche/health` — только четыре вида здоровья + версия.
* `POST /api/anticliche/refresh` дополнен: `version` теперь реальная
  действующая, добавлены `rules`, `sources`, `paused`, `published`.

RBAC — существующий global-admin (как было). Мутации (toggle/check/analyze) —
AC-API; сервисные функции для них уже есть (`set_enabled`, `check_one`).

## 9. Поведение воркера (Stage A)

1. `freshness-skip` по `fetched_at` (7 дней) сохранён; `force=True` (ручной
   запуск) его не ждёт.
2. Отбираются включённые источники, которым `attempt_decision` разрешает
   попытку (анти-storm). Остальные попадают в `paused[]` с причиной.
3. Проверки идут независимо (`check_sources`, bounded параллелизм 3,
   изоляция исключений); каждая пишется в `anticliche_source_state` и
   событием в `mca_events`.
4. Если usable-источников нет: `unchanged` (все ответили «без изменений»,
   LLM не вызывалась) / `fetch_error` (все упали, LKG сохранён) / `fresh`
   (все на cooldown).
5. Bounded добор до вместимости: общий счётчик `max_rounds()` на прогон —
   бюджет провайдера не умножен на число источников. Новые элементы
   помечаются `source`/`source_revision`.
6. Публикация: `ok`; при недоступной части источников — `partial_success`
   (§4.3), статус кэша тоже `partial_success`, а не «ok».
7. `check_one(source_id, manual=True)` — только проверка: без LLM, без
   публикации, без изменения набора (тест 18 §9.2).

## 10. Тесты

Новый файл: `tests/test_anticliche_sources_ac_data.py` — **62 теста**,
без сети (транспорт инъектируется):

* классификация 200/304/401/403(политика)/403(лимит)/429/404/410/5xx/timeout;
* HTML вместо Markdown, невалидный JSON, пустой документ, отсутствующий путь;
* `Retry-After` (секунды и cap), bounded backoff, `policy_blocked` без
  автоповтора, ручная проверка разрешена один раз;
* независимость: Wikipedia 403 не мешает другим, исключение транспорта
  изолировано, независимые записи `check_id`;
* GitHub: реальная ревизия, ожидаемые пути, 6/6 документов, missing-путь не
  зелёный;
* LKG: snapshot → `ok`; недоступный snapshot → `lkg` с версией и числом
  правил; пустой банк → `none`; PG down → `unavailable` (не 0); все источники
  упали → версия 9 сохранена; сбой модели (`llm_error`) и невалидный JSON
  модели (`parse_error`) → версия и набор не изменились; `last_success`
  переживает сбой и «рестарт»;
* четыре вида здоровья независимы (все заблокированы + runtime works;
  `works_previous_version`; `no_published_rules`; `compiler_error`;
  `unavailable`);
* `local/manual` без HTTP, `db_error`, библиография без вызовов транспорта,
  знаменатели, `stale` отдельно от статуса, выключенный источник не выглядит
  здоровым;
* воркер: `partial_success` (A=403 + B=200/changed, публикация по B, A
  красный), блокированный источник не ретраится, `check_one` без LLM;
* API: раздельные поля источника, детали/404, `/health` с четырьмя видами.

Фальсифицируемость проверена мутациями (5 мутаций → тесты падают):
403→`policy_blocked` по одному коду; отключённый LKG-фолбэк; отсутствие
изоляции источников; сведённые в один вид здоровья; игнор `Retry-After`;
потеря lineage.

Ломающиеся по контракту старые тесты обновлены (не ослаблены):
фикстуры транспорта теперь отдают настоящую форму ответа Wikipedia action
API (раньше — произвольную прозу, что по §9.2 тест 8 обязано быть
`parse_error`); id локального источника — `local/manual`; агрегированный
статус стадии источников — `sources_unavailable`; патч httpx перенесён на
единственный транспорт (`services.anticliche_sources`).

## 11. Что должен использовать AC-PIPE

1. **Реестр и статусы — не дублировать.** `anticliche_sources.SOURCES`,
   `check_source`/`check_sources`, `record_check`, `emit_check_event`.
   Stage A уже пишет `docs_fetched/docs_parsed/bytes/checksum/revision`.
2. **Тексты документов.** `fetch_source_documents(source, revision=…)` →
   `{text, documents[{path,status,chars,bytes,checksum}], documents_parsed}`;
   разбор (пример клише ≠ пояснение), категории и quarantine — на его стороне.
3. **После активации источников** (`set_enabled`/флаг `enabled` через
   AC-API) разбор должен пометить `docs_parsed` фактическим числом
   разобранных документов, иначе `content_health` останется `partial`/`failed`.
4. **Анализ.** Писать `last_analysis_status`/`last_success_analysis_at` в
   `anticliche_source_state` (колонки уже есть) — оттуда берётся
   `analysis`-вид здоровья. Не выводить «анализ завершён» из reachability.
5. **Публикация.** `INSERT anticliche_snapshot(state='published')` +
   upsert `anticliche_cache` в одной транзакции; таблица уже создана.
   После публикации `read_active_version` → `ok`, UI перестаёт показывать
   `works_previous_version`.
6. **Run-события.** `trace_id=run_id` для событий проверок и стадий, чтобы
   `mca_events` давал вкладкам «Анализ»/«Журнал» связанную историю.
7. **Статусы воркера.** Новые коды: `partial_success`, `unchanged`,
   `sources_unavailable` (в `anticliche_cache.ALLOWED_STATUSES` уже внесены).

## 12. Риски и остаточные ограничения

* **Wikipedia заблокирована по robot policy** (живой факт). Пока `ru-repo-*`
  выключены, банк не растёт автоматически. Это следствие честной политики, а
  не регрессия: включать русские источники должен AC-PIPE после разбора.
  Решение о включении — не «канарейка», а обычный per-source флаг.
* **Живая проверка выполнена с машины разработчика**, не с прод-сервера:
  статус `available` для GitHub подтверждён реальными ответами; на прод-VPS
  IP другой, итог проверки может отличаться (это штатно: статус — результат
  последней реальной проверки на конкретном хосте).
* **`ru-repo-a` NOASSERTION.** GitHub не распознаёт лицензию автоматически;
  MIT подтверждён чтением файла LICENSE на ревизии — это записано в
  `Licence.note`, чтобы не выдавать NOASSERTION за «нет прав».
* **`bib-yurova`** — точный URL публикации не подтверждён и не выдуман:
  `url=""`, `verified=False`, авто-доступ запрещён.
* `GET /api/anticliche/sources` не пагинируется: источников 9, пагинация
  преждевременна (AC-API при необходимости добавит фильтры).
* **Legacy-блок «Анти-клише: динамический список»** (`web/app.js`,
  `clicheStatusLabel`) знает старые коды: три новых честных статуса
  (`unchanged`, `sources_unavailable`, `partial_success`) он покажет
  сырым кодом (fallback `map[st] || st`). UI не трогал (вне scope пакета;
  блок удаляется AC-UI и заменяется ссылкой). Для AC-UI: либо метки в
  legacy-мапе, либо удаление блока — второе уже предписано ТЗ §5.1.

## 13. Incidental findings

* `anticliche_worker.fetch_source` дублировал HTTP-логику — сведён к
  единственному транспорту (`anticliche_sources.fetch_document`).
* Старые тесты подавали «прозу» вместо ответа wiki API; это скрывало
  регрессию «битый формат = успех» — исправлено фикстурой реальной формы.
* `ALLOWED_STATUSES` не содержал честных исходов стадии источников
  (`unchanged`, `sources_unavailable`, `partial_success`) — при попытке
  записать их кэш молча писал `never`. Расширено осознанно.
