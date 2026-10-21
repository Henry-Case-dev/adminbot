# FIX-VISION-FENCE — strip markdown-fence в parse_analysis_payload

Дата: 22.10.2026. Кандидат: коммит `fix(vision): strip markdown-fence in
parse_analysis_payload` (services/mca_vision.py, `_strip_markdown_fence` +
строка вызова в `parse_analysis_payload`). База: HEAD 60110e77.

## Корень (до фикса)

Модели стабильно возвращают КОРРЕКТНЫЙ JSON, обёрнутый в markdown-забор
```` ```json … ``` ````; строгий `parse_analysis_payload` (голый
`json.loads`) честно давал `parse_error` на валидном JSON:

- `before-w1-postgen.json` (копия w1-postgen.json @1b03c428): postgen-turn
  → `postgen_statuses=["failed"]`, `reason=parse_error`, Writer без
  утверждений о содержимом (защита DOD3 работала, позитив недостижим).
- `plans/features/p0-vision-universal/evidence/harness-r1/heavy-frame.json`:
  тяжёлый PNG 960x2600/1 114 350 B — failed/parse_error на glm-4.5v и
  gemini-2.5-flash-lite, GT 0/3; сырые головы ответов — валидный JSON в
  заборе.

## Фикс

`_strip_markdown_fence`: снимается ТОЛЬКО обёртка (первая строка
```` ```<метка> ```` и хвостовой ```` ``` ````); содержимое не правится и
проходит прежнюю строгую валидацию `json.loads` — невалидный JSON остаётся
честным `failed/parse_error`. Никаких regex-извлечений и «умной починки».

## Тесты (tests/test_mca19_block_b_round1043.py, REGRESSION owner=POSTGEN-ON/S9 + P0V heavy)

- `fence-fix-red-tests.txt` — ДО фикса: `test_markdown_fenced_json_parsed`
  FAILED (воспроизведение), инвариант-тест зелёный.
- `fence-fix-green-tests.txt` — ПОСЛЕ фикса: весь файл 33 passed
  (31 существующих + 2 новых).

## Верификационный прогон (w5-fence-fix.json, офлайн-harness ADTR-HARNESS-R1:
реальные provider-вызовы, FakeBot-доставка, 0 сообщений в Telegram)

1. POSTGEN-ON / S9 / DOD3(2) — полный ход «нарисуй маленький красный
   квадрат»: генерация 518 988 B + доставка; capability probe + анализ
   фактического bitmap (2 vision-вызова); **postgen status=ready**,
   описание «Маленький красный квадрат расположен по центру на белом
   текстурированном фоне.» (78 симв.); блок с
   `image_analysis status="ready"`; Writer-ответ по факту картинки.
2. P0V heavy-кадр — тот же fixture_heavy.png (byte-ident, sha12 в JSON)
   через штатный `validate_or_normalize` + `analyze_adaptive`:
   **status=ready, GT 3/3** (ZEBRA77, QUARTZ88, LOTUS99), OCR дословный
   (включая W-01..W-03 и END-маркер), 1 vision-вызов.

Бюджет прогона: 1 gen + 3 vision + 3 LLM (embed 401 офлайн — ожидаемо,
fail-open FTS). Провайдер: apinet (vision gemini-2.5-flash-lite,
gen gemini-3.1-flash-image) — те же, что в w1/heavy-frame «до».
