# CFG-02B — «Лимит частоты генерации» (burst + пауза): design + evidence

**Лейн:** CFG-02B-BUILD (Builder; БЕЗ коммита — на ревью; SSH/прод не трогались).
**Дата:** 19.10.2026 · база HEAD `cb74531e` (на момент сборки; позже чужие docs-коммиты
подняли HEAD до `0ef8201b` — файлы дельты CFG-02B не пересекаются) · прод 2.58.89 ·
релиз-кандидат P0 2.58.90.
**Карта:** `plans/features/cfg/requirements-map.json`, слайс CFG-02B (17 строк: 02B.1–8, AC2–AC7).
**Тесты/логи:** `red-baseline.txt` (RED), `green-contract.txt` (GREEN), `blast-radius.txt`,
`ui/*.png` (Playwright + Browser Use), e2e-лог — `$OPENCODE_WORKFLOW_SCRATCH/_ui_cfg02b_image_freq.json`.

---

## 1. Design (зафиксировано до кода)

### 1.1 Ключи (4 поля СУЩЕСТВУЮЩЕЙ группы `limits_images`, per-chat, не-секреты)

| pg_key | Settings | тип/виджет | заводской дефолт |
|---|---|---|---|
| `limits.image_freq_limit_enabled` | `IMAGE_FREQ_LIMIT_ENABLED` | bool (тумблер) | **False** (§02B.1) |
| `limits.image_freq_limit_burst` | `IMAGE_FREQ_LIMIT_BURST` | int (number, ≥1) | 3 |
| `limits.image_freq_limit_cooldown_seconds` | `IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS` | int (number, ≥0, секунды) | 300 |
| `limits.image_freq_limit_mode` | `IMAGE_FREQ_LIMIT_MODE` | str + `widget=select` | `per_user` (§02B.2.3) |

Mode — ОДИН select из двух взаимоисключающих вариантов («Для каждого пользователя» /
«Общий на весь чат»); серверный select-контракт `web/api/routes.py` отклоняет чужие опции
(422), значит двух независимых галочек быть не может по построению.

### 1.2 Состояние лимитера (переиспользование, не новый стор)

- `services/persistent_throttling.py`: тот же token-bucket `throttle_state`, новый scope
  **`image_freq`**; ключ счётчика — `(chat_id, user_id|0)`: `per_user` → `user_id` участника,
  `per_chat` → `0`; `per_user` при неизвестном участнике → `0` (общий запас чата, «личного
  счётчика-обхода» не появляется).
- Состояние живёт в БД → переживает рестарт и делится между воркерами (AC7); refill —
  полное восстановление через `cooldown` от ПОСЛЕДНЕГО допущенного обращения (R50-7, тот же
  SQL, что у Direct Chat, кламп при смене лимитов — CFG-01).
- Runtime-SQLite берётся через существующий публичный геттер `lore_runtime.get_lore_db()`
  (тот же инстанс `DatabaseService`, что у Direct Chat; проводка `bot.py` без изменений).
  Нет БД → fail-open allow + WARNING; витрина честно показывает `no_db`.

### 1.3 Порядок гейтов в `generate_and_send` (единая точка до платного вызова)

```
read-only image_freq_state(chat)   # пауза активна → отказ (ничего не пишется!)
   ↓
_reserve_or_consume(...)           # CFG-02A: journal + дневная квота/legacy + replay
   ├ deny('budget')  → CFG-02A-отказ (журнал denied) + факт-строки обоих лимитов
   ├ already_ok      → «уже обработано»; частотный заряд НЕ трогается (replay)
   ↓
атомарное списание заряда image_freq_consume(...)   # ПЕРЕД платным вызовом
   ├ отказ (гонка) → release дневного резерва (квота возвращается) + отказ с остатком
   ↓
generate() → доставка
```

Почему так: read-only проверка даёт «отказ по паузе» ДО журнала/квоты (ничего не пишется),
атомарный `allow()` — единственная точка решения при параллели, replay оплаченного
сообщения до гейта не доходит (заряд не списывается второй раз), а отказ в гонке
освобождает уже созданный дневной резерв (§02B.4 «без списания дневной квоты»).

**Политика списания (документирована и покрыта тестами §02B.7):** заряд списывается в
момент допуска перед платной попыткой; provider error / отмена / delivery failure заряд НЕ
возвращают (восстановление только по времени, как у Direct-Chat bucket); replay
оплаченного сообщения — 0 дополнительных зарядов; при исчерпании обоих лимитов сообщение
показывает обе причины и оба срока («раньше более позднего срока недоступно»).

### 1.4 Семантика смены конфигурации/режима (спорная точка L87 — трактовка)

- Смена burst/cooldown посреди паузы: состояние не сбрасывается, заряды клампятся до
  нового лимита (CFG-01-семантика); уменьшение паузы укорачивает остаток на следующей
  проверке; увеличение burst «бонусных» зарядов не выдаёт.
- OFF→ON: выключение снимает запрет немедленно (гейт не применяется), состояние
  сохраняется; повторное ON возвращает прежний запрет (без «подарка»).
- **Смена режима (per_user ↔ per_chat)**: применяемый счётчик меняется (это и есть смысл
  настройки), но счётчики НЕ сбрасываются — после возврата к прежнему режиму прежний запрет
  продолжает действовать (тест `test_mode_switch_does_not_reset_counters`). Админ-смена
  режима не является пользовательским обходом: лимит продолжает действовать, просто по
  другому счётчику; оба состояния сохраняются в БД. Это осознанная трактовка L87
  «никаких скрытых сбросов» — вынести на решение Reviewer.

### 1.5 Область применения (§02B.5)

- Все пользовательские пути сходятся в `image_generation.generate_and_send` (direct
  пре-гейт `maybe_handle_keyword` → `run_image_request`; tool-путь `tool_router._generate_image`;
  legacy-ветки). Участник прокинут: `ImageRequest.requester_id` → `generate_and_send(user_id=…)`,
  `ctx.user_id` → tool/direct legacy.
- Контур обложек Summary (`generate_image_verbose` из `summary_generator`/cover-pipeline)
  лимитер НЕ проходит — доказано тестом `test_summary_cover_path_is_not_charged`
  (полная двусторонняя изоляция учёта — CFG-02C).
- Master-рубильник `flags.budgets_enabled` OFF снимает enforcement лимитера (учёт/состояние
  сохраняются) — паритет с `image_reserve_mode` («лимиты целиком»); витрина честно
  показывает «не действует: мастер-рубильник выключен».

### 1.6 Текст отказа (§02B.6)

- Новый класс/шаблон `message.image_failure.freq_limited` (константа
  `services.chat_prompts.IMAGE_FAILURE_FREQ_TEXT`, регистрация в `services/prompt_registry.py`
  с `pg_key=content.image_failure.freq_limited`, редактируется Factory Defaults; fingerprint
  набора речевых канонов переутверждён осознанно).
- ФАКТ-строки добавляются кодом (не часть шаблона): остаток паузы через существующий
  `format_remaining_time` («через 10 мин 20 сек (для тебя|на весь чат)»), свежий на каждую
  попытку; при исчерпании обоих лимитов — и суточная строка сброса + оговорка «раньше, чем
  закончатся оба ограничения, генерация недоступна».
- Observability: `image_generate/skipped` с существующим честным reason-кодом `cooldown`
  (без расширения словаря §17.2); отказ происходит до платного вызова.

### 1.7 Витрина (§02B.8)

- Каталог + `web/app.js` (`CONFIG_ITEM_DISPLAY_OVERRIDES`, помощники) + `web/index.html`:
  при OFF зависимые настройки скрыты (компактно), при ON показываются; «Время ожидания»
  показывает человеческий формат («≈ 10 мин 20 сек»).
- Новый блок фактов `data-image-freq-facts` в секции «Лимиты генерации» из аддитивного
  блока `freq` существующего `GET /api/workers/budget`: активность (ON-и-действует /
  ON-но-не-действует с причиной / заводской OFF), режим счёта, остаток (per-user — для
  запросившего админа, per-chat — весь чат), источник наследования, следующая доступность.
  Viewer передаётся аддитивно (`viewer_user_id`) — файл `web/api/gates.py` добавлен в
  allowlist bounds-тестов с NOTE-санкцией (прецедент прошлых волн).
- Второго счётчика нет: читается тот же `throttle_state` (`image_freq`).

---

## 2. Приёмка по строкам карты (evidence)

| req_id | Статус | Evidence |
|---|---|---|
| CFG-02B.1 | `TESTED` (preprod UI — за живой проверкой) | `TestCatalogAndDefaults::test_factory_defaults_off_and_per_user`, `TestFactoryOff::*` (3 генерации при OFF, состояние не пишется), e2e `freq_toggle_state=false`, `freq_active_label_off`, `frequency_off` note; скриншоты `ui/01-off-global.png`, `ui/browseruse-desktop-off*` |
| CFG-02B.2 | `TESTED` | e2e `dependent_hidden_when_off=0` / `dependent_visible_when_on=3`, `burst_input_present`, `cooldown_input_present`, `cooldown_human_label="10 мин 20 сек"`, `summary_line`; `ui/02-active-per-user.png` |
| CFG-02B.2.1 | `TESTED` | каталог: type int, «Положительное целое…один заряд перед каждой платной попыткой»; `normalize_image_freq_limits` (мусор → 1) |
| CFG-02B.2.2 | `TESTED` | каталог: секунды; `imageFreqCooldownLabel` («10 мин 20 сек»), e2e-проверка |
| CFG-02B.2.3 | `TESTED` | `test_mode_is_single_select_with_two_options` + серверный select-контракт; e2e `mode_select_options.opts == [Для каждого пользователя, Общий на весь чат]` |
| CFG-02B.3 | `TESTED` | `test_per_user_a_exhausted_b_continues`, `test_per_chat_shared_supply`, `test_buckets_are_isolated_per_chat`, `test_dm_positive_chat_id_not_mixed_with_daily`, `test_unknown_requester_uses_chat_bucket_no_bypass`, `test_resolver_paths_source_and_normalization` (chat/global/default, мусор) |
| CFG-02B.4 | `TESTED` | `test_third_attempt_denied_before_paid_call` (список платных вызовов не растёт), `test_after_pause_generation_allowed_again`, `test_config_change_during_pause_keeps_state`, `test_mode_switch_does_not_reset_counters`, `test_state_survives_restart_and_is_shared_between_workers`, `test_parallel_attempts_consume_exactly_burst`, `test_hot_reload_burst_takes_effect_without_restart` |
| CFG-02B.5 | `TESTED` | `test_direct_and_tool_paths_share_one_limiter`; обложки: `test_summary_cover_path_is_not_charged` (scope `image_freq` пуст после cover-вызова) |
| CFG-02B.6 | `TESTED` (preprod UI — за живой проверкой) | `test_bot_reply_carries_factual_remaining` (бот-блок: «через 10 мин», «весь чат»), `test_per_user_reply_names_user_scope` («для тебя»), `test_both_limits_details_list_both`; шаблон `freq_limited` в реестре (Factory Defaults) |
| CFG-02B.7 | `TESTED` | `test_replay_does_not_consume_frequency_twice` (−1 заряд), `test_provider_error_keeps_charge_quota_returned`, `test_delivery_failure_keeps_charge`, `test_both_limits_details_list_both` (оба срока) |
| CFG-02B.8 | `TESTED` (preprod UI — за живой проверкой) | `TestUsageFacts::*` (`enabled/active/active_reason/mode/source/per_user/per_chat/next_available_at`), `test_day_summary_passes_viewer`; e2e-блок `[data-image-freq-facts]` (активность/режим/источник/остаток/доступность) + Browser Use DOM-факты и скриншоты |
| CFG-02.AC2 | `TESTED` | `TestFactoryOff::test_off_does_not_limit_and_writes_nothing` (3 генерации, 0 запретов/замедлений) + e2e OFF |
| CFG-02.AC3 | `TESTED` | `test_third_attempt_denied_before_paid_call` + `test_bot_reply_carries_factual_remaining` + `test_after_pause_generation_allowed_again` |
| CFG-02.AC4 | `TESTED` | `test_per_user_a_exhausted_b_continues` |
| CFG-02.AC5 | `TESTED` | `test_per_chat_shared_supply` |
| CFG-02.AC6 | `TESTED` | `test_off_lifts_pause_immediately_state_preserved` + `test_parallel_attempts_consume_exactly_burst` |
| CFG-02.AC7 | `TESTED` (частично preprod) | hot-reload/мультиворкер/рестарт/параллель/replay/provider/delivery — перечислены выше; «суточный сброс и разные TZ» — CFG-02A-контур (TZ дня квоты) + тест DM/daily; живой прогрев — preprod |

**Live (preprod UI/поведение) — за живой проверкой окна CFG:** §02B.1/.2/.2.3/.6/.8, AC2/AC3
(скриншоты локального детерминированного стека приложены; реальный прод-стек — CFG-FINAL/ADD-2.2).

## 3. Каталог-дельта и заморозки

См. `catalog-delta.md`. Кратко: +4 ParamSpec (REGISTRY 575→579, Settings 454→458,
categorized 550→554, delta 164→168); GROUPS/_TAB_BY_GROUP/TAB_RULES/routes — без изменений;
`gen_param_registry --check` = OK; `PARAM_CATALOG_SHA256_FOLLOWUP` и
`FACTORY_SET_SHA256_12` переутверждены инструментом `tools/_cfg02b_reissue_f8.py`.

## 4. Остатки/риски

- **R1 live:** preprod-стек (02B.1/.2/.2.3/.6/.8, AC2/AC3) — отдельное окно CFG (не в этом лейне).
- **R2 трактовка L87 (смена режима)** — вынести на ревью (см. §1.4).
- **R3 соседний незакоммиченный лейн в рабочем дереве**: `web/api/routes.py` +
  `services/mca_vision.py` + `services/cover_style_jobs.py` + `tests/test_mca19_block_b/c_round1043.py`,
  `tests/test_mca23_planned_vs_actual.py` (P0-vision дельта; их re-pin `ROUTES_SHA256_F11 =
  21f72a8e…` и CRLF-перелицовка `tests/test_round1025_f8_registry.py` прилетели от них в
  03:46). На момент сдачи весь прогон зелёный (1959 passed), но коммитить дельту CFG-02B
  следует отдельно от этих файлов; правила `plans/current_task.md`/`plans/workflow_state.md`
  не трогались.
- **R4** `image_reserve_mode` legacy (env kill-switch) не отключает частотный лимитер —
  осознанно (отдельный тумблер); master бюджета OFF — отключает.
