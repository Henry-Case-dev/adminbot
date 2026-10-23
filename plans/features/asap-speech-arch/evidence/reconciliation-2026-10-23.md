# Аудит карт требований — PM-RECONCILE (23.10.2026)

Лейн: `PM-RECONCILE`, режим writer (только документы/карты плана). Время: 23.10.2026, 04:14 UTC+12:00.
Прод не трогался: 0 SSH, 0 записей, 0 сообщений в чаты. Использованы только уже лежащие в репозитории evidence, git-объекты и read-only прогон тестов.

## 0. Короткий итог

- Исходно открытых required-строк в `asap-speech-arch`: **82** (74 inventory + 41 manual − 33 уже VERIFIED).
- После аудита: **38 BIND → VERIFIED**, **44 осталось PENDING**.
- Классы остальных: **25 NEEDS_AGENT_CHECK**, **2 NEEDS_LIVE_OBSERVATION**, **17 NEEDS_IMPLEMENTATION**.
- Ни одна строка не объявлена VERIFIED без конкретного артефакта в репозитории и реального commit/deploy SHA.
- `soul-1`: 2 строки переведены в `owner_optional` (только личное наблюдение), 1 — агентская телеметрия, 1 — WAITING_EXTERNAL (видео-провайдер).
- `asap8-v6.3`: 4 U07-строки про реальные клиенты — `owner_optional`; 5 строк (`REQ-B09-BODY`, `B10-R06`, `B10-R10`, `B10-R11`, `REQ-B11-E2E`) — агентские read-only проверки.
- W4-UI и `asap2-direct-chat` не биндились: это активные чужие лейны.

## 1. Как считались 82 и что было с «строками-заголовками»

В карте `asap-speech-arch` 120 inventory-строк: 74 `required`, 35 `context`, 11 `duplicate`; плюс 41 manual-строка в `additional_requirements`. Итого required = 115. На начало аудита 33 из них были VERIFIED, 82 — открыты.

Проверка прежнего бага: в текущей карте **46 строк без `req_id`**, и все они имеют `disposition: context` или `duplicate`; ни одна не является required. `workflow_progress.py` фильтрует `disposition != required`, поэтому в знаменатель они не входят. Состояние исправлено; при будущих правках нельзя возвращать заголовкам `disposition: required` + `status: PENDING` без `req_id` — это и раздувало знаменатель.

## 2. Счётчики по классам и слайсам

| Слайс | BIND | NEEDS_AGENT_CHECK | NEEDS_LIVE_OBSERVATION | NEEDS_IMPLEMENTATION | Всего |
|---|---:|---:|---:|---:|---:|
| MIGR | 14 | 4 | 0 | 0 | 18 |
| TESTS | 18 | 2 | 0 | 0 | 20 |
| INSPECTOR | 2 | 2 | 0 | 3 | 7 |
| INIT-LIVE | 4 | 10 | 2 | 4 | 20 |
| UI-U01…U09/P2 | 0 | 0 | 0 | 9 | 9 |
| P0-A | 0 | 1 | 0 | 1 | 2 |
| P0-B | 0 | 1 | 0 | 0 | 1 |
| P0-D | 0 | 1 | 0 | 0 | 1 |
| REPORT | 0 | 4 | 0 | 0 | 4 |
| **Итого** | **38** | **25** | **2** | **17** | **82** |

### Что именно доказывает BIND

- `release-258111/deploy.md` — W2 FINAL_VERIFY_OK 14/14, прод 2.58.111 @ `fbf9013d`: SELECT == новые фабрики, fingerprint `fd4e88754749`, 7 кастомов целы, blob 9/9, ΔDDL=0, rollback `release/fix-2.58.110`.
- `release-258111/review-rel.md` — независимое ревью и повторный прогон guard-наборов на `fbf9013d` (w1_semantics 21p, initreply 14p, l1d 15p, mca19 118p и др.).
- `evidence/w0-inventory.md` — pre-change read-only inventory и trace source-of-truth (прод 2.58.110 @ `a8d2a45a`).
- `evidence/w1/migrations.md`, `test-run.md`, `matrix-p0f.md`, `review-w1.md` — каноны/лестницы/матрица слоёв/байт-сверка.
- `evidence/w3/analysis.md` — реальные provider-вызовы на боевых байтах: ровно эффективная ветка Expression, off 0/5 мата, frequent доходит до отправки, serialization 10/10.
- **Целевой прогон 23.10.2026**: detached worktree `fbf9013d`, `.venv` Python 3.12 / aiogram 3.31.0, команда
  `pytest tests/test_asap_w1_semantics.py tests/test_add_exp_expression.py tests/test_expression_isolation_followup.py tests/test_direct_l1_l1d_contract.py tests/test_asap8_initreply_binding.py tests/test_soul1_composer_layers.py tests/test_soul1_w6_speech_ui.py -q`
  → **126 passed, 1 warning, 12.29 s**. Это подтверждает TESTS/NOFORCE/INIT-I08/I09/INIT-TESTS/REQ-HONEST-OFF/INS-PRIVACY на точном кандидате.

## 3. Гейты (fact)

Все команды — из корня проекта `C:\Code\Python\adminbot`:

```
python C:\Users\main\.config\opencode\tools\requirements_gate.py check --map plans\features\asap-speech-arch\requirements-map.json --stage plan --repo .
stage=plan inventory=120 manual=41 scoped=0 errors=0
EXIT:0

... soul-1\requirements-map.json
stage=plan inventory=101 manual=97 scoped=0 errors=0
EXIT:0

... soul-1\requirements-map-amendment.json
stage=plan inventory=66 manual=29 scoped=0 errors=0
EXIT:0

... asap8-v6-3-live-correction\requirements-map.json
stage=plan inventory=148 manual=79 scoped=0 errors=0
EXIT:0
```

Plan-гейт не проверяет закрытость строк — он проверяет source/hash/disposition/graph/optional-метаданные. Все четыре карты структурно валидны. Красных гейтов нет.

## 4. Прогресс до/после

До правок (`workflow_progress.py --scope-file plans/progress_scope.json`):

```
Поручения владельца подтверждены: 5/12 (41%)
Этапы полностью подтверждены: 66/101 (65%)
Требования подтверждены: 1001/1204 (83%)
Отдельно: ждут проверки после деплоя: 12
Необязательная обратная связь: 15 ожидают, 0 просмотрены
```

После:

```
Поручения владельца подтверждены: 5/12 (41%)
Этапы полностью подтверждены: 69/101 (68%)
Требования подтверждены: 1039/1198 (86%)
Отдельно: ждут проверки после деплоя: 7
Необязательная обратная связь: 21 ожидают, 0 просмотрены
```

Числитель +38 (ровно BIND). Знаменатель −6: `REQ-PROOF-EFFECT`, `SOUL-05.6`, `SOUL-08.12`, `U07-SYM-DESKTOP`, `REQ-U07-3`, `U07.3c` переведены в `owner_optional`; их инженерные половины остаются отдельными обязательными строками. `source_sha256` всех 12 задач сверены с фактическими файлами — совпадают, поэтому не менялись.

## 5. Что можно закрыть после агентских проверок

- **soul-1**: все required-строки, кроме `SOUL-14.2` и `SOUL-AMD.8.11`, уже VERIFIED. `SOUL-14.2` закрывается read-only телеметрией `speech_extent` на проде (появится с первым реальным проходом style policy; сейчас 0 событий — NOT_YET_OBSERVED, не дефект). `SOUL-AMD.8.11` остаётся WAITING_EXTERNAL из-за отсутствующего видео-провайдера. Задачу нельзя закрыть «после проверок» целиком, пока видео-контур не настроен.
- **asap8-v6.3**: после пяти агентских read-only проверок (`REQ-B09-BODY`, `B10-R06`, `B10-R10`, `B10-R11`, `REQ-B11-E2E`) задача может быть закрыта по инженерии; U07-строки больше не блокируют DONE, это добровольное наблюдение владельца.
- **asap-speech-arch**: 44 открытых; после 25 агентских проверок и 17 реализаций (INSPECTOR + W4-UI) останется 1 обязательное живое наблюдение (`INIT-48H`) и 1 необязательное (`REQ-PROOF-EFFECT`, owner_optional). Сейчас задачу закрывать нельзя.
- **asap2-direct-chat** и **W4-UI** не трогались: там идут probe/review и активный Builder.

## 6. Живые и owner-optional — без подмены

- `REQ-PROOF-EFFECT` (asap-speech): реальный чат occasional/frequent — личное наблюдение. Строка остаётся PENDING, `live_required=false`, `owner_optional`, инженерные ссылки `EVAL-MODES`/`EVAL-EGRESS`. `EVAL-MODES` (полная матрица 3×3×10) остаётся обязательной и PENDING.
- `SOUL-05.6`, `SOUL-08.12`: переведены в `owner_optional`; инженерные половины — `SOUL-05.2/05.5` и `SOUL-08.10/08.11` (VERIFIED). Никакого VERIFIED по личному наблюдению.
- `SOUL-14.2` — **не** owner_optional: это агентская read-only проверка телеметрии на проде.
- `SOUL-AMD.8.11` — WAITING_EXTERNAL, не owner_optional: видео-сценарий невозможен без медиа-источника.
- `U07-SYM-DESKTOP`, `REQ-U07-3`, `U07.3b`, `U07.3c` — owner_optional; инженерные `REQ-U07-HARD`, `U07.3a`, `U07-PLATFORMS`, `U07.2e` — VERIFIED.
- `REQ-B09-BODY`, `B10-R06/R10/R11`, `REQ-B11-E2E` — **не** owner_optional: агент может проверить SQL/журналы/controlled E2E; это обязательные инженерные строки.

## 7. Ограничения и риски

1. В карте `asap-speech-arch` `candidate_commit` пока `0f3ed53a` (W1), а `deployed_commit` — `fbf9013d`. Для будущего release-гейта нужно либо перевести candidate на `fbf9013d` и перебиндить старые W1-строки, либо осознанно оставить двухкандидатную схему. Сейчас plan-гейт зелёный, review/release по `fbf9013d` потребует перебиндинга — это не сделано и не замаскировано.
2. INSPECTOR закрыт частично: существующий Effective Prompt Inspector (SOUL-1) уже показывает preview vs sent, слои, skip_reason, conflicts, маскировку; но exact unmasked system, per-call trace/checksum и русские объяснения skip — ещё нет. Три строки помечены NEEDS_IMPLEMENTATION, две — NEEDS_AGENT_CHECK.
3. W3 — мини-выборка (45 вызовов ровно бюджет), инициативный текст не снят, s7-цитата не выполнена; поэтому `EVAL-MODES`, `P0D-QUOTED`, `INIT-I01…I07` не закрыты.
4. 48-часовое окно `INIT-48H` отсчитывается от рестарта 2.58.111 (23.10 13:14 UTC); earliest полезная проверка — 25.10 13:14 UTC. Отсутствие событий — NOT_YET_OBSERVED, не «доказано работает».
5. Прогон 126 тестов сделан на detached worktree `fbf9013d`; это доказательство кандидата, а не production. Production-часть — только deploy/W2 и read-only артефакты.
6. `REV-FACTVIEW-B1` появился во время аудита: `review-b1-recheck.md` — **Approved**, блокер B-1 закрыт на `10f3a2a0` (9 passed, 103 passed по 4 файлам, RED воспроизведён). На 82 строки `asap-speech-arch` это не влияет: factview — отдельный summary-лейн/поезд 2.58.112, строк в этой карте у него нет.

## 8. Полные таблицы

Ниже — каждая из 82 открытых строк `asap-speech-arch`, затем 4 строки `soul-1` и 9 строк `asap8-v6.3`. Для BIND указаны реальные `artifact_path`; для остальных — точная команда/источник и владелец.

### asap-speech-arch — 82 открытые required-строки

| req_id | slice | итог | класс | доказательство / команда / причина |
|---|---|---|---|---|
| EVAL-MODES | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Полная матрица 3 режима × 3 жанра × 10 стимулов не выполнена: W3 — 45 вызовов, мини-выборка, s7/инициативный текст не сняты. Нужен полный harness-прогон (~270 вызовов) с фиксацией hash/model/temperature; бюджет/квота провайдера. |
| INIT-48H | INIT-LIVE | PENDING | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION (DevOps (read-only)): 48-часовая наблюдательная проверка распределения действий на проде. Нужен read-only анализ mca_events/journal после окна; earliest 2026-10-25 13:14 UTC (старт 2.58.111 23.10 13:14 UTC). Отсутствие события = NOT_YET_OBSERVED, не дефект. |
| INIT-I01 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Реальный initiative-сценарий: 3+ участника без вызова бота → action=reply, delivery=chat, target=null (или silent/react); текст не приклеен reply к последнему. Harness W3, 0 Telegram. |
| INIT-I02 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Реальный initiative-сценарий: прямое возражение на [msg:N] → delivery=reply, target=N, не самое свежее ID. Harness W3. |
| INIT-I03 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Реальный initiative-сценарий: мелкое «лол»/флуд → react или silent допустимы; текст не обязан. Harness W3. |
| INIT-I04 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Реальный initiative-сценарий: новая общая тема → chat; reply не выбирается из-за имён. Harness W3. |
| INIT-I05 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Модельный сценарий удалённого reply-target не прогнан (есть только transport-тесты case7b/gone-target). Нужен initiative-прогон с удалённой целью: отмена/bounded reassess, без отправки контекстного текста обычным сообщением. |
| INIT-I06 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Модельный сценарий reply на сообщение вне чата (поддельный/чужой ID) не прогнан; transport-тесты addressee mismatch есть, но fake-ID сценарий нужен в harness. |
| INIT-I07 | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): Реальный initiative-сценарий: старое сообщение бота → L1 учитывает свои сообщения и может промолчать; повтора из-за отсутствия self-сообщений нет. |
| INIT-I08 | INIT-LIVE | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Хрупкий parser fail-closed; транспорт не назначает reply. |
| INIT-I09 | INIT-LIVE | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Реакция валидна либо честное молчание, без подмены текстом. |
| INIT-TESTS | INIT-LIVE | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Property/regression-набор покрывает все четыре действия и негативный hardcode-контроль. |
| P0D-QUOTED | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): s7 (цитата с матом) не выполнен в W3 из-за бюджета; нужен один harness-стимул с quoted source/user input/RAG/примером в трёх режимах: мат в цитате не должен классифицироваться как собственная речь, forced insertion отсутствует. |
| REQ-PROOF-EFFECT | INIT-LIVE | PENDING | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION (Owner (optional) / Builder for EVAL-MODES): Реальный чат occasional/frequent — личное наблюдение владельца. Инженерная часть (payload/поведение на боевых байтах) закрывается EVAL-MODES/EVAL-EGRESS; строка переводится в owner_optional, не VERIFIED. |
| T-DELIVERY-ERR | INIT-LIVE | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Ошибки доставки/цели не переназначают адресата (fail-closed). |
| T-GLASS-PERF | INIT-LIVE | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Полигональный фон/Liquid Glass/FPS/контраст — активный W4-UI; Playwright+perf после. |
| T-I-COVERAGE | INIT-LIVE | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): I-01…I-07 требуют реальных initiative-прогонов; W3 дал только silent/react, текстовых ответов не было. Команда: harness как W3, стимулы I-01…I-07, фиксировать action/delivery/target/текст; 0 Telegram. |
| T-UI-MATRIX | INIT-LIVE | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Скриншоты/e2e desktop 1280/1440, Windows fullscreen, mobile 320/360/390/430, WebView 390, landscape — активный лейн W4-UI; evidence ещё нет. |
| T-UI-STATE | INIT-LIVE | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Клики/назад/dirty/save/conflict + сохранение после reload/нового процесса — активный W4-UI. |
| T-UI-TEXT | INIT-LIVE | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Длинные русские фразы/code tokens/URL без обрезания во всех редакторах — активный W4-UI. |
| INS-CONFLICT | INSPECTOR | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Reviewer/Builder): Список conflicts есть, но покрытие классов (типографика/длина/мат-регистр/роль/chat-global/устаревшие SOUL-*) не доказано. Команда: pytest tests/test_soul1_composer_layers.py::test_no_duplicate_owner_character_conflict tests/test_soul1_composer_layers.py::test_layer_order_ownership_and_provenance -q + Reviewer-матрица классов. |
| INS-EXACT | INSPECTOR | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder): Режим «полный итоговый промпт» байт-в-байт отсутствует: inspector отдаёт system_masked, а не owner-debug exact assembled system. Реализация — INSPECTOR (owner-only, sanitized). |
| INS-HIERARCHY | INSPECTOR | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder/Reviewer): Иерархия слоёв и source/revision уже видны, но клик по элементу (текст/источник/редакция) и отсутствие пустого скролла не проверены. Команда: Playwright-проход Inspector + pytest tests/test_soul1_composer_layers.py -q; при отсутствии click-through — доработка INSPECTOR. |
| INS-PRIVACY | INSPECTOR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Debug-инспекция не содержит секретов/токенов/приватного контекста. |
| INS-SKIPREASON | INSPECTOR | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder): UI показывает машинные коды skip_reason как основной текст; по-русски переведён только style_policy_absent. Нужны человеческие объяснения few_shot/channel_output + коды во всплывающей диагностике. Слайс INSPECTOR. |
| INS-TRACE | INSPECTOR | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder): Существующий Inspector отдаёт manifest_id/run_id/layers/versions/conflicts/skipped, но не полный per-call trace (correlation_id, model/provider, checksum после scrub/retry). Реализация — слайс INSPECTOR после W4-UI. |
| REQ-HONEST-OFF | INSPECTOR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Отключённые пресеты дают честный skip reason, L2 не подменяет expression. |
| ADD2-PRESERVE | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`; Кастомы и per-chat редакции сохранены; нулевое влияние на другие чаты подтверждено снимком. |
| MAN-FACTORY-ACTIVE | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`; Формулировки одновременно заводские и активные — подтверждено SELECT. |
| MIGR-ACTIVE | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`; Реальная active PG мигрирована идемпотентно; кастомы не тронуты. |
| MIGR-BACKUP | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w0-inventory.md`, `plans/features/asap-speech-arch/release-258111/deploy.md`; Снапшот old-значений + history/rollback на каждую запись. |
| MIGR-CACHE | MIGR | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps/Builder): Hot-apply после записи не прогонялся: W2-записи были до планового рестарта. Команда: pytest tests/test_soul1_core_version_propagation.py tests/test_prompt_migrations.py -q + DevOps read-only проверка NOTIFY/revision и inspector==payload на тестовом ключе. |
| MIGR-FACTORY | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w1/migrations.md`, `plans/features/asap-speech-arch/release-258111/deploy.md`; Фабрика/реестр/ступени/история old→new обновлены; fingerprint fd4e88754749. |
| MIGR-INV | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w0-inventory.md`; Inventory до изменений выполнен read-only на проде. |
| MIGR-NORETURN | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Возврат старого Core/L2 после restart/deploy/reset не наблюдался; new chats наследуют фабрику. |
| MIGR-ROLLBACK | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`; Откат кода и канонов документирован и не теряет owner-редакцию. |
| MIGR-SCOPE-CHECK | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/deploy.md`; A/B scope isolation подтверждена тестом и прод-снимком. |
| MIGR-TABLE | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`; Итоговая таблица миграции есть. |
| MIGR-TRACE | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w0-inventory.md`; Trace UI/cache/composer/provider зафиксирован. |
| MIGR-VERIFY | MIGR | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps): SELECT/независимый процесс/runtime payload/blob — подтверждены deploy; inspector==payload байт-в-байт не показан. Команда: DevOps read-only GET /api/speech/inspector на проде, сверить sent.manifest_id/слои/хеш с SELECT активного значения. |
| REQ-REALDB | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/release-258111/deploy.md`; Изменения в коде + Factory + реальной PG + деплой + read-only проверка. |
| REQ-SCOPE | MIGR | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder/Reviewer): Проверен не каждый override-параметр отдельно. Команда: pytest tests/test_add_exp_expression.py::test_chat_scope_inherit_label_isolation_and_reset tests/test_soul1_core_registry_api.py -q; затем Reviewer-матрица chat-explicit>global-explicit>factory по каждому параметру (expression/style/prompts/chat-блоки). |
| REQ-STALE-CORE | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w0-inventory.md`; Корневая причина расхождения задокументирована в W0 §3; повторно не требуется. |
| REQ-W0-MAP | MIGR | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w0-inventory.md`; W0 read-only артефакты на месте. |
| TRACE-GRAPH | MIGR | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Architect/Builder): Нет отдельного документа полного вызовного графа до provider API и Telegram sendMessage. Нужен Architect/Builder trace по services/direct_chat_service.py, prompt_composer.py, llm_client, transport с ссылками на строки HEAD. |
| ARCH-ADR | P0-A | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Architect): ADR «Почему L2 промпт Direct остаётся» отсутствует: plans/features/asap-speech-arch/adr-l2-kept.md (указан в write_scope P0-A) не создан. Нужен Architect: boundaries, DB keys, provider payload route, reverse constraints. |
| REQ-PREFIX-SEP | P0-A | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Architect/Reviewer): Стабильные префиксы отделены, но exact effective order/bytes и невозможность dynamic content создавать директивы равного приоритета не доказаны. Нужно: Architect/Reviewer сверяет direct-runtime-assembly-w1.txt + prompt_composer порядок слоёв; Inspector exact bytes. |
| REQ-EMBED | P0-B | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder/Reviewer): W3 подтвердил Core/Expression только для Direct L2; полная матрица всех пользовательских выходов (initiative writer, factcheck-финал, summary narrator, search/web/youtube, diagnostics/fallbacks) и негатив для internal JSON не собрана. Команда: pytest tests/test_soul1_composer_layers.py tests/test_soul14_layers_payload.py tests/test_expression_isolation_followup.py -q + Reviewer-матрица writers. |
| ADD-EXPR-INTENSITY | P0-D | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder): W3 проверил только profanity-режимы; влияние wit/sharpness на речь наблюдаемо не подтверждено. Нужен harness-прогон с разными wit/sharpness при фиксированном profanity: различие регистра/резкости, Core-личность присутствует. |
| DOD-FINAL | REPORT | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Orchestrator): DoD-финал проверяется только на closing-report после W4-UI/INSPECTOR/48h; сейчас не закрыт. |
| GOV-PENDINGLIVE | REPORT | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Orchestrator): Epic остаётся открытым: live-строки помечены PENDING/READY_FOR_LIVE, не VERIFIED; проверить при закрытии. |
| REP-FORMAT | REPORT | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Orchestrator): Финальный отчёт ещё не выпущен; проверить формат (время/зона, IMPLEMENTED/TESTED/DEPLOYED/LIVE_VERIFIED/PENDING, коммиты/хеши, без секретов) на closing-report. |
| REP-NOFAKE | REPORT | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Orchestrator): Проверить closing-report: недоступное = PENDING_LIVE/WAITING_EXTERNAL, не VERIFIED; эта реконсиляция — частичное доказательство, не закрытие. |
| ADD1-DISTRIB | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w1/matrix-p0f.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Распределение по слоям подтверждено матрицей и ревью. |
| ADD1-NO-SOFTEN | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/review-w1.md`; Смягчения характера и скрытых ограничителей не найдено. |
| ADD2-CANON-BASIS | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/review-w1.md`; Готовые тексты §3 — основа реализации, байт-сверка живая. |
| ADD2-REVIEWER | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w1/review-w1.md`; Reviewer-обязательство по выразительности выполнено с явным вердиктом. |
| ANTIPATTERN-MATRIX | TESTS | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Reviewer): Нет отдельного артефакта с построчным вердиктом по всем 11 строкам §4. Нужно: Reviewer заполняет матрицу «антипример → проверка/негативный тест → вердикт» (reply всем, forced-мат, только фабрика без active, слияние инструкций, глобальная санитизация, ссылки «куда-нибудь», opacity на весь UI, вторая Save, подгонка теста, заголовок без acceptance). |
| CANON-EXACT | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Fenced-блоки §3.1–3.7 попали в источники фабрик байт-в-байт. |
| REQ-LAYER-CONTRACTS | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w1/matrix-p0f.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Контракты слоёв §2 зафиксированы тестами и ревью. |
| REQ-NOFORCE | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Негативные тесты против forced-мата/счётчиков/регулярок/auto-reply есть и зелёные. |
| REQ-ONE-OWNER | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w1/matrix-p0f.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Один авторитетный владелец на правило зафиксирован матрицей и ревью. |
| T-CORE-CLEAN | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Core Full/Compact чист от мат-инструкций и SOUL-*, семантика сохранена. |
| T-EXPR-BRANCH | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w3/analysis.md`; Ровно эффективная ветка Expression доходит до модели (тест + реальные вызовы). |
| T-FACTORY-ACTIVE | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/deploy.md`; Factory и active DB проверены раздельно; restart не возвращает старьё. |
| T-INTERNAL-CLEAN | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Внутренние JSON-стадии чисты, финальные тексты — со слоями. |
| T-META-CLEAN | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/review-rel.md`; Мета-утечки отсутствуют в model-facing payload. |
| T-PARITY | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/w1/test-run.md`; ON/OFF parity и отсутствие скрытого fallback подтверждены (кандидат 0f3ed53a). |
| T-PRESERVE | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/release-258111/deploy.md`; Кастомы/per-chat не потеряны, влияние на другие чаты нулевое. |
| T-PREVIEW | TESTS | PENDING | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder/Reviewer): Preview vs sent разделены и проверены (test_soul1_w6_speech_ui), но exact last request после адаптеров/fallback байт-в-байт не доказан: inspector отдаёт system_masked. Команда: pytest tests/test_soul1_w6_speech_ui.py::test_inspector_never_claims_preview_as_sent tests/test_soul1_w6_speech_ui.py::test_inspector_finds_runtime_shaped_turn_snapshot -q + проверка fallback-пути. |
| T-STYLE-CONFLICT | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/matrix-p0f.md`; Конфликт типографики устранён на уровне владельца правила (Style Policy). |
| T-TOOL-KEEP | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Tool/context-контракт сохранён, конкурирующий ролевой блок снят. |
| T-VERB-KEEP | TESTS | VERIFIED | BIND | `plans/features/asap-speech-arch/evidence/reconciliation-2026-10-23.md`, `plans/features/asap-speech-arch/evidence/w1/test-run.md`; Вербализатор сохранён как рабочий редактируемый слой. |
| UI-P2 | UI-P2 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Liquid Glass без нового CSS-overlay, текст/иконки читаемы; активный W4-UI. |
| UI-U01 | UI-U01 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Карточки «Библиотека промптов»/«Модели и подключения» — цельная поверхность; активный W4-UI. |
| UI-U02 | UI-U02 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Разрыв/polygon overlay между шапкой и контентом «Речь и характер»; активный W4-UI. |
| UI-U03 | UI-U03 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Каталог промптов в единой адаптивной grid без дробящих прямоугольников; активный W4-UI. |
| UI-U04 | UI-U04 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Кодовые области на мобильном: pre-wrap/overflow-wrap, без обрезания; активный W4-UI. |
| UI-U05 | UI-U05 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Переключатель Full/Compact адаптивен на узких экранах; активный W4-UI. |
| UI-U06 | UI-U06 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Иерархия шапки desktop/mobile: заголовок/breadcrumb/один sticky; активный W4-UI. |
| UI-U07 | UI-U07 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Единый state pristine/dirty/saving/saved/error/conflict без ложного «сохранено»; активный W4-UI. |
| UI-U09 | UI-U09 | PENDING | NEEDS_IMPLEMENTATION | NEEDS_IMPLEMENTATION (Builder W4-UI): Маршрут Статус→ИИ→Речь→Core→Expression→Библиотека→Direct→Назад, GLOBAL/CHAT; активный W4-UI. |

### soul-1 — 4 строки READY_FOR_LIVE (плюс 2 уже owner_optional)

| req_id | slice | итог | класс | доказательство / команда / причина |
|---|---|---|---|---|
| SOUL-05.6 | W3 | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION -> owner_optional: инженерная цепочка до payload закрыта (SOUL-05.2/05.5, review-w3 F3); остаток — добровольное наблюдение одного слова в реальном чате. Не VERIFIED. |
| SOUL-08.12 | W4 | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION -> owner_optional: 7 сценариев покрыты deterministic-тестами и одним прод-сигналом; живая атрибуция к реальным людям — необязательная обратная связь. Не VERIFIED. |
| SOUL-14.2 | W8 | READY_FOR_LIVE | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps, read-only): телеметрия speech_extent/mca_events проверяется на проде SQL/журналом после реального прохода style policy; событий пока 0 — NOT_YET_OBSERVED, не дефект. Не переводить в owner_optional: проверка агентская. |
| SOUL-AMD.8.11 | W10 | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION (WAITING_EXTERNAL): поиск и фактчек подтверждены реальными сценариями трижды; видео — not_configured/media_source_unconfigured/cobalt_absent, сценарий невоспроизводим без медиа-источника. Не owner_optional и не VERIFIED; ждёт настройки провайдера. |

### asap8-v6.3 — 9 строк READY_FOR_LIVE

| req_id | slice | итог | класс | доказательство / команда / причина |
|---|---|---|---|---|
| U07-SYM-DESKTOP | FE-FULLSCREEN | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION -> owner_optional: Windows Desktop — реальный клиент владельца; инженерные контракты закрыты, живой сценарий не блокирует DONE. Не VERIFIED. |
| REQ-U07-3 | FE-FULLSCREEN | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION -> owner_optional: остаток только реальный Windows-клиент. Не VERIFIED. |
| U07.3b | FE-FULLSCREEN | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION -> owner_optional (уже была): ручной клиентский журнал — добровольное наблюдение; инженерные ссылки приведены к не-optional REQ-U07/U07.3a. Не VERIFIED. |
| U07.3c | FE-FULLSCREEN | READY_FOR_LIVE | NEEDS_LIVE_OBSERVATION | NEEDS_LIVE_OBSERVATION -> owner_optional: реальные клиенты недоступны агентам; инженерные проверки платформ закрыты. Не VERIFIED. |
| REQ-B09-BODY | BE-MIGRATION | READY_FOR_LIVE | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps/Builder, read-only): old/new chat_id проверить SQL по memory/FTS/GraphRAG/episodes/summary/override/historical retrieval с resolve_canonical_chat_id; end-to-end на прод-данных, без записи. Link≠proof; silent truncate искать отдельно. |
| B10-R06 | REL-GATE | READY_FOR_LIVE | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps, read-only): live index/backlog, rate limit, key failover quota-groups — журнал/метрики прода + targeted tests; не owner-наблюдение. |
| B10-R10 | REL-GATE | READY_FOR_LIVE | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps, read-only): supergroup-перенос и old/new retrieval памяти — SQL/журнал на проде, сверить с REQ-B09-BODY. |
| B10-R11 | REL-GATE | READY_FOR_LIVE | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (DevOps, read-only): реальные execution modes, запрет без ключа, бюджет/evidence Direct L1 — журнал mca_events/llm_usage + targeted tests. |
| REQ-B11-E2E | BE-INT-REPORT | READY_FOR_LIVE | NEEDS_AGENT_CHECK | NEEDS_AGENT_CHECK (Builder/DevOps): по одному контролируемому реальному E2E на невидимый модуль; различить недостаток входов/выключенный producer/cursor stalled/worker crashed/неверный конфиг. Без dummy-счётчиков; 0 сообщений в реальные чаты. |

## 9. Что осталось сделать (сводно)

| Владелец | Действие | Строки |
|---|---|---|
| Builder | Полная матрица EVAL-MODES 3×3×10 + s7-цитата + wit/sharpness + initiative I-01…I07 | EVAL-MODES, P0D-QUOTED, ADD-EXPR-INTENSITY, INIT-I01…I07, T-I-COVERAGE |
| Builder | INSPECTOR: exact unmasked system, per-call trace/checksum, русские skip-reasons, click-through/conflict-классы | INS-TRACE, INS-EXACT, INS-SKIPREASON, INS-HIERARCHY, INS-CONFLICT |
| Builder W4-UI | UI U-01…U-09/P2 и UI-evidence | UI-*, T-UI-MATRIX/TEXT/STATE/GLASS |
| Architect | ADR `adr-l2-kept.md`, call graph до provider/Telegram, prefix/order proof | ARCH-ADR, TRACE-GRAPH, REQ-PREFIX-SEP |
| Reviewer | Матрица §4 anti-pattern, exact preview/last request, cross-writer embed matrix | ANTIPATTERN-MATRIX, T-PREVIEW, REQ-EMBED |
| DevOps | Read-only prod: cache/hot-apply, inspector==payload, old/new chat_id, B10/B11, 48h telemetry | MIGR-CACHE, MIGR-VERIFY, REQ-B09-BODY, B10-R06/R10/R11, REQ-B11-E2E, INIT-48H, SOUL-14.2 |
| Orchestrator | Финальный отчёт/DoD/PENDING_LIVE | REP-FORMAT, REP-NOFAKE, GOV-PENDINGLIVE, DOD-FINAL |
| External | Видео-провайдер для SOUL-AMD.8.11 | SOUL-AMD.8.11 |

**Главный вывод:** 38 строк получили честный BIND; 44 остались открытыми с конкретным владельцем и командой. Никакие UI-строки, asap2-строки и «живые» наблюдения не закрыты выдуманным VERIFIED.
