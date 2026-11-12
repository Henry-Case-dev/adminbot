# P0IM-PB-LLM — контролируемое доказательство на 25876167 (2.58.197)

Дата: 2026-11-13 (system-local +12:00). Автор: Builder (subagent), по решению
владельца: закрывать инициативу без ожидания естественной LLM-попытки; нужен
контролируемый технический прогон через реальный конвейер.

- База: `2587616759de31283585ffc105c91e7193c2e89e` (release/2.58.197).
- Ветка/воркtree: `fix/p0im-pbllm-proof`, отдельный worktree из
  `workflow_housekeeping.py worktree-path` (зарегистрирован, unit
  `p0im-pb-llm-proof`).
- Production не затрагивался: нет деплоя, нет изменения вероятности/настроек/
  промптов/моделей, нет сообщений в Telegram, нет обращений к БД прода.

## Что именно доказывается

Одна попытка проходит НАСТОЯЩИЙ путь `meme.consider_chat` → `_consider_once`:
реальные шаги A/B (`_default_summarize`/`_default_joke`), настоящий
`LLMClient.generate`, настоящий журнал попыток в temp-SQLite, настоящая бронь
публикации и read-model. Подменены только внешние границы:

- `LLMClient._post` (сеть) — существующий тестовый прецедент
  `test_default_summarizer_matches_real_client_contract`;
- `image_provider` (граница Image API) — существующий хук пайплайна;
- `sender` (граница Telegram) — существующий хук доставки.

Кольцо `prompt_composer.provider_calls` — НЕ подменяется и НЕ заполняется
вручную. Тест читает его так же, как это делают Inspector и карточка попытки.

## Команда и результат

```text
cd <worktree fix/p0im-pbllm-proof>
.venv/Scripts/python.exe -m pytest tests/test_evol014_meme_initiative.py -q
62 passed in 14.95s
```

Новый тест:
`tests/test_evol014_meme_initiative.py::test_controlled_pipeline_attempt_binds_identity_ring_and_delivery`
— PASS (входит в 62). Сфокусированные соседние наборы:

```text
pytest tests/test_speech_inspector_exact.py -q     -> 23 passed, 1 warning
pytest tests/test_initiative_publications_api.py -q -> 40 passed, 1 warning
```

Warning — внешний `StarletteDeprecationWarning` от `fastapi.testclient`.
Весь репозиторий не запускался (по рамке задачи).

## Наблюдённые данные контролируемого прогона

Job этой попытки (детерминированные NOW/tz теста):
`meme:-100:2026-10-30:005e1d47e849`.

### Durable detail этапов (SQLite `meme_initiative_attempt`, `detail` JSON)

```json
"summary": {
  "chars": 30,
  "llm": {"provider": "llm.example.invalid", "model": "chat-model",
          "slot": null, "slot_reason": "slot_not_used"},
  "prompt": {"block": "initiative.meme.summary", "source": "factory",
             "revision": "act:175781ddfd7e", "sha12": "175781ddfd7e"},
  "source": "factory"
},
"joke": {
  "chars": 29, "limit": 171, "ceiling": 200, "mode": "fixed",
  "llm": {"provider": "llm.example.invalid", "model": "chat-model",
          "slot": null, "slot_reason": "slot_not_used"},
  "prompt": {"block": "initiative.meme.joke", "source": "factory",
             "revision": "act:2f30ca1f9a6b", "sha12": "865e6f11f00b"},
  "source": "factory",
  "speech": {"composer": "on", "manifest": "a62a7c70736b4dc6",
             "system_sha12": "0a0385a42c48"}
},
"image_generation": {
  "chars": 58, "template_chars": 29,
  "template_revision": "fac:f81fe7e4b505(meme-image-evol014)",
  "template_source": "factory", "joke_chars": 29,
  "prompt_sha12": "d5bde9b57e05",
  "api": {"called": true, "ok": true, "status": "ok",
          "bytes": 3, "bytes_present": true,
          "format": "png", "format_source": "filename",
          "filename_present": true}
}
```

Терминальная строка (`publish`, `outcome=published`):

```json
{"attempt_mode": "automatic", "delivery": "sent", "gate": "ok",
 "manual": false, "mode": "automatic",
 "publication": {"delivery": "sent", "output": {"tg_message_id": 777},
                 "claim": {"granted": true, "state": "claimed"},
                 "sending": {"granted": true, "state": "sending"}},
 "events": [{"name": "source_snapshot"}, {"name": "digest_ready"},
            {"name": "joke_ready"}, {"name": "image_ready"},
            {"name": "publication_requested"},
            {"name": "publication_sent", "reason": "sent", "delivered": true,
             "detail": "tg:777"}]}
```

Важное уточнение о месте identity: терминальная строка `publish` по
утверждённой архитектуре (R0) содержит только факты публикации/доставки.
Провайдер/модель/слот и промпты живут в строках этапов `summary`/`joke`, а
факты Image API — в строке `image_generation`; все строки связаны одним
`job_id`, и detail-эндпоинт отдаёт их одной цепочкой `chain`. Тест проверяет
именно такую связку одной попытки (identity + prompt + image API +
`tg_message_id` + подтверждение), а не выдуманные поля в терминальной строке.

Read-model попытки: `outcome=published`, `delivered=true`,
`message_id=777`, `generated=true`.

### Кольцо композера (`prompt_composer.provider_calls`) — реально заполнено

```json
[
 {"correlation_id": "meme:-100:2026-10-30:005e1d47e849#meme_summary",
  "module": "initiative", "step": "meme_summary",
  "model": "chat-model", "provider": "llm.example.invalid", "status": "ok",
  "system_sha256": "175781ddfd7e34534e627d948864fd4aaba480ee9a599f7446a94817d49e7723",
  "messages_checksum": "889dc15d2dcb98b4626c4693fcce4f15a1fb20835b72052b3a6ea37539c6270e"},
 {"correlation_id": "meme:-100:2026-10-30:005e1d47e849#meme_joke",
  "module": "initiative", "step": "meme_joke",
  "model": "chat-model", "provider": "llm.example.invalid", "status": "ok",
  "system_sha256": "0a0385a42c4809c348b3ac7bf038a65e62ca9f1af1a61f7ae43c6cf981f15ba6",
  "messages_checksum": "524ce0c802f4f0c658e62423d69531d1baefc1424380f85ff3051c4a9e178b7c"}
]
```

Доказательства связности:

- `summary.prompt.sha12 == sha256(system этапа A)[:12]` (175781ddfd7e);
- `joke.prompt.sha12 == sha256(J-директивы)[:12]`, а system этапа B
  НАЧИНАЕТСЯ с этой директивы (полный system = директива + речевые слои,
  его хеш — `joke.speech.system_sha12 = 0a0385a42c48`);
- в кольце этап A: system-промпт выжимки и user — JSON окна сообщений
  (тест проверяет наличие «реплика 0»);
- в кольце этап B: user-сообщение равно ровно выжимке
  `КОНТРОЛЬНАЯ ВЫЖИМКА ДЛЯ КОЛЬЦА`.

### Inspector и карточка попытки

- `_inspector_correlation_payload(-100, "<job>#meme_summary")`:
  `requested_correlation_recorded=true`, `exact.is_actual=true`,
  `exact.step="meme_summary"`, `exact.model="chat-model"`,
  `exact.provider="llm.example.invalid"`,
  `exact.messages_checksum=889dc15d…` (совпадает с кольцом).
- То же для `#meme_joke`: `recorded=true`, `is_actual=true`, и в ответе
  присутствует фактическая выжимка (user этапа B).
- `_full_text_evidence(-100, job, False)`: `available=true`, оба шага
  `{step: summary|joke, recorded: true, reason: ""}`. То есть отсутствие
  полного текста в журнале не выдаётся за «нет данных»: адрес полного текста
  (существующий Inspector) реально указывает на записанные вызовы.

### Нет полного текста в durable detail

Dump всех строк журнала не содержит:

- выжимку `КОНТРОЛЬНАЯ ВЫЖИМКА ДЛЯ КОЛЬЦА`;
- прикол `КОНТРОЛЬНЫЙ ПРИКОЛ ДЛЯ КОЛЬЦА`;
- текст system-промпта выжимки («Придумай короткий…»);
- текст image-промпта («Создай мем…»).

В журнале остаются только счётчики, source/revision/sha12, статус/формат/байты
Image API и `tg_message_id`.

### Нет дополнительных вызовов

- Транспорт LLM вызван ровно 2 раза (этапы A и B); Image API — ровно 1 раз.
- После чтения кольца, Inspector correlation, `full_text` и read-model в кольце
  по-прежнему ровно 2 записи, счётчики вызовов не изменились.
- Диагностика не создаёт ни LLM-, ни image-вызовов.

### Проверка чувствительности теста (falsification)

Одноразовый пробник (не в репозитории): `prompt_composer.record_provider_call`
заменён на no-op, после чего вызван новый тест.
Результат: `EXPECTED FAILURE (ring not recorded): []` — тест падает на пустом
кольце. Значит утверждение о кольце является несущим: тест не может «пройти»
с подделанным `not_recorded`/пустым кольцом. Пробник удалён после проверки.

## Честные границы доказательства

- Сеть/провайдер не вызывались: `_post` подменён на границе HTTP. Проверен
  путь построения/записи вызова, ретраи и fallback-каскад в этом прогоне не
  исполнялись (успешная одиночная попытка).
- Image API — хук `image_provider`; реальный `_default_image`/внешний провайдер
  не вызывались. `format` берётся из имени файла, `bytes` — из длины content.
- Доставка — фейковый `sender`; Telegram не вызывался, `tg_message_id=777`
  синтетический.
- `provider` в identity берётся из `LLMClient._provider_label` (host базового
  URL); в этом окружении fallback-модель не сконфигурирована. В продакшене
  подпись провайдера может быть иной — код того же шва, но конкретное значение
  production не подтверждается этим прогоном.
- `source="factory"` отражает тестовое окружение без chat/global override.
  Ветки override проверены существующими тестами (`test_initiative_publications_api`),
  но не этим прогоном.
- Кольцо процесса ограничено 24 записями и живёт до рестарта; доказательство
  привязано к этому запуску.
- Это НЕ естественное production-событие и не замена живому наблюдению: статус
  строк карты не выставляется этим документом (решение PM/Reviewer).

## Изменения и коммиты

- Код продукта не менялся: кольцо уже захватывает мем-вызовы
  (`LLMClient.generate_with_metadata` → `_record_sent_call` → существующий
  `record_provider_call`), поэтому это test-only доказательство.
- Тест: `tests/test_evol014_meme_initiative.py` (один новый тест).
- Документ: этот файл. В базовой ветке релиза `plans/` отсутствует; файл
  добавлен на ветку `fix/p0im-pbllm-proof` и должен быть перенесён в
  `plans/`-дерево (master, 8f8ee671) при принятии.
- SHA коммитов: см. handoff (код/тест и документ коммитятся отдельно).
