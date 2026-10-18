# REVIEW-V-FIX2 — вердикт (фикс воркера/состояния Vision по живой приёмке 2.58.91)

Независимое ревью кандидата (uncommitted поверх `aea59748`; в дереве параллельно
TR-FIX2-файлы — не его, не смешивал). Этот коммит — только данный документ.

Биндинг (sha256_12, сверено — здесь бриф использует sha256, не blob):
`services/mca_vision.py` **`f8cb004c6c84`**, `web/api/routes.py` **`2a5ecb391360`**,
`tests/test_p0_vision_fix_core.py` **`57cf6b792d5e`**, re-pin
`tests/test_round1025_f8_registry.py` **`5cf2b13149f7`**,
`tests/test_mca23_planned_vs_actual.py` **`be5a35166ac7`** — все совпали.
Оценка — на текущем дереве + worktree `aea59748` (создан/удалён мной).

## 1. RCA skip'ов — убедительно, подтверждено журналом

Живая приёмка: `SKIPS=36` (20:17–21:07, серии подряд), `LOCKED=5`
(20:40:14, 20:41:19/40, 21:03:19/40) с честной оговоркой о втором писателе
harness'а; пропуски есть и вне окон harness (20:17–20:37). Механизм: энтри тика
ждал БД-фазы (`recover_stale` — write-tx с single-writer локом; `_expire_deferred`
— до 50 `finish()` по одному; чтение `active()` — на единственном aiosqlite-
соединении), `busy_timeout`=5 с ≈ `VISION_TICK_SECONDS` ⇒ APScheduler выбрасывал
следующий тик. Серия из N подряд = инстанс жил N×5 с (не блокировка цикла —
остальные воркеры тикали, ERR=0). Принимаю.

## 2. Фикс — прочитан, соответствует

`_tick` = только `_request_claim()` + `_request_maintenance()` (ни одного
`await` до `create_task`; инстанс планировщика завершается в той же итерации).
Два независимых single-flight sweep'а: claim (`_claim_once`: `active()` +
CAS `mark_running` только из `queued` + спавн обработок + backfill ниже live) и
maintenance (`recover_stale` → `_expire_deferred`, каденс
`VISION_MAINTENANCE_SECONDS=30`). Каждая фаза bounded
(`wait_for` 30 с), таймаут/сбой одной не отменяет другую; медленная фаза видна в
логе (`claim sweep slow`/`maintenance stage timeout`). Сохранены: CAS-claim без
дублей, heartbeat живой джобы, `recover_stale(stale_after=120)`, deferred-TTL →
`skipped`, приоритет manual>auto, backfill только при пустой live-очереди,
breaker, `drain`/`shutdown` (sweep'ы в lifecycle, НЕ занимают слоты
`ANALYSIS_CONCURRENCY`); `_tick_body` (инлайн) сохранён для тестов/диагностики.

## 3. Тесты — 6/6 GREEN; RED воспроизведён мной

* GREEN (мой прогон): `-k "fix2 or per_chat_context"` → **6 passed**.
* **RED (мой прогон на чистом `aea59748` + финальный тест-файл): 6 failed** —
  включая подлинный прод-симптом APScheduler
  `skipped: maximum number of running instances reached` и
  `sqlite3.IntegrityError: UNIQUE constraint failed: mca_media_analyses...`
  (сопряжённый дефект revision). Ассерты содержательные: энтри <0.5 с при
  5-секундных БД-фазах; ноль пропусков при интервале 0.2 с + очередь доезжает
  до `ready`; per-chat state (global `vision_disabled` vs chat `requested=true`,
  секрет не раскрыт); 429-окно→`queued`/терминал за окном; live-ретрай после
  лимита → `ready`; backfill: retry-долг уважается, re-arm через cooldown →
  `ready`, идемпотентный повтор = 0.

## 4. 429 и сопряжённый дефект — логика верна

`_retry_allowed`: свежая джоба — прежний бюджет; `vision_rate_limited` моложе
`RATE_LIMIT_RETRY_WINDOW_SECONDS=3600` — повтор сверх бюджета (частота ограничена
`_backoff` ≤ `RETRY_MAX_SECONDS=900` + jitter); за окном — терминал. Для
`vision_unavailable`/прочих — прежний бюджет. Backfill re-arm:
`_backfill_job_ready` (нет строки / `queued` с истёкшим `next_retry_at` /
терминал по transient-причине старше `BACKFILL_REARM_COOLDOWN_SECONDS=900` →
`store.requeue`, существующий API `task_supervisor:712`); постоянные причины не
переставляются. UNIQUE-фикс: `finish_media_analysis` делает CAS-бамп
`revision=revision+1`, поэтому повтор той же гранулы падал на UNIQUE; теперь
вставка берёт `_next_granule_revision` = max+1 (ключ гранулы совпадает с
UNIQUE-колонками: asset/scope/schema/config_revision/quality_profile) —
воспроизведено RED-ом и снято GREEN-ом.

## 5. routes и re-pins

`get_vision_state`: `chat_id` (query) / `X-Chat-Id` (header) → проверка
`can_access_chat`; чужой чат → глобальный слой (без утечки per-chat); RBAC
(global admin или `can_view_key_value(keys.vision_api_key)`) и маскировка не
менялись; тест подтверждает global/chat/R17. Re-pins `ROUTES_SHA256_F11` = sha256
файла routes.py (старый `21f72a8ebb4e…` → новый `2a5ecb391360…` == текущему
sha256) — обоснованы: тот же эндпоинт, опциональный контекст, инвентарь маршрутов
не менялся.

## 6. Числа

6/6 ✓; профильный свод — мой супернабор 19 файлов **372 passed / 0 failed**
(заявленные 322 — иная композиция); UI e2e **7 passed** ✓; pre-existing:
`test_write_points_go_through_single_writer` падает standalone (201 vs 198,
задокументировано); загрязнение hot-cache (`test_env_off_beats_product_toggle` в
совместном прогоне) — **воспроизведено мной на чистом `aea59748`** (1 failed /
381 passed) ⇒ пред-существующее, не FIX2.

## 7. Границы

Оговорка «блокировку event-loop >5 с это не лечит» — честная и достаточная:
наблюдённый отказ был именно долгим инстансом (серии пропусков), а не стоящим
циклом (остальные джобы живы, ERR=0); энтри без `await` реально снимает класс
«инстанс живёт из-за БД». Каденс уборки 30 с — ок: `recover_stale` 120 с и
deferred-TTL измеряются минутами/часами, задержка ≤30 с семантику не меняет;
`Retry-After` не читается (контракт транспорта) — осознанный компромисс с
bounded-окном+backoff.

## Находки

**NF-1 (блокирующая, малая; один файл + тест): проба `/api/vision/test` всё ещё
отдаёт КОНТЕКСТ-НЕЗАВИСИМОЕ (глобальное) `state`, и UI перетирает им per-chat
состояние.** `web/api/routes.py:2274` (`post_vision_test`) вызывает
`runtime_snapshot(lore_db())` без chat-контекста, а `web/app.js` после пробы
делает `self.visionState = vprobe.state; self._visionStateAt = Date.now()`.
В прод-сценарии приёмки (глобально `flags.vision_enabled=false`, per-chat
override `true`) нажатие «Проверить подключение» возвращает линию/факты к
глобальному `vision_disabled` («Распознавание изображений выключено») на ~30 с
или до пере-входа на вкладку — прямое противоречие цели FIX2 (finding 6 приёмки)
на том же экране. Мини-фикс: в `post_vision_test` применить ту же резолюцию
скоупа, что в `get_vision_state` (`X-Chat-Id`/`chat_id` + `can_access_chat` →
`runtime_snapshot(..., chat_id=scope_chat)`), либо переиспользовать общий
хелпер; тест: проба с `X-Chat-Id` → `state.requested` отражает per-chat
(и без заголовка — прежний глобальный). Recheck: 6 fix2-тестов + расширенный
тест пробы + UI e2e 7.
* F2 (косметика): в `hashes-and-commands-2026-10-19.md` написано «5 failed», а
  фактический `red-2026-10-19.txt` — **6 failed** (все шесть новых падают на
  базе); уточнить.
* F3 (опционально): ветка «чужой чат → глобальный слой» в `get_vision_state`
  покрыта только кодом; можно добавить 1 ассерт в существующий тест.

## Рекомендации леджеру

| Строка | Решение |
|---|---|
| `P0V-PIPE-WORKER` (живой фикс skip'ов) | код → **V**; живое `SKIPS=0` — повторная приёмка |
| `P0V-SYMPTOMS` | код → **V** (SKIPS=36/LOCKED=5 атрибутированы; фикс энтри+фаз) |
| `P0V-PIPE-E2E` (+`P0V-UI-DISPLAY`) | код → **V** по GET-пути; **после NF-1** — и по пробе (state per-chat) |
| `P0V-PROBE-CACHE` (+`P0V-PIPE-FALLBACK`) | код → **V** (429-окно/терминал/re-arm/UNIQUE-фикс; RED IntegrityError снят) |
| Повторная приёмка | «SKIPS=0» + per-chat state (включая пробу) — postdeploy-проверка агентом (PET) |

## Вердикт

**Needs Fixes** — единственный блокер NF-1 (контекст-независимый `state` в
`POST /api/vision/test` перетирает per-chat линию/факты после пробы; мини-фикс в
одном месте + 1 тест). Остальное (RCA, энтри/sweep'ы, 6/6 GREEN и
воспроизведённый RED с прод-симптомом и IntegrityError, 429/re-arm/UNIQUE,
re-pins, пред-существующие списки) — подтверждено; F2/F3 — косметика/опция.