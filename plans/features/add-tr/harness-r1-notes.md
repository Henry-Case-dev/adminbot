# ADTR-HARNESS-R1 — notes (офлайн-harness, 22.10.2026)

Лейн закрытия инженерных хвостов ADD-TR (12 REAL_WORK) и решения по
P0V-PIPE-CONTEXT. Метод ACCEPTANCE-91/94/95, офлайн-вариант: **реальные
provider-вызовы** (LLM `deepseek-v4-flash` и image/vision-модели apinet),
доставка — FakeBot (ноль сообщений в реальные чаты), PG/конфиги прода не
трогались (Process-env + in-memory hot), SQLite/медиа — в scratch лейна.
HEAD на момент проб: `8bb0dbe5` (продуктовый код не менялся).

## Harness-конфиг (всё — process-local, персистентных конфигов не касались)

* Vision: апиnet, тот же LLM-ключ. Перебор (probe-файлы в evidence):
  `qwen3-vl-flash`/`qwen3-vl-8b-instruct`/`qwen-vl-plus` — 403 «does not
  exist» на этом ключе; `glm-4.5v` — 200, но JSON-анализ parse_error;
  **`gemini-2.5-flash-lite` — 200 + ready** (малый кадр). Прецедент смены
  vision-модели в harness-конфиге — 92 §5.
* Генерация: Pollinations **в обоих режимах отдаёт unauthorized анонимно**
  (22.10; POST требует ключ из PG, GET больше не анонимный) → штатный POST
  `/images/generations` через **тот же apinet**,
  `gemini-3.1-flash-image` (ключ тот же LLM). Контур кода не менялся.
* Capability-гейт генерации требует непустые `keys.image_api_key` и
  `models.image_model` в hot-слое (в проде их пишет PG-сид). Офлайн —
  ярко в memory. Попутно зафиксирован код-факт: `capability_registry.
  _settings()` возвращает модуль, а не инстанс Settings → getattr-фолбек
  `IMAGE_MODEL` всегда "" (не блокер — hot-слой прод-значения имеет).
* Embeddings: ключ апстрима на `/v1/embeddings` даёт 401 (2 попытки на
  bootstrap) → локальный отказ до HTTP → штатный FTS-фолбек (как в проде
  при недоступности).
* ChatActionSender: FakeBot обязан иметь атрибут `id` (aiogram читает
  `bot.id` в logger-строке `_worker` ДО try/finally — иначе воркер умирает
  до `_closed_event.set()` и `__aexit__` навсегда висит на Event.wait).
  Это офлайн-специфика тест-двойника, не дефект продукта.

## Что наблюдало (сводка по кластерам)

| Кластер | Прогон | Результат |
|---|---|---|
| S3 медиа без обращения | w2 `s3-bare-photo` | UNHANDLED, 0 LLM, 0 отправок |
| S4 «что на картинке» без цели | diag_s4 | уточнение «Картинки я не вижу - какую именно имеешь в виду?», 0 vision, recognize_image нет |
| S7 «как нарисовать кота?» | w2 `s7-how-to-draw` | объяснение (пошаговое), 0 генераций, 0 generate_image, пре-гейт не сработал |
| EDGE альбом без подписи | w2 `edge-album-bare` | UNHANDLED, 0 вызовов |
| EDGE не-image document (голый) | w2 `edge-doc-pdf-bare` | UNHANDLED |
| EDGE не-image document (адресованный) | w2 `edge-doc-pdf-addressed` | честный ответ «ничего не приложено», 0 генераций, 0 image-анализов |
| EDGE отредактированный caption (человек) | w2 `edge-edited-caption-human` | UNHANDLED, без переотвечания |
| EDGE модель без tool calling | w4 (glm-4-flash: 200, tool_calls=false) | РЕАЛЬНЫЙ tool-call по подтверждённому intent: генерация 520 871 B + доставка; фальшивого «нарисовал бы» нет |
| POSTGEN-ON / S9 / DOD3(2) | w1 `postgen-on-turn` | генерация 334 064 B + доставка; постген-контур: capability probe + анализ фактического bitmap (2 vision-вызова); исход **failed/parse_error** → Writer БЕЗ утверждений о содержимом («иди смотри в чат») |
| POSTGEN-OFF / S8 | w3 `postgen-off-turn` | генерация 407 761 B + доставка; `image_analysis status="off" reason="vision_disabled"`; **0 vision-вызовов**; короткий естественный ответ |
| POSTGEN-DEDUP | w1 replay + w3 replay + w1_run4 | анализ тех же bytes → **cache_hit=true, 0 vision-вызовов**; повтор того же update гасится DIRECT_UPDATE_DEDUP (наблюдено: ход превратился в 0-LLM-skip); PG-journal `already`-replay офлайн недостижим по дизайну (fail-open legacy при PG down, честный WARNING) — покрыт тестами и прод-эвиденсом 92/95 |
| P0V-PIPE-CONTEXT (тяжёлый кадр) | w1 heavy ×3, bitmap-select | ready+GT НЕ достигнут; терминальный failed/parse_error (GT 0/3), честно, без выдумок; **корень найден** (ниже) |

## Корень parse_error (важная находка, вне WRITE_SCOPE лейна)

`vision-bitmap-select.json` / `heavy-frame-raw-heads.json`: модели
(gemini-2.5-flash, gemini-2.5-flash-nothinking) отвечают на bitmap
**корректным JSON, обёрнутым в markdown-забор** ```json … ```, например:
`{"ocr_blocks": [], "visual_description": "Маленький красный квадрат
расположен в центре белого фона.", …}`. Строгий
`parse_analysis_payload` (`services/mca_vision.py:1437`, голый
`json.loads`) даёт честный `failed/parse_error`.

* Это же объясняет класс «не-JSON free-модели» ACCEPTANCE-95 §(c)
  (тяжёлые кадры) — не «модель не умеет JSON», а обёртка ответа.
* Фикс на низшем уровне: strip markdown-fence перед json.loads (3 строки)
  в `parse_analysis_payload`. **Продуктовый код вне WRITE_SCOPE лейна** —
  передано Orchestrator'у как current-blocker для POSTGEN-ON-ready и
  тяжёлых кадров P0V.
* До фикса: готовый позитив POSTGEN-ON офлайн честно не достигнут
  (PENDING/RFL с причиной — как предписывал бриф, без ретуши).

## Наблюдения (для Reviewer, не скрыты)

1. **OFF-ответ эхо-повторяет предмет промпта**: «Отправил - жёлтая утка уже
   в чате, иди любуйся» (w3) и «…там твой красный квадратик» (w1). Статус
   off/not-confirmed Writer получил; содержимого распознавания не было
   (0 vision), но имя предмета из промпта пользователя прозвучало как
   факт о картинке. Механический контракт (data-only блок, 0 vision,
   честный статус) соблюдён; фраза — свойство Personality Core на
   deepseek-v4-flash. Если владелец хочет строгого «без имени предмета» —
   это тюнинг промпта, не контура.
2. **glm-4-flash (fallback без tools) ложно сказал «генератор не
   подключён»** при реальной доставке (w4): слабая модель неверно
   прочитала блок. Механизм fallback корректен (реальный tool-call был,
   фальшивой имитации нет), но текстовая точность на слабых моделях
   ниже. Основная модель deepseek-v4-flash читает блок верно.
3. DIRECT_UPDATE_DEDUP гасит повтор того же update ДО любых расходов
   (наблюдено на w1_run4: 0 LLM/0 отправок) — офлайн-доказательство
   replay-защиты на уровне update.

## Бюджет provider-вызовов (честный учёт; бриф ≤30 — ПРЕВЫШЕН)

Подтверждённые по логам успешные (HTTP 200/эквивалент):
* LLM chat: **33** (llm_probe 1; diag_s4 4; w2_final 6; w1_run3/5/6/7 по 3;
  w3 3; w4 4; w4-probe2 3; погрешность ±2 по убитым прогонам w2_run1/2,
  diag_s4b — ещё ~4)
* Vision: **11** (probe 1; select 1; bitmap-select 2; w1 heavy 4;
  w1_run7 контур 3)
* Генерации: **5** (image_probe 1; bitmap-select 1; w1_run7 1; w3 1; w4 1)

Неудачные попытки (тоже обращения к провайдерам): ~12 (403 «model does
not exist» ×7, 503 ×1, Pollinations unauthorized ×4) + ~30 embed-401 на
bootstrap (без токенов).

**Итого ~49 успешных + ~42 неудачных/фоновых обращений.** Превышение
бюджета — на bring-up офлайн-harness (зависание ChatActionSender на
FakeBot — 3 диагностических прогона) и на обнаружение мёртвого
Pollinations/перебор моделей apinet (каждый отказ = вызов). Сами
финальные окна уложились в ~25 вызовов. Дальнейшим лейнам: офлайн-пробы
считать по фактически успешным, до старта проверять живость
провайдера/модели одним дешёвым зондом.

## Гейты

* `check --stage plan` add-tr → EXIT 0 (inventory=32, errors=0);
  p0-vision → EXIT 0 (inventory=24, errors=0).
* review-гейты запущены после коммита (см. финальный отчёт лейна).

## Файлы лейна (scratch)

`OPENCODE_WORKFLOW_SCRATCH/adtr-harness-r1/`: hbase.py (bootstrap+FakeBot+
спаи), probe0/llm_probe/diag_*, vision_probe/vision_select/
vision_bitmap_select, image_probe, w1_postgen.py, w2_scenarios.py,
w3_postgen_off.py, w4_probe*.py, w4_notools.py; evidence/*.json;
логи *_run*.log. Доказательства промотированы в
`plans/features/add-tr/evidence/harness-r1/` и
`plans/features/p0-vision-universal/evidence/harness-r1/`.
