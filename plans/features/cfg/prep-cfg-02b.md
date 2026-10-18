# PREP-CFG-02B — разбор очереди после CFG-02A и минимальный план CFG-02B

**Лейн:** PM-PREP-CFG-02B (read-only; единственный артефакт — этот документ; карты, код, `current_task.md` и прод не менялись; SSH не использовался).
**Дата:** 19.10.2026, 01:20 (UTC+12) · HEAD master `01b0839e` · прод **2.58.89 @ `d59fab94`** · релиз-кандидат P0 **2.58.90 @ `f2cd3a71`** (собран, ещё НЕ задеплоен; REV-REL-25890 = Needs Fixes → FIX-DEPLOY-90).
**Источники:** `plans/features/cfg/{requirements-map.json, slice-graph.json, plan.md}`; `plans/current_task.md` §CFG (строки 1232–1629, только чтение); `plans/workflow_state.md`; `plans/features/p0-save-init-ux/*` (карты, source §1–5); `plans/features/soul-1/requirements-map-amendment.json`; код `services/*`, `config/settings.py`, `web/app.js`, `tests/*` (только чтение).

---

## 1. Фактическое состояние на сегодня

- **Карта CFG:** `openworkflow-coverage-v1`, `strict_evidence=true`, `slice-graph.json` (12 слайсов, строго последовательная цепочка). Кандидат-линия `83ecd202`, deployed `d59fab94`. Классифицировано 244 обязательных строки: **18 VERIFIED, 4 READY_FOR_LIVE, 222 PENDING**.
- **CFG-01 = закрыт полностью** (13/13 VERIFIED; прод-эвиденс окон agent-checks-1/2).
- **CFG-02A = 5 VERIFIED + 4 READY_FOR_LIVE.** Уже **задеплоен в прод 2.58.89** (порт `119b1f7d` на релиз-линии; поэтому 4 RFL — это агентские post-deploy проверки на живом проде, не «ожидание сборки»).
  RFL-строки: `CFG-02A.3`, `CFG-02A.4`, `CFG-02A.5`, `CFG-02.AC1` (правка квоты на проде без рестарта + переживание reload/рестарта + отказ со временем сброса).
- **P0 (2.58.90):** лейн сохранения/инициативы/ностальгии/UX завершает фикс деплой-скрипта; деплой и приёмка §4 — впереди. По ADD-0.1 очередь CFG стартует **автоматически после завершения P0**; CFG-02B — пауза до конца P0 (workflow_state: «автовозврат CFG-02B»).
- **SOUL §5-уточнения (capability/image generation):** все 18 строк `SOUL-AMD.5.1–5.18` = **VERIFIED** — отдельной работы по §5 нет; CFG-02 обязана лишь сохранить единый pipeline (single `generate_image`/tool wiring), не пересобирая его.
- Мастер-линия после 2.58.90 = прод-89 + P0 + CFG-02A (порт) + bump; это база для CFG-02B.

---

## 2. Состав очереди после CFG-02A (до CFG-FINAL)

Порядок строго последовательный (ADD-0.1; serial joins оформлены `depends_on` в `slice-graph.json`); параллельных писателей нет.

| # | Волна | Строк | Суть (обязательства) | Модули/файлы-кандидаты | Зависимости | Acceptance (вкл. live) | Риски |
|---|-------|-------|----------------------|------------------------|-------------|------------------------|-------|
| 1 | **CFG-02B** | 17 (02B.1–8 + AC2–AC7) | Новый **частотный лимит генераций**: factory **OFF**, «сколько подряд» + «время ожидания», режим «Для каждого пользователя»/«Общий на весь чат» (один выбор, рекомендуемый заводской — per-user); все пользовательские пути через один limiter; обложки Summary исключены полностью; отказ до платного вызова с фактическим остатком; устойчивое состояние между воркерами; честная судьба при OFF/ON/смене конфига; витрина в «Лимиты генерации» | `services/image_generation.py` (`_reserve_or_consume` L1612, `generate_and_send` L1731, `image_reserve_mode` L246), `services/worker_budget.py` (прецедент `reserve_image` L601), `services/persistent_throttling.py` (token bucket `throttle_state`, L158) или новый модуль, `services/param_catalog.py` + `config/settings.py` (новые ключи), `services/chat_params.py`/`worker_settings` (effective), `web/app.js` (секция «Лимиты генерации»), `tests/*` (см. §3.6) | после деплоя+приёмки P0 2.58.90; закрытие 4 RFL CFG-02A; база — мастер после P0 | preprod UI/поведение (02B.1/.2/.2.3/.6/.8, AC2/AC3); отказ «через N» до платного вызова; вклад в ADD-2.2 (postdeploy, CFG-FINAL) | R1 кат. дельта+re-pin; R2 выбор стора; R3 daily+freq; R4 carry-over TZ-источник; R5 изоляция обложек (полная — 02C) |
| 2 | **CFG-02C** | 13 (02C.1–7, 02C.D/.B, ADD-1.T2, CFG-02.F, AC8–AC9) | **Жёсткая изоляция** `user_image` ↔ `summary_cover`: разделение бюджетов/счётчиков; тип потребления `user_image`/`summary_cover` (+base/styled_edit/retry-recovery/fallback); сохранение правил Summary; честный shared-provider ceiling; витрина «Обложки сводок здесь не учитываются»; атомарность; двусторонние отрицательные тесты | `services/budget_limits.py`, `services/worker_settings.py`, `services/cover_style_pipeline.py`, `services/cover_style_jobs.py`, `services/image_generation.py`, `tests/test_cover_style_wave_b_asap4.py` | после CFG-02B (продолжает её контуры) | preprod: user limit `0`+частота ON → Summary Base/Style Edit работают; исчерпан Summary-лимит → user-картинка работает; ретрай обложки не меняет user burst; мем не меняет `summary_cover.used` | регрессия обложек (B04-контур!), смешение журналов, миграция исторического учёта |
| 3 | **CFG-03** | 19 + §5-обновление | **Аудит ВСЕХ параметров MiniApp**: manifest на каждый параметр (UI→Registry→scope→API→DB→кэш→resolver→runtime consumer→поведение→тест); классификация (в т.ч. `UI_missing`); hot-параметры без рестарта; отрицательный тест на каждый редактируемый; честность OFF/ON; coverage manifest + Reviewer-аудит | `services/param_catalog.py`, `services/chat_params.py`, `services/chat_settings_seed.py`, `web/app.js`, `tests/test_chat_params.py` | после CFG-02C; **P0 уже покрыл часть** (см. §5) | hot-параметры ui+preprod; manifest с реальными consumer или честным `unverified`; 100% не объявляется при непроверенных | объём; «зависшие» ключи вне каталога; соблазн зачесть HTTP 200 |
| 4 | **CFG-04** | 20 + §5-обновление | **Мобильные формы/save**: один основной CTA сохранения (без двух конкурирующих), нижняя панель при dirty с safe-area/клавиатурой, не перекрывать последнее поле/каретку, dirty из значений, подтверждение API/persistence, различимость «Сохранить»/«Factory»/«Сбросить override», поворот без потери ввода, автотесты 320/360/390/430 + ландшафт, before/after, живая Android/Desktop | `web/app.js`, `web/index.html`, `web/static/app.css`, `tests/js/**` | после CFG-03; **P0 уже покрыл часть** (см. §5); композицию U01/HOTFIX/логотип/fullscreen НЕ трогать; glass/полигон не менять | live preprod + postdeploy (AC/D4/D5); блок-критерий 04.B | пересечение с P0 UX (двойной писатель — не допускать); регрессии шапки/стекла |
| 5 | **CFG-05-Verify** | 8 | `OBSERVED_FIXED / REUSE_EXISTING`: однократная сверка deployed SHA + U08/SOUL-17 evidence + наблюдение владельца; **без** нового кода/рендеров/CSS/A-B; заморозить полигональный фон; при новой регрессии — точечно в существующей задаче | только `plans/features/cfg/evidence/cfg-05/**` | после CFG-04 (регрессия «стекло не сломано») | postdeploy: сверить на живом проде, принять производственный скриншот владельца; рефракция/фон сохранены | соблазн «исследовать стекло заново» — запрещён |
| 6 | **CFG-06** | 93 (самый крупный) | **Единый фактчек-pipeline A–J**: suitability после широкого контекста (не отказ по короткой реплике), план и осмысленные запросы, реальные web/chat evidence, grounded verdict с provenance, temporal как стадия (не второй pipeline), Telegram-safe renderer (bold/списки/inline-ссылки), наблюдаемость/кеш/бюджеты, один контракт на всех fallback; отрицательные тесты | `handlers/factcheck.py`, `services/factcheck_service.py`, `services/factcheck_prompts.py`, `services/temporal_factcheck.py`, `services/search_aggregator.py`, `services/system2_handoff.py`, `services/prompt_style_blocks.py`, `tests/*` | после CFG-05-Verify | provider/live preprod (web/chat tool traces) + live postdeploy (F.6, G.8, J.6): реальные отправки Telegram, без JSON/unknown | провайдеры поиска (Tavily/Exa/DDG), стоимость; соблазн третьего pipeline; массовые ложные отказы |
| 7 | **CFG-07A** | 11 | **Анти-backstage аудит** речевого маршрута: effective payload (Core→style→юмор/мат→каналы→verb→postprocess), запрет внутренних метаречей, отличие слома персонажа от честных ограничений, все LLM/fallback-пути, машинные поля не доходят до Writer; матрица SOUL не пересобирается | `services/prompt_composer.py`, `services/prompt_style_blocks.py`, `services/mca_authorial_speech.py`, `web/api/speech.py`, `tests/test_soul1_w4_humor_craft.py` | после CFG-06; переиспользует P0-фикс сохранения/витрины речи (см. §5) | prod-флаги postdeploy (A.1) + preprod сценарии 07D.1/.2 | не доказанная причинность «юмор→ответ»; соблазн regex-блэклиста |
| 8 | **CFG-07B** | 12 | Переключатель **«Использовать мат»** (factory **ON**) как одно правило (`profanity_use`) в существующей Speech Style Policy: GLOBAL/CHAT/наследование, ON — сильное требование грубого регистра, OFF — без нового мата с защитой цитат; hot; Inspector `applied/exempted/failed` | `services/style_policy.py`, `services/mca_style_scope.py`, `services/param_catalog.py` (при необходимости), `web/api/speech.py`, `web/app.js`, `tests/test_soul1_w6_speech_ui.py` | после CFG-07A | ui/live preprod (07B.1/.6/.8, 07D.3); ON/OFF, override, hot-reload, fallback независимо | оверинженеринг «уровней»; порча цитат; не второй Core |
| 9 | **CFG-07C** | 12 | **public_speech_guard** на точке outbound (после Composer, до финальной сериализации): JSON/role/tag/reason_code-утечки, метаречь, непредусмотренный HTML, незаземлённые ссылки; детерминированный sanitize + bounded retry; честный fail-soft; факты/цитаты не искажаются; все публичные каналы | `services/prompt_composer.py`, `services/mca_authorial_speech.py`, `services/style_policy.py`, `web/api/speech.py` | после CFG-07B | postdeploy (07C.6, 07D.6): сквозные маршруты на проде | не второй Writer; риск «удалить текст и оставить дыру» |
| 10 | **CFG-FINAL** | 17 | ADD-2 №1–8: сквозная приёмка дельты CFG-01…07, process-контроль ADD-0, регрессии `current_task`, итоговый status report с полной `requirements-map`; незакрытые owner-only видимы, но не бесконечны | `plans/features/cfg/**`, `plans/workflow_state.md` | после CFG-07C | postdeploy (ADD-2.1–2.7), включая CFG-02 (ADD-2.2) | фиктивный DONE; потеря строк |

**Что из очереди уже закрыто смежными работами (не переигрывать):**
- **CFG-01** — закрыт; CFG-02B использует его же паттерны (persistent token bucket, `format_remaining_time`, анти-обход).
- **CFG-02A** — задеплоен; 4 RFL закрываются агентской live-проверкой (см. §7).
- **SOUL §5** — закрыт (18/18 V).
- **P0 §5** (source `source-p0-hotfix-2026-10-18.md` L53): P0 уже исправил часть требований CFG-03/04 и компонентов CFG-07 — детали в §5.

---

## 3. CFG-02B — точный разбор и минимальный план

### 3.1 Обязательства (точные формулировки источника; source-cfg-addendum L79–L91, L109–L115)

| req_id | Формулировка (сжато, дословные опоры) | live |
|---|---|---|
| CFG-02B.1 | Отдельный переключатель **«Лимит частоты генерации»**; **Factory Default: ВЫКЛЮЧЕНО**; при OFF новое ограничение «не должно вообще запрещать или замедлять генерации»; суточная квота действует независимо; настройки количества/паузы хранятся, но применяются только при ON | preprod |
| CFG-02B.2 | При включении — компактные настройки (количество подряд, время ожидания, режим счёта) | preprod |
| CFG-02B.2.1 | «Сколько генераций подряд» — положительное целое, документированная политика списания | — |
| CFG-02B.2.2 | «Время ожидания» — секунды/минуты, понятный формат | — |
| CFG-02B.2.3 | «Считать лимит» — **один из двух взаимоисключающих** вариантов (рекомендуемый заводской: «Для каждого пользователя», при OFF не действует); не две галочки | preprod |
| CFG-02B.3 | Per-user: индивидуальный счётчик `(chat_id, user_id)`, исчерпание A не блокирует B; per-chat: один счётчик на `chat_id`; CHAT-режим локален, глобальный — дефолт; проверить DM и ключ скоупа; не смешивать с дневным | — |
| CFG-02B.4 | Точная семантика «подряд» и паузы: списание **перед платной попыткой**, порядок восстановления, отсчёт, параллельные запросы, смена конфигурации/режима посреди паузы; никаких скрытых сбросов для обхода; состояние устойчиво между воркерами | — |
| CFG-02B.5 | Все **пользовательские** пути (ключевик, L1/Tool Router, повторный вызов) через общий limiter + бюджет + идемпотентность; **второй image pipeline не создавать**; **любые этапы обложек Summary полностью исключены**, включая режим «Общий на весь чат» | — |
| CFG-02B.6 | Отказ **до платного запроса** с фактическим остатком («через 8 минут 20 секунд»), в стиле Personality Core, без поминутного спама; свежий остаток на каждую попытку; текст редактируем через Factory Defaults/Speech Style Policy, без хардкодных несовместимых фраз | preprod |
| CFG-02B.7 | Provider error/отмена/replay/ошибка доставки: политика списания согласована с реальной стоимостью и зафиксирована тестами; нет повторной платной генерации при replay; при обоих исчерпанных лимитах — истинное **самое раннее** время с учётом обоих | — |
| CFG-02B.8 | Секция «Лимиты генерации»: *активно ли ограничение*, scope, остаток пользователя/чата, источник наследования, следующая доступность; компактно и одинаково на мобильном/десктопе; фон и дизайн не менять | preprod |
| CFG-02.AC2 | «При заводском `frequency_enabled=false` создать несколько пользовательских изображений (в пределах дневной квоты): частотный ограничитель не вмешивается» | preprod |
| CFG-02.AC3 | «Включить короткий лимит 2 генерации и паузу: третья попытка блокируется до платного вызова; ответ содержит корректный остаток; после паузы можно снова» | preprod |
| CFG-02.AC4 | Режим per-user: A достиг лимита, B продолжает в том же чате | — |
| CFG-02.AC5 | Режим per-chat: A и B исчерпывают один запас, следующий заблокирован | — |
| CFG-02.AC6 | Выключить → немедленное снятие короткого запрета; включить → документированная судьба счётчиков без обхода в конкурентном режиме | — |
| CFG-02.AC7 | Смена без рестарта; global→chat→inheritance; параллель; несколько воркеров; перезапуск; retry; idempotency; provider/delivery failure; суточный сброс и разные TZ | — |

Внешние приёмки: ADD-2.2 (postdeploy, CFG-FINAL) — дневная квота видна, частотный **OFF по умолчанию**, per-user/per-chat проверены, обложки не расходуют пользовательские лимиты, shared-ceiling показывает истинную причину.

### 3.2 Кодовая опора (проверенные якоря; строка кода — кандидат на изменение)

| Что | Где | Роль для 02B |
|---|---|---|
| Точка входа генерации | `services/image_generation.py:1612 _reserve_or_consume` → `:1731 generate_and_send` | **Единая точка врезки частотной проверки** (до платного вызова), рядом с резервом дневной квоты; `already`/replay-ветки уже есть |
| Дневной резерв | `services/worker_budget.py:601 reserve_image`, `:731 commit_image`, `:750 release_image`, `:44 LIMIT_IMAGE_DAILY`, `:35 METRIC_IMAGE_CALLS` | Прецедент атомарного журнала/idempotency; **не дублировать дневную квоту** |
| Честность режима/факты UI | `services/worker_budget.py:803 image_limits`, `:825 image_usage_summary`; `services/image_generation.py:246 image_reserve_mode`, `:269 image_quota_reset_note` | Расширяемые факты секции «Лимиты генерации» (02B.8); образец «честного тахометра» |
| Persistent burst/cooldown | `services/persistent_throttling.py:158 PersistentThrottle.allow/refresh` (`throttle_state`, один атомарный UPSERT; проживает рестарт/воркеры; scopes перечислены в docstring L3–5) | **Кандидат №1 переиспользования** для лимитера (scope `image_*`, `user_id` = участник для per-user / 0 для per-chat). Проверить, нет ли пин-теста на список scope |
| Нормализация границ | `services/persistent_throttling.py:319 normalize_direct_chat_limits` | Прецедент клампа burst/cooldown (CFG-01) |
| Формат остатка | `services/smartmodule_throttling.py` (`format_remaining_time`, используется CFG-01), пул фраз `services/smartmodule_phrases.py:11/123`, `services/smartmodule_utils.py:324 throttle_phrase` | Отказ «через 8 мин 20 сек» в стиле персонажа (02B.6); решение «какой источник текста» — зафиксировать в дизайне (прецедент CFG-01 принят ревью) |
| Пользовательские пути | прямой пре-гейт `services/direct_chat_service.py:6594 _image_pre_gate_block`; семантика `services/direct_capabilities.py` (SOUL-AMD.5); tool `services/tool_router.py:2960` → `generate_and_send` | Все три пути должны проходить один limiter (02B.5); ключевик и «бот, надо сделать мем» — один контур |
| Каталог/настройки | `services/param_catalog.py:56 _PER_CHAT_CATEGORIES`, `:337 GroupSpec limits_images`, `:2000 IMAGE_DAILY_LIMIT` → pg_key `limits.image_daily_limit`; `config/settings.py:3061 IMAGE_DAILY_LIMIT`, `:1823 IMAGE_DAILY_LIMIT_ENABLED`, `:2131–2133 CHAT_BURST_LIMIT/CHAT_COOLDOWN_SECONDS` | Образец регистрации новых ключей (factory-значения через Settings-дефолт) |
| Витрина MiniApp | `web/app.js:1309–1348` (CONFIG_GROUP_DISPLAY `limits_images`, подписи `limits.image_daily_limit`), `:1369–1388` (`IMAGE_QUOTA_KEY`, `imageQuotaValueValid`), `data-image-quota-*`, сохранение через общий config-путь (~`:2128`, `:5707`, `:12892`) | Сюда встраивается секция лимита частоты (02B.1/.2/.8) |
| Заморозка каталога | `tests/test_round1025_f8_registry.py` (sha256 `param_catalog.py`, counts 575/120/118/23, `catalog_baseline.json`), `tools/gen_param_registry_round1025.py --check`, `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md` | См. §3.4 — обязательные re-pin'ы при кат. дельте |
| Обложки (для 02B.5) | `services/cover_style_jobs.py`, `services/cover_style_pipeline.py` (собственный контур, вызывает `generate_image_verbose` напрямую) | Полная двусторонняя изоляция — **CFG-02C**; 02B обязана лишь не подключать частотную проверку к контуру обложек и доказать это тестом |
| E2E-прецедент UI | `tools/ui_cfg02a_image_quota_e2e.py` (`data-image-quota-*`, 6 скриншотов, `RESULT: PASS`) | Образец для `tools/ui_cfg02b_*_e2e.py` |

### 3.3 Ключевые проектные решения (зафиксировать в дизайне до кода)

1. **Состояние лимитера:** рекомендация — переиспользовать `throttle_state` через `PersistentThrottle` (атомарный UPSERT, переживает рестарт и делится между воркерами — ровно 02B.4), добавив dedicated scope (напр. `image_freq`); per-user → `user_id=member`, per-chat → `user_id=0`. Альтернатива — отдельная таблица/модуль: дороже, дублирует проверенные семантики. Решение уровня Builder+Reviewer, не Human Gate.
2. **Порядок проверок в `_reserve_or_consume`:** частотный отказ **до** платного вызова и **без** списания дневной квоты; replay того же сообщения не должен списывать burst второй раз (идемпотентность уже даёт `idem_key`; для 02B зафиксировать явно в тестах «replay не списывает частоту»).
3. **«Подряд» и восстановление:** по аналогии с CFG-01/R50-7 — полное восстановление зарядов через паузу от **последнего допущенного** обращения; смена конфига/режима на активной паузе — документированная политика (не случайный сброс, не дать «бонус» через переключение scope).
4. **Судьба счётчиков OFF→ON (AC6):** документировать (вариант «сохранять состояние, но не применять» согласован с 02B.1 «настройки можно сохранить»); тест на конкурентный режим.
5. **Единое «самое раннее время» (02B.7):** если исчерпаны и суточная, и частотная — сообщать реальный min(времена) с корректным ТЗ-источником; иначе наследуется carry-over дефект из review CFG-02A (§65: shared-env `limit_global` сводится к reason `budget`, и текст может назвать неверную TZ-причину).
6. **Текст отказа:** свежий остаток на каждую попытку; не хардкодить фразу, несовместимую с каноном (прецедент — пул `smartmodule_phrases`/Style Policy); если текст должен быть редактируемым после SOUL-1 — использовать существующий механизм, не изобретать новый.

### 3.4 Каталожная дельта (обязательный, ранее не встречавшийся в CFG шаг)

CFG-02A прошла с «Δ каталога = 0» (витринный слой). **CFG-02B так не может:** нужны 1 переключатель + 3 настройки (burst, cooldown, mode). Рекомендуемый состав новых ключей (имена — на решение Builder, группа `limits_images`, per-chat, factory-defaults в `Settings`):
`IMAGE_FREQ_LIMIT_ENABLED` (bool, factory **False**), `IMAGE_FREQ_LIMIT_BURST` (int, положительное), `IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS` (int/float), `IMAGE_FREQ_LIMIT_MODE` (select: `per_user`|`per_chat`, заводской `per_user`).

Следствия (проверено по коду; при 4 Settings-backed ключах — планировать заранее):
- `REGISTRY` 575 → **579**, Settings-полей 454 → **458**, categorized 550 → **554** (GROUPS/TAB_RULES не меняются);
- re-pin `test_round1025_f8_registry.py` (`PARAM_CATALOG_SHA256_*` по прецеденту L-F11S-1 + `test_counts_frozen`), перевыпуск `tests/fixtures/round1025/catalog_baseline.json`;
- обновление счётчиков в пин-тестах: `test_budget_settings_round1019.py`, `test_budget_guardrails_round1024.py`, `test_budget_global_toggle_round1024.py`, `test_budget_data_repair_round1024.py`, `test_decision_making_round1026.py`, `test_cfg02a_image_quota_ui.py`, `test_frontend_tab_mapping.py`, `test_image_context_memory_round1026.py`, `test_ia_inventory_round1025.py` (baseline), и ревью-скан остального;
- регенерация `plans/docs/param-registry-round1025.tsv` + `meta.md` (`python tools/gen_param_registry_round1025.py` / `--check`), обновление `plans/docs/screen-map-round1025.md` (новым ключам нужно место — они лягут в существующую секцию «Лимиты генерации»);
- JS-витрина: `web/app.js` — подписи новых ключей и элементы секции.

Это рутинная, но заметная дельта: делать **отдельным коммитом** «catalog delta + re-pins» с чек-листом, чтобы Reviewer не смешивал её с логикой лимитера.

### 3.5 Минимальный план исполнения (фазы)

**Ф0 — Возврат очереди (после приёмки P0).**
- Подтвердить прод `healthz=2.58.90`, `NRestarts=0`; синхронизировать мастер.
- Закрыть/запланировать 4 RFL CFG-02A (агентская live-проверка; конфиг-правки с возвратом; безопасное окно).
- Проверить достаточность `write_scope` слайса в `slice-graph.json`: рекомендуется **добавить** `services/worker_budget.py` и `services/persistent_throttling.py` (или новый модуль лимитера), новый тестовый файл и `tools/ui_cfg02b_*` (правка графа — действие PM при старте слайса).

**Ф1 — Дизайн-фикс (§3.3) + план кат. дельты (§3.4).** Выход — короткий раздел «Design» в `plans/features/cfg/evidence/cfg-02b/README.md` (без отдельного большого документа).

**Ф2 — RED.** Новый файл `tests/test_cfg02b_image_freq_limits.py` (`TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-02B`), кейсы:
factory OFF → no-op (AC2); burst=2+пауза → 3-я блокировка до платного вызова + фактический остаток + после паузы можно (AC3/02B.6); per-user A/B (AC4); per-chat A+B (AC5); OFF→ON→OFF судьба счётчиков (AC6); hot-reload global→chat→inherit, мультиворкер, рестарт, повторы/идемпотентность, provider/delivery (AC7/02B.7); daily+freq — самое раннее время; direct/tool — один контур; обложки не проходят частотную проверку (spy; жёсткая изоляция — 02C); модель/валидация новых ключей; UI-контракт (секция/подписи/скрытие настроек при OFF).
Прогнать RED на базовом коммите (фиксация падения).

**Ф3 — IMPL.** Лимитер (переиспользование паттерна §3.3.1) → врезка в `_reserve_or_consume` → новые ключи/resolver → текст отказа → UI-секция → кат. дельта и re-pin'ы одним коммитом.

**Ф4 — GREEN + бласт-радиус.**
```
py -3 -m pytest tests/test_cfg02b_image_freq_limits.py -q
py -3 -m pytest tests/test_cfg02a_image_quota_ui.py tests/test_image_daily_limit_round1026.py ^
  tests/test_persistent_throttling.py tests/test_budget_settings_round1019.py ^
  tests/test_direct_chat.py tests/test_direct_chat_concurrency.py tests/test_tool_router.py -q
py -3 -m pytest tests/test_round1025_f8_registry.py tests/test_frontend_tab_mapping.py ^
  tests/test_param_catalog.py tests/test_ia_inventory_round1025.py -q
py -3 tools/gen_param_registry_round1025.py --check
.venv\Scripts\python.exe tools\ui_cfg02b_image_freq_e2e.py        # новый, по образцу ui_cfg02a
node tests/js/<соответствующие JS-тесты image/модулей>            # JS-sweep
```

**Ф5 — Evidence + Review.** `plans/features/cfg/evidence/cfg-02b/{README.md, red-green.txt, e2e-log.json, ui/*.png}`; `review-cfg-02b.md`; гейт:
`py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --stage review --slice CFG-02B --candidate <sha>`.

**Ф6 — Release.** Порт на релиз-линию (dual-line, прецедент `119b1f7d` CFG-02A) → bump/пины → T0-деплой (fail2ban-дисциплина) → live-проверки §3.7 → гейт `--stage release --candidate <sha> --deployed-commit <sha>` → закрытие строк; далее CFG-02C.

### 3.6 Что уже есть из тестов (не переписывать, переиспользовать)

| Файл | Что покрывает | Как использовать |
|---|---|---|
| `tests/test_image_daily_limit_round1026.py` | Дневной резерв: гонка, deny/release, идемпотентность, доставка, TZ, kill-switch, fail-open | Мини-стаб PG-пула для 02B-тестов (как 02A) |
| `tests/test_cfg02a_image_quota_ui.py` (27) | Витрина/эффективность/отказ/пути/tap режима | Образец контрактных UI-тестов и стабов; расширять кейсами 02B |
| `tests/test_persistent_throttling.py` | Token bucket: атомарность, изоляция ключей, рестарт, кламп при смене лимита, fail-open | База для scope-решений и тестов частотного лимитера |
| `tests/test_direct_chat.py` + `test_direct_chat_concurrency.py` | CFG-01: hot-reload, анти-обход, параллель | Образец сценариев «изменение без рестарта/мультиворкер» |
| `tests/test_budget_settings_round1019.py` | Каталог limits-групп, сентинелы | Точка обновления счётчиков при кат. дельте |
| `tests/test_round1025_f8_registry.py` + fixtures/round1025 | Заморозка каталога | Re-pin процедура (§3.4) |
| `tools/ui_cfg02a_image_quota_e2e.py` | Playwright e2e секции «Лимиты генерации» | Образец для 02B e2e |

### 3.7 Живые проверки CFG-02B (preprod + postdeploy)

Preprod (UI/поведение, закрывает 02B.1/.2/.2.3/.6/.8, AC2/AC3):
1. Секция «Лимиты генерации»: переключатель виден, по умолчанию **выключен**; видно active/scope/остаток/источник/следующую доступность (моб. 390 + десктоп).
2. Factory OFF: несколько генераций в пределах дневной квоты проходят — частотный не вмешивается.
3. ON c лимитом 2 и паузой: третья попытка — отказ **до платного вызова** с фактическим остатком; после паузы снова можно; в логах отказа нет обращений к провайдеру.
4. Per-user: A исчерпал — B в том же чате продолжает. Per-chat: A+B общий запас.
5. OFF → короткий запрет снимается немедленно; повторное ON — документированная судьба счётчиков.
6. Смена без рестарта; global→chat→inherit; параллельные запросы; рестарт сервиса.
7. Прямой («бот, нарисуй») и tool-путь («бот, надо сделать мем») — одинаковые лимиты.
8. Обложки Summary не получают отказ от пользовательского частотного лимита (полная изоляция — подтверждается в CFG-02C).
Postdeploy: то же на проде в рамках ADD-2.2 (CFG-FINAL), с записью traces/логов; платные генерации — строго ограниченно (2–3 картинки в пределах квоты).

### 3.8 Перенесённые находки (не терять)

- `review-cfg-02a.md` §65: отказ по shared-env (`limit_global`) сводится к reason `budget` и получает текст «Суточная квота обновится… (TZ чата)», что может назвать неверный источник/час — **кандидат на уточнение в CFG-02B/02C** (истинный источник отказа и время в тексте).
- `review-cfg-02a.md` §6 R2: обложка Base расходует тот же user-контур (`summary_generator → generate_image_verbose(chat_id=…)`) — hard-split учёта — **CFG-02C** (не дублировать в 02B; в 02B — только «частотный limiter не подключён к покрытиям»).

---

## 4. Зависимости и риски (сводно)

**Зависимости:**
1. **От P0-деплоя:** очередь CFG не стартует до завершения текущей очереди (ADD-0.1); CFG-02B — «автовозврат» после приёмки 2.58.90 и леджеров P0. Прямой код-зависимости у CFG-02B от P0 нет (разные модули), но база кандидата — мастер после P0, и публикация релиза CFG-02B идёт следом за релизом P0 (общая релиз-дисциплина, изоляция, T0-скрипт).
2. **От CFG-очереди:** строго последовательная цепочка (02B → 02C → 03 → 04 → 05 → 06 → 07A → 07B → 07C → FINAL); никаких параллельных писателей; `CAN_PARALLEL_WITH: нет`.
3. **От CFG-02A:** уже задеплоена; 4 RFL закрываются live-проверкой (агентской) — логически часть завершения 02A, выполняется в окне возобновления CFG.
4. **Пропускная способность прода:** все live-проверки — в штатных окнах, малый объём платных генераций (в пределах квоты), fail2ban-дисциплина.

**Риски:** R1 кат. дельта (средний, управляемый; см. §3.4, митигация — отдельный коммит+чек-лист); R2 выбор стора лимитера (митигация — reuse `throttle_state`, проверить пин scope-набора); R3 честный отказ при обоих лимитах (тест обязателен); R4 carry-over TZ-источник (см. §3.8); R5 обложки (регрессия B04-контура — не трогать, изоляция в 02C); R6 стоимость/шум live-проверок; R7 «не второй image pipeline» (любая новая обвязка — только в существующей точке `_reserve_or_consume`).

---

## 5. §5-обновление CFG-03/04/07 после P0 (что закрыто P0, что осталось)

Опоры: `source-p0-hotfix-2026-10-18.md` §5 L53 («Не дублировать CFG-03/CFG-04/CFG-07 и выполненные пункты SOUL-1; обновить их статус…»); обе карты P0 (`requirements-map.json`, `requirements-map-followup.json`) с `alias_of`-ссылками.

| CFG-строка (остаётся владельцем) | P0-строка (алиас) | P0-статус на сегодня | Что это даёт CFG | Что остаётся за CFG |
|---|---|---|---|---|
| CFG-03.2 (классификация параметров) | P0A-PERSIST-CAUSE | VERIFIED | Первопричины сохранения классифицированы для «Речь и характер» | Полная матрица по **всем** параметрам |
| CFG-03.3 (read/write/reload, 409, rollback, scope) | P0A-ACCEPT-PERSIST | PENDING | Уже задан объём: полный E2E по каждому типу настроек | Распространить на все параметры, не только речь |
| CFG-03.11 (отрицательные тесты) | P0A-ACCEPT-PERSIST-EDGE | PENDING | Concurrency/документ/БД/наследование/rollback по речевым настройкам | Остальные параметры |
| CFG-03.F (успех = read-after-write+runtime) | P0A-PERSIST-TRUTH | RFL | Центральный контракт уже реализован | Свод/manifest |
| CFG-03.R3 (формат «причина/пути/правка/тест/evidence») | P0A-PERSIST-AUDIT + P0A-PERSIST-CENTRAL | VERIFIED | Формат аудита и централизованный фикс (с `chat_params pool is None`) | Распространение формата на все сбои |
| CFG-04B.2/.4 (нижняя панель; dirty/ошибки) | P0A-UX-SAVE | PENDING (UX-IMPL Approved `57ff8c85`) | Логика сохранения/черновиков/честных ошибок | 04B.1 (два CTA), 04B.3 (последнее поле/клавиатура), 04B.5 |
| CFG-04C.1/.4 (одна колонка; клавиатура/модалки) | P0A-UX-COMPACT | PENDING (Approved) | Компактная компоновка секции речи | Для форм всех модулей; ландшафт-панели |
| CFG-04C.3 (длинные техключи) | P0A-UX-TECHJUNK | PENDING (Approved) | Убран техмусор в секции речи | Остальные экраны |
| CFG-04D.2/.4 (viewport-матрица; живые Android/Desktop) | P0A-ACCEPT-UX | PENDING | Уровни viewport и живые проверки уже заявлены | Остальные формы/сценарии CFG-04D.1/.3/.5 |
| CFG-07 (вся дельта) | — алиасов нет | — | P0 исправил **сохранение/витрину** компонентов «Стиль/Выражение» (Expression с матом), на которые опрётся CFG-07B/07C; алиасов требований нет | CFG-07A/B/C целиком (backstage, `profanity_use`, egress-guard) |
| ADD-0.2 / ADD-0.3 / ADD-0.5 / ADD-2.Q | P0A-OPS-NODUP / P0B-WF-NODUP / P0B-WF-* | PENDING | Подтверждает непереигрывание и очередь | Закрытие в CFG-FINAL |
| SOUL §5 (capability/image) | — | **все SOUL-AMD.5.1–5.18 = VERIFIED** | Единый image-pipeline и truthful capability уже приняты | Не пересобирать; только не сломать (CFG-02B/02C) |

**Действие PM после леджеров P0:** обновить статусы/evidence указанных строк CFG-03/04 по факту P0-леджеров (алиас — не дубль реализации); строки, полностью покрытые, закрывать с P0-эвиденсом; частично покрытые — сохранять владельцем CFG и доисполнять остаток. Карту CFG в этом лейне не менять (запрещено условием лейна).

---

## 6. Guardrails (жёсткие «не делать»)

- Не создавать второй image pipeline; лимитер врезается только в существующую точку (`_reserve_or_consume`/`generate_and_send`).
- Не менять обложки Summary по существу (это CFG-02C); в 02B — только «частотный limiter не подключён к покрытиям» + тест.
- Не переигрывать CFG-02A/CFG-01/SOUL §5; не переименовывать каталоговые ключи (это CFG-03).
- Не менять полигональный фон, стекло, палитру, композицию; не трогать навигацию/fullscreen/логотип (владельцы U01/U02/U07/HOTFIX).
- Не открывать Human Gates: все решения 02B — технические; вопрос владельцу — только при реальной неразрешимой продуктовой альтернативе (прецедент — нет).
- Не публиковать проценты по CFG до леджеров P0/обновления карт (прогресс считается только по актуальным картам).

---

## 7. Что делать дальше (точное действие Orchestrator)

1. Дождаться `FIX-DEPLOY-90` → push master → **деплой 2.58.90** → приёмка §4 → леджеры P0A/P0B (уже запущенные лейны закрываются штатно).
2. **PM-обновление §5:** синхронизировать статусы CFG-03/04 (+CFG-07-компоненты) с P0-картами (см. §5); отметить, что CFG-02A RFL → V после live-записи.
3. **Возврат очереди → CFG-02B** по §3.5: Ф0 (закрытие 4 RFL CFG-02A, проверка/правка `write_scope` слайса в slice-graph, синк базы) → Ф1 → Ф2…Ф6. Отдельные лейны создавать по фазам (Builder/Reviewer/DevOps), без параллельных писателей.
4. Далее строго по цепочке: CFG-02C → CFG-03 → CFG-04 → CFG-05-Verify → CFG-06 → CFG-07A → CFG-07B → CFG-07C → CFG-FINAL (см. таблицу §2).

*Документ подготовительный; единственный источник истины остаётся `plans/features/cfg/requirements-map.json` + гейт `requirements_gate.py`. Карты, код и `current_task.md` в этом лейне не изменялись.*
