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

## C. Initiative live — ЗАКРЫТО (HTTPS + журнально-БД подтверждение)

Артефакты: `acceptance-bc-25890-read.json`, `journal-25890-phase1.json`.

HTTPS-витрины:
* `scan_anchored = 1` в **durable-счётчиках** задачи `initiative.observe`
  (`/api/memory/intel-funnels`). Маркер `scan_anchored`/`SCAN_FRESH_LOOKBACK_SECONDS`/`stage="anchored"`
  существует **только в 2.58.90** (`git show d59fab94:services/initiative_observer.py` — 0 совпадений),
  а инкремент счётчика и эмиссия события `stage="anchored"` — одна и та же ветка кода
  (`services/initiative_observer.py:959-967`).
* Пост-деплойный прогон наблюдателя: `job.status=completed`,
  `finished_at = 2026-10-18T13:55:05Z` ≥ T0; `liveness.last_tick_ts` = 13:55:05Z, `heartbeat_ok=true`.
* События за 24ч: `initiative_observer_scan=282`, `opportunity=5`, `decided=4`,
  `writer_generated=2`, `recheck_passed=0`, `sent=2`, `observer_diagnostic=1`.
* Решения: `stage="new_message"`, `reason_code="default"` (silent/success); причины молчания окна:
  `eval_not_due=197`, `not_enough_messages=72`, `min_gap=7`, `direct_address_seen=1`
  — новые коды этой волны видны в живом прод-окне.
* Вердикт панели: `activity.state=ok` «Инициатива доставляется»; последняя доставка из ledger —
  `message_id=1165152` (12:57:43Z, `delivery_status=delivered`, `core_revision=r1.040581a3b4b0`) — **до T0**.

Журнально-БД подтверждение (`mca_events`, read-only SQLite, фаза-1):
* `scan_anchored_events_since_t0 = 1`; сама строка —
  **`ts=1792330806` (= 2026-10-18T13:40:06Z), `event_name='initiative_observer_scan'`,
  `stage='anchored'`, `outcome='success'`, `chat_id=null`** — то есть подтяжка курсора к живому
  чату выполнена новым кодом 2.58.90 через ~6 мин после деплоя.
* Всего `initiative_observer_scan` после T0: **7** (13:40–13:58, все `success`, `stage='observed'`
  кроме одной `anchored`).

## D. Журнал / ошибки прода

Фаза-1 (один SSH-коннект, read-only, 2026-10-18T14:07:29Z; `journal-25890-phase1.txt`):
* узел: `HEAD=3b02366e`, `BRANCH=master`, `/healthz={"status":"ok","version":"2.58.90"}`,
  `MainPID=3430462`, `NRestarts=0`, `ExecMainStatus=0`, `ActiveState=active`.
* окно 1703 строк журнала с T0: `CRITICAL=0`, `WARN_NOSTALGIA=0`, `SPEECH_WARN=0`;
  `ERR=2`, `TRACEBACK=1` — **две строки подлежат идентификации** (фаза-2 печатает их
  вместе с контекстом). Отдельно: независимая витрина `/api/status/logs` (ring-буфер процесса,
  `logs-ring-25890.json`) в своём окне даёт `ERROR=0`, `CRITICAL=0` (`INFO=969`, `WARNING=31`).
* ностальгия после T0: строк нет (`NOST_SCEN_A=0`, `NOST_SKIP=0`, `NOST_SENT=0`,
  `NOST_TICK_LINES=0`), `nostalgia_log` с T0 — 0 строк; события `nostalgia_run` с T0 — 0.
  Это ожидаемо: первый тик — T0+60…80 мин (14:34–14:54Z).
* журнальные следы приёмки A: `13:52:16`/`14:03:11` `[prompt_factory] chat override reset | chat=-1002661910336 | key=character.core`;
  `13:52:25`/`14:03:19` `[style_policy] document saved | scope=chat | revision=1 | rules=1`;
  `13:59:13` `[gates] set | chat=-1004482340693 feature=nostalgia enabled=True by=5885953495`.

Наблюдение (не блокер, честно): в ring-буфере два WARNING
`[prompt_registry] persisted speech value withheld | key=prompts.direct_chat_verbalizer_system_prompt |
reason=provenance_missing` (13:52:27 и 14:03:21) — это следствие моих вызовов `/api/speech/try`
(превью резолвит базу L2 Writer): сохранённое значение удерживается штатным механизмом
legacy-подавления (не применяется), записи в прод нет. Severity: низкая, область: speech/registry.

## E. Негативные ветки (без записи) — ЗАКРЫТО

Артефакт: `acceptance-edges-25890.json` (**3/3 PASS**).
* `POST /api/speech/style` (chat) с правилом неизвестного вида → **409**
  `документ не прошёл проверку: rule_kind_unknown:no_such_kind`; состояние чата не изменилось
  (`chat_revision=0`, `inheritance=global`) — валидация не подавлена, правило не потеряно молча.
* `POST /api/speech/core/meta` с `detail_level="bogus"` → **422** «неизвестный detail_level»;
  уровень не изменён.
* Итоговый дифф после негативных проб: `{}`.

## F. Payload-уровень: применяется ли значение в сборке без рестарта — ЗАКРЫТО

Артефакт: `acceptance-payload-25890.json` (**4/4 PASS**), `/api/speech/inspector` (GET + POST).
* До правки: `preview.versions = {core: r5.040581a3b4b0, core_detail: "full:owner_setting",
  style_policy: c8.fe503bd7f9d1, composer: "w2", channel: "speech_plain/plain/text/3c4e0608968f"}`;
  `core.chars=2835`.
* После chat-scope правки Core (без рестарта процесса): тот же композер отдаёт
  `core: r6.ff28f0720a23`, `core_detail: "compact:owner_setting"` — **активный payload реально
  использует применённое значение**, правка была только в БД.
* После снятия переопределения: манифест вернулся к `r5.040581a3b4b0` / `full:owner_setting`
  (совпадает с baseline), итоговый дифф `{}`.
* Честная граница: `last_run_present=false` — в памяти процесса нет снимка манифеста последнего
  **реального** хода (после рестарта реального ответа ещё не было), поэтому «фактически отправлено
  в LLM» этой пробой не утверждается. Ревизии реальной отправки видны в манифестах доставок
  (`core_revision`/`style_policy_revision`) и снимаются в фазе-2, если после T0 состоится отправка.

## G. Живая загрузка прод-сборки в браузере

`live-web/` (Playwright против прода, 14:16–14:17Z): страница `…/web/` открывается, приложение
исполняется (хуки Telegram WebApp, хаб «Статус/Ещё», стеклянный фон), **0 ошибок консоли**,
5 предупреждений — только вендорный `telegram-web-app.js`; вне Telegram — честное сообщение
«миниапп открыт без Telegram-контекста». Полный UI-цикл сохранения в браузере не выполнялся
(нет initData) — функциональный цикл закрыт HTTPS-приёмкой A; визуальная вёрстка — зона Reviewer.



## Как воспроизвести (без SSH)

```
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py readonly
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py full
`.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py recheck
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py edges
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_acceptance_25890.py payload
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_live_bc_25890.py read
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_live_bc_25890.py enable-gate
.venv\Scripts\python.exe plans/features/p0-save-init-ux/evidence/release-25890/acceptance/probe_logs_ring_25890.py
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
| `probe_acceptance_25890.py` | `4f3a73b80ab7897f` | пробник A (readonly/full/recheck/edges/payload) |
| `probe_live_bc_25890.py` | `0f8f15b838cd5a3a` | пробник B/C (read/enable-gate) |
| `probe_journal_25890.sh` | `998f9677c8f4fe3d` | журнальная фаза (bash, read-only) |
| `run_journal_ssh_25890.py` | `88ad20630008f325` | раннер журнальной фазы (один коннект) |
| `journal-25890-phase1.txt` | `e260c48e8765dbd1` | фаза-1: вывод журнала + SQLite (C закрыт, B ожидает тик) |
| `journal-25890-phase1.json` | `df58c11ccddd9a60` | фаза-1: SQLite-payload (`stage='anchored'` 13:40:06Z и др.) |
| `logs-ring-25890.json` | `824f88728d2144b9` | `/api/status/logs` ring-буфер: `ERROR=0`, `CRITICAL=0` |
| `probe_logs_ring_25890.py` | `714efb6c0e5c3962` | пробник ring-буфера логов |
| `acceptance-edges-25890.json` | `ada8b2bc4f68b99c` | E: негативные ветки (409 `document_invalid`, 422) без записи |
| `acceptance-payload-25890.json` | `d3278c13a5adf4ed` | F: payload-уровень (Inspector: preview-манифест композера) |
| `live-web/live_web_390.png` | `7fd5978f3e3db53a` | живая загрузка прод-сборки в браузере (390px) |
| `live-web/console.txt` | `a69ebdf06a6de56b` | консоль браузера: 0 errors, 5 вендорных warnings |
| `live-web/page_snapshot.yml` | `97f17be32215afd5` | a11y-снимок «нет Telegram-контекста» |

## Остатки (не закрыто в этом лейне)

1. **B**: первый тик ностальгии после T0 (окно 14:34–14:54Z) → строка `[nostalgia] scenario=A`,
   события `nostalgia_run` (`start` + терминальный outcome) и новые строки `nostalgia_log`
   (для PET `-1004482340693` — гейт уже включён 13:59:13Z). Проверка не ранее **14:58:00Z**
   (рекомендуется 15:00–15:10Z), фаза-2 того же пробника.
2. **D**: идентификация `ERR=2`/`TRACEBACK=1` (фаза-2 печатает сами строки с контекстом) и
   итоговые `ERROR/CRITICAL` за окно приёмки от T0.
3. После п.1–2 → обновление live-пунктов карт (`P0A-*`, `P0B-LIVE-*`) и release-стадия
   requirements-gate (`--candidate 3b02366e --deployed-commit 3b02366e`).
