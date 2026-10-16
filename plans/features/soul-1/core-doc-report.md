# SOUL-1 / CORE-DOC — отчёт слайса: Personality Core (первоисточник + компактная runtime-редакция)

- **Lane:** CORE-DOC (writer: registry/content/tests). **Join barrier:** YES —
  без зарегистрированного Core планировать голосовой канареечный релиз нельзя.
- **Кандидат:** master `d9b7f389` + рабочее дерево 17.10.2026 (без коммита).
  `sha256_12`: `prompt_registry.py`=`f4a0246947a3`, `prompt_factory.py`=`fbbab19ce304`,
  `prompt_composer.py`=`a0bb5f408196`, `chat_prompts.py`=`3c465e0cfa2b`.
- **FIX-CORE-DUP (R1 ревью `review-core.md`):** блок CORE-DOC был записан в
  `services/chat_prompts.py` **трижды** (строки 439–486/489–536/539–586, один
  diff-hunk): активна была последняя копия, теневые COMPACT-варианты отличались
  текстом (261/251/249 слов). Удалены строки 439–538; оставшаяся копия
  сохранена байт-в-байт (`040581a3b4b0`/`ff28f0720a23` — те же), рантайм не
  изменился. Добавлен регресс-тест
  `test_core_constants_are_defined_exactly_once_in_module_source`
  (AST-счёт определений по самому файлу; фальсифицирован теневой копией в
  scratch — падает с `assert 2 == 1`).
- **Требования:** `requirements-map-amendment.json` SOUL-AMD.1.1 (+1.3),
  `requirements-map.json` SOUL-02.0–02.8; проверяются также SOUL-AMD.4.1–4.3
  (Factory Defaults/история/откат) для нового блока. Привязка — §6.
- **Что НЕ делалось:** UI «Речь и характер» (W6), каталог `flags.*`/UI-регистрация
  флагов, голосовой канареечный релиз, прод/деплой, коммит.

## 1. Что зарегистрировано (реестр, `services/prompt_registry.py`)

| Registry ID | Что это | Фабричная ревизия | Где живёт значение |
|---|---|---|---|
| `core.personality` | **ПОЛНЫЙ авторский текст** «Речь, юмор и мышление» (SOUL-02, строки 43–53 первоисточника) — Factory Default | `fac:040581a3b4b0(soul02-author-full-v1)` | поле `full_text` документа `character.core` |
| `core.personality.compact` | **компактная runtime-редакция** (ручное сжатие, 249 слов) | `fac:ff28f0720a23(soul02-compact-v1)` | поле `compact_text` того же документа |

- Провенанс первоисточника — `pr.CORE_SOURCE` (путь, §3 SOUL-02, заголовок
  «### Речь, юмор и мышление», строки 43–53, `SOUL-02.1–02.6`, карта
  `requirements-map.json`, amendment `SOUL-AMD.1.1`, метка фабричной ревизии).
- Оба блока — новый тип спеки: `pg_key="character.core"` + `pg_doc_field`
  (блок = ПОЛЕ JSON-документа, `design-source-of-truth` §2.1). Это позволило
  не заводить вторую сущность и не дублировать текст: фабричный текст
  резолвится из код-канона `services/chat_prompts.PERSONALITY_CORE_FULL_TEXT` /
  `..._COMPACT_TEXT` (инвариант «нет скрытого дубля» цел, тест
  `test_factory_default_is_the_catalog_code_canon` продолжает проходить).
- Guard реестра обновлён ЛЕГАЛЬНО (осознанный бамп, не отключение):
  `FACTORY_SET_SHA256_12` `8cc27a902dae` → `381aa1f0a9e4`,
  `REGISTRY_VERSION` `soul1-w1-2` → `soul1-w1-3`; тест «правка канона без
  регистрации ломает отпечаток» остался и проверен новым тестом.
- Каталог `prompts.*`/`flags.*` НЕ расширялся → `Δ каталога = 0`
  (`CHECK OK: реестр 572 == REGISTRY`), артефакты round1025 не перегенерировались.

## 2. Компактная редакция (ручная, НЕ LLM-пересказ)

Текст (249 слов, `sha256_12=ff28f0720a23`, целиком — `evidence/w1/_core_compact_revision.txt`):

```
Ты общаешься как живой участник неформального русскоязычного чата. Тебе свойственны остроумие, абсурдное мышление, язвительность и непристойный юмор, но главное - не агрессия, а способность замечать нелепое в обычных вещах.

**Как рождается юмор.** Когда разговор располагает к шутке, ищи неожиданную интерпретацию сказанного: принимай оговорку, нелепую предпосылку или метафору буквально и смотри, к чему это ведёт. Нашёл смешную идею - развивай её, а не бросай после первой фразы: добавляй логически связанные последствия, бытовые детали, воображаемые правила. Абсурд может нарастать до неожиданного вывода. Смешивай несовместимые области - быт, философию, бюрократию, экономику, биологию, технологии, религию, криминалистику: интересны не случайные сравнения, а связи, которые после прочтения кажутся почти логичными.

**Мат и грубость.** Мат - естественная часть речи, а не приправа к каждому предложению: используй его, когда он делает фразу выразительнее, смешнее или эмоционально точнее. Не подменяй шутку оскорблением: прямое «сам дурак» - самый скучный вариант, интереснее довести идею собеседника до нелепого следствия. Резким, злым, циничным и неприличным быть можно, но не превращай каждое общение в бессмысленную ссору.

**Ритм.** Длина разная: иногда достаточно одного слова, иногда нужны несколько предложений и нарастающий абсурд. Не обрывай удачную мысль ради искусственной краткости, не используй постоянно одну композицию. Не объясняй собственные шутки, не называй использованные приёмы, не сообщай, что сейчас иронизируешь.

**Чего избегать.** Передразнивания, бесконечного перекидывания оскорблений, очевидных метафор, одинаковых финальных фраз, искусственного философствования, сюрреализма без связи с темой. Не пытайся быть смешным в каждом сообщении: обычный разговор, серьёзный ответ, сухая реплика и молчание тоже часть характера. Не выдумывай ради шутки реальные события, сведения о людях и статистику чата.
```

Деривация (код-константа `PERSONALITY_CORE_COMPACT_DERIVATION`, проверяется
тестом против САМОГО первоисточника): каждый задокументированный маркер обязан
присутствовать и в строке источника, и в сжатии.

| Строка первоисточника | Абзац | Маркеры смысла, обязанные остаться |
|---|---|---|
| 43 | характер/угол зрения | `замечать нелепое`, `не агрессия` |
| 45 | как рождается юмор | `буквально`, `нарастать`, `почти логичными` |
| 47 | мат и грубость | `приправа`, `сам дурак`, `бессмысленную ссору` |
| 49 | ритм | `одного слова`, `Не обрывай удачную мысль`, `одну композицию`, `использованные приёмы` |
| 51 | чего избегать | `в каждом сообщении`, `часть характера`, `статистику чата` |

Закрывающий абзац 53 («**Важно:** это *семантическое описание характера*, а не
форматный контракт…») в runtime-редакцию сознательно НЕ входит: он описывает сам
документ, а форматные правила — отдельный слой Speech Style Policy (SOUL-16).
Компактная редакция — сжатие ТЕХ ЖЕ предложений: новых правил/личности не
добавлено, «ассистентского» голоса нет (тест на анти-цели §1.3).

## 3. Выбор редакции: детерминированно и видимо

`prompt_registry.core_selection(doc, source, budget_tokens)` — чистая
синхронная функция (ни одного LLM/IO-вызова, доказано тестом): документ
владельца + заводские редакции + бюджет аддитивных слоёв. Причины —
закрытый набор `CORE_DETAIL_REASONS`:

| Причина | Когда |
|---|---|
| `factory_default` | документа владельца нет → действует заводская редакция (в проде `character.core` не существовал) |
| `document_default` | документ есть, `detail_level` владелец не выбирал (дефолт `compact`) |
| `owner_setting` | `detail_level` документа = выбор владельца |
| `context_budget` | просили `full`, но стоимость полной редакции > бюджета слоёв → компактная |
| `full_text_missing` / `compact_text_missing` | запрошенной редакции нет ни у владельца, ни в заводской (защитные ветки) |

Видимость выбора:
* манифест композера — слой `core` получил `detail`
  (`level=compact reason=factory_default origin=factory words=249 doc=factory`),
  плюс `versions["core_detail"]` = `"<level>:<reason>"`; поля добавлены и в
  `render_effective_layers`, и в R17-safe `manifest_for_events` (текст промпта
  в события не утекает — проверено тестом);
* Inspector — `prompt_composer.core_inspection(chat_id)` (редакция, причина,
  источник, ревизия, заводские редакции обоих блоков с размерами/хешами,
  провенанс первоисточника) и `prompt_registry.core_selection_view(doc)` (без
  сырого текста);
* реестр/UI-слой — `registry_view()` отдаёт `pg_doc_field`, оба блока видны в
  `param_catalog.speech_registry_view()` / `unmanaged_speech_blocks()`
  (`ui=catalog_pending`, владелец W6 — редактор в MiniApp).

**Осознанное решение (граница):** `withheld_values()` для Core НЕ применяется.
Удержание (W1) защищает от legacy persisted-значений старых канонов; у
`character.core` таких значений не существует (ключ в проде никогда не
создавался → `core_absent`), а сам документ — новая владельческая сущность,
правка которой обязана действовать со следующего ответа (SOUL-02.7/15.5,
действующие тесты W2). Проверено тестом
`test_core_blocks_visible_in_registry_view_and_unmanaged_list`
(`provenance_required is False` с обоснованием).

## 4. Правка Core через API реестра (§4): семантика

`prompt_factory.write_speech_value("core.personality"|"core.personality.compact", text)`
— документ-осознанный: пишет ПОЛЕ документа `character.core`
(категория записи `content`), не трогая второе поле.

* **правка редакции делает её действующей** (`detail_level` документа = уровень
  правленой редакции). Иначе правка «неактивной» версии не имела бы
  наблюдаемого эффекта, а требование «правка Core меняет следующую генерацию»
  не выполнялось бы. Уровень остаётся явным полем документа и виден в
  манифесте/Inspector.
* **per-chat правка** собирает документ из глобального (наследование всех
  полей) + правит целевое поле; глобальное ядро не меняется (SOUL-02.8),
  `reset_chat_override` возвращает наследование (не заводской сброс).
* **«Вернуть заводской вариант»** (`plan`/`apply_factory_reset`) документ-осознан:
  diff и запись только по правленому полю, `set_level=False` (сброс значения не
  переключает уровень), история/откат — на блок (`history_for`,
  `character.prompt_history`), повторный сброс идемпотентен.
* Заводское значение поля наследуется ПОЛЕМ: если владелец сохранил только
  одну редакцию, вторая остаётся заводской (не пустой).

## 5. Провенанс: полный текст = первоисточник, байт-в-байт

`evidence/w1/_core_full_text_byte_exact.txt`:

```
factory block_id : core.personality
factory revision : fac:040581a3b4b0(soul02-author-full-v1)
chars            : 2835   sha256_12: 040581a3b4b0
source chars     : 2835   BYTE-EXACT: True   code == constant: True
source_sha256 (файл) == map source_sha256 : True
SOUL-02.1 строка 43 карта ee5f96d4462a1154… == файл …: True (в тексте: True)
SOUL-02.2 строка 45 … SOUL-02.6 строка 53 — все шесть совпали
```

Сравнение идёт с САМИМ файлом `plans/features/soul-1/source-current-task.md`
(строки 43–53; границы под-блока проверяются по заголовку выше и по абзацу
`**Runtime:**` ниже) и со строчными `source_text_sha256` карты — копии текста в
тесте нет, поэтому расхождение с первоисточником ломает тест.

## 6. Приёмка

| Пункт брифа | Статус | Доказательство |
|---|---|---|
| Байт-в-байт сравнение заводской полной редакции с первоисточником | **PASS** | `_core_full_text_byte_exact.txt` (BYTE-EXACT True, 2835 chars, 6/6 строчных хешей карты) + `tests/test_soul1_core_doc_text.py` (6 тестов) |
| Компактная редакция: текст, размер, деривация, сохранение смысла/запретов | **PASS** | `_core_compact_revision.txt` (249 слов, 5 абзацев-источников, маркеры) + тесты `test_compact_revision_keeps_documented_meaning_markers`, `test_compact_keeps_character_and_prohibitions_without_assistant_slop` |
| Компактная НЕ генерируется в рантайме (нет LLM), выбор детерминирован и видим | **PASS** | `test_core_selection_is_deterministic_and_reasons_are_closed`, `test_core_selection_path_contains_no_llm_call`, `test_resolve_core_does_not_write_or_call_llm`, `test_core_does_not_add_llm_calls` (ON/OFF: 1 вызов L2) |
| Правка любого блока через API меняет effective Core и не трогает другой | **PASS** | `test_editing_full_block_changes_effective_core_only_full`, `test_editing_compact_block_changes_effective_core_only_compact`, `test_owner_core_edit_changes_next_generation` (реальный `_l2_write_answer`) |
| `FACTORY_SET_SHA256_12` всё ещё падает при правке канона без регистрации | **PASS** | `test_factory_guard_fails_when_canon_edited_without_registration` (+ существующий `test_factory_registry_completeness::test_factory_fingerprint_matches_declared_constant`) |
| Core реально доезжает до prompt при ON; OFF-байты не тронуты | **PASS** | `_core_manifest_direct_l2.{txt,json}` (слой `core` между `channel_contract` и `identity`, `fac:ff28f0720a23`, 1934 chars/484 tok) + `test_factory_core_reaches_real_l2_system_when_on`, `test_off_path_renders_no_core_and_writes_no_manifest` |
| Паритет OFF 13/13 | **PASS** | `_core_tests.txt` блок [1]: `13 passed` |
| Флаги OFF (прод не включён) | **PASS** | `_core_checks.txt`: `UNIFIED_COMPOSER_ENABLED` env не задан, `env_enabled=false`, `effective_enabled=false`; `character_core_enabled=true` (W2-дефолт, без мастера не рендерится) |
| Каталог: `--check` | **PASS** | `_core_checks.txt`: `CHECK OK: реестр 572 == REGISTRY` (Δ=0, каталог не расширялся) |
| Сьюты/периметр | **PASS** | `_core_tests.txt`: новые файлы 25 passed; все SOUL-1 156 passed; каталог/реестр 129 passed; периметр `soul1|catalog|registry|prompt|direct_chat|summary|config` **3164 passed / 0 failed** |
| Нет скрытого дубля (check 3; R1 ревью) | **PASS (после FIX-CORE-DUP)** | `chat_prompts.py`: ровно одно определение каждой Core-константы (AST-счёт: `FULL` 457–467, `COMPACT` 469–477, `DERIVATION` 480–486; было 3+3+3); регресс-тест `test_core_constants_are_defined_exactly_once_in_module_source`, фальсификация в scratch — `assert 2 == 1` |

## 7. Изменённые файлы

```
f4a0246947a3 services/prompt_registry.py      fbbab19ce304 services/prompt_factory.py
a0bb5f408196 services/prompt_composer.py      3c465e0cfa2b services/chat_prompts.py
b1ebd47900bb tests/test_soul1_core_doc_text.py
3c88ac5a1e5f tests/test_soul1_core_registry_api.py
d1bc98158087 tests/test_soul1_core_composer_integration.py
8118f48cff47 tests/test_soul1_core_version_propagation.py (переанкерен 1 тест)
evidence/w1/_core_full_text_byte_exact.txt      _core_compact_revision.txt
evidence/w1/_core_selection_probe.json          _core_manifest_direct_l2.{txt,json}
evidence/w1/_core_tests.txt                     _core_checks.txt
evidence/w1/_core_provenance_probe.py           _core_dump_manifest_direct_l2.py
evidence/w1/_core_run_checks.py
```

Периметр: реестр (2 новых блока + выбор редакции), фабрика (документ-осознанные
write/reset/plan), композер (резолв Core + трасса `detail` + Inspector-вид),
код-канон Core, тесты, evidence. `web/**`, каталог, maps/plan/reviews,
`plans/current_task.md`, `plans/workflow_state.md` не тронуты.

## 8. Осознанные границы слайса

1. **MiniApp-редактор «Характер (Ядро)» — W6.** Слайс даёт всё, что редактору
   нужно: два блока реестра, `write_speech_value` (глобально/чат),
   `plan/apply_factory_reset`, историю/откат, `registry_view` с
   `pg_doc_field`, `core_inspection`. Сам UI и ключи каталога не добавлялись
   (Δ каталога = 0).
2. **Переанкерен один тест W2** — `test_core_absent_is_visible_state_not_error`
   (`tests/test_soul1_core_version_propagation.py`): до регистрации Core
   «нет документа» = `core_absent`; теперь это заводская редакция
   (`source=default`, `origin=factory`, `fac:<sha12>`), а `core_absent`
   остаётся честным состоянием при недоступном заводском тексте и при PG down
   (инвариант W1 §4 — OFF-паритет не затрагивается). Это не «подгонка теста»:
   изменился контракт (появился Factory Default), тест переанкерен на новый
   контракт с сохранением исходного смысла «состояние видно, а не падает».
3. **`mca_gates.character_core_enabled()` docstring** («рендерится при наличии
   документа `character.core`») слегка устарел (теперь действует и заводская
   редакция) — файл вне WRITE_SCOPE, поведение не изменилось; правка строки —
   W2/слайс регистрации флагов.
4. **Канареечный релиз/живой прогон** не входят в слайс: Core-текст проверен
   тестами и офлайн-сборкой реального Direct-пути; сравнение полной/компактной
   редакций на живых обезличенных сценах чата (§8 amendment) — отдельный шаг
   релиза с включённым флагом.

## 9. Инцидентальные находки (не блокируют)

* `chat_params.set_chat_params` требует живой PG-пул: per-chat правка Core в
  тестах идёт через те же инъекции `get_root`/`set_root`, что и W1 (не дефект).
* `aiosqlite`-teardown `tests/test_summary_memory.py` — предсуществующее
  (исключён из периметра, как в W1).

## 10. TEST-LIFECYCLE

Все новые тесты — `CONTRACT owner=SOUL-AMD.1.1 / SOUL-02.1–02.8` (шапки файлов);
`PROVISIONAL` нет. Переанкеренный тест W2 сохранил класс CONTRACT
(owner=SOUL-1/W2, SOUL-15.5/02.7). Регресс-тест FIX-CORE-DUP —
`REGRESSION owner=SOUL-1/FIX-CORE-DUP` (единственность определения канона,
`tests/test_soul1_core_doc_text.py`).
