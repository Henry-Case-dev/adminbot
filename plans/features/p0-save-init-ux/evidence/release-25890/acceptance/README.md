# ACCEPTANCE-90 — прод-приёмка §4 релиза 2.58.90 (18.10.2026, UTC)

Лейн: **ACCEPTANCE-90** (DevOps, приёмка §4; деплой — отдельный лейн DEVOPS-DEPLOY-90).
Прод: **2.58.90**, commit `3b02366e`, ветка `master`, T0 = **2026-10-18T13:34:23Z**
(рестарт, PID 3430462). Канал: **HTTPS API админки** (TMA initData владельца);
SSH в фазе A не использовался (fail2ban-дисциплина: одна журнальная фаза — один коннект).

Чаты: рабочий `-1002661910336`, PET `-1004482340693`.

## A. Real-DB цикл сохранения — ЗАКРЫТО

Артефакт: `acceptance-25890.json` (mode=full, **17/17 PASS, failures=0**),
независимая перепроверка только-GET: `acceptance-recheck-25890.json` (PASS, `diff_significant={}`).

| Шаг | До → После | Коды | Замечание |
|---|---|---|---|
| A1 Core global | `detail_level` full → compact → **full** | POST 200 (`applied:true`, revision 4) / POST 200 (revision 5) | read-after-write тем же GET: level=compact; после возврата — level=full, source=global |
| A2 Core chat (рабочий) | chat-override отсутствовал: full → compact (inheritance=chat, revision 6) → **снят** | POST 200 / POST `block/core.personality/reset` 200 | возврат = снятие переопределения (`inherits.source=global`, sha12 `040581a3b4b0`) |
| A3 Expression | chat-override отсутствовал: `wit=high` (inheritance=chat, revision 1, `rendered_chars=243`) → **factory_default** | POST 200 / POST `reset-chat` 200 | `rendered_text` слоя вырос 0 → 243 симв. (эффект виден) |
| A4 Style policy | временное правило `trailing_period.hard.strip` (chat-revision 0 → **1**, source=chat, revision `g8.fe503bd7f9d1\|c1.28f8d723ec64`) → **снято** | POST 200 / `try` 200 `repaired=1`, `style_text_masked="Проверка стиля пробой"` / POST `reset-chat` 200 | rev++ подтверждён; эффективность подтверждена живой try-сборкой (0 LLM, без отправки) |
| A5 Humor / learning | craft `enabled` true → false → **true** (revision 3 → 4); learning `paused` false → true → **false** | POST 200 / POST 200 | значения и поведение восстановлены |
| A6 Изоляция | правки на чате A (`-1002661910336`) **не видны** на чате B (`-1004482340693`): core level/inheritance и expression values B не менялись | GET оба | две независимые проверки изоляции (core, expression) |
| A7 Конфликт/безопасность | POST `/api/speech/style` c устаревшим `expected_updated_at=2000-01-01T00:00:00Z` → **409** «документ изменён другим путём — обновите экран; ваш текст не потерян»; состояние чата не изменилось (`rules_same=true`, `chat_revision=0`) | 409 | данные не потеряны, ложного успеха нет |
| A8 Финал | все значения == исходным (`diff_significant={}`, `diff_provenance_only={}`) | — | `/healthz` = `{"status":"ok","version":"2.58.90"}` |

Примечания:
* Прогон-1 (`acceptance-25890-run1-full-cycle.json`) выполнен до правки классификатора диффа и
  зафиксировал единственное отличие — **провенанс** `humor.craft: default → global`
  (правка+возврат значения создаёт owner-документ; поведение идентично: `enabled=true`,
  `disabled_techniques=[]`). Отдельного API «удалить документ» в речи нет by design, поэтому
  это не потеря данных; в прогоне-2 (с уже существующим документом) дифф равен нулю.
* `revision`/`updated_at` из сравнения исключены намеренно: они растут от любой правки, в т.ч. обратимой.

## B. Nostalgia live — ЧАСТЬ СДЕЛАНА, ТИК ОТЛОЖЕН (окно ниже)

Сделано сейчас:
* **per-chat гейт `gates[nostalgia]` для PET `-1004482340693` включён**
  (`acceptance-bc-25890-enable-gate.json`): PUT `/api/chat/-1004482340693/gates` → 200
  `{"feature":"nostalgia","enabled":true}`; повторный GET — `nostalgia=true`,
  `updated_at` 2026-10-17T21:42:38Z → **2026-10-18T13:59:13Z**. Рабочий чат не тронут (`nostalgia=true` как и был).
* `nostalgia_log` (HTTPS `/api/memory/nostalgia/log`): **2 исторических строки** по рабочему чату,
  обе `status=sent` (`ts` 1789787010 / 1789269398 — **до T0**); по PET — 0 строк.
* `/api/memory/cognition/status`: у обоих чатов `nostalgia.scenario="active"` (`active=true`,
  mode=silence) — условие сценария A выполняется (живая беседа), т.е. на следующем тике
  ожидается `scenario=A`, а не прежний `silence_too_short`.

Не наблюдаемо сейчас (честная отсрочка):
* Тик ностальгии после T0. Интервал джоба = `60 мин + jitter ≤ 20 мин`, первый запуск —
  от момента регистрации (13:34:23Z), т.е. **14:34–14:54Z**. Поэтому строк журнала
  `[nostalgia] scenario=A`, событий `nostalgia_run` и новых строк `nostalgia_log` после T0 пока нет.
* **NOT_BEFORE_UTC = 2026-10-18T14:58:00Z** (рекомендуется запуск 15:00–15:10Z — тик может идти минутами).
* Что смотреть: `NOST_SCEN_A≥1`, `NOST_GATE_SKIP` (для PET ожидается 0 после включения гейта),
  `[nostalgia] sent|skip reason=…`, `nostalgia_run` (start+терминальный outcome) в `mca_events`,
  новые строки `nostalgia_log` (`sent` либо честный `skipped`+reason).

## C. Initiative live — ЗАКРЫТО по HTTPS-фактам (журнальная строка отложена)

Артефакт: `acceptance-bc-25890-read.json`.
* `scan_anchored = 1` в **durable-счётчиках** задачи `initiative.observe`
  (`/api/memory/intel-funnels`). Маркер `scan_anchored`/`SCAN_FRESH_LOOKBACK_SECONDS`/`stage="anchored"`
  существует **только в 2.58.90** (`git show d59fab94:services/initiative_observer.py` — 0 совпадений),
  а инкремент счётчика и эмиссия события `stage="anchored"` — одна и та же ветка кода
  (`services/initiative_observer.py:959-967`). Значит подтяжка курсора к живому чату
  выполнена новым кодом уже после деплоя.
* Пост-деплойный прогон наблюдателя: `job.status=completed`,
  `finished_at = 2026-10-18T13:55:05Z` ≥ T0; `liveness.last_tick_ts` = 13:55:05Z, `heartbeat_ok=true`.
* События за 24ч: `initiative_observer_scan=282`, `opportunity=5`, `decided=4`,
  `writer_generated=2`, `recheck_passed=0`, `sent=2`, `observer_diagnostic=1`.
* Решения: `stage="new_message"`, `reason_code="default"` (silent/success); причины молчания окна:
  `eval_not_due=197`, `not_enough_messages=72`, `min_gap=7`, `direct_address_seen=1`
  — новые коды этой волны видны в живом прод-окне.
* Вердикт панели: `activity.state=ok` «Инициатива доставляется»; последняя доставка из ledger —
  `message_id=1165152` (12:57:43Z, `delivery_status=delivered`, `core_revision=r1.040581a3b4b0`,
  `style_policy_revision=g8.fe503bd7f9d1`) — **до T0**; новых отправок после T0 нет, что согласуется
  с `eval_not_due`/`not_enough_messages` (инициатива не подменяется тестовой отправкой).
* Остаток: журнальная (mca_events) строка `event_name='initiative_observer_scan' AND stage='anchored'`
  — снимается тем же одним коннектом отложенной фазы (`probe_journal_25890.sh`).

## D. Журнал / ошибки прода

* Фаза журнала отложена вместе с B/C (один SSH-коннект, read-only):
  `journalctl -u admin_bot --since 2026-10-18T13:34:23Z` → `ERR/CRITICAL/Traceback`,
  `[nostalgia]`-строки, `[b01]`/`[speech]`/`[style_policy]` WARNING, плюс read-only SQLite-выборка
  `mca_events`/`nostalgia_log` после T0.
* Уже известно из деплой-лейна (`../final-verification.txt`, 13:35:01Z): `ERR=0`, миграции без новых DDL.

## Как воспроизвести (без SSH)

```
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py readonly
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py full
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py recheck
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_live_bc_25890.py read
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_live_bc_25890.py enable-gate
```

Отложенная журнальная фаза (ровно один SSH-коннект, read-only; креды — из локального
`deploy_commands.txt`, в вывод не печатаются; T0 передаётся как RFC3339 UTC):

```
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/run_journal_ssh_25890.py "2026-10-18T13:34:23Z"
```

## Артефакты (sha256_16)

| файл | sha256_16 | что это |
|---|---|---|
| `acceptance-25890.json` | `3fce71931522ad28` | полный цикл A (17/17 PASS, дифф = {}) |
| `acceptance-recheck-25890.json` | `ad87e9dae3c58deb` | только-GET сверка с baseline полного цикла |
| `acceptance-25890-run1-full-cycle.json` | `6a995d53e1bf6063` | прогон-1 (исторический; провенанс-дельта humor.craft) |
| `acceptance-bc-25890-read.json` | `8cc9914dd915cf9a` | B/C: гейты, funnels, vitality, nostalgia_log, cognition |
| `acceptance-bc-25890-enable-gate.json` | `e419e6aa1f0c5e1f` | включение PET-гейта `nostalgia` |
| `probe_acceptance_25890.py` | `d16ff573ea5e4657` | пробник A (readonly/full/recheck) |
| `probe_live_bc_25890.py` | `0f8f15b838cd5a3a` | пробник B/C (read/enable-gate) |
| `probe_journal_25890.sh` | `5ffa46d2384562fc` | журнальная фаза (bash, read-only) |
| `run_journal_ssh_25890.py` | `236ddc8307c32a64` | раннер журнальной фазы (один коннект) |

## Остатки (не закрыто в этом лейне)

1. **B**: тик ностальгии после T0 → `scenario=A`, `nostalgia_run`, новые строки `nostalgia_log`
   (NOT_BEFORE_UTC 2026-10-18T14:58:00Z).
2. **C**: журнальное подтверждение `stage='anchored'` в `mca_events` (тот же коннект).
3. **D**: `ERROR=0/CRITICAL=0` за окно приёмки от T0 (тот же коннект).
4. Итог по п.1–3 → обновление live-пунктов карт (`P0A-*`, `P0B-LIVE-*`) и
   release-стадия requirements-gate (`--candidate 3b02366e --deployed-commit 3b02366e`).
