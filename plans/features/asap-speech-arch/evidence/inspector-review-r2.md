# INSPECTOR exact — повторное ревью R2 (REV-SPEECH-INSPECTOR-R2)

- Кандидат: `18030a8cc797b7a7b180f37476f14470fa21d44b`, база `7c3df396`
- Время: 24.10.2026, локальное UTC+12:00; read-only, изменён только этот файл
- Вердикт: **Needs Fixes** — **не в поезд 2.58.115**
- Проверялись: F1 (fallback exactness), F2/R17, F3 (trace coverage),
  регрессии и scope. F4 (карта/граф/gate) — зона PM, здесь только отмечена.

## 1. Приёмка

| Пункт | Статус | Что установлено |
|---|---|---|
| F1, успешный fallback | **VERIFIED** | `_post_with_key`/`_post_fallback` пишут фактически отправленное тело; `_record_sent_call` берёт `sent[-1]`. Тест `test_fallback_trace_is_the_body_that_went_on_the_wire` проходит: `journal.checksum == payload_checksum(http_body)`, `model=trace-fallback-1`, `messages[-1]=Q-cut`, `channel=fallback`, `provider=fallback.example`; неудачная primary не подменяет финальный снимок. |
| F1, неудачный fallback | **FAILED** | При primary 500 + fallback 500 реально уходит 4 HTTP-запроса, а в журнале остаётся 1 запись — primary error. Fallback-попытки не фиксируются, хотя прежняя минимальная коррекция F1 требовала «отдельно фиксировать неудачные fallback-попытки». |
| F2, hierarchy + exact | **VERIFIED** | `_inspector_payload` строит hierarchy из `sent["layer_texts"]` (уже `_mask_text`); exact маскирует `system`/`messages[].text`. Тест `test_inspector_hierarchy_is_masked_but_keeps_provenance` и e2e DOM-проверки проходят. |
| F2, весь JSON/DOM Inspector | **FAILED** | `preview.style.hint_text` (и `excluded[].text`) отдаются **сырыми**; это prompt-текст в том же Inspector JSON/DOM. См. B1. |
| F3, каналы (success) | **VERIFIED** | `generate`, `generate_chat`, `generate_background` (dedicated), `generate_worker` (dedicated), `stream_chat_completion` (успешный SSE) пишут в журнал; независимый probe совпал по checksum с телом на проводе. `embed` честно `covered:false` с причиной. |
| F3, error-пути | **FAILED** | Есть молчаливые пробелы: fallback-попытки при общем провале; `generate_chat` при 200 + `content:null` без tools/reasoning; `generate_background` помечает `ok` до разбора JSON. См. B2. |
| Регрессии | **VERIFIED** | 12 / 115 / e2e 142/0 / W4 failures=0 / ASAP3 PASS 10 / node 0. |
| Scope | **VERIFIED** | Изменения аддитивные, каноны промптов не тронуты; `web/app.js` не изменён; `index.html` — только новые блоки. |

## 2. Блокирующие findings

### B1. R17: сырой style-hint в JSON и DOM Inspector

- Серьёзность: **BLOCKER** (INS-PRIVACY/R17; P0).
- Требование: debug-инспекция не содержит секретов/токенов/длинных ID; бейдж
  «маскировка» не должен быть ложным.
- Места: `web/api/speech.py:1297` (`hint_text` = raw `policy.hint`),
  `web/api/speech.py:1197` (`excluded[].text` raw soft-instruction),
  `web/api/speech.py:2148/2171` (`preview["style"]`),
  `web/index.html:9607` (`preview.style.hint_text` в `<pre>`),
  `web/index.html:9592` (`excluded[].text`).
- Repro: `_style_build_summary` с hint `ID 123456789012 ... sk-live-...`
  возвращает их без маски; `_preview_manifest` кладёт это в
  `preview["style"]["hint_text"]` (проверено inline-probe). Штатные
  `test_inspector_hierarchy_is_masked...` и e2e кладут секрет/ID только в
  identity, поэтому 12/142 зелёные, но весь Inspector не проверяют.
- Влияние: если style soft-instruction содержит токен/длинный ID, он виден в
  JSON API и в DOM, хотя страница обещает маскировку.
- Минимальная коррекция: в `_preview_manifest` (граница Inspector, не глобально —
  style-редактор вправе видеть свой текст) прогнать `_mask_text` по
  `hint_text` и `excluded[].text`; в тест/e2e добавить style-инструкцию с
  секретом и длинным ID.
- Перепроверка: `SECRET`/`LONG_ID` отсутствуют в JSON и DOM со style-фикстурой;
  checksum exact по-прежнему равен фактическому телу.

### B2. INS-TRACE: реальные error-вызовы не попадают в журнал / врут статусом

- Серьёзность: **BLOCKER для literal INS-TRACE** (P1, локальный патч).
- Требование: trace на каждый реальный LLM-вызов, включая статус; «last actual
  request» должен быть последним фактическим запросом.
- Repro (все три воспроизведены probe-скриптом):
  1. primary 500 + fallback 500: 4 HTTP-вызова, журнал — 1 запись
     (`primary/error`), fallback-записи нет; `_inspector_payload` затем может
     показать primary как `last actual request`, хотя последним был fallback.
     Места: `services/llm_client.py:1404-1406`, `_fallback_with_retries`.
  2. `generate_chat` с 200 и `content:null` без tools/reasoning: исключение
     `LLMBadResponseError`, журнал пуст (`services/llm_client.py:1734-1735`).
  3. `generate_background` с 200 и невалидным JSON: журнал `status=ok`, затем
     исключение (`services/llm_client.py:1476-1484`).
- Влияние: при сбоях владелец не видит финальную fallback-попытку/ошибку
  tool-вызова, а статус `ok` противоречит фактическому отказу.
- Минимальная коррекция: перед `raise` при `fb_response is None` записать
  последнее `sent`-тело как `channel=fallback/status=error`; в `generate_chat`
  записать error перед empty-content raise; в `generate_background` перенести
  success-запись после `response.json()` (или писать error на `ValueError`).
  Добавить по тесту на каждый путь.
- Перепроверка: probe показывает записи для fallback-error, chat-empty и
  background-invalid-json; exact больше не выдаёт primary за последний запрос
  при провале fallback.

## 3. Связанное (не главный блокер)

- **Per-message sha ≠ фактические байты.** `manifest_checksum` считается по
  raw payload (проверено: True), но `exact.messages[].sha256` и
  `messages_checksum` считаются по уже маскированному тексту
  (`llm_client._record_provider_call` маскирует до composer). Evidence/коммит
  говорит «sha256 … по фактическим байтам» — это неточно для per-message sha.
  UI показывает только checksum, поэтому не блокирует; исправить формулировку
  evidence либо считать sha по raw body отдельно (не храня raw text).
- **F4 (вне этого лейна, но блокирует release):** `requirements-map.json` всё
  ещё `candidate_commit=e4ee54f3`, INS-* `PENDING`; `slice-graph.json`
  write_scope устарел. PM должен привязать карту/граф к `18030a8c` и прогнать
  `requirements_gate.py check --stage review`.

## 4. Числа (кандидат 18030a8c)

- `tests/test_speech_inspector_exact.py` → **12 passed** (py -3 и .venv)
- `tests/test_llm_client.py` → **115 passed** (.venv; py -3 — те же 115)
- `tests/ui_inspector_exact_e2e.py --no-shots` → **checks=142 failures=0**, exit 0
- `tools/ui_w4_ui_e2e.py --no-shots` → **failures=0, POST=8, notes=163**, exit 0
- `tests/ui_asap3_hint_speech_e2e.py` → **PASS: 10**, exit 0
- `node --check web/app.js` → **0**

## 5. Итог

F1 (успешный fallback) и F2 (hierarchy/exact) закрыты; каналы F3 покрыты и
проверены. Но R17 не выполнен для `preview.style` (B1), а literal INS-TRACE
имеет молчаливые error-пробелы (B2). Поэтому кандидат **нельзя** включать в
поезд 2.58.115. После двух локальных правок и повторного targeted recheck
(style-probe + три error-probe + 12/115/142/0 + node) — PM обновляет карту/
граф (F4) и запускает release-gate.
