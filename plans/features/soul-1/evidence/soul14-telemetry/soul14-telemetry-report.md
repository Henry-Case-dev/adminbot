# SOUL-14.2 — telemetry: распределение extent + exact one_word compliance

Строка карты: SOUL-14.2 (M00195, source L195). Слайс: телеметрия extent.

## Что сделано

Пер-сообщенческая метрика `speech_extent` в СУЩЕСТВУЮЩИЙ контур
`mca_events` (никакой новой таблицы/сервиса/модели):

- точка эмиссии: `services/style_policy.py::_emit_extent_metric`, вызывается
  в конце `apply_style_policy` рядом с существующим `_emit_style_event`,
  при `emit_events=True and chat_id` (оба прод-вызова: direct_pre_send,
  initiative_pre_send);
- одно событие на каждый проход с реально выполненным extent-check —
  сырьё распределения extent; агрегация — по существующей таблице
  `mca_events` (колонки event_name/stage/chat_id/usage_json);
- payload `usage_json` (R17-safe, только счётчики/коды, БЕЗ текстов):
  `extent` (one_word..exhaustive | auto), `status`
  (pass/repaired/failed/conflict/not_applicable), `one_word` (0/1),
  `one_word_exact` (0/1: финальный текст ровно одно лексическое слово —
  pass/repaired), `words` (счётчик лексических слов), `reason`,
  `context` (regular|initiative);
- исходы только из `ALL_OUTCOMES`: pass/repaired→success(INFO),
  failed/conflict→failed(WARN), not_applicable→skipped(INFO)
  (урок B1 8cd2ca14: невалидный outcome build_event молча роняет);
- extent-check не шёл (style OFF / без плана) → события НЕТ (честное
  отсутствие); OFF `SPEECH_STYLE_POLICY_ENABLED` → байт-паритет, текст
  не меняется, событий нет; kill-switches контура
  (`MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED`)
  уважаются как для остальных событий;
- 0 LLM-вызовов, данные не выдумываются (дорогой per-message LLM-оценки
  нет); доставленный payload дополнительно проверяется существующим
  `verify_outbound_payload` (mismatch уже эмитится существующим событием
  `style_policy` failed с `check.as_dict()` — не дублируется).

Остальные семейства метрик строки SOUL-14.2 едут существующими контурами
(без дублей в этом слайсе): feedback label counts / lessons applied —
`mca_humor_feedback` (SOUL-08.2, strategy в capture_send); повторяемость —
`detect_repetition` → usage_json style-события; пропуски слоя с reason —
существующий паттерн `stage_event(..., reason_code=...)`; latency/cost —
контрактные колонки duration_ms/cost_usd/input/output_tokens; injected
Core tokens — detail лог композера (core_tokens/budget).

## Тесты

- `tests/test_soul14_telemetry_extent.py` — НОВЫЙ, CONTRACT
  owner=SOUL-14.2, 11 тестов: success/failed/repaired исходы one_word,
  распределение micro/compact, honest auto→skipped, initiative context,
  честное отсутствие (без плана), OFF-паритет, приватность (нет текстов
  во всём событии), рантайм-проба build_event без spy (B1-паттерн),
  дефолт-ON гейтов.
- Related: `tests/test_soul1_extent_one_word.py` +
  `tests/test_soul1_style_policy.py` — зелёные.

## Прогон (локально, HEAD bf17a972 + слайс)

```
$ py -3 -m pytest tests/test_soul14_telemetry_extent.py tests/test_soul1_extent_one_word.py tests/test_soul1_style_policy.py -q
97 passed, 2 warnings in 2.85s
```

(в т.ч. test_soul14_telemetry_extent.py: 11 passed)

## Локальная эмуляция реального контура (не spy)

Реальный `emit_mca_event` (gates ON, терминальный outcome) → событие в
durable-буфере `_pending` (очередь flush в таблицу mca_events):

```
buffered: speech_extent success direct_pre_send 303
usage_json column: {"extent": "one_word", "status": "pass", "one_word": 1,
"one_word_exact": 1, "words": 1, "context": "regular"}
LOCAL EMULATION OK: real contour buffers speech_extent; kill-switch
respected; aggregation columns present
```

Kill-switch OFF (`MCA_EVENT_CONTRACT_ENABLED=False`) → эмиссия no-op,
буфер не растёт (поведение контура unchanged).

## Приватность

В payload нет текста ответа и слов ответа — только счётчики/коды;
`usage_json` дополнительно проходит `sanitize()` в `build_event`
(defense-in-depth, B-MCA13-1).
