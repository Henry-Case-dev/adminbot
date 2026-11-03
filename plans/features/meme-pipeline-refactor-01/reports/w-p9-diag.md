# P9 / MEME-INIT-DIAG — диагностика ПО КАЖДОМУ механизму (сервисный слой)

Исполнитель: Builder (lane `feat/meme-init-diag`).
База: `a43e366e` (merge P8 MEME-INIT-COORDINATION).
Карта: `requirements-map.json`, слайс `MEME-INIT-DIAG`, строки
`MEME-IIC-DIAG-TIMES` / `-RANDOM` / `-COOLDOWN-CONFLICT` / `-NO-MIX`
(`owner_input_id = OI-2026-11-03-INITIATIVE-INDEPENDENCE`, `strict_evidence: true`).
`MEME-IIC-DIAG-UI` (слайс `MEME-UI-FIELDS`) — P4, здесь сознательно НЕ делается.

## 1. Одна функция, два независимых блока

`services/initiative_diagnostics.py` (аддитивно, 718 строк в конце модуля):

```python
await collect_mechanism_diagnostics(db, chat_id, *, now=None,
                                    meme_settings=None, ledger=None,
                                    image_health=None, publication=None)
# -> {"schema_version": 1, "generated_at": int, "chat_id": int|None,
#     "text_initiative": {...блок...}, "meme": {...блок...},
#     "degraded": ["text_initiative"|"meme", ...]}
```

Внутри — две отдельные сборки: `text_mechanism_diagnostics` (читает
`initiative_observer.chat_block_state` — то же read-model, что у ворот боевого
пути) и `meme_mechanism_diagnostics` (журнал попыток + `payload["meme"]["chats"]`
+ бронь `PublicationCoordinator.precheck`). Ни одно поле одного блока не
вычисляется из другого; `output_kind` различает источники
(`initiative_reply` / `meme_initiative`). `degraded` — список механизмов с
`publication.coordination == "degraded"` (готовая подсказка для UI).

Источники — только существующие: `task_jobs.payload` (`kind='initiative.observe'`),
`meme_initiative_reservation` (журнал попыток), `mca_bot_outputs`,
`chat_publish_claim` (бронь). **Новых таблиц, миграций, колонок и событий нет**
(в `mca_events` не пишется ничего). Сборщик никогда не бросает, ничего не
отправляет, LLM не вызывает.

## 2. Контракт блока (P4 читает ровно это)

`MECHANISM_BLOCK_FIELDS` — все ключи есть **всегда**:

| Поле | Тип / значения | Семантика «нет данных» |
|---|---|---|
| `mechanism` | `"text_initiative"` \| `"meme"` | всегда |
| `output_kind` | `"initiative_reply"` \| `"meme_initiative"` | всегда |
| `source` | строка-источник | `""` при `chat_not_selected` |
| `available` | bool | `false` = данных нет |
| `data_state` | `"ok"` \| `"no_data"` | дубль-флаг к `available` |
| `no_data_reasons` | список кодов `NO_DATA_*` | `[]` когда данные есть |
| `ready` | bool \| null | `null` = готовность неизвестна (мем: `availability` не прочитан, текст: список ворот недоступен) |
| `ready_reason` | код причины | `""` |
| `last_check_ts` | int \| **null** | `null` = проверок НЕ БЫЛО НИКОГДА (в журнале это `0`) |
| `next_check_ts` | int \| null | `null` = дата не рассчитана |
| `next_check_basis` | `payload_state`\|`cooldown`\|`eval_interval`\|`every_pass`\|`unknown`\|`never_checked`\|`chat_not_selected` | — |
| `random` | `DRAW_FIELDS` \| null | `null` = трассы draw нет |
| `conditions` | плоские скаляры \| null | `null` = условий не записано |
| `stages` | счётчики стадий \| null | у текста всегда `null` (стадий нет) |
| `skip` | `SKIP_FIELDS` \| null | текущая причина «не сработает сейчас» |
| `skip_recorded` | `SKIP_FIELDS` \| null | что записал прошлый проход |
| `cooldown` | `COOLDOWN_FIELDS` | всегда (см. §3) |
| `quota` | `QUOTA_FIELDS` | всегда (см. §3) |
| `publication` | `PUBLICATION_FIELDS` \| null | `null` = бронь не проверялась |
| `blocking` | `{"blocked":[{"gate","status","reason_code","label"}...], "warned":[...]}` \| null | только текст (`chat_block_state.items`); у мема `null` |

`random` (`DRAW_FIELDS`): `performed`, `outcome` (`draw`|`no_draw`), `value`,
`hit`, `probability`, `purpose`, `draw_id`, `source` (ФАКТИЧЕСКИ использованный
источник), `source_impl`, `provider`, `selected_source` (выбранный настройкой),
`fallback` (bool) + `fallback_reason`, `policy_version`, `attempts`, `reason` +
`reason_label`, `no_draw_reason`, `ts`.

`cooldown` (`COOLDOWN_FIELDS`): `scope="mechanism_own"`, `own_seconds`
(int|null — свой кулдаун механизма), `remaining_seconds` (int|null),
`basis` (`last_initiative_publication`|`last_provider_call`|
`no_prior_publication`|`no_prior_provider_call`), `basis_ts` (int|null).

`quota` (`QUOTA_FIELDS`): `scope`, `limit`, `used`, `remaining`, `unlimited`,
`limit_reached`, `available` (мем: прочитан ли журнал), `next_reset`.

`publication` (`PUBLICATION_FIELDS`): `available`, `coordination`
(`ok`|`degraded`), `degraded`, `degraded_reason`, `conflict` (bool|null —
**единственный** признак конфликта), `conflict_state`
(`clear`|`conflict`|`unknown`), `ok`, `reason` + `reason_label`, `detail`,
`state`, `holder_kind` (для кого спрашивали), `claimed_by` (кто реально держит
бронь), `other_kind`, `other_age_seconds`, `interval_seconds`,
`manual_priority_until`, `checked_at`.

`skip` (`SKIP_FIELDS`): `code` (существующий код механизма из
`initiative_observer.REASON_LABELS`), `label`, `origin`
(`gate`|`availability`|`quota`|`cooldown`|`quiet_hours`|`publication` —
текущее состояние; `payload_state`|`journal` — запись прошлого прохода).

## 3. Честные правила (реализованы, проверяются тестами)

1. `{}`/`null`/пустой список = «данных нет», а не нули: `random`, `conditions`,
   `stages`, `publication`, `skip`, `skip_recorded` — `null`; `cooldown.own_seconds`
   и `quota.limit` — `null`, если настройку прочитать не удалось.
2. `last_check_ts == null` = «никогда»; `0` из журнала превращается в `null`
   (`_stamp_or_none`), 1970 год в UI не появляется. При этом
   `cooldown.remaining_seconds = 0` — **законный** ноль, его причина видна в
   `cooldown.basis` (`no_prior_publication`/`no_prior_provider_call`). «Никогда»
   и «нулевой остаток» — разные поля.
3. `publication` — единственная правда о конфликте. При
   `coordination="degraded"` (бронь недоступна) пишется `available=false`,
   `conflict=null`, `conflict_state="unknown"` — деградация НЕ выдаётся за
   «конфликта нет». Записанный в payload `skip_reason="publication_conflict"`
   сам по себе конфликт не создаёт (он попадает в `skip_recorded`).
4. `random.reason="probability_one"` (порог 1.0, боевой паритет) → `performed=false`,
   `outcome="no_draw"`, `hit=null`, `value=null`, `draw_id=null`,
   `no_draw_reason="probability_one"`. То же для `probability_zero`,
   `deferred`/`random_unavailable`. `fallback_reason` при наличии `value` — НЕ
   отказ: `performed=true`, в `source` — фактически использованный источник.
5. Остаток кулдауна считается ТОЛЬКО по собственному кулдауну механизма:
   текст — `effective.min_gap_seconds` от последней ИНИЦИАТИВНОЙ публикации;
   мем — `settings.cooldown_seconds` от `ledger.last_provider_ts` (ровно базис
   боевого гейта `consider_chat`, строки 1484–1487). TTL брони
   (`CLAIM_TTL_SECONDS=90`, `SENDING_TTL_SECONDS=120`,
   `MANUAL_PRIORITY_SECONDS=600`) и `manual_priority_until` в кулдаун не
   попадают — они только в `publication`.
6. Квота: у мема `daily_limit <= 0` — предел (боевой гейт отдаёт
   `daily_quota_reached`), у текста `max_replies_per_day <= 0` — «без капа».
   Поэтому `quota_block(..., zero_means_unlimited=...)` и поле `limit_reached`
   вместо одного «unlimited» на оба механизма.
7. Причина пропуска — существующие коды, порядок = порядок боевых гейтов:
   мем `availability` → квота → кулдаун → тихие часы → бронь; текст — первый
   `block` из `chat_block_state.items`. Проверяется тестом:
   `skip.code in REASON_LABELS` (новых кодов пайплайна не введено).
8. R17: наружу только коды/числа/ID. Текст прикола/выжимки/промптов в ответ не
   попадает: `conditions`/`stages` фильтруются `_scalar_dict` (плоские скаляры),
   ключи ответа фиксированы контрактом. `NO_DATA_*` — локальные маркеры
   отсутствия данных, не `reason_code` пайплайна (в события/payload не пишутся).

## 4. Тесты (`tests/test_meme_init_diagnostics.py`, 14 тестов, CONTRACT)

| # | Тест | Что доказывает |
|---|---|---|
| 1 | `two_blocks_are_present_and_independent` | мем проверялся, текст — ни разу: у мема время/draw/стадии, у текста `null` + `never_checked` |
| 2 | `never_checked_is_distinguishable_from_zero_cooldown` | `last_check_ts=null` vs законный `remaining_seconds=0` с `basis`; `next_check_ts=null` |
| 3 | `degraded_coordination_is_reported_as_degradation` | нет таблицы брони → `degraded`, `conflict=null`, `conflict_state=unknown`, `ok=null`, `degraded=[оба]` |
| 4 | `conflict_marker_comes_only_from_publication` | записанный `publication_conflict` → `skip_recorded`, конфликт появляется только после реальной публикации другого типа |
| 5 | `probability_one_is_reported_as_no_draw` | `performed=false`, `hit=null`, `value=null`, `draw_id=null`, источник не выдумывается |
| 6 | `cooldown_remaining_uses_mechanism_cooldown_not_claim_ttl` | 6 ч своего кулдауна − 1 ч = 5 ч; ни 90/120/600 не подменяют; `manual_priority_until` только в `publication` |
| 7 | `no_joke_summary_or_secret_leaks` | тексты прикола/выжимки отсутствуют в JSON; ключи ⊆ контракта; в условиях только короткие коды |
| 8 | `diagnostics_is_additive_and_does_not_mix_meme_analytics` | `analytics_snapshot` до/после: те же ключи и типы; durable payload не перезаписан; `output_kind` мема не в `INITIATIVE_OUTPUT_KINDS` |
| 9 | `collector_never_raises_on_broken_source` | `db` бросает → оба блока `no_data`, исключения нет |
| 10 | `blocks_match_documented_contract_shape` | ключи блока = `MECHANISM_BLOCK_FIELDS`, вложенные = своим константам, `skip.code ∈ REASON_LABELS` |
| 11 | `two_states_change_times_conditions_and_recorded_skip` | два разных состояния → разные `last_check_ts`/`conditions`/`skip_recorded`, `next_check_ts` сдвигается ровно на разницу (не константа) |
| 12 | `current_skip_reports_own_cooldown_and_quota` | мем в паузе → `cooldown_active` (origin `cooldown`); квота → `daily_quota_reached` (origin `quota`) при нулевом кулдауне |
| 13 | `zero_limit_semantics_differ_per_mechanism` | `daily_limit=0` у мема = предел; `cap<=0` у текста = без капа |
| 14 | `missing_chat_yields_no_data_blocks` | `chat_id=null` → оба блока `chat_not_selected`, кулдаун/квота `null`, без исключения |

Нормализация времени — параметром (`now`), `sleep` нет; внешние швы мема
(`summarizer`/`joke_generator`/`image_provider`/`sender`/`random_source`) —
штатные DI-аргументы; предмет проверки (payload, журнал, бронь, сборщик) не
подменяется.

**Мутационная проверка (тесты умеют падать).** Внешним pytest-плагином
(`WorkspaceData/runs/p9-diag-mutations`, исходники не менялись) по очереди
ломалась семантика: кулдаун из `CLAIM_TTL_SECONDS`; `degraded → conflict=false`;
`_stamp_or_none` возвращает `0` вместо `null`; `draw_block` всегда
`performed=true`; текст получает блок мема; в ответ добавляется лишний ключ
`joke_preview`; в `conditions` попадает свободный текст. Каждый раз падал
соответствующий тест (1/2/3/5/6/7/10), после снятия мутации — снова зелено.

## 5. Прогоны

| Набор | Результат |
|---|---|
| `tests/test_meme_init_diagnostics.py` | **14 passed** (5.5 с) |
| `test_soul1_w5_initiative_vitality` + `test_initiative_coordination` + `test_initiative_delivery_telemetry` + `test_round1025_f8_registry` + новый файл | **133 passed** (24 с) |
| `-k "meme or initiative or init_coord"` (весь `tests/`) | **328 passed**, 17595 deselected (46 с) |

Мутационные прогоны — по одному целевому тесту на мутацию, все падения ожидаемые.
Изменены только: `services/initiative_diagnostics.py` (аддитивно, +718 строк) и
новый `tests/test_meme_init_diagnostics.py`. `services/meme_initiative.py`,
`services/initiative_observer.py`, `publication_coordination.py`, `web/**`,
`handlers/**` не тронуты.

## 6. Что P4 (UI) делает и чего не делает

* Читать `collect_mechanism_diagnostics(...)["text_initiative"]` и `["meme"]`
  как **два отдельных блока**; ключи — как в §2; каждый `null` показывать как
  «нет данных», отдельно от нуля (особенно `last_check_ts` и
  `cooldown.remaining_seconds`).
* Конфликт публикаций рисовать ТОЛЬКО из `publication`; при
  `degraded` — плашка «координация недоступна», а не «конфликта нет».
* Для старых БД/пустого payload блок остаётся полным, просто с `no_data_reasons`.
* P4 НЕ вызывает `text_mechanism_diagnostics`/`meme_mechanism_diagnostics`
  по отдельности для склейки: склейка на стороне UI запрещена (смешение
  показателей разных механизмов).

## 7. Ограничения / что осталось непроверенным

* `MEME-IIC-DIAG-UI` (Playwright + API-проверка двух блоков в админке) — P4,
  вне этой полосы; здесь доказан только сервисный контракт.
* Живая приёмка на проде (`live_when: preprod`, `live_required: false` по карте)
  не выполнялась: web/Telegram не трогались, деплоя нет.
* `MEME-IIC-DIAG-TIMES`: «причина собственного кулдауна» для текста приходит из
  ворот (`min_gap`/`anti_flood`), потому что собственный кулдаун текста и есть
  `min_gap`; отдельного поля `cooldown.skip_reason` в payload нет и не заводится.
* `blocking` у мема `null` намеренно: у мема нет списка ворот, его состояние
  выражено `ready`/`ready_reason`/`skip`. Если P4 понадобится единый вид —
  использовать `skip` (у текста он тоже заполняется боевым первым блоком).
