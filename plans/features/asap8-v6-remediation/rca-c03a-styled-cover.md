# RCA C03A — «Base появляется, styled не появляется / не восстанавливается» (P0)

Лейн: V6-SCAN-A; HEAD `1e98027` (2.58.77); read-only. Симптом зафиксирован владельцем на проде.
Вопрос RCA: где конкретно разорван путь `Summary → Base → Style → publication`, и почему styled
не появляется и не восстанавливается.

## 0. Ключевой архитектурный факт (основа всех находок)

**Style-стадия выполняется INLINE внутри публикации Summary, а не durable-воркером.**
`services/summary_generator.py:3202` → `_maybe_apply_cover_style` (:3359-3449) → `run_style_job` —
один await внутри `_publish_rich_document_impl`. Строка `task_jobs` (begin_cover_job, §42/§43) —
только durable-состояние/артефакты, НЕ очередь с консьюмером. Следствия:

-Publication строится один раз: `cover_for_publish = styled_path or base_path`
  (summary_generator.py:3213). Успел styled за inline-окно → едет styled; нет → едет Base **навсегда**.
- «Восстановить styled после публикации» коду нечем: в репо нет `edit_message_media`/замены
  медиа опубликованного сообщения (grep по `edit_message_media|replace_cover` — 0 совпадений).
  Любой «поздний» styled-успех не может попасть в уже опубликованный пост.

## 1. Цепочка стадий: код / условие тихого пропуска / telemetry

| # | Стадия | Где код | Когда молча пропускается | Telemetry / что видит Inspector |
|---|---|---|---|---|
| 1 | Summary → Base request/persist | summary_generator.py (cover-блок, :3100-3194) | Base-fail → `_degrade_without_cover` (публикация без обложки) — не наш симптом (Base есть) | COVER_BASE_SUCCEEDED/FAILED, provenance no_cover |
| 2 | Style eligibility/config/master | summary_generator.py:3383-3414 (`_maybe_apply_cover_style`) | kill-switch `COVER_STYLES_ENABLED` OFF → `None` без события; snapshot OFF → тихие `return None` (:3406-3414, legacy-бит-в-бит); профиль без style-стадии → `None` (не fail) | snapshot ON: COVER_STYLE_SELECTION + COVER_STYLE_SKIPPED{reason} + provenance base_fallback (:963-1003 report_style_skip) |
| 3 | Job enqueue (durable) | cover_style_jobs.py:721-753 begin_cover_job → task_jobs INSERT status=`queued` (task_supervisor.py:442) | — | строка task_jobs, coalesce_key=`cover_style:<run_id>` |
| 4 | Durable claim | **ОТСУТСТВУЕТ**: `mark_running` для cover-джоб не вызывается; джоба живёт `queued` весь inline-прогон (checkpoint_ref меняется, status нет — task_supervisor.py:615-662 не пишет status) | watchdog/recover_stale смотрят только `status='running'` (mca_watchdog.py:59-71, task_supervisor.py:556) → зомби-`queued` невидим | checkpoint_ref: BASE_SUCCEEDED→STYLE_SUBMITTED→… (CoverJobState.to_json) |
| 5 | Model/route/credentials | cover_style_jobs.py:1632-1710 (resolve_style_slot_inherited, connections, api-key лестница) | snapshot ON: `connection_missing`/`not_configured`/`reference_missing`/`edit_unsupported` → ранний `_style_failed` ДО paid call | COVER_STYLE_RESOLVE (configured/resolve_source), COVER_STYLE_FAILED reason_code (без generic-схлопывания при snapshot ON, :2232-2246) |
| 6 | Edit request с Base image | cover_style_jobs.py:1976-1999 (`_call` → edit_image, base_image_path, route) | — | COVER_STYLE_SUBMITTED (prompt_len/hash, route, limit_source), COVER_STYLE_RUNNING каждые 30с (events, НЕ task_jobs heartbeat) |
| 7 | Provider response | cover_style_jobs.py:1995-2010; retry prompt_limit (:2018-2156, ровно 1 bounded) | exception → EditResult(ok=False, reason=cls) | latency/cost метрики; manifest attempts[] |
| 8 | Payload validation | cover_style_jobs.py:2186-2210 | `result.ok and result.content` → `_write_temp_image` (**подпись/валидность image-байт стиля не проверяется**; `_image_signature_ok` есть только для референсов :1053) | — |
| 9 | Styled persistence | cover_style_jobs.py:2186-2208 (STATE_STYLE_SUCCEEDED + persist + COVER_STYLE_SUCCEEDED + provenance styled) | — | provenance status=styled, final_asset_id |
| 10 | Publication linkage | summary_generator.py:3207-3213 | `styled_path or base_path` — one-shot; после отправки связи «styled↔сообщение» нет и не может появиться (см. §0) | publication gate идемпотентен (summary_runs.publication_status + ledger reconcile :856-925) — дублей нет, но и обновления обложки нет |
| 11 | Telegram/UI rendering | отправка rich (:3257-3260) | — | Run Inspector: cover_prompts_status {base,style} (cover_style_jobs.py:1401-1473), манифест state.prompt_manifest |

## 2. Найденные точки разрыва (файл:строка), ранжированные по вероятности для симптома владельца

### R1 — Production retry/recovery styled ОТСУТСТВУЕТ (главный разрыв, v6-кейс 2 нарушен)
- v6 C03A требует: «повторная допустимая попытка может восстановить styled без генерации второго Base».
- Факт: после `_style_failed` (cover_style_jobs.py:2224-2247, state→STYLE_FAILED, publish Base)
  НЕТ ни одного производственного пути, который снова вызывает `run_style_job` для этого
  `job_id`/run. Единственный requeue — preview-контур: cover_style_preview.py:259
  (`start_preview_job`, kind=preview, кнопка «Протестировать стиль»).
- Хуже: `_maybe_apply_cover_style` после стайл-фейла вызывает `finish_cover_job(outcome=RESULT_BASE)`
  (summary_generator.py:3433-3439) → **status=`completed`** (cover_style_jobs.py:636-637:
  RESULT_BASE считается completed). Джоба стайл-фейла терминально «успешна» с reason_code —
  retry-семантики нет даже на уровне данных.
- Следствие для владельца: любой одноразовый сбой стиля (timeout/401/не та модель/limit) =
  Base навсегда, восстановить нельзя, кроме как дождаться нового Summary-рана (это будет
  НОВАЯ Base — нарушает «без генерации второго Base»).

### R2 — Рестарт посреди Style-стадии = зомби + потеря публикации (v6-кейс 3 нарушен по существу)
- Строка task_jobs остаётся `queued` (нет mark_running), heartbeat в task_jobs не пишется
  (`_run_with_heartbeat` :1337-1355 эмитит mca_events, не store.heartbeat()).
- Watchdog recover: только `status='running'` (mca_watchdog.py:59-71); `recover_stale` помечает
  `interrupted`, НЕ перевставляет в очередь (task_supervisor.py:547-569). Консьюмера kind=cover_style нет.
- Рестарт убивает и саму публикацию (inline!): run остаётся в STATE_STYLE_EDIT
  (summary_run_store.py:55,94). Докатка run'а — только при СЛЕДУЮЩЕМ триггере Summary этого чата
  (summary_generator.py:526-547), и stage-level resume НЕ реализован:
  `last_completed_summary_run_stage`/`srs.last_completed_stage` не имеют вызывающих в генераторе
  (grep: только определение database.py:5058, обёртка summary_run_store.py:248) → текст/Base
  генерируются заново, temp-файл старой Base мог быть удалён.
- Прод-контекст: деплой 1e98027 = `systemctl restart` — все in-flight summary-стили на момент
  деплоя погибли именно этим путём. Это конкретный, воспроизводимый механизм «Base была в
  прошлом ране, styled нет и не будет».
- Формально «durable pending не помечается completed» — да (висит queued), но смысл требования
  (job дообратабатывается) не выполнен: job вечно зомби.

### R3 — Семантический контур: `semantic_preservation_failed` / `UNVERIFIED_SEMANTIC` ОТСУТСТВУЮТ (v6-кейсы 5-6)
- grep по репо: обе строки существуют только в v6-документе. F3-fail-soft — ДО paid call и только
  по промпту (`story_identity_dropped` | `prompt_limit_exceeded`, cover_style_jobs.py:1175-1203,1905).
- Если провайдер вернул картинку, проигнорировав preservation-инструкцию (generic scene) — код
  публикует styled как УСПЕХ (COVER_STYLE_SUCCEEDED, provenance styled). Тихая замена «успехом»,
  которую v6 прямо запрещает, сегодня невыразима в терминах системы.
- «Два разных сюжета + один style-profile → generic scene» — кодом необнаружимо; владелец видит
  только визуально. Механизма честного `UNVERIFIED_SEMANTIC` в UI нет.
- Бонус-дефект валидации: байты styled-результата не проверяются на валидное изображение
  (:2186-2210) — `_write_temp_image` пишет как есть; битый payload → успех → сломанная обложка в Telegram.

### R4 — Идемпотентность linkage/provenance — частичная
- Публикация идемпотентна (gate + content-hash барьер, :856-925) — дублей постов нет.
- Но `record_provenance` — голый INSERT без ключа идемпотентности
  (cover_style_registry.py:880-905): повторная попытка/preview по тому же run создаст вторую
  provenance-строку; читатель берёт что есть — связи «один run ↔ один финальный исход» на уровне
  данных нет. Для retry-фичи (R1) это надо чинить до её появления.

### R5 — Тихие пропуска в snapshot-OFF ветке (минорный, но контакт с «тtextи»)
- `_maybe_apply_cover_style` :3406-3414: без snapshot ранние `return None` БЕЗ события/провенанса
  (legacy parity). Snapshot ON (default, :290-302) — всё видно. Если у владельца env
  COVER_STYLE_SNAPSHOT_ENABLED=false — пропуски невидимы. На проде значение env не проверено.

## 3. Что снять на проде, чтобы подтвердить/опровергнуть (без кода)

1. **task_jobs**: `SELECT job_id,status,checkpoint_ref,reason_code,updated_at FROM task_jobs WHERE kind IN ('cover_style','cover_base') ORDER BY updated_at DESC LIMIT 30;`
   — ищем: зомби-`queued` с checkpoint STYLE_* (R2), `completed`+reason_code≠NULL (R1-фейлы),
   STYLE_FAILED в checkpoint_ref.
2. **mca_events**: последние `COVER_STYLE_SELECTION/SKIPPED/SUBMITTED/FAILED/SUCCEEDED` по чату
   владельца — какой reason_code реально срабатывал (`style_publish_skipped`, `not_configured`,
   `edit_unsupported`, `connection_missing`, `timeout`, ...).
3. **cover_style_provenance**: последние строки по run_id владельца — status styled/base,
   fallback_mode, provider/model/route.
4. **Логи**: `[cover_style_jobs]`/`summary cover: style stage skipped (fail-open)` (
   summary_generator.py:3446 — fail-open глотает исключения ВСЕЙ style-стадии с одним WARNING).
5. **Run Inspector** (global-admin): последний run → cover_prompts_status и манифест
   (style_publish_skipped/attempts), сверить с п.1-2.
6. **env/конфиг**: COVER_STYLES_ENABLED, COVER_STYLE_SNAPSHOT_ENABLED, keys.image_style_api_key /
   connection профиля — исключить конфигурационные ранние фейлы (R5-класс).

## 4. Ответы на обязательные вопросы v6

1. **Восстанавливается ли styled после Style-фейла при повторной попытке БЕЗ новой Base?**
   Нет. Механизма production-retry нет (R1); после фейла джоба terminally completed.
2. **Idempotent publication linkage?** Публикация — да (gate/ledger); linkage styled↔сообщение —
   one-shot, после публикации обновление невозможно (§0); provenance-INSERT неидемпотентен (R4).
3. **Durable job переживёт restart и не пометится completed?** Строка переживёт (останется
   `queued`/checkpoint), но: никогда не дообрабатывается (нет консьюмера/recovery для этого kind — R2),
   а при фейле ДО рестарта помечается completed (R1).
4. **semantic_preservation_failed vs тихий успех?** Причины не существует; провайдерский
   content-loss публикуется как успех (R3). Единственная защита — промпт (F3) + превентивный
   fail-soft по компиляции.
5. **Два сюжета + один style-profile → generic scene?** Код не различит (R3); нужен либо
   выходной semantic-compare, либо честный UNVERIFIED_SEMANTIC + owner visual gate (v6 допускает
   второй вариант, но его тоже нет).

## 5. Остаточные действия (не кодить в этой фазе)

- A1 (evidence): снять прод-срезы §3 — определить, какой разрыв сработал у владельца (ожидаемо
  R1/R2 или конфигурационный ранний фейл).
- A2 (design, Architect): минимальный контракт recovery — bounded retry styled по существующей
  Base (asset/persist), отдельный от publication канал честности (`styled_status=failed` + reason
  в Inspector уже частично есть через F4), `semantic_preservation_failed`/`UNVERIFIED_SEMANTIC`
  семантика, идемпотентный provenance. Отдельное решение — куда крепить восстановленный styled
  (новый пост/редакт/только артефакт) — требует owner-выбора.
- A3 (test): сквозной provider-recording тест на настоящем runtime-seam + негативные:
  restart-mid-style, retry-after-fail, duplicate-provenance.
