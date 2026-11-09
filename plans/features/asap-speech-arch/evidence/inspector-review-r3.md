# INSPECTOR exact — ревью R3 (REV-SPEECH-INSPECTOR-R3)

- Кандидат: `4553495a53aafbb83b0869a9f0ae54793925df97`, база `18030a8c`.
  Пять файлов диффа в рабочем дереве не изменены; ревью read-only.
- Время: 24.10.2026 04:18 (UTC+12).
- Вердикт: **Needs Fixes** — один остаточный gap в fallback-журнале
  (`generate_chat`); R17 и error-статусы закрыты, числа сходятся.

## 1. R17 style-срез — VERIFIED

`_mask_style_view()` (`web/api/speech.py:1202-1225`) применяется к обоим
срезам: `sent["style"]` (`:1985`) и `preview["style"]` (`:2019`). Маскируются
`hint_text`, `hint_block_masked`, `excluded[].text`; счётчики/ревизии/причины
не меняются, исходный preview не мутируется (копия dict + новый список).

Независимый probe (вне тестов): секрет и 12-значный ID в `hint_text` и в
`excluded[].text` → `***`/`[id]`; `hint_chars=40`, `layer.state=rendered`,
`reason_label` и `payload_included` сохранены; исходный объект не изменён.
Тест `test_inspector_masks_style_hint_text` проходит и проверяет отсутствие
секрета/ID во всём JSON Inspector. DOM не имеет второго источника: `<pre>`
`preview.style.hint_text` (`web/index.html:9607`) и `excluded[].text`
(`:9591-9594`) читают тот же masked JSON; снимок — `sent.style.hint_block_masked`
(`:9629-9630`), замаскирован.

Замечание к покрытию (не блокер): фикстура теста не создаёт непустой
`excluded` (нет лимита), поэтому ветка `excluded[].text` тестом не
исполняется — она проверена прямым probe функции.

## 2. Fallback-журнал — FAILED (частично)

`generate`: 4 HTTP-попытки → **4 записи** (2 primary + 2 fallback), все
`status=error`, `last actual` = последняя fallback-попытка,
`manifest_checksum == payload_checksum(http body)`. Подтверждено тестом
`test_total_fallback_failure_logs_every_attempt` и независимым probe.

`generate_chat` (`services/llm_client.py:1692`): при том же сценарии —
**3 записи на 4 попытки**: primary-ретраи схлопываются в одну запись, потому
что здесь остался `_record_sent_call`, тогда как в `generate`
(`:1392-1398`) уже `_record_sent_attempts`. В проде `LLM_MAX_RETRIES=2`
(settings.py:396) → 3 primary + 2 fallback = 5 HTTP-попыток, в журнале 3.
`last actual` при этом корректен (последняя fallback), checksum последней
записи == её тело.

В evidence (`inspector-exact.md`, §5, строка 2) утверждение «`_post`/
`_post_fallback` пишут КАЖДУЮ попытку … Журнал: 2 primary + 2 fallback»
сформулировано без оговорки о `generate_chat` — для tool_loop-пути это
неверно.

Минимальная правка: `:1692` → `_record_sent_attempts(...)` (как в
`generate`), добавить в существующий probe проверку `generate_chat`:
4 попытки/4 записи (тестовая конфигурация) или 5/5 (дефолтные ретраи).
Повторная проверка: тот же probe + `test_speech_inspector_exact.py`.

## 3. generate_chat empty / background invalid JSON — VERIFIED

- `generate_chat`, 200 + `content:null` без tools/reasoning:
  error-запись `status=error`, `LLMBadResponseError`, затем raise
  (`services/llm_client.py:1789-1796`); тест проходит.
- `generate_background`, невалидный JSON: success-запись перенесена после
  валидации content; все три ветки (invalid JSON / нет choices / пустой
  content) пишут `status=error` (`:1512-1541`); тест проходит.

Побочно (pre-existing, вне r3): `generate_background` не передаёт `sent` в
`_post`, поэтому ретраи фонового канала в журнал не попадают; сид
`sent=[("primary", payload)]` может записать «попытку» до фактической
отправки.

## 4. Числа — подтверждены

| Проверка | Результат |
|---|---|
| `tests/test_speech_inspector_exact.py` | **16 passed** |
| `tests/test_llm_client.py` | **115 passed** |
| `tests/ui_inspector_exact_e2e.py --no-shots` | **checks=142 failures=0**, exit 0 |
| `tools/ui_w4_ui_e2e.py --no-shots` | **failures=0**, exit 0; `web/index.html` в диффе нет → W4 не менялся |
| `tests/ui_asap3_hint_speech_e2e.py` | **PASS: 10**, exit 0 |
| `node --check` | не перезапускался: JS/UI в кандидате не менялись |

## 5. Ослабления/лишние правки — нет

Дифф: `web/api/speech.py`, `services/llm_client.py`,
`services/prompt_composer.py`, `tests/test_speech_inspector_exact.py`,
evidence. Тесты только добавляют проверки (старые assert не удалены);
`headers={}` у фейкового ответа нужен retry-коду; ключ журнала на
`itertools.count` — обоснованный фикс (одинаковые тела ретраев с
`time.time_ns()` могли схлопнуться). Лишних правок нет.

## Итог

R17 (п.1) и error-статусы (п.3) закрыты; числа сходятся; п.2 закрыт для
`generate`, но не для `generate_chat` (tool_loop). Пользовательский путь не
сломан, «last actual» верен, поэтому риск низкий, но literal INS-TRACE
«каждая HTTP-попытка» на этом пути не выполнен. Однострочная правка + probe
— и кандидат готов к выкату.