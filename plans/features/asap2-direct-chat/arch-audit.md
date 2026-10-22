# Архитектурный аудит asap2-direct-chat (GOV-ARCH-AUDIT)

Дата: 23.10.2026 04:16 +12:00. Лейн `ARCH-ASAP2`, read-only (записан только этот файл).
База: кандидат `5ad73933`; в рабочем дереве (`HEAD ceba0e13`) лежит незакоммиченная правка `services/direct_l1.py` — учтена отдельно в §4. Код/тесты/карты/прод/SSH не менялись.
Внешние источники не нужны: все выводы repo-local, версионных внешних контрактов нет.

## 1. Единственный интерпретатор намерения

Цепочка Direct при L1 ON: `handle` → `_plan_direct_l1` (`direct_chat_service.py:2828`) → L1 payload (`:4179-4182`) → модель → `parse_l1_plan` → `normalize_l1_plan` (`direct_l1.py:341`) — **единственное** место, где `needs_clarification` получает значение.

| Потребитель поля | Код | Эффект |
|---|---|---|
| Tool-гейт | `direct_chat_service.py:4426` | `needs_clarification` → tools не запускаются |
| Writer-директива | `direct_chat_service.py:3643-3644` → `direct_l1.py:942-951` | узкая фраза §4.3 только при true + непустой target |
| L2-отказ (fallback) | `direct_chat_service.py:3674-3687` | гейт по тому же полю |

Второго решателя нет:
- Speech: `clarify_action` (`claim_envelope.py:409-431`) возвращает только `none`/`assume`; `render_speech_block` (`:489-524`) содержит лишь «не переспрашивай»; `_l1_speech_hints` (`direct_chat_service.py:4042-4066`) подаёт `act/quote/negation/humor_risk/clarify=assume`, `short_dependency` в L1 не уходит вовсе.
- `response_act` не является гейтом: он маппится в `task_kind` (`direct_l1.py:198-204`), отдельно учитывается только `comparison` в evidence (`direct_execution.py:953-957`). Модельный текст из него — только строка плана (§4).
- Legacy media-уточнение (`response_extent.clarification_question`, `:825-835`) требует `task_kind ∈ {media_download, transcription}` (`:822`); планы L1 таких значений не дают (`direct_l1.py:199-204`), а legacy-ветка выключена при `direct_l1_on` (`direct_chat_service.py:3249-3262`). Второй интерпретатор на L1-пути недостижим.

## 2. Effective-резолв промптов на проде

| Слой | Код | Поведение |
|---|---|---|
| Factory (код) | `prompt_registry.factory_text`; guard `FACTORY_SET_SHA256_12="24ae494ac422"` (`prompt_registry.py:1666`) | заводская редакция, возврат/история — `prompt_factory` |
| Рантайм-резолв | `resolve_prompt` (`prompt_style_blocks.py:224-243`) → `hot.get` (`hot_config.py:71-76`) → `resolve_hot_prompt` (`prompt_registry.py:2385-2402`) → `resolve_speech_value` (`:2269-2309`) | PG/hot значение + вычистка legacy + удержание без провенанса; пусто → код-канон |
| Hot-кэш | `ConfigCache._settings` (`config_cache.py:235-285`), запись PG→память в `set`/`set_many` (`:681-714`) | `hot.get` читается каждый ход; LISTEN/NOTIFY нет — внешний SQL требует reload/restart |
| Startup-миграция | `bot.py:1366-1369` → `migrate_prompt_canons` (`prompt_migrations.py:518-552`) | точное совпадение байт → `cache.set` (PG+память); кастом не трогается |

Ключевая асимметрия (проверено исполнением с fake-ConfigCache, W1-байты, venv py3.12):
- L1 `prompts.direct_l1_planner_system_prompt`: `speech=False` (`prompt_registry.py:300-306`) → effective **равен PG-значению** (W1-old = True, новый канон = False). Правка одной константы не действует.
- L2 `prompts.direct_chat_verbalizer_system_prompt`: `speech=True, legacy_persona=True` (`:283-292`) → `withholding_required=True` (`:2132-2146`), значение без провенанса **удерживается**: effective = factory (новый канон), source=`default`, лог `withheld | reason=provenance_missing | stored_sha=be03964322aa`. Правка одной PG не действует.
- Per-chat override для этих ключей Direct-рантаймом **не читается**: у `resolve_prompt` нет `chat_id`; L2 берёт `base_prompt` из него (`direct_chat_service.py:4624-4627`), а `resolve_base_source` (`prompt_composer.py:1014-1034`) даёт только метку провенанса; текст — `PromptPlan.base_prompt` (`:4559-4562`).
Следствие: обновлять нужно factory **и** global PG; PG-only rollback для L2 — no-op, пока factory новый (откат = revert кода по runbook). Фактические хеши прода здесь не снимались — это MIGR-INSPECT/DevOps.

## 3. Четыре существующих места + контекст

| Место | Роль | Текущее состояние | Соответствует | file:line |
|---|---|---|---|---|
| L1 schema / `needs_clarification` | типо-безопасный разбор единственного флага; канон-контракт | `= data.get("needs_clarification") is True`; схема и правило 5 не изменены, секция §4.1 вставлена | да | `direct_l1.py:341`; `chat_prompts.py:562-573, 801-805, 813-827` |
| `build_l2_plan_block` | единственный plan-hint для L2; директива только от валидного поля | директива §4.3 корректна; строка `смысловой акт ответа: clarification` была вторым сигналом на `5ad73933` (см. §4) | частично → §4 | `direct_l1.py:872-953` |
| `claim_envelope.clarify_action` / `render_speech_block` | описательные речевые сигналы; не имеют права требовать вопрос | `ask`-ветка удалена, остались `none`/`assume`; `assume` = анти-переспрос | да | `claim_envelope.py:409-431, 489-524` |
| `_l1_speech_hints` | короткие R17-safe коды для L1 | `act/quote/negation/humor_risk/clarify=assume`; `clarify=ask` не подаётся; `short_dependency` не передаётся | да | `direct_chat_service.py:4042-4066` |
| Контекст продолжения `build_l1_context` | донести существующую историю и прошлые реплики бота; без новой памяти | window `smart_messages` (20; при бюджете 10→5→0) + `bot_replies` ≤3 в окне `CHAT_BOT_REPLIED_RECENTLY_SECONDS` (600 с) | да, с остаточным риском | `direct_l1.py:648-703`; `direct_chat_service.py:1962-1986, 4130-4177` |

Риск контекста (не нарушение единственного владельца): ответ на уточнение позже 10 минут уже не гарантированно несёт вопрос бота через `bot_replies`, а кап бюджета сжимает окно первым. Это существующая доставка контекста; проверяется CLAR-CTX тестами/пробой, новой памяти не требует.

Измеренная типо-безопасность (`normalize_l1_plan`): `True→True`; `False`, `"true"`, `"false"`, `null`, `1`, `0`, `[]`, `{}` → `False`.

## 4. Остаточный сигнал `direct_l1.py:890-892` — подтверждён

На кандидате `5ad73933` `build_l2_plan_block` добавлял строку `смысловой акт ответа: clarification` при `needs_clarification=false` и при `true` с пустым target. Исполнение подтвердило дословно:
`'<Response_Plan>\nдействие: reply\nсмысловой акт ответа: clarification\n</Response_Plan>'`.

Это **реальный второй model-facing сигнал**, не debug: строка входит в user-часть L2 (`direct_chat_service.py:4643-4644`), называет акт ответа «clarification», и при этом план не требует вопроса. L2-канон §4.2 разрешает спрашивать только по плану — план сам себе противоречит; нарушены §3.2 и T31 («ни один второй флаг не включает уточнение»). Тест `tests/test_asap2_clar_contract.py:100-101` ловит только русское «уточняющ» и английский enum пропускает.

Минимальный контракт исправления (без реализации здесь): строку `act=clarification` выводить только в валидной ветке (`clarification=True` ∧ строгий `needs_clarification is True` ∧ непустой target), иначе не выводить; прочие значения `response_act` не трогать; новых функций/валидаторов/списков слов не добавлять. Проверка: для `{act:clarification, needs_clarification:false}` и для `true`+пустой target в блоке нет подстроки `clarification`; в валидной ветке строка и директива допустимы.

Фактическое состояние рабочего дерева: правка уже применена (незакоммичена, `git diff services/direct_l1.py` = +12/−3, `direct_l1.py:891-903`). Измерено: `false` → блока нет; `true`+пустой target → блока нет; `true`+`media_target` → строка + директива; `response_act=explanation` → строка сохранена. То есть по кандидату дефект есть, по рабочему дереву — устранён; нужны коммит и assert на enum, иначе привязка к `5ad73933` оставит B1 ревьюера открытым.

## 5. Границы изменения и вердикт

**ARCH_REUSE_CONFIRMED.** Новых подсистем/схем/квот/LLM-вызовов не требуется; всё укладывается в существующие компоненты. Diff `5ad73933` по `services/` не содержит новых `def`/`class`/`re.compile`/`CREATE TABLE`/порогов (проверено `git show`).

Замороженные контракты:
- `L1Plan.needs_clarification: bool` — единственный владелец решения; разбор строго `is True`.
- `build_l2_plan_block(plan, *, rejected, clarification, low_confidence, include_delivery)` — сигнатура и набор строк прежние; меняется только условие вывода одной строки.
- `SpeechUnderstanding.clarify` фактически `{none, assume}`; `CLARIFY_ASK` (`claim_envelope.py:351`) остаётся неиспользуемым значением enum, не новым классом.
- Ключи `prompts.direct_l1_planner_system_prompt` / `prompts.direct_chat_verbalizer_system_prompt`; `PROMPT_MIGRATIONS` / `ROLLBACK_MIGRATIONS` / factory-fingerprint — существующая процедура, без миграций схемы БД.
- `build_l1_context(...)` и состав секций — прежние; новых источников контекста нет.

Что должен доделать Builder (без реализации здесь): (1) закоммитить правку §4 и добавить assert на отсутствие `clarification` в невалидных ветках; (2) в evidence MIGR зафиксировать асимметрию L1(PG-эффективен)/L2(factory-эффективен, PG-only rollback — no-op) и что per-chat для этих ключей не читается; (3) закрыть покрытие T19–T24/T33/T34 (это уже блокеры `review-struct.md`, не архитектура). Слайсы: CLAR-PLAN (+тест), MIGR (evidence), TESTS; остальные без изменений.

Что уже корректно и переписывать не нужно: канон L1 §4.1 и правило 5-отсылка, строгий boolean, снятие speech-императива (`clarify_action`/`render_speech_block`/`_l1_speech_hints`), узкая директива §4.3 при непустом target, лестницы миграций и rollback, сборка контекста продолжения.

Параллельность: правка §4 пишет только `services/direct_l1.py` (+ его тест) и не пересекается с MIGR (`prompt_*.py`) и TESTS; действующая зависимость CLAR-PLAN → TESTS сохраняется. Риск R1 (одна строка + тест, откат — revert). Приёмка: unit A/B/C/D из §4, структурный payload L2 без `clarification` при `false`; семантика реальной модели остаётся за ASAP2-PROBE.
