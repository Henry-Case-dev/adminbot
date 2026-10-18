# NOSTALGIA-FIX — evidence (P0 follow-up §2–§3, 18.10.2026)

Лейн: `NOSTALGIA-FIX` (writer; БЕЗ коммита — на ревью вместе с лейном INIT-FIX в том же
рабочем дереве; пересечений по файлам нет).
Базовая точка: commit `2c916f35` (все RED/GREEN-прогоны привязаны к нему).
Прод-диагностика: один read-only SSH-коннект (см. `prod-readonly-2026-10-18.txt`).

## 1. Диагностика блокеров (§2) — факты

| # | Блокер | Вердикт | Факты |
|---|--------|---------|-------|
| 1 | OFF на старте → job не регистрируется; hot-включение не поднимает | **ПОДТВЕРЖДЁН (механизм, латентный)** | `services/nostalgia_worker.py::start()` делал ранний `return` при флаге off; единственный вызов `start()` — `bot.py:760` (grep по репо: иных точек регистрации/ре-регистрации нет). Если бот стартовал с `memory.nostalgia_enabled=false`, последующее hot-включение не создавало джоб до рестарта. В текущем прод-инстансе замаскирован: в PG флаг уже `true`, журнал 18.10 07:37:35 «NostalgiaWorker started (tick=60min, silence=45min, max_per_day=3, aggressiveness=0.3)» + почасовые тики. Тот же паттерн у DreamWorker уже исправлен ранее (ARCHITECTURE F7 D4: «регистрирует джобы **всегда** … переключение тумблера действует без рестарта»). |
| 2 | Заводской `NOSTALGIA_ENABLED=False` | **ПОДТВЕРЖДЁН (код)** | `config/settings.py:3214` default False; `param_catalog` — «оба рубильника off (Q12)». В проде `.env` ключа `NOSTALGIA_ENABLED` нет (grep .env: только `DB_PATH`/`GRAPH_RAG_ENABLED`), включение идёт через hot PG: `memory.nostalgia_enabled = true` (+ `memory.nostalgia_layer_a_enabled = true`). Т.е. ось включения = hot; она теперь работает и без рестарта. |
| 3 | 45-мин тишина применяется и к контекстному сценарию | **ПОДТВЕРЖДЁН (прод, основной фактический блокер)** | Каждый тик (28+ строк в journal за 30 дн): `[nostalgia] skip | chat=-1002661910336 | reason=silence_too_short`; чат активен постоянно (2 026 184 сообщения, последнее — минуты назад), поэтому ни один кандидат не достигнут: в окне «год назад ±10д» лежит 26 738 сообщений. `nostalgia_log` за всю историю: `sent`=2, `budget_skip`=209. |
| 4 | cooldowns/quiet hours/лимиты/пороги/budget-гейты | **НЕ ПОДТВЕРЖДЁН как блокер (кроме quiet hours-как-второго-замка)** | В `nostalgia_log` НЕТ ни одной строки с reason cooldown/max_per_day/threshold/budget — до этих гейтов не доходило (тишина резала раньше). `worker_budget` в норме (global llm_calls: 17 за сутки, llm-бюджет не выбирался; все 209 `budget_skip` — это `{"reason": "gate_nostalgia"}` per-chat тяжёлого гейта чата -1004482340693, не budget). Quiet hours (23–8 local) сам по себе не наблюдался на практике, но в паре с тишиной он бы закрывал любую вечернюю живую беседу — в сценарии A снят. Порог/лимиты/cooldown/Q14 сохранены как анти-навязчивость. |
| 5 | SILENT после делегирования в общий Decision | **НЕ ПОДТВЕРЖДЁН прод-данными о самой ностальгии; механизм есть — штатный mca-10b** | В `nostalgia_log` нет ни одной строки `initiative_*` — делегирование в проде фактически не запускалось (кандидаты не проходили тишину). Код-уровень: при K1+K3 ON (в проде ON) кандидат идёт в `handle_initiative` с `prepared_text`; наш `InitiativeSituation` — все дефолты (direct_pending/sensitive/topic_open → проходят). Возможный silent = штатный mca-10b exploration: `memory.random_exploration_probability` (default **0.05**, `mca_random_source.py:134`) — рекон INIT-FIX фиксирует живые `random_uses/stage=conversation_variant outcome=success` в проде (`evidence/initiatives/prod-readonly-dump-02-recon.txt`), т.е. ось активна; при success ~1 из альтернатив — форма `silence` (action=silent) → честное молчание, либо `deferred` → `random_fallback`. Это общий механизм всех инициативных путей, не второй контур ностальгии, дефектом лейна не является; после включения наблюдать `initiative_*` причины. Наш путь различим: `source=nostalgia`, `trigger_kind=nostalgia_due`, `prepared_text_ref=nostalgia:<fact|kind>` (закреплено тестом). |

## 2. Что исправлено (файлы + sha12)

| Файл | sha12 | суть |
|------|-------|------|
| `services/nostalgia_worker.py` | `da8c9b79e9cf` | (a) `start()` регистрирует джоб ВСЕГДА (idempotent `replace_existing`); (b) `_run_tick` при OFF — дешёвый no-op (событие `nostalgia_run` skipped/disabled); kill-switch `run_once` сохранён; (c) A/B-разделение: последнее юзерское сообщение свежее окна тишины → **сценарий A** (гейты «45-мин тишины» и quiet hours НЕ применяются), старше → **сценарий B** (прежние гейты: quiet hours/cooldown/лимит/Q14); (d) `active` пробрасывается в user-блок LLM; (e) на ON-пути композера база — функциональный `NOSTALGIA_CORE_CANON` (legacy-персона не конкурирует с SOUL-1 Core); OFF-путь — байт-в-байт прежний канон. |
| `services/nostalgia_prompts.py` | `26b8e73ece03` | новый `NOSTALGIA_CORE_CANON` (формат ответа + слово отказа UNCHANGED, без тонально-личных утверждений); `build_nostalgia_user(..., active=False)` — преамбула «В чате сейчас живая беседа…» для A (обратная совместимость по умолчанию сохранена; B — прежний текст). |
| `services/mca_authorial_speech.py` | `1708a1425605` | аддитивный `core_canon: str | None = None` — функциональная база для режима с Core; `None` → прежнее поведение; OFF-путь всегда отдаёт `legacy_canon` байт-в-байт. |
| `services/param_catalog.py` | `0fc58b110fcc` | описание `memory.nostalgia_enabled` приведено к правде («тик становится дешёвым no-op; горячее включение работает без рестарта») — прежний текст «тик не регистрируется, 0 влияния» стал ложью. |
| `plans/docs/param-registry-round1025.tsv` / `.meta.md` | `5c5bef03d4b2` / `d11ea9c010bb` | ре-эмиссия тем же инструментом (`tools/gen_param_registry_round1025.py`), дельта 1 строка (только это описание); `--check` OK (575 строк). |
| `tests/test_p0_followup_nostalgia_ab.py` (new) | `92c304ae50d8` | контракт A/B + hot-enable + единый Decision (см. воронки ниже). TEST-LIFECYCLE: REGRESSION (job registration) + CONTRACT (A/B split), owner=p0-followup/NOSTALGIA-FIX. |
| `tests/test_nostalgia_worker.py` | `4e28a5254e88` | обновлены два теста под новый контракт: джоб регистрируется всегда (OFF → no-op, run_once режется kill-switch); короткая тишина — не «silence_too_short»-скип, а сценарий A. |
| `tests/test_soul1_w4_authorial_genre.py` | `1e2bf44d179b` | новый кейс `core_canon` (ON-путь: Core+жанр+UNCHANGED, без «токсично-тёплый»). Прежние W4-контракты (в т.ч. OFF-паритет) не изменены и зелёные. |
| `tests/test_round1025_f8_registry.py` | `21625eae27c2` | re-pin freeze-теста каталога по прецеденту L-F11S-1 (новая константа `PARAM_CATALOG_SHA256_FOLLOWUP` + комментарий; исторический fixture не тронут). |

Хвостовые артефакты (по решению PM/Orchestrator, вне лейна): `plans/ARCHITECTURE.md` §2c (строка ~332) описывает тишину как безусловный skip-гейт — после A/B это устарело.

## 3. Как доказано (RED → GREEN)

- **RED** — `red-baseline-2c916f35.txt`: чистый `git worktree` на `2c916f35` + только файлы этого лейна (код-фиксы НЕ копировались, тесты — да): **9 failed / 1 passed** — все новые контракты падают на прежнем поведении (job отсутствует; `silence_too_short` режет A; quiet hours режут A; `no_candidates`/`unchanged` недостижимы; в system-промпте живёт «токсично-тёплый»; `authorial_system(core_canon=…)` — TypeError; делегирование не достигается). Контроль B (quiet chat + quiet hours → skip) был зелёным — прежний контракт B сохраняется.
- **GREEN (лейн изолированно)** — `green-lane-only-2c916f35.txt`: тот же worktree + код-фиксы лейна: `334 passed`, 0 failed.
- **GREEN (комбинированно, рабочее дерево с uncommitted INIT-FIX)** — `green-combined-main-worktree.txt`: `370 passed`, 0 failed (20 файлов: nostalgia/soul1-W4/mca17/mca09-b/d/e/off-parity/feature_gates/webapp-мемори/каталог/freeze/registry).
- Смежные массовые прогоны: `-k "soul1 or nostalgia or authorial or param_catalog or prompt_registry"` → **766 passed**; `tools/gen_param_registry_round1025.py --check` → **OK** (575 == REGISTRY, TSV/map идемпотентны).
- Честная заметка: один промежуточный комбинированный прогон дал `test_candidate_ready_defers_intent_backoff` (файл лейна INIT-FIX, `test_mca09_intents_block_e_round1040.py`) — падение было транзиентным в момент их правок файлов; standalone и повторный комбинированный прогон — зелёные. К моему лейну не относится.

## 4. Воронки (контролируемые сценарии; тесты, не «запуск планировщика»)

- **A (живая беседа, `last_user` 300 c назад)**: наблюдение → кандидат `year_back` (вес 0.7 ≥ порога 0.45) → 1 LLM-вызов → отправка → `nostalgia_log: sent/year_back`; в user-блоке — «В чате сейчас живая беседа. Вот память:» (без ложного «давно тихо»).
- **A + quiet hours (23:00)**: отправка проходит (в B тот же час — skip, контрольный тест).
- **A-отказы**: кандидатов нет → `skipped/no_candidates` (строка лога, без отправки); LLM вернул UNCHANGED → `skipped/unchanged` (дневной лимит не тратит).
- **A через единый Decision (K1+K3 ON)**: спй на `handle_initiative` фиксирует `source=nostalgia`, `trigger_kind=nostalgia_due`, `prepared_text_ref=nostalgia:*`, готовый текст; строка лога `sent`, `meta.path=initiative` — тот же единый Decision/транспорт, второй send-path не создан.
- **Hot-enable без рестарта**: старт с OFF → джоб `nostalgia_tick` всё равно зарегистрирован, тик — no-op, `run_once` — kill-switch skip; после смены флага в hot-кэше тот же процесс на следующем тике отправляет (sent=1).
- **B (затишье)**: quiet hours/тишина/паузы работают как раньше (контрольные тесты зелёные).

## 5. Что осталось живой проверкой (после штатного деплоя; не засчитывать тик как доказательство)

1. Journal: появилась строка `[nostalgia] scenario=A (живая беседа) | chat=-1002661910336 …` (тик ≤60 мин + jitter ≤20 мин после рестарта).
2. Дальше по воронке — либо `[nostalgia] sent | chat=… | kind=year_back|golden`, либо честная причина (`no_candidates`/`threshold`/`unchanged`/`budget_skip`/`initiative_*` — зафиксировать код).
3. `nostalgia_log` (SQLite): новая строка по чату `-1002661910336` (sent или skipped+reason) — впервые за долгое время (исторически sent=2).
4. `mca_events`: `nostalgia_run` start + success; при наличии кандидатов не должно вечно оставаться `skipped/no_relevant_memory`.
5. Чат `-1004482340693` остаётся за per-chat гейтом (`gate_nostalgia`, 209 записей) — для PET-релиза включить per-chat `gates[nostalgia]=true` (конфиг, не код); после этого тот же прогон воронки.
6. Не делать лишних SSH-коннектов (fail2ban); все проверки — read-only (journalctl/sqlite/psql SELECT).

## 6. Остатки/находки
- **UI-правдивость (related, вне лейна)**: `web/api/memory_agi.py::_nostalgia_state` (стр. 745–769) + `web/app.js::nostalgiaLabel` (стр. 20713–20723) показывают «Тишина: N/45 мин» там, где теперь действует сценарий A (вспоминание уже возможно). Рекомендация UI-слайсу: добавить поле `active` (mode 'silence') и лейбл «Живая беседа — вспомнит, если уместно». Функциональный фикс не блокирует.
- **exploration/mca-10b** (см. блокер 5) — при `random_uses/conversation_variant` draw (default p=0.05) возможен `initiative_*`-silent/`random_fallback`; штатное поведение общего Decision, наблюдать в живом прогоне (`mca_events`/`nostalgia_log`).
- `bot_replied_recently` в `InitiativeSituation` делегирования остаётся дефолтным `False` (нет дешёвого источника «последней реплики бота»); защита — cooldown/лимиты/Q14.
- Backlog **T-1764** (nostalgia читает `memory.nostalgia_*` только глобально, без per-chat) не входит в P0-followup и не трогался.
- Pre-existing (до лейна): `test_intent_status_snapshot` (restricted/no_chat) падал на базовой точке — исправлен правками лейна INIT-FIX; в комбинированном прогоне зелёный.

## 7. Координация с картой требований и лейном INIT-FIX

- Карта (`requirements-map-followup.json`, обновлена PM в 20:41 18.10): слайс **P0B-NOST**. Покрытие этим лейном (код + тесты + pre-deploy диагностика): `P0B-NOST-RESTORE` (§1), `P0B-NOST-DIAG` (прод-диагностика — этот README + `prod-readonly-2026-10-18.txt`; пост-деплой артефакт — см. §5, шаг релиза), `P0B-NOST-SCEN-A/-B` (код-контракт и контролируемые воронки — тесты; живое подтверждение — после штатного деплоя), `P0B-NOST-ONE-CONTOUR` (артефакт `system-prompt-on-vs-off.txt`: ON-промпт без legacy-персоны, UNCHANGED сохранён, OFF байт-в-байт), `P0B-SEPARATION` (поля кандидата в том же артефакте + тест делегирования). `P0B-LIVE-*`, `P0B-GOAL`, деплой/ревью — вне лейна.
- В том же рабочем дереве — **uncommitted** правки лейна INIT-FIX (`services/direct_chat_service.py`, `services/initiative_observer.py`, `services/mca_intents.py`, `services/status_service.py`, их тесты, `evidence/initiatives/**`). Пересечений по файлам с этим лейном нет; мой «lane-only» прогон (worktree на `2c916f35` + только файлы этого лейна) — 334 passed, чистый от их состояния.
- Пер-чат гейт `gates[nostalgia]` для чата `-1004482340693` — конфиг прода (включение при релизе, PET); в код не входит.
- Файл `tests/test_round1025_f8_registry.py` получил re-pin freeze-хэша каталога (L-F11S-1) — ожидаемо для правки description; `--check` зелёный.
