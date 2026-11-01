# W2 / P1 - независимое ревью: общесистемный L1 decision-profile

- Кандидат: ветка `feat/fc-voice-p1-l1-profile`, HEAD `1aa818c5af34`, база `2317d26f`; worktree `WorkspaceData/worktrees/c742e4de9e92c489/evol-71536a366a11-3e50c850`.
- Контракт: `arch/l1-decision-profile-contract.md`; источник владельца: `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md` §5, пп.17-22; отчёт Builder: `reports/w2-p1-l1-profile.md`.
- Окружение проверки: Python 3.12 (venv проекта), aiogram 3.31.0, SQLite/без PG. Деплоя, Telegram и прода нет: только код, стенды и собранные payload.
- Дата: 2026-11-02.

## 1. Что инспектировано (реальные пути)

| Файл | Что смотрел |
|---|---|
| `services/bot_persona.py:326-500` | `DECISION_PROFILE_SECTION`, `_profile_dimensions`, `_profile_rule_value`, `_profile_legacy_habits`, `build_decision_profile_block`, `decision_profile_source`, `resolve_character_context` (пин кадра), `CharacterReadContext.frame_version` |
| `services/direct_l1.py:852-870,1431-1520,1521-1659` | `L1_PROFILE_SECTION`, `build_l1_context(decision_profile=...)`, `_cap_context` (protected, шаги 0-4) |
| `services/direct_chat_service.py:3697-3720,3820-3845,5306-5475,5610-5625,11832-12010` | `_plan_direct_l1`, `_initiative_character`, `plan_initiative_decision`, провенанс в `record_l1_diagnostics` |
| `services/mca_self_model.py:280-300,326-360,1012-1057,1551-1600` | `CompiledRule`, `BehaviorFrame`, `INITIAL_DIMENSIONS`, `set_run_frame/current_run_frame` (ContextVar без сброса) |
| `services/chat_prompts.py:1370-1400` | EVR3 = байты EVR2 + одно правило статуса секции |
| `services/prompt_registry.py:178-190,356-370,2746-2768` | метка `l1-planner-decision-profile`, печать `ef61a9dd6798`, `FACTORY_SET b1c1ab5b3b68` |
| `services/prompt_migrations.py:1-12,256-268,499-560,858-918` | статус лестницы `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` |
| `services/prompt_release_policy.py:1-36,932-1030,1112-1266` + `bot.py:1378-1384` | ФАКТИЧЕСКИЙ механизм активации (метка+печать) |
| `services/memory_maintenance.py:480-545` | цикл `for candidate in due` по чатам в одной долгоживущей задаче |
| `tools/er65_prompt_segment_snapshot.py`, `evidence/er65/sent-segments.json` | состав сегментов, границы доказательства |
| `tests/test_asap_fc_voice_l1_decision_profile.py` (12 тестов), диффы 13 обновлённых тест-файлов | assertions, а не только имена |

## 2. Мутации (воспроизведены самостоятельно)

| Мутация | Способ | Наблюдение |
|---|---|---|
| A. Планер не получает профиль (`build_decision_profile_block` возвращает пусто) | pytest-плагин, без правки файлов | **9 failed, 3 passed**, красные ровно контрактные тесты payload |
| B. `L1_PROFILE_SECTION` убран из `protected` | временная копия `direct_l1.py` в WorkspaceData + подмена модуля | **1 failed**: `test_profile_survives_budget_compression_at_live_budget`, budget=400, `резкость: 0.50` вырезана из секции |

Обе заявленные Builder мутации реально красные; тест бюджета падает именно из-за сжатия, а не из-за отсутствия секции.

## 3. Мои зонды (наблюдаемые результаты)

| # | Что проверял | Результат |
|---|---|---|
| P1 | `decision_profile_source` на legacy-блоке (кадр недоступен) | **вернул `frame`**: ложный провенанс (см. F2) |
| P2 | Тот же task: кадр чата 111, затем вызов без резолва (чат 222) | профиль чата 111: version `aaaa...`, `инициативность: 0.90 (в этом чате)` (см. F1) |
| P3 | Реальные `_plan_direct_l1` и `plan_initiative_decision` на одном кадре | секции **байт-идентичны**; `meta.l1_profile_source=frame`, `l1_profile_chars=290`; прозы Writer (тег Persona) нет ни в payload, ни в system |
| P4 | `build_l1_context` при 1600/400/150, длинные окно и вопрос, 8 измерений | секция цела на всех (458 симв., 170 токенов); payload: 1143 / 377 / 377 токенов; при 150 пакет **превышает** бюджет (protected не режется, поведение как у `СООБЩЕНИЕ`) |
| P5 | `compose_machine_system` для 8 фоновых блоков | везде `profile=machine_json`, rendered только `channel_contract`, тегов Persona/Expression_Settings/Speech_Base/Few_Shot и секции профиля нет |
| P6 | Снимок ER-65: где встречается секция профиля | 11 вхождений: ревизия канона + 4 L1-стадии (system/user) и их `blocks`; фоновых стадий нет |
| P7 | Реальный `plan_initiative_decision` для чата 222 после кадра чата 111 (persona OFF, ctx не резолвится) | payload чата 222 содержит version и значения кадра чата 111 с пометкой «(в этом чате)» (см. F1) |
| P8 | Независимые пины: sha12 канона и слепка, печать, `FACTORY_SET` | `15453 -> 09f3d533d173`, `16341 -> ef61a9dd6798`, `seal_integrity()` пуст, `b1c1ab5b3b68`; всё совпадает |
| P9 | `tools/er65_prompt_segment_snapshot.py --check` | `OK ... stages=27, segments=58, two isolated processes identical` |

Прогоны: новый набор - **12 passed**; 14 целевых файлов (канон, миграции, реестр, L1, парность, soul1) - **342 passed**. Полный `pytest tests` не перезапускал: Builder привёл побайтовое сравнение 88 падающих узлов с базой `2317d26f`; это правдоподобно и не относится к срезу, принимаю как **переиспользованное доказательство**, а не как своё наблюдение.

## 4. Блокирующие findings

### F1 (BLOCKER, Builder). Кадр не привязан к ходу и чату: профиль чужого чата

- Нарушение: §21 (свежесть без устаревшего кеша), §19 (единственный источник, без второй личности), п.2c задания ревью (провенанс frame|legacy).
- Место: `bot_persona.build_decision_profile_block` читает `mca_self_model.current_run_frame()`, то есть ContextVar, который `set_run_frame` пишет и **никто не сбрасывает**; `direct_chat_service._initiative_character:11839-11871` при `flags.persona_enabled=False` (или при исключении) возвращает пустую пару ДО `resolve_character_context`, то есть кадр не обновляется; `memory_maintenance.py:533-540` обрабатывает несколько чатов в ОДНОЙ долгоживущей задаче (цикл `for candidate in due`).
- Воспроизведение: P2 и P7 (реальный `plan_initiative_decision`). Чат 222 получает `инициативность: 0.90`, `сарказм: 0.80`, version кадра чата 111 и пометку «(в этом чате)». Тот же эффект при транзиентном сбое PG в `resolve_character_context` (внутренний except: кадр не ставится).
- Влияние: планер решает об участии по чужому характеру, а след `l1_profile_source=frame` при этом врёт. Дефект внесён этой правкой: до неё инициатива читала только прозу.
- Минимальная правка (без редизайна): использовать амбиентный кадр только если он принадлежит текущему резолву, например сверять `current_run_frame_version()` с `ctx.frame_version` (оба call site уже передают ctx) и при несовпадении или None идти в честный legacy/absent; либо очищать пин кадра в начале каждого L1-хода и каждой итерации цикла.
- Перепроверка: новый тест «тот же task, кадр чата A, затем ход чата B без резолва: в payload B нет значений и версии A», плюс существующий набор.

### F2 (BLOCKER, Builder). `decision_profile_source` возвращает frame для legacy-блока

- Нарушение: п.2c (провенанс frame|legacy наблюдаем и правдив).
- Место: `bot_persona.py`: проверка `if _PROFILE_SOURCE_FRAME in text`, а `_PROFILE_SOURCE_LEGACY` = «источник: кадр поведения недоступен» содержит ту же подстроку.
- Воспроизведение: P1, блок «недоступен» даёт `frame`.
- Влияние: Inspector и трасса сообщают frame, когда кадра нет; ровно тот случай, когда диагностика должна показывать деградацию. Тест `test_direct_service_l1_payload_gets_profile_from_turn_frame` проверяет только frame-ветку, поэтому зелёный.
- Минимальная правка: проверять legacy-строку первой (или startswith).
- Перепроверка: assert `decision_profile_source(legacy_block) == "legacy"`.

### F3 (BLOCKER-документ, Builder). В отчёте неверно описан механизм активации и откат канона

- Нарушение: п.2d задания ревью (честно указать механизм) и требования к доказательствам; ошибка того же класса, что уже ловили в P0.
- Место: `reports/w2-p1-l1-profile.md` §2.5: «миграция срабатывает ТОЛЬКО на точное совпадение байт: кастомы владельца не перезаписываются (проверено тестом...)»; «откат (активные в PREV_..._EVR2) первым шагом».
- Факт: с EVOL-016/012 активацию решает `prompt_release_policy.apply_release` (метка заводской ревизии + печать содержимого), вызываемый из `bot.py` через `migrate_prompt_canons`; `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` стартом НЕ вызываются и активацию не решают, `rollback_prompt_canons` при прямом вызове отказывает (ERROR). Новая заводская метка по решению владельца активируется **поверх** ручной правки (прежний текст остаётся ревизией), а откат выполняется через `activate_revision`, а не ступенью словаря. Тест `test_migration_and_rollback_only_match_exact_deployed_bytes` проверяет только членство в словаре, то есть вообще не про активацию.
- Влияние: принятое доказательство описывает несуществующий механизм отката; это опасно ровно в момент отката релиза.
- Минимальная правка отчёта: заменить §2.5 на «активация: метка+печать (post-EVOL-016); лестница: хранилище слепков, мёртвый код; откат: activate_revision; новая метка активируется поверх ручной правки (EVOL-012)». Код менять не нужно: метка, печать и FACTORY_SET подняты верно (P8).

## 5. Вердикт по пунктам владельца 17-22

| Пункт | Статус | Основание |
|---|---|---|
| 17. Direct: профиль есть, речевого мусора в машинном JSON нет | **PROVEN (pre-deploy)**: в user-payload реальные значения, тегов Persona/Expression_Settings/Speech_Base/Few_Shot нет, system = канон, схема плана не расширена. Остаточная часть («JSON-выход без стилевого текста») зависит от модели, проверяется live | P3, P4, тесты |
| 18. Initiative: стиль не заставляет отвечать при SILENT, высокий сарказм не переключает tone | **НЕ ПРОВЕРЕНО (только live)**: доставка данных и неизменность критериев молчания и канона подтверждены, вывод модели нет | payload содержит «Умерший повод» и silent; решает модель |
| 19. Один источник, те же байты у Direct и Initiative | **PROVEN** (байт-идентичность на реальных путях), но при деградации кадра источник неверный (F1) | P3 |
| 20. Фон (Summary/Sleep/Memory) без Core/Expression/профиля и без веб-проверок | **PROVEN** | P5, P6, тест фона |
| 21. Изменение GLOBAL/chat отражается на следующем запросе, без устаревшего кеша | **FAILED**: при несостоявшемся резолве в том же task используется кадр предыдущего хода или чата | P2, P7 |
| 22. Фактические assembled prompts и source/skip provenance | **PARTIAL**: `--check` зелёный, состав сегментов и L1-стадии подтверждены, но в снимке профиль = «кадр поведения недоступен» (PG-значений нет), live `record_provider_call` нет, а провенанс в трассе ложен в legacy-ветке (F2) | P6, P9, P1 |

Итого: доказано 3 пункта (17 в части payload, 19, 20), провален 1 (21), не доказаны 2 (18 только live, 22 частично).

## 6. Качество тестов: что зелёное, а что им не ловится

- 12 новых тестов помечены CONTRACT; assertions содержательные (реальные байты, отказы, отсутствие инструкций 2-го лица, порядок измерений, `seal_integrity`, точные sha12). Вакуумных проверок не нашёл.
- **Не ловится**: (а) ложный провенанс legacy (F2): нет ни одного assert на `decision_profile_source == "legacy"`; (б) переиспользование чужого кадра (F1): тест «смена кадра» передаёт `frame=` явно и не проходит амбиентный путь `current_run_frame()`, а инициативный тест подменяет `_initiative_character` заглушкой; (в) проброс `character_ctx=_decision_ctx` из `_plan_direct_l1`: тест вызывает с `character_ctx=None`, поэтому снятие проброса на call site останется зелёным (в кадровой ветке ctx декоративен).
- `test_soul1_composer_parity_off` больше не пинит записанную секцию, а подставляет её текущим выводом builder (`_profile_patch`): ослабление эталона. Содержимое профиля пинится другими тестами, поэтому NONBLOCKING, но зафиксировано.
- Обновления пинов в 13 файлах - законный сдвиг байт канона; ослаблений (кроме `_profile_patch`) не увидел.

## 7. Гейт карты требований

`requirements_gate.py check --map ... --stage review --slice FC-L1-PROFILE --candidate 1aa818c5...` даёт FAIL: `candidate_commit` в карте пуст; FCV-L1-01/02/03/04/06/08 и FCV-ACC-17/18/19/21 в PENDING; FCV-L1-05 и FCV-L1-07 помечены VERIFIED с **пустым evidence** (при `strict_evidence: true` недопустимо). Это PM-синхронизация, а не новый цикл разработки: строки 17 и 20 закрываются этим ревью, 18/21/22 требуют live или исправления, ложные VERIFIED надо снять.

## 8. Вне области и наблюдения (не блокеры среза)

1. При бюджете 150 токенов пакет превышает бюджет (377 токенов): protected не режется. Для прод-бюджета (по умолчанию 1600, env-минимум 200) не проявляется; поведение унаследовано от `СООБЩЕНИЕ`.
2. ER-65: `direct.l2_writer.fallback_model_capacity` (709 против 745) - прежний дрейф, L2 этой правкой не тронут, владелец ER-08-RC. В снимке профиль L1 = «кадр поведения недоступен», то есть артефакт не доказывает реальные PG-значения.
3. В корне остались игнорируемые dev-скрипты (`probe.py` и др.) с устаревшим `persona_frame=`; на продукт и тесты не влияют.

## 9. Вердикт

**Needs Fixes.**

- Builder: F1 (привязка кадра к ходу и чату), F2 (провенанс), F3 (текст отчёта), плюс два узких теста из §6 (а, б).
- PM: после исправления связать строки FCV-L1-01..08 и ACC-17..22 с evidence, снять ложные VERIFIED (FCV-L1-05, FCV-L1-07), оставить 18/21/22 PENDING до live.
- Повторное ревью: только F1/F2, затронутые места и новый тест изоляции кадра; доказательства P3/P4/P5/P8/P9 и 342 targeted переиспользуются.

### Что обязательно перепроверить после деплоя (live)

1. Реальный L1-user-payload конкретной модели: секция профиля с фактическими PG-значениями и `l1_profile_source=frame` в Inspector; бюджет модели фактический, не 1600.
2. Initiative: высокие инициативность и склонность спорить не отменяют SILENT на умершем поводе; высокий сарказм не переключает tone на нейтральном вопросе.
3. L1 не стал болтливее или токсичнее (частота reply/silent и грубость до и после).
4. Смена GLOBAL/chat-измерения применяется со следующего запроса без рестарта.
5. `record_provider_call`/`provider_calls`: канон `ef61a9dd6798` активен в PG после рестарта; откат через `activate_revision`, не лестницей.

---

# Re-review 2 (узкая проверка F1/F2/F3)

- Новый кандидат: HEAD `0eec0996` (коммиты `715c1605` F1/F2/F3 + тесты и `0eec0996` снимок ER-65), был `1aa818c5`; база `2317d26f` не менялась.
- Область: только F1, F2, F3 и регрессии рядом с ними. Продуктовый код не правился (в worktree только этот отчёт, untracked).

## Что проверено в коде

| Место | Факт |
|---|---|
| `services/bot_persona.py:435-470` | `_pinned_frame_for_turn(ctx, chat_id)`: четыре условия (непустой `ctx.frame_version`, наличие пина, `RunFrame.chat_id == chat_id`, равенство версий), иначе None |
| `services/bot_persona.py:472-483` | `reset_turn_frame()` вызывает `clear_run_frame()`, fail-open |
| `services/bot_persona.py:532-552` | `decision_profile_source` сравнивает ЦЕЛУЮ строку `источник:`: legacy-строка проверяется первой, неизвестный или пустой блок дают legacy |
| `services/mca_self_model.py:1051-1068` | `current_run_frame_pin()` отдаёт пин целиком (frame + chat_id); `clear_run_frame()` снимает ContextVar |
| `services/direct_chat_service.py:3707-3727,5450-5460` | Direct: `reset_turn_frame()` до резолва, затем `build_decision_profile_block(character_ctx, chat_id=chat_id)` |
| `services/direct_chat_service.py:11896-11918,11990-12005` | Initiative: `reset_turn_frame()` в начале хода, резолв в fail-open, `build_decision_profile_block(_initiative_ctx, chat_id=chat_id)` |
| `services/chat_prompts.py`, `prompt_registry.py`, `prompt_release_policy.py`, `bot.py:1383-1384` | канон/метка/печать не менялись этой правкой; активация по-прежнему метка+печать |
| `reports/w2-p1-l1-profile.md` §0 и §2.5 | F3: текст переписан на реальный механизм (см. ниже) |

Единственные два места, где профиль собирается в проде, оба передают ctx и chat_id; других вызовов `build_decision_profile_block` в `services/` и `tools/` нет.

## Мои пробы (наблюдаемые результаты)

| # | Сценарий | Результат |
|---|---|---|
| R1 | Провенанс: frame-блок, legacy-блок, пустая строка, блок без строки источника | frame / legacy / legacy / legacy |
| R2 | Пин чата 111; вызов без ctx для чата 222; вызов с версией чата 111, но chat_id 222; свой чат; после `reset_turn_frame` | legacy (значений 0.90 нет) / legacy / frame / legacy |
| R3 | Реальный `plan_initiative_decision` чата 222 при пиннутом кадре чата 111, persona OFF | секция «кадр поведения недоступен»; ни version, ни 0.90, ни 0.80, ни пометки «(в этом чате)» |
| R4 | То же, резолв характера поднимает исключение (PG down) | тот же честный legacy, без значений чата 111; ход не падает |
| R5 | Положительный контроль: чат 222 резолвит свой кадр в этом ходе | frame, version и `краткость: 0.30 (в этом чате)`, значений чата 111 нет |
| R6 | Реальный `_plan_direct_l1` чата 222 со своим кадром | `meta.l1_profile_source=frame`, значения в payload, прозы Writer и тега Persona нет |
| R6b | Direct чата 999 с ctx-версией от пина чата 222 | `legacy`, значений чата 222 нет |

## Мутации (воспроизведены самостоятельно)

| Мутация | Наблюдение |
|---|---|
| Вернуть ambient-чтение кадра И снять `reset_turn_frame` (состояние `1aa818c5`) | **4 failed**: `test_profile_does_not_reuse_a_pinned_frame_of_another_chat`, `test_profile_rejects_a_stale_pin_of_the_same_chat`, `test_turn_reset_drops_the_previous_chat_frame`, `test_initiative_of_chat_b_never_receives_chat_a_values` |
| Вернуть подстрочный провенанс | **3 failed**: `test_decision_profile_source_is_structural_not_substring`, `test_profile_absent_is_honest_and_not_invented`, `test_profile_does_not_reuse_a_pinned_frame_of_another_chat` |

Число красных совпадает с заявленным Builder.

## Прогоны и снимок

- Контрактный набор: **17 passed** (было 12).
- Мой набор из 21 затронутого файла (новый контракт, канон, миграции, реестр, Direct L1, парность soul1, mca-18, initiative vitality): **459 passed**.
- ER-65 между `1aa818c5` и `0eec0996`: **0 изменённых сегментов** (58/58, 27 стадий, 229879 символов), изменились только digest'ы `services/bot_persona.py` и `services/direct_chat_service.py`; `--check` даёт `OK (27 стадий, 58 сегментов, два изолированных процесса идентичны)`.

## F3: текст отчёта

§2.5 и новый §0 теперь говорят: активация - метка заводской ревизии + печать через `prompt_release_policy.apply_release` (вызов из `bot.py:1383-1384` через делегатор `migrate_prompt_canons`); новая метка активируется ПОВЕРХ ручной правки (EVOL-012); рестарт без новой метки - no-op; откат - `activate_revision`; `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` стартом не исполняются, а соответствующие пины названы проверками мёртвого кода. Это соответствует коду (`prompt_migrations.py:1-12,858-918`, `prompt_release_policy.py:932-1030`). Замечание закрыто.

## Пункты владельца 17-22 после правки

| Пункт | Статус |
|---|---|
| 17. Direct: профиль есть, речевого мусора нет | **PROVEN (pre-deploy)**; вывод модели остаётся live |
| 18. Initiative не отвечает там, где нужен SILENT | **НЕ ДОКАЗАНО**: доставка данных и канон подтверждены, но решение принимает модель; только live |
| 19. Один источник, те же байты | **PROVEN**: байт-идентичность и корректный владелец кадра на реальных путях |
| 20. Фон без Core/Expression/профиля | **PROVEN** (без изменений) |
| 21. Свежесть без устаревшего кеша | **PROVEN на уровне механизма**: пин на ход, проверка владельца и версии, отказ от чужого/устаревшего кадра; отражение реального PG/Core - live |
| 22. Фактические assembled prompts + provenance | **PROVEN для сборок и провенанса** (ER-65 + 17 тестов); live `provider_calls` остаётся |

Итого: 5 из 6 закрыты до деплоя; п.18 и live-части 17/21/22 требуют прогона на проде.

## Остаточные наблюдения (не блокеры, без изменений)

1. При бюджете 150 токенов пакет превышает бюджет (protected не режется); для прод-бюджета не проявляется.
2. `test_soul1_composer_parity_off` по-прежнему подставляет секцию текущим выводом builder через `_profile_patch` (ослабление эталона).
3. ER-65: дрейф `direct.l2_writer.fallback_model_capacity` (709 против 745) - прежний, L2 не тронут.

## Вердикт Re-review 2

**Approved for controlled deployment (срез P1), parent not DONE.**

- F1, F2, F3 закрыты и проверены на кандидате `0eec0996`; заявленные мутации краснеют.
- PM может связывать строки P1 с evidence на `0eec0996` в объёме, доказанном до деплоя (см. ниже); строки, зависящие от поведения модели и реальных PG/Core-значений, остаются PENDING до post-deploy проверок.
- После деплоя обязательны: п.18 (SILENT при высоких инициативности/споре, tone при сарказме), отсутствие роста болтливости/токсичности, реальные PG-значения в payload и `l1_profile_source=frame`, применение смены GLOBAL/chat со следующего запроса, активность канона `ef61a9dd6798` и откат через `activate_revision`.
