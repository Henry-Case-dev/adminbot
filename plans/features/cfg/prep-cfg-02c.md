# PREP-CFG-02C — бриф исполнения: жёсткая изоляция `user_image` ↔ `summary_cover`

**Лейн:** PM-PREP-CFG-02C (read-only; единственный артефакт — этот документ; код, карты, `current_task.md` и прод не менялись; SSH не использовался).
**Дата:** 19.10.2026, 02:05 (UTC+12) · HEAD master `948c2004` · прод **2.58.90 @ `3b02366e`** · релиз-поезд 2.58.91 (CFG-02B `7e5edd75`/`7db919df` + Vision + GRID + ENTRY + INIT-ARCH) — **собран, ещё НЕ в проде**; в рабочем дереве незакоммичен VISION-UI (`web/app.js`, `web/index.html`, `web/static/app.css`); `services/` чисто.
**Источники:** `plans/features/cfg/{requirements-map.json (13 строк слайса), slice-graph.json, plan.md, source-cfg-addendum.md L93–L105/L116–L117/L21/L67, review-cfg-02a.md §6/§65, review-cfg-02b.md, prep-cfg-02b.md}`; `plans/workflow_state.md`; код (только чтение): `services/{image_generation,worker_budget,persistent_throttling,cover_style_jobs,cover_style_pipeline,cover_style_preview,cover_style_edit,summary_generator,capability_registry,budget_limits,usage_events,pg_db,param_catalog}.py`, `web/api/summary_test.py`, `web/app.js`, `tests/*`.

---

## 1. Состав слайса (13 строк, все PENDING)

| # | req_id | Источник | Глагол-обязательство | Что именно доказывать |
|---|--------|----------|----------------------|------------------------|
| 1 | **ADD-1.T2** (L21) | таблица v0.7 | «переиспользовать существующую image pipeline; обложки Summary **не входят** в пользовательские счётчики» | Единый pipeline сохранён (не второй); ни один Summary-этап не попадает в user-счётчики (негатив в сторону обложек). |
| 2 | **CFG-02.F** (L67) | рамка CFG-02 | «не дублировать дневную квоту в backend; сохранить работоспособность/расходы/семантику; **обе** настройки не распространяются на обложки» | Дневная квота не переписана (те же ключи/reserve/journal); сентинелы 0/−1/>0 сохранены; обложки не тратят ни суточную, ни частотную пользовательскую настройку. |
| 3 | **CFG-02C.D** (L95) | решение владельца | «лимиты „Генерация изображений“ относятся **только** к изображениям, которые пользователи просят создать в общении; обложки — другой бизнес-процесс с собственной политикой и **независимым учётом**» | Совпадение scope/модели/инструмента/провайдера **не** объединяет квоты: доказать независимый учёт при технически общем провайдере. |
| 4 | **CFG-02C.B** (L105) | блокирующий критерий | «user-лимиты не ограничивают обложки; обложки не тратят user-лимиты; общий техбюджет не маскируется под лимит продукта» | Три негатива + честная атрибуция отказа: источник отказа в диагностике всегда истинный (user/chat/daily/freq/shared-infra). |
| 5 | **CFG-02C.1** (L97) | норма 1 | «**не смешивать бюджеты и счётчики**» — расход/отказ/время разблокировки user-лимитов **никак не учитывают** вызовы обложек; обратно: генерация/стилизация/повтор/восстановление обложки **не уменьшают** пользовательские остатки и **не блокируются** исчерпанной user-квотой; user `generate_image` не расходует специализированную квоту Summary | **Двусторонний негатив** на уровне счётчиков: (а) покрытие обложки при `user daily = 0` и при активной freq-паузе; (б) user-мем при исчерпанной Summary-квоте (если введена) и при исчерпанном freq per-chat/burst — работают. Проверяются оба контура дневной квоты: per-chat `limits.image_daily_limit` **и** env shared `WORKER_DAILY_IMAGE_CALLS_GLOBAL`. |
| 6 | **CFG-02C.2** (L98) | норма 2 | «сделать **явный тип потребления**»: на уровне источника операции/резервирования/журнала различать `user_image` и `summary_cover`, внутри обложек — `base`, `styled_edit`, `retry/recovery`, `fallback`; привязка **от исходной задачи до commit/release**, не из текста промпта/имени инструмента; не писать Summary в общий `image_calls` как пользовательское; мигрировать/разделить контур с корректным историческим учётом | Тип едет параметром вызова от call-site до журнала; в `image_reservation`/метрике видны типы; дневной user-счётчик читается только по типу `user_image`; исторические записи (source direct/tool) не переписаны ложно. |
| 7 | **CFG-02C.3** (L99) | норма 3 | «сохранить собственные правила Summary»: base/styled_edit/recovery/fallback работают по существующему pipeline, идемпотентны, не запускают повторную дорогую базовую генерацию; новые лимиты Summary (если нужны) — только в разделе Summary с независимым scope/метрикой и видимой администратору причиной отказа; не включать Summary в user-burst «на весь чат» только потому, что обложка публикуется в том же чате | Регрессия B04-контура: стилевой edit, recovery (bounded `recovery_max_attempts`), fallback-исходы не изменились; повторный styled-запуск не удваивает платный вызов; в user-витрине обложки не появляются. |
| 8 | **CFG-02C.4** (L100) | норма 4 | «реальная общая инфраструктурная квота — исключение, но не смешанный user-лимит»: провайдер/ключ/баланс/защитный бюджет вправе ограничивать обе ветки, но это **отдельный** `provider/shared budget`, а не «достигнут лимит картинок пользователя»; в диагностике/админке — истинный источник отказа и расход отдельно по двум типам операций; не обещать независимость физически общего лимита | Отказ по env shared-потолку (`limit_global`) в user-пути называет **технический бюджет**, не «пользовательскую квоту»; в UI/диагностике расход user vs cover показывается раздельно. **Проверить carry-over `review-cfg-02a §65`:** сейчас `limit_global` сводится к reason `budget` и текст подставляет TZ-дату чата вместо честного источника/shared-TZ. |
| 9 | **CFG-02C.5** (L101) | норма 5 | «MiniApp: секция „Лимиты генерации“ ясно обозначает „**Пользовательские изображения**“ и поясняет „**Обложки сводок здесь не учитываются**“; настройки лимитов обложек (если существуют) — в Summary; агрегат расходов — с разбивкой по источникам, один счётчик не выдаётся за другой» | UI-факт (live preprod): подпись + пояснение видны на мобильном и десктопе; ни в витрине, ни в агрегатах расходов нет смешения; фон/дизайн не переделываются. |
| 10 | **CFG-02C.6** (L102) | норма 6 | «конкурентность/транзакционность»: reservation/commit/release/idempotency остаются атомарными; параллельные user-мем и Summary-обложка в одном чате не мешают по продуктовым квотам; ошибки/ретраи/рестарты/отмены **не переносят** списания между контурами и **не удваивают** платные вызовы | Интеграционный негатив: одновременные параллельные операции, сбой провайдера/доставки, рестарт в середине — изоляция сохраняется, двойных списаний нет. |
| 11 | **CFG-02C.7** (L103) | норма 7 | «обязательные отрицательные и интеграционные тесты **в обоих направлениях**»: user daily `0` + freq-запрет → Summary Base и Style Edit работают; исчерпан Summary-лимит → user-изображение работает; генерация/ретрай обложки не меняет `user_image.used` и персональный/чатовый burst; мем не меняет `summary_cover.used`; ошибки провайдера/recovery/delivery/параллель не разрушают изоляцию; инфраструктурные лимиты — тестировать отдельно с корректной причиной, без дорогого массового прод-прогона | Полный двусторонний тестовый набор в песочнице; spy-контракты: cover-путь **не вызывает** user-ограничители/списание, user-путь **не вызывает** cover-контуры. |
| 12 | **CFG-02.AC8** (L116) | приёмка CFG-02 | «„бот, нарисуй“ и „бот, надо сделать мем“ проходят **одинаковые** пользовательские лимиты; обложки Summary не проходят **ни суточный, ни частотный** лимитер, включая общий burst на чат» | direct- и tool-путь — один user-контур (частично уже 02B.5); для обложек — негатив по обоим лимитерам и по per-chat burst. |
| 13 | **CFG-02.AC9** (L117) | приёмка CFG-02 | «доказать двустороннюю изоляцию расходов `user_image`/`summary_cover` при Base, Style Edit, Recovery, конкурентных задачах и ошибках; честно показать объективно общие ограничения провайдера» | Сводный сценарий-доказательство на все 4 этапа обложек + параллель + ошибки + honest shared display. |

Живые пометки карты: `CFG-02C.5` — `live_required=true, live_when=preprod` (UI); остальные `live_required=false` (агентские/песочница). Внешняя приёмка ADD-2.2 (postdeploy) — в CFG-FINAL (строки не дублировать).

---

## 2. Где сталкивается сейчас (карта кода; правок не вносилось)

### 2.1 Фактический механизм смешения (корень дефекта)

| Точка | Якорь | Что происходит сейчас |
|---|---|---|
| **Base-обложка Summary** | `services/summary_generator.py:3390` → `generate_image_verbose(chat_id=chat_id)` | `image_generation.py:1549` → `_consume_budget(chat_id)` (:1061) → `worker_budget.consume` для `scope='global'` **и** `scope='chat:<id>'`, metric `image_calls`. Т.е. обложка списывает **тот же** per-chat счётчик, который управляется `limits.image_daily_limit` (и тот же env shared `WORKER_DAILY_IMAGE_CALLS_GLOBAL`), **вне журнала** `image_reservation` (журнал пишет только user-путь через `reserve_image`). |
| **Test-run обложки** | `web/api/summary_test.py:482` (`generate_image_verbose`, `chat_id=entry.chat_id`) | Тот же смешанный путь; участвует в «витрине» тестовой генерации обложки. |
| **Preview Base (Test Style)** | `services/cover_style_preview.py:515` (`generate_image_verbose`, `chat_id=None`) | Тратит только shared `global` `image_calls`. |
| **Styled Edit / Recovery** | `services/cover_style_jobs.py` (`edit_image`, импорт :41; публикация styled :2042) + `services/summary_generator.py:3759–3781` (bounded recovery, `csj.recovery_max_attempts()`) | Платного image-бюджета **не** списывает (нет `_consume_budget`); правила recovery/идемпотентности — сохранить, не сломать. |
| **User-путь** | `services/image_generation.py:1897 generate_and_send` (freq: :1933–1969; reserve: `_reserve_or_consume` :1775) | Daily reserve + freq limiter; freq-гейт в cover-путь **не подключён** (уже доказано `tests/test_cfg02b_image_freq_limits.py:705 test_summary_cover_path_is_not_charged`). |

### 2.2 Факты, которые обязана чинить 02C

1. **Daily-счётчик**: обложки повышают `worker_budget.chat:<id>.image_calls.used` → `limits.image_daily_limit` «съедается» обложками; в журнале `image_reservation` строк обложек нет (used > journaled) — `image_usage_summary`/витрина искажены.
2. **Диагностика/gates**: `capability_registry._image_quota` (:374–415) читает этот же счётчик → статус `image_generation` может стать `quota_exhausted` из-за обложек; `budget.image_calls` — gate способности (SOUL-1 W10 F3 pin завязан на порядок shared→chat).
3. **Reason-коллапс**: `_reserve_or_consume` (:1818–1835) сводит `limit_global`/`limit_chat` к `"budget"`; `image_denial_details` (:401–444) при `quota_exhausted` добавляет note «Суточная квота обновится … (TZ чата)» и при shared-причине называет **неверный источник/TZ** (carry-over `review-cfg-02a §65`). `worker_budget.ImageReserveResult` уже различает `limit_global`/`limit_chat` — не потерять.
4. **Аналитика расходов**: `image_generation._record_image_event` (:1360) пишет `module='image'`, `source='image'` для **обеих** ветвей; в `llm_usage_events` нет типа потребления → «разбивка по источникам» (02C.5) и честные агрегаты (02C.4) недоказуемы без типа. `usage_events.SOURCES` (:34) — whitelist source-домена (добавление значения — код-only, но проверить пин-тесты домена).
5. **DDL-PG**: `image_reservation` (`services/pg_db.py:372–390`) — PG-only, прецедент аддитивной колонки (`ADD COLUMN IF NOT EXISTS` :340/:509), retention 30д; `worker_budget` (:192) PK(day,scope,metric). SQLite `user_version` **не трогать** (в A5 была санкция Δ DDL ≠ 0 только для PG-таблиц; проверить актуальную санкцию в дизайне).

### 2.3 Кандидаты правок (не финальный список; PM расширяет `write_scope` при старте слайса)

- **Текущий scope графа**: `services/budget_limits.py`, `services/worker_settings.py`, `services/cover_style_pipeline.py`, `services/cover_style_jobs.py`, `services/image_generation.py`, `tests/test_cover_style_wave_b_asap4.py`, `plans/features/cfg/evidence/cfg-02c/**`.
- **Обязательно добавить (по фактическому смешению/UI)**: `services/worker_budget.py` (учёт/метрика/факты), `services/summary_generator.py:3390` (call-site base-обложки + recovery), `web/api/summary_test.py:482` (test-run), `services/cover_style_preview.py:515` (preview), `services/capability_registry.py` (только если честная диагностика/матрица затронет — иначе read-only проверка), `services/usage_events.py` (тип в аналитике, если решено), `services/pg_db.py` (DDL журнал/тип), `web/app.js` (+ при необходимости `web/index.html`) для §02C.5, `tests/test_cfg02b_image_freq_limits.py` (pin spy cover-пути), `tests/test_hotfix5_summary_cover_window_round1025.py` (пины `_consume_budget`), `tests/test_image_daily_limit_round1026.py`/`test_cfg02a_image_quota_ui.py` (регрессии+пины), новый `tests/test_cfg02c_image_isolation.py`, `tools/ui_cfg02c_*_e2e.py`.
- **Каталог/`param_catalog` не ожидается**: новых ключей не требуется (и «настройки лимитов обложек» сейчас отсутствуют — фиксировать это фактом, не выдумывать ключ). Δ каталога = 0 → re-pin каталога **не** нужен; проверить только UI-доки/screen-map, если правки попадут в пины витрины. Если дизайн всё же вводит Summary-лимит — это +1..N каталоговая дельта с полным re-pin-чеклистом (прецедент §3.4 prep-02b), решение — внутри слайса по нужде, не по умолчанию.

### 2.4 Контуры, вовлечённые в доказательство (перечень для тестов)

Квоты/флаги: `limits.image_daily_limit` (sentinels 0/−1/>0), env `WORKER_DAILY_IMAGE_CALLS_GLOBAL`/`PER_CHAT`, `IMAGE_DAILY_LIMIT_ENABLED` (kill-switch), `flags.budgets_enabled` (master, `budget_gate`), freq `limits.image_freq_limit_{enabled,burst,cooldown_seconds,mode}` (`persistent_throttling.py:438–444`), `COVER_STYLE_SNAPSHOT_ENABLED`, `MEDIA_EXECUTION_POLICY_ENABLED`, `csj.recovery_enabled()/recovery_max_attempts()`.
Счётчики/журналы/кеши/дедуп: `worker_budget` (day/scope/metric), `image_reservation` (PK `reservation_key`, статусы reserved/committed/released/denied), `throttle_state` (scope `image_freq`), media job idempotency (`tool_result.idempotency_key`, K2 ON), `ChatParamsCache` TTL (~120 с, `worker_budget._chat_tz_name`), `hot_config`.
Публикация/подпись: user `sendPhoto` (`generate_and_send` :1999–2024) vs cover styled публикация `cover_style_jobs.py:2042` (`summary_cover_styled.jpg`) и `telegram_send.py:27 SUMMARY_COVER_MEDIA_ID="summary_cover"` — **не** смешивать media-id и учёт.

---

## 3. Зависимости и порядок (что нельзя параллелить)

1. **Chain**: `CFG-02B → CFG-02C` (slice-graph). CFG-02B **уже в master** (`7e5edd75`/`7db919df`, Approved `ba3ff438`, LEDGER `dea5f84a`), но **не в проде**: релиз-поезд 2.58.91 (CFG-02B + Vision + GRID + ENTRY + INIT-ARCH) ещё не выкачен. 02C-кандидат строится поверх master + 2.58.91-линии; релиз 02C — следующий поезд после 2.58.91.
2. **Нельзя параллелить по файлам**:
   - `web/app.js`, `web/index.html`, `web/static/app.css` — заняты незакоммиченным **VISION-UI** (сейчас dirty tree). UI-часть §02C.5 (подпись/пояснение) — только после его коммита, иначе двойной писатель (прецедент запрета).
   - `services/image_generation.py` — не занимать другим лейном одновременно (postgen-правка `948c2004` уже влита; подтвердить, что VISION-UI его не трогает).
   - Релиз-поезд 2.58.91 заморозить без 02C: не подмешивать 02C-дельту в уже собираемый релиз.
3. **Можно параллелить**: read-only дизайн/разведка (этот документ), подготовка RED-тестов в **новом** файле `tests/test_cfg02c_image_isolation.py` — только после старта слайса и на чистом `services/` (риск минимален); правки `services/worker_budget.py` и `summary_generator.py` не конфликтуют с текущими лейнами (postgen/vision — web/api+vision-файлы), но запускать их параллельно с 02B-f8-reissue (tests/fixtures) безопасно лишь формально — тесты 02C будут пересекаться по прогонам с reissue, поэтому **сначала закрыть NF-1 f8-пару**, затем писать 02C.
4. **Прод-дисциплина**: живые проверки — в штатных окнах, малый объём платных вызовов (2–3 картинки в пределах квоты), fail2ban-правила проекта.

---

## 4. Фазы (по образцу CFG-02B)

**Ф0 — Возврат очереди.** Подтвердить выкат/приёмку 2.58.91 (`healthz`, `NRestarts=0`), синк master; проверить, что f8-пара CFG-02B влита (NF-1 закрыт); **PM расширяет `write_scope` слайса CFG-02C** (§2.3) отдельной правкой графа; зафиксировать базу кандидата.

**Ф1 — Дизайн (короткий раздел «Design» в `evidence/cfg-02c/README.md`).** Зафиксировать:
1. Таксономия типа: `user_image` | `summary_cover{base, styled_edit, retry_recovery, fallback}`; передача типа — **явным параметром** от call-site (summary_generator / summary_test / cover_style_preview / user-раннер), не из промпта/имени инструмента.
2. Судьба shared-бюджета: обложки сохраняют доступ к env shared-потолку как **технический** потолок (или отдельная метрика `image_calls_cover` — решить и обосновать); user-метрика `image_calls` перестаёт включать обложки.
3. Журнал/DDL: аддитивная колонка типа в `image_reservation` (и/или отдельная метрика), атомарность reserve/commit/release **без изменений семантики**; исторические строки не переписываются (только forward-разделение).
4. Honesty-фикс (carry-over §65): сохранить `limit_global`/`limit_chat` в reason и текстах; shared-отказ называет технический бюджет (TZ `WORKER_BUDGET_TZ`), user-отказ — свою квоту/паузу.
5. UI (02C.5): подпись «Пользовательские изображения» + пояснение «Обложки сводок здесь не учитываются» в существующей секции «Лимиты генерации»; разбивка агрегатов — где агрегат показывается.
6. Рекомендация по catalog Δ: **ожидаемо 0**; если дизайн вводит Summary-лимит — отдельный чек-лист re-pin.

**Ф2 — RED.** Новый `tests/test_cfg02c_image_isolation.py` (`TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-02C`), кейсы:
- (a) user daily `0` + freq ON → Summary Base **и** Style Edit работают (провайдер доступен), списаний user нет; баланс `user_image.used`/burst не меняется;
- (b) исчерпанный Summary-потолок (если введён) / исчерпанный shared-потолок с честным reason → user-мем работает (когда shared позволяет) или отказ называет **истинный** shared-источник;
- (c) генерация/ретрай/recovery/fallback обложек не меняют `user_image.used` и per-user/per-chat burst (spy на отсутствие списания; «cover-override не вызван»);
- (d) мем (direct + tool) не меняет `summary_cover.used` (spy: Summary-контуры не затронуты);
- (e) параллель: мем + обложка в одном чате — обе квоты независимы, без двойных платных вызовов; provider/delivery error, рестарт между reserve/commit — изоляция и атомарность;
- (f) тип потребления виден в журнале/метрике; `user_image`/`summary_cover` не смешаны; history-миграция forward-only.
Прогнать RED на базовом коммите (фиксация падения).

**Ф3 — IMPL.** Явный тип в call-chain → раздельные учётные контуры → сохранение reason/текстов честности → UI-подпись/пояснение (после VISION-UI) → (опц.) тип в аналитике.

**Ф4 — GREEN + бласт-радиус:**
```
py -3 -m pytest tests/test_cfg02c_image_isolation.py -q
py -3 -m pytest tests/test_cfg02b_image_freq_limits.py tests/test_cfg02a_image_quota_ui.py ^
  tests/test_image_daily_limit_round1026.py tests/test_hotfix5_summary_cover_window_round1025.py ^
  tests/test_summary_cover_model_compat_round1024.py -q
py -3 -m pytest tests/test_cover_style_wave_b_asap4.py tests/test_asap7_cover_fix.py ^
  tests/test_summary_cover_round1023.py tests/test_asap8_v6_c03a_style_recovery.py ^
  tests/test_extra_cover_style_jobs.py tests/test_extra_cover_style_pipeline.py ^
  tests/test_soul1_capability_fallbacks.py tests/test_soul1_capability_registry.py -q
py -3 -m pytest tests/test_unified_image_request_round1026.py tests/test_tool_router.py ^
  tests/test_direct_chat.py tests/test_direct_chat_concurrency.py tests/test_persistent_throttling.py -q
node tests/js/<image/сводки JS-тесты>          # JS-sweep
.venv\Scripts\python.exe tools\ui_cfg02c_image_isolation_e2e.py   # подпись/пояснение, моб.+десктоп
```
Плюс прогон пинов, если затронуты: `test_round1025_f8_registry.py --check` (только при кат. дельте), `test_budget_settings_round1019.py`, `test_decision_making_round1026.py`.

**Ф5 — Evidence + Review.** `plans/features/cfg/evidence/cfg-02c/{README.md, red-green.txt, e2e-log.json, ui/*.png}`; `review-cfg-02c.md`; гейт:
`py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --stage review --slice CFG-02C --candidate <sha>`.

**Ф6 — Release/live.** Порт на релиз-линию (dual-line, прецедент `119b1f7d`) → bump/пины → T0-деплой (fail2ban-дисциплина) → live: user daily `0` + freq ON → Summary Base/Style Edit работают; ретрай обложки не меняет user burst; мем не меняет `summary_cover.used`; UI-подпись/пояснение на проде; shared-потолок называет истинный источник → гейт `--stage release --candidate <sha> --deployed-commit <sha>` → закрытие строк.

---

## 5. Риски

| ID | Риск | Митигация |
|---|---|---|
| R1 | **Регрессия B04-контура обложек** (base/style/recovery/fallback) | Не менять pipeline; изоляция — только учёт; полный регрессионный прогон §Ф4; recovery-пинты не трогать по существу |
| R2 | **Каталог-инкремент** — ожидаемо **нет** (новых ключей не нужно) | Если дизайн вводит Summary-лимит — отдельный коммит «catalog delta + re-pins» (прецедент §3.4 prep-02b); иначе Δ=0 и никаких re-pin |
| R3 | **Смешение журнала/метрики** | Тип — явный параметр, не вывод из промпта; forward-only разделение; `reserve/commit/release` атомарность не ломать |
| R4 | **Исторический учёт** (в PG used уже включает обложки) | Не переписывать историю; честно документировать в evidence: будущие периоды раздельны, прошлые — как есть |
| R5 | **Reason-коллапс/shared-TZ** (carry-over §65) | Сохранить `limit_global`/`limit_chat` в отказ/диагностику; тест на текст/TZ-источник |
| R6 | **UI-текст** (§02C.5) — двойной писатель с VISION-UI | UI-часть строго после коммита VISION-UI; Playwright/Browser Use acceptance моб.+десктоп |
| R7 | **«Не второй pipeline»** | Любая обвязка — только в существующих точках (`generate_image_verbose`/`generate_and_send`/`reserve_image`); новых генераторов/фетчеров нет |
| R8 | **Стоимость live-проверок** | Песочница по умолчанию; live — 2–3 картинки в пределах квоты, без массовых платных прогонов |
| R9 | **TTL/кеши** (ChatParamsCache 120 с, hot_config) | Тесты изоляции делать на фактическом резолве, с pytest-фикстурами из CFG-02B; не полагаться на «прогретый» кэш |

---

## 6. Что уже покрыто (алиасы — не дублировать)

| Строка/работа | Статус | Что берём в 02C, что НЕ дублируем |
|---|---|---|
| **CFG-02A.6 (L76)** | VERIFIED | User-пути (direct/tool/replay) уже доказаны; изоляция обложек здесь **явно отложена** в 02C (README §3/§6). 02C не перепроверяет user-пути целиком, только негативы изоляции. |
| **CFG-02B.5 + `test_summary_cover_path_is_not_charged`** | VERIFIED (Approved `ba3ff438`) | Freq-лимитер уже не подключён к cover-пути. 02C расширяет: daily-счётчик, журнал/тип, shared-честность — без повторного «freq-не-подключён». |
| **SOUL-AMD.5.1–5.18 (SOUL §5)** | VERIFIED | Единый image pipeline и capability-матрица уже приняты; не пересобирать, только не ломать (`budget.image_calls` gate). |
| **SOUL-1 W10 F3** | зафиксировано ревью | Матрица `_image_quota` shared→chat и порядок списания — прецедент; 02C дополняет честной атрибуцией, не переписывает матрицу. |
| **CFG-06 / MCA-20 (`plans/archive/features/mca-20-temporal-factcheck`)** | в CFG-06 | К обложкам/квотам изображений отношения нет — алиасов для 02C **нет** (не заявлять «уже покрыто»). |
| **P0 (2.58.90)** | прод | Alias-строк к 02C нет: P0 закрыл сохранение/UX, не image-учёт. |
| **ADD-2.2** | CFG-FINAL (postdeploy) | Внешняя приёмка «дневная квота видна, частотный OFF, обложки не расходуют, shared-ceiling честный» — исполняется в CFG-FINAL, здесь только слайс-строка. |

---

## 7. Guardrails («не делать»)

- Не создавать второй image pipeline; не менять генерацию обложек по существу (политика/style/recovery сохраняются).
- Не менять ключи каталога и сентинел-семантику `limits.image_daily_limit`; Δ каталога без отдельного re-pin-коммита запрещён.
- Не переписывать исторический учёт в PG; только forward-разделение.
- Не трогать web/* до коммита VISION-UI; не подмешивать 02C в поезд 2.58.91.
- Не открывать Human Gate: все решения 02C — технические (владельческий выбор уже зафиксирован в L95, повторно не спрашивать).

---

## 8. Точное действие Orchestrator

1. После выката/приёмки 2.58.91 и закрытия NF-1 f8-пары → **старт слайса CFG-02C**: PM одной правкой расширяет `write_scope` (§2.3) и при необходимости `notes` в `slice-graph.json`; проверить план-гейт `requirements_gate.py check --stage plan`.
2. Запустить Builder по фазам §4 (Ф0→Ф6); UI-часть — только после коммита VISION-UI; без параллельных писателей на `services/image_generation.py`.
3. После GREEN+ревью — evidence `cfg-02c/**`, review-гейт `--slice CFG-02C`, затем релиз и live-проверки §4/Ф6; закрытие 13 строк только по фактам.

*Документ подготовительный; единственный источник истины — `plans/features/cfg/requirements-map.json` + гейт `requirements_gate.py`. В этом лейне карты, код, `current_task.md` и прод не изменялись; SSH не использовался.*
