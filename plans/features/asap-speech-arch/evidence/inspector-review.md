# INSPECTOR exact — независимое ревью (REV-SPEECH-INSPECTOR)

- Кандидат: `7c3df3961e39d3f8401d464ec95e29b1f8883fa2` (`HEAD`)
- Время: 24.10.2026, 03:10, UTC+12:00
- Режим: read-only; изменён только этот файл
- Вердикт: **Needs Fixes** — **не в поезд 2.58.115**
- Проверяемый объём: INS-EXACT, INS-TRACE, INS-SKIPREASON, INS-HIERARCHY,
  INS-CONFLICT, INS-PRIVACY, U-04

## 1. Приёмка по пунктам

| Пункт | Статус | Что установлено |
|---|---|---|
| INS-EXACT (primary) | **VERIFIED** | На успешном primary-вызове `LLMClient.generate` журнал берёт тот же `payload`, что уходит в `_post`; unit-тест и независимый пересчёт sha256 дают совпадение. |
| INS-EXACT (fallback) | **FAILED** | При fallback фактическое тело отличается: `_post_fallback` копирует payload и меняет `model`; журнал получает старый `payload` и **исходные** `messages`, а не `payload["messages"]` после адаптера. Repro ниже: `checksum == http` = `False`, в UI показан неотправленный текст. |
| INS-TRACE | **PARTIAL / не VERIFIED** | Есть correlation_id, chat_id-маска, model/provider, module/step, status/error, checksum и текст. Но это только `generate`; реальные `generate_chat` (tool-calling Stage-1/tool) и фоновые каналы не пишутся. Для literal acceptance «на каждый реальный LLM-вызов» этого мало; в карте нет owner-approved сужения. |
| INS-SKIPREASON | **VERIFIED** | Все 39 кодов `SKIP_REASONS` имеют русские подписи; в карточке пропусков машинный код только в `title`; тест `tests/test_speech_inspector_exact.py` это проверяет. |
| INS-HIERARCHY | **PARTIAL** | Для реального хода клик раскрывает текст/источник/редакцию, пустого скролла нет (e2e). Но в preview-only состоянии у включённых блоков текста нет (`_preview_manifest` не отдаёт layer texts), клик показывает «текст недоступен». |
| INS-CONFLICT | **PARTIAL** | Типографика/длина/роль/бюджет/SOUL-* — из реальных данных; `profanity_case` честно 0 с `coverage_note`. Но класс «чат против global» всегда 0: `chat_global_rule_override` попадает в `typography`/`length`, а не в `chat_global`; UI пишет «не найдено» при реальном override. |
| INS-PRIVACY | **FAILED** | Иерархия отдаёт **сырой** текст слоёв: в `web/api/speech.py:1961-1966` в `_inspector_hierarchy` передаётся `layer_texts` без `_mask_text`; маскированная копия `sent["layer_texts"]` существует, но UI её не использует. Секрет/длинный ID из Core/Identity попадают в ответ и в DOM. |
| Scope | **PASS с замечанием** | `llm_client` не меняет отправку (только fail-open trace); каноны промптов не тронуты. Но `write_scope` слайса в `slice-graph.json` не перечисляет фактически изменённые `services/llm_client.py`, `web/api/speech.py`, `web/app.js`, `web/index.html`, новые тесты — граф устарел. |
| UI/U-04 | **PASS для фактического хода** | e2e 121/0 на 7 viewports; проверены 320/360/390/430/1280/1440/667×375, длинные строки и URL без горизонтальной прокрутки; W4 `failures=0`; ASAP3 hint `PASS 10`; `node --check` 0. Browser Use 390: карточка exact и checksum отображаются, горизонтальной прокрутки нет. |
| Requirements gate | **BLOCKED** | `requirements_gate.py check --stage review --slice INSPECTOR --candidate 7c3df396` → exit 1: map всё ещё на `e4ee54f3`, INS-* `PENDING`, evidence не привязано к кандидату; `INS-PRIVACY` опирается на старые evidence. |

## 2. Блокирующие findings

### F1. Fallback: Inspector показывает не тот payload и не тот checksum

- Серьёзность: **BLOCKER** (INS-EXACT, P0; одновременно ломает INS-TRACE).
- Требование: «checksum payload после scrub/truncation/fallback retry»;
  «полный итоговый промпт» байт-в-байт = вызов provider.
- Места: `services/llm_client.py:1118-1119` (`fallback_payload` — копия с
  `model=self._fallback_model`), `services/llm_client.py:1353-1358`
  (адаптер меняет `payload`, но `messages` остаётся исходным),
  `services/llm_client.py:1394-1398` (журнал получает `payload` и `messages`),
  `services/prompt_composer.py:1970+` (checksum считается по `payload`).
- Воспроизведение (реальный путь `_post_fallback`, тестовый транспорт):
  primary падает, `fallback_payload_adapter` меняет user-блок, fallback
  отвечает 200. Фактическое тело: `model=fallback-model`,
  `user="Q-cut"`; журнал: `model=fallback-model`, `user="Q"` (исходный),
  `checksum(actual) != journal`. Проверено на `7c3df396`.
- Влияние: при реальном fallback владелец видит в «фактическом запросе»
  текст, которого провайдер не получал, и checksum, не совпадающий с телом.
  Это ровно то, что требование запрещает.
- Причина: в журнал передаётся объект `payload` до подмены `model` в
  `_post_fallback`, а `messages` — аргумент `generate`, а не
  `payload["messages"]` после адаптера.
- Минимальная коррекция: фиксировать фактически отправленное тело
  (`dict(payload)` + `model=fallback_model`; `messages` из этого тела) и
  отдельно фиксировать неудачные fallback-попытки; добавить тест на
  реальный `_post_fallback` с адаптером.
- Перепроверка: тот же probe → `journal.checksum == payload_checksum(http_body)`
  и `journal.messages[i].text == http_body.messages[i].content`.

### F2. R17: иерархия отдаёт сырые секреты/длинные ID

- Серьёзность: **BLOCKER** (INS-PRIVACY/R17; P0).
- Требование: debug-инспекция не содержит секретов/токенов; UI сам
  заявляет «маскировка: секреты и длинные ID».
- Места: `web/api/speech.py:1961-1966` — в `_inspector_hierarchy` идёт
  `layer_texts` (сырой `render_layer_texts`), а не `sent["layer_texts"]`
  после `_mask_text`; `web/api/speech.py:1680` кладёт `text` в item;
  `web/index.html:9342` — бейдж маскировки; `web/index.html:9468` —
  показ `item.text`.
- Воспроизведение: манифест с Identity `api_key=sk-live-...` и
  `id 5885953495`; `_inspector_payload` → в `hierarchy` присутствуют
  и секрет, и сырой ID. `sent.layer_texts` при этом маскирован.
- Влияние: секрет/приватный ID попадает в JSON API и DOM Inspector,
  хотя интерфейс обещает маскировку; это регрессия относительно старого
  `system_masked`/`_mask_text` поведения.
- Минимальная коррекция: передавать в `_inspector_hierarchy` уже
  маскированный `sent["layer_texts"]` (одна строка); в `_inspector_exact`
  применять `_mask_text` к `system`/`messages[].text`, сохраняя checksum
  по исходному payload; либо убрать ложный бейдж. Добавить R17-тест на
  весь JSON Inspector (не только trace).
- Перепроверка: в JSON Inspector нет секрета/длинного ID; checksum
  остаётся прежним и совпадает с фактическим телом.

### F3. INS-TRACE буквально не покрывает каждый реальный вызов

- Серьёзность: **BLOCKER для строгой приёмки INS-TRACE** (P0 в карте;
  решение о сужении объёма владельцем не зафиксировано).
- Места: единственная точка записи — `LLMClient.generate`
  (`services/llm_client.py:103`, вызовы 1313/1362/1372/1382/1394);
  `generate_chat` (`:1514`) и фоновые каналы не инструментированы.
  Evidence `inspector-exact.md:173-175` сам это признаёт.
- Влияние: tool-calling Stage-1/tool-вызовы невидимы; Inspector может
  показать более поздний `generate` как «last actual request», не имея
  per-call ревизий слоёв/effective scope/skip reason для `generate_chat`.
- Минимальная коррекция: инструментировать `generate_chat` (и явно
  решить судьбу `generate_worker`/background) либо зафиксировать
  owner-approved сужение scope в карте; без этого INS-TRACE нельзя
  помечать VERIFIED.
- Перепроверка: тест вызывает `generate_chat` и видит запись в журнале
  с correlation_id/model/provider/step.

### F4. Requirements gate и slice graph не соответствуют кандидату

- Серьёзность: **BLOCKER процесса** (не runtime).
- `plans/features/asap-speech-arch/requirements-map.json`:
  `candidate_commit=e4ee54f3`, INS-TRACE/EXACT/SKIPREASON/HIERARCHY/CONFLICT
  `PENDING`, evidence не привязано к `7c3df396`; `INS-PRIVACY` — старые
  evidence. `requirements_gate.py check ...` → exit 1 (10 errors).
- `slice-graph.json` INSPECTOR `write_scope` не содержит фактически
  изменённые `services/llm_client.py`, `web/api/speech.py`, `web/app.js`,
  `web/index.html`, `tests/test_speech_inspector_exact.py`,
  `tests/ui_inspector_exact_e2e.py`; в графе указан несуществующий
  `tests/test_prompt_inspector.py`.
- Влияние: strict review нельзя закрыть; граф больше не описывает
  принятый слайс и небезопасен для параллельных писателей.
- Коррекция: PM/Orchestrator обновляет candidate/evidence/write_scope;
  после этого повторно `--stage review`.
- Это не правится Builder-ом в коде; нужно до финального approval.

## 3. Связанные, но не главные findings

- **INS-CONFLICT, класс chat/global**: `_style_rule_conflicts` возвращает
  `chat_global_rule_override` с `class=typography`; `_inspector_conflicts`
  для этого id по умолчанию ставит `length`; класс `chat_global` всегда
  0. В UI «Правило чата против глобального — не найдено» при реальном
  override. Repro: `exact={'dash':'em'}`, `clash={'dash':'hyphen'}` →
  `typography=1`, `chat_global=0`. Исправить классификацию/показ, тест
  обновить. (P1, локально.)
- **Hierarchy detail показывает машинный код**: `web/index.html:9463-9466`
  выводит `({{ item.skip_reason_code }})` видимым текстом, а не только в
  `title`; для few_shot/channel_output это нарушает «machine code — не
  основной текст». Перенести в `title`/`data-*`.
- **Preview hierarchy без текста**: `web/api/speech.py:1996` строит
  иерархию без `layer_texts`; в состоянии «только предпросмотр» клик по
  включённому блоку показывает «(текст недоступен)». Если click-through
  обещан и для preview, отдать маскированные тексты preview-манифеста.
- **Exact и длинные ID**: `services/llm_client.py:116-118` маскирует
  только секреты; `web/api/speech.py:1817` отдаёт `messages[].text` как
  есть. Длинные Telegram ID/tg-ссылки в exact не маскируются, хотя бейдж
  обещает «длинные ID». Это тот же root, что F2; исправить вместе.
- **Тесты**: e2e `build_payload` пишет вызов в журнал напрямую
  (`composer.record_provider_call`), а unit-тест `_TraceClient`
  переопределяет `_post_with_key` и не проходит fallback. Поэтому зелёные
  121/0 и 8/0 не ловят F1. Нужен тест на реальном fallback-пути.

## 4. Ограничения: блокируют ли

- **In-memory bounded 24**: само по себе не блокер для owner-debug в
  PET-проекте: после рестарта Inspector честно пишет «только предпросмотр».
  Но это не durable log; при высокой частоте вызовов запись чата может
  вытесниться. Оставить как явное ограничение, не выдавать за полный лог.
- **Trace только generate**: блокирует literal INS-TRACE (F3), пока нет
  явного сужения scope владельцем.
- **Preview checksum несравним с actual**: корректно и честно подписано;
  не блокер. Проверять preview отдельно от actual.

## 5. Числа прогонов на `7c3df396`

- `pytest tests/test_speech_inspector_exact.py` → **8 passed**
- `pytest tests/test_llm_client.py` → **115 passed**
- 8 файлов (`test_speech_inspector_exact` + 7 связанных) → **109 passed**
- `tests/ui_inspector_exact_e2e.py --no-shots` → **checks=121 failures=0**,
  exit 0; 7 viewports
- `tools/ui_w4_ui_e2e.py --no-shots` → **failures=0, POST=8, notes=163**
- `tests/ui_asap3_hint_speech_e2e.py` → **PASS: 10 проверок**
- `node --check web/app.js` → **exit 0**
- `requirements_gate.py check --stage review --slice INSPECTOR
  --candidate 7c3df396` → **exit 1**, 10 errors (map на `e4ee54f3`,
  INS-* PENDING, evidence не привязано)

## 6. Итог

Код и UI в основном готовы для **primary**-пути, но P0-контракт
«фактический payload после fallback» нарушен, а новый Inspector отдаёт
сырые секреты в иерархии. Поэтому кандидат **нельзя** включать в поезд
2.58.115. После исправления F1/F2 (минимальные локальные правки), решения
по F3 и обновления карты/графа (F4) нужен повторный targeted recheck:
fallback-probe, R17-полный-JSON, 8/115/109/121 и `requirements_gate`.
