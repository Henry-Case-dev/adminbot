# EMBED-RESOLVER-PREDEPLOY — резолвер совместимости на реальных строках прод-БД

**Дата:** 23.10.2026, 16:2x (UTC+12) = **2026-10-23T03:2x UTC** (прод-сервер живёт в UTC).
**Кандидат кода:** `570e1eee55dff89450deef27696425a0b87a471b` (HEAD `e48a2506` — docs-only сверху:
`git diff 570e1eee HEAD -- services config tests` пуст). Сам этот отчёт лежит в коммите `22264e8e`
(только `plans/features/...`, кода не касается).
`services/embedding_control_plane.py` sha256 `5319e4aed4d549c33eb7b5e85a7069fb34a6bdc157280af041c8918be92a12a3`,
`services/graphrag_rebuild.py` sha256 `7c9197f77ee32ccdd2e8e4ad7ebccda249527231bb483489dc1c0fd21d158ecd`.
**Прод (не менялся):** версия `2.58.111`, коммит `fbf9013d`, активен с `2026-10-22 13:14:31 UTC`, `NRestarts=0`;
`/healthz` **200 → 200** (`status=ok`, см. `raw/healthz.json`).
**Вердикт:** **`insufficient(compat_not_proven)` → проба → `compatible` (ADMITTED). Полной перевекторизации НЕ будет.**
Рекомендация: **deploy (GO)**.

## 1. Что реально лежит в прод-реестре (до пробы)

`mca_embedding_index_generations`, namespace `default` — **всего 2 строки, ACTIVE нет**:

| index | gen | status | model | dims | preprocessing_version | provider | endpoint_fp | config_revision |
|---|---|---|---|---|---|---|---|---|
| `graph_facts_vec` | 1 | `building` | gemini-embedding-001 | 3072 | `casefold-strip-v1` | generativelanguage.googleapis.com | `e42d6fd4c65855c2` | NULL |
| `smart_archive` | 1 | `building` | gemini-embedding-001 | 3072 | `casefold-strip-v1` | generativelanguage.googleapis.com | `e42d6fd4c65855c2` | NULL |

Обе строки: `fingerprint 96f80838…`, созданы `2026-09-29T10:39:22Z`. У `graph_facts_vec`
`pause_reason='rate_limit:quota_group'`, `next_allowed_at=2026-10-23T00:05Z` (уже прошёл), `attempts_total=592`.

Данные на момент копии: `graph_facts_vec` **16 003** вектора, `graph_facts` 20 108 фактов,
`smart_archive` **0**, `smart_archive_facts` **0**.
Eligible-фактов (`expires_at IS NULL OR > now`) — **15 868**: из них **4 224** без вектора (остаток backfill),
а **4 359** векторов ссылаются на уже неeligible факты (истёкшие) — см. §7.7.

**Практическое следствие:** без ACTIVE-строки индекс сегодня обслуживается как FTS-only
(`_index_generation_ok`, `summary_memory.py:1909-1910`) — 16 003 старых вектора лежат, но не отдают поиск.
Именно это и должен снять допуск.

## 2. Конфиг сверен с продом (не предположение)

* PG `bot_settings`: `models.embedding_model_name = "gemini-embedding-001"`, `models.embedding_dim = 3072`,
  `models.embedding_base_url = "https://apinet.cloud/v1"` — совпадает с локальным `.env`.
* Живые логи бота за 48 ч: `embed_once OK | model=gemini-embedding-001` (5 последних вызовов).
* Отсюда MSI (space) = **`e540d4ad890e121d`** — тот же вход, что у прода; `conn = d2e6314e3586c547`.
* `fingerprint_now = 2d0efab0…` ≠ сохранённый `96f80838…` — различие только в провайдере/endpoint
  (сменился шлюз), MSI-поля совпадают.
* `EMBED_COMPAT_ADOPTION_ENABLED` не выставлен → механизм допуска **включён**.

## 3. Что вернул резолвер на реальных строках копии

**Шаг 1 — `resolve_index_compat` (read-only, без сети, как на старте/тике):**

```
state          = insufficient
reason_code    = compat_not_proven
needs_probe    = True
action         = retry_canary
class          = COMPATIBILITY_UNKNOWN
serviceable    = False
space          = e540d4ad890e121d   (совпал с текущим)
dims           = 3072     rows = 1
candidate      = {generation: 1, status: building, dims: 3072,
                  model: gemini-embedding-001, provider: generativelanguage.googleapis.com,
                  fingerprint: 96f80838…}
```

`incompatible` **не возвращался**: ACTIVE-строки нет, но `_pick_space_candidate` нашёл строку-провенанс
с тем же MSI → путь «доказать пробой», а не «перевекторизовать».

**Шаг 2 — `ensure_index_compat` (проба на старых векторах + adopt):**

| Показатель | Значение | Порог кода |
|---|---|---|
| вызовов провайдера | **1 батч** (12 текстов, HTTP 200, 4.28 s, dims 3072) | ≤3 |
| checked | **12** | ≥8 |
| mean / min / hit5 | **1.0 / 1.0 / 1.0** | ≥0.995 / ≥0.990 / ≥0.80 |
| verdict | **compatible**, `reason_code=""`, `runs=1` | — |
| итог | `state=compatible`, `class=ADMITTED_COMPATIBLE`, `serviceable=true`, `action=none` | — |

Записан durable-допуск (в копии):
`config_revision = adopt1:e540d4ad890e121d:d2e6314e3586c547:12:1.000000:1.000000:1.0000:1792725644`
(`1792725644` = 2026-10-23T03:20:44Z). Строка `graph_facts_vec` → `status=active`, `activated_at` заполнен,
`fingerprint`/`provider`/`endpoint_fingerprint` **сохранены** (провенанс прежнего шлюза).
Реестр после пробы: **по-прежнему 2 строки**, новых поколений (`building`/`building_target`) не появилось.
Повторный `resolve_index_compat` → `compatible` (идемпотентно).

## 4. Legacy-строка без `preprocessing_version` (проверено отдельно, на копии копии)

| Сценарий | Ответ резолвера | Что произойдёт |
|---|---|---|
| A. `preprocessing_version=NULL`, fingerprint сохранён | `insufficient / compat_not_proven`, `needs_probe=true`, кандидат найден | B3 выводит версию предобработки из сохранённого fingerprint → тот же безопасный путь пробы |
| B. `model/dims/provider=NULL` + невоспроизводимый fingerprint | `insufficient / legacy_metadata_missing`, `needs_probe=false`, `action=need_old_vectors`, `legacy_rows=1` | rebuild **запрещён**, target не регистрируется, ждём восстановления провенанса |
| C. `model='text-embedding-004'` (доказанно другая модель) | `incompatible / identity_changed`, `class=REINDEX_REQUIRED` | штатная контролируемая миграция (честный негатив работает) |

Ни в A, ни в B резолвер не изменил реестр (строки остались `building`, `config_revision=NULL`):
сам по себе вызов не регистрирует и не планирует поколение.

## 5. `smart_archive` (пустой источник)

`state=source_empty`, `reason_code=source_empty`, `source_empty=true`, `needs_probe=false`, `action=none`.
Ложного reindex нет — как и задумано (`graphrag_rebuild.py:1904-1911`).

## 6. Что произойдёт при деплое (по фактическому коду)

1. На старте `MemoryManager` сразу вызывает `_ensure_index_compat_inline()` (`summary_memory.py:1758`) —
   **до** backfill, чтобы не сжечь ~316 вызовов на перестройку.
2. `smart_archive` → `source_empty` (без сети). `graph_facts_vec` → `insufficient` + **одна** проба 12 текстов →
   `compatible` → adopt одной транзакцией.
3. Пока вердикта нет, новое `building`-поколение не регистрируется (`summary_memory.py:1872-1881`),
   а `maybe_schedule_rebuilds` при `insufficient`/`compatible` делает `continue` (`graphrag_rebuild.py:2023-2041`).
   **Полной перевекторизации не будет ни в одном из этих состояний.**
4. После adopt: `generation_status` → `state=active`, `serviceable=true`, `reindex_required=false`;
   `_index_generation_ok` → True (векторный поиск открыт).
5. Если проба не дойдёт до API → `insufficient` (никогда `incompatible`), сборка ставится на обратимую паузу
   `paused_compat_insufficient`; после рестарта пауза остаётся durable и снимается вердиктом.
6. 4 224 eligible-факта без векторов остаются за штатным backfill (как и планировалось в A0),
   это не «перевекторизация»: существующие 11 644 вектор-факта не трогаются.
7. **Посторонняя находка (low, не блокер):** 4 359 из 16 003 векторов ссылаются на уже неeligible факты
   (истёкшие/удалённые). Для проб/поиска это не опасно — `_fetch_sample_pool` и выдача фильтруют по
   `expires_at`, — но индекс на ~27% состоит из «мусорных» записей, и KNN может возвращать их до фильтра.
   Это предсуществующее состояние, не связанное с текущим релизом; отдельная задача на очистку — на усмотрение PM.

## 7. Честные ограничения

1. **Копия — снимок, не живой процесс.** Снята `2026-10-23 03:18 UTC` read-only соединением (`mode=ro`,
   `PRAGMA query_only=1`). Бот писал в это время: `graph_facts` вырос 20 108 → 20 119 за сессию
   (11 фактов), `graph_facts_vec` остался 16 003 (совпало с замером A0 ранее в тот же день и с повторным
   счётом в конце сессии). Реестр — 2 строки в обоих read-only снимках.
2. **Копия без `embedding_i8`**: sqlite-vec 0.1.9 не даёт перезаписать int8-колонку прочитанным значением.
   Проба и KNN читают float-колонку `embedding` — ровно так же, как прод-код (`_read_live_vector`, `_knn_top_ids`).
3. **`task_jobs` в копию не попал**: шаг «отменить ненужную сборку» получил отсутствующую таблицу
   (в логе `graphrag rebuild: compat pause lookup failed`) и стал no-op. На проде в этот момент были только
   `embedding_rebuild_lease` со `status=finished` — отменять было нечего.
4. **Проба шла локальным ключом** из `.env` (тот же шлюз/модель, что в PG). sha256 ключа не сравнивался;
   идентичность векторов доказана метрикой (mean=min=hit5=1.0 на 12 реальных строках), а не равенством ключей.
5. **`pause_reason='rate_limit:quota_group'` и `attempts_total=592`** остаются на принятой строке как провенанс
   отменённой сборки: панель может показать последнюю паузу/попытки. На обслуживание не влияет —
   авторитет даёт `status='active'` + допуск (повторный резолвер → `compatible`).
6. Это **pre-deploy** проверка. Она не заменяет post-deploy live-проверку (ACC-10): реальный поиск по старым
   фактам, панель `/api/memory/embeddings` (`serviceable=true`, canary ≈1.0), лог `EMBEDDING_COMPAT_ADMITTED`.

## 8. Рекомендация

**DEPLOY (GO).** На реальных строках резолвер ведёт себя ровно как задумано: недоказанность → проба →
допуск; перевекторизация не запускается ни на реальных строках, ни на legacy-вариантах без провенанса.
Откат остаётся дешёвым: `UPDATE … SET status='building', config_revision=NULL` (векторы и факты целы,
поиск возвращается в FTS-only). Форсировать ничего не нужно.

## 9. Операции и стоимость

* SSH-коннектов: **7** (один логин `nik`, интервал >60 c, **ни одной неудачной аутентификации**;
  лишние 3 — технические ошибки сборки копии на сервере, не перебор кредов). Fail2ban не сработал,
  `/healthz` 200 на всех проверках.
* Прод: **ни одной записи**; серверный scratch `/tmp/embed-resolver-pre` удалён сразу после скачивания
  (`CLEAN_OK`); оригинал БД открывался только `mode=ro` + `query_only=ON`.
* Копия: **198 МиБ** (207 798 272 B), gz **176 МиБ** (184 854 681 B),
  sha256 `78e44bc2d8ccf92fd499207bb27138b078d78f70c6eaf11ed10c2a5a43a5f2dd` — совпал на сервере и локально.
* Локальный прогон: `2026-10-23T03:20:44Z`; embed-вызовов к провайдеру — **1** (12 текстов).

## 10. Артефакты

```
evidence/resolver-pre/
  report.md                 этот отчёт
  raw/resolver_results.json машинный результат: step1/step2, реестр до/после, legacy A/B/C, smart_archive
  raw/remote_meta.json      DDL, счётчики таблиц, query_only, размер копии, task_jobs-ошибка
  raw/data_counts.json      счётчики фактов/векторов и «мусорных» векторов (eligible-фильтр)
  raw/transfer.json         sha256 сервер/локально, размер gz
  raw/recon.txt             read-only рекогносцировка: файлы БД, реестр, DDL
  raw/healthz.json          healthz 200 / 2.58.111 (с метками времени)
  raw/fetch.log             сборка копии на сервере + sha256 + скачивание
  raw/run.log               локальный прогон резолвера (JSON-результат)
  raw/verify_config.log     .env/системд: версия, коммит, PG-наличие DSN
  raw/verify_model.log      PG bot_settings (model/dim/base_url), логи embed_once, task_jobs
  raw/run_resolver.py       локальный прогон (read-only копия + реальный compat_probe)
  raw/remote_copy.py        сборка сокращённой копии на сервере
  raw/ssh_recon.py, raw/fetch_copy2.py, raw/verify_config.py, raw/verify_model.py
```

Секретов в артефактах нет (проверено поиском по токенам/DSN/паролям; печатались только имена полей,
наличие DSN и неконфиденциальные значения model/dim/base_url).

## 11. Привязка evidence (для PM/Reviewer — карту не редактировал, вне write scope)

* `DEC-09` («при insufficient_data сохраняются индекс, факты и возможность отката») — прямое подтверждение
  на реальных строках: `insufficient` не разрушает и не планирует перестройку, adopt обратим `config_revision`.
* `CANARY-03` («проба возвращает фактические model/dim») — проба вернула `dims=3072`, `checked=12`, фактические метрики.
* `ACC-10` — **не закрывает**: это post-deploy live-проверка. Мои данные — лишь предпосылка
  (на копии hit5=1.0, но не на живом сервисе).
* `IDENT-02` — косвенно: MSI/space вычислен из реального конфига (`e540d4ad890e121d`).
