# ADTR-POSTGEN — design note адаптера и адресные решения

## Что построено

`services/postgen_vision.py` — небольшой доверенный адаптер «фактически
сформированный исходящий файл → существующий анализатор MCA-19»:

```
GenerationResult.content (bytes)
  → mca_vision.resolve_effective_state(chat_id)        # гейт: requested+capable
     (pending → одна bounded-проба ensure_capability, прецедент D8)
  → mca_vision.validate_image_bytes(bytes)             # тот же сниффер/лимиты MCA-19
  → mca_vision.analyze_image_bytes(image, chat_id=…)   # тот же вызов модели
  → PostgenVisionOutcome (data-only)
```

Точки инъекции результата Writer-у (обе — в существующих контурах):
1. direct pre-gate: подблок `<image_analysis …>` внутри `<image_result>`
   (`services/image_generation.py::maybe_handle_keyword`) — инъекция в
   user-blocks ответа (прецедент блока `<image_result>`/`<dig_result>`);
2. tool-путь: поле `image_analysis` в JSON-результате `generate_image`
   (`services/tool_router.py::_generate_image`) + обновлённый
   HOW-TO-INTERPRET-фрагмент описания `generate_image`
   (`services/tool_schemas.py`, V21; legacy-текст OFF-рубильника A3 не тронут).

## Почему так (и что явно НЕ сделано)

- **Второй pipeline не создан** (M-ADTR-POSTGEN-REUSE): провайдер, route,
  ключ, схема ответа, лимиты и единственный вызов — MCA-19. Адаптер — это
  только упаковка bytes → `DownloadedImage` (через существующий
  `validate_image_bytes`) и те же reason-коды (словарь не расширен).
- **Исходящий файл не регистрируется активом и не ставится в durable-очередь.**
  Observer пропускает сообщения бота (`handlers/summary.py:333-334`), поэтому
  чужих пользовательских триггеров нет; наш контур — in-memory анализ того же
  анализатора, без `register_intake_assets`/`process_asset_job`. Это и есть
  ответ на «собственное generated image не считается пользовательским
  запросом» и «несколько результатов/медиа-группы»: генерация = один
  `ImageRequest` = один файл = один анализ; альбомы входящих не затрагиваются.
- **Prompt/success/metadata в описание не попадают по конструкции**: адаптер
  получает только bytes + chat_id + correlation_id — промпт ему недоступен
  физически; поля `visual_description`/`ocr_blocks` — дословный выход
  анализатора MCA-19 (канал `untrusted_image_data` сохранён).
- **Bounded latency** (L59): и проба capability (≤8 с), и анализ ограничены
  `IMAGE_POSTGEN_VISION_TIMEOUT_SECONDS` (default 20 с, env-only ClassVar,
  min 0.05). Исчерпание бюджета → `pending`/`deadline_exceeded`; ни генерация,
  ни доставка, ни ход не блокируются и не отменяются.
- **Дедуп** (L61): кеш исходов `(chat_id, sha256(bytes))`, TTL 15 минут,
  ≤64 записей; повторная обработка тех же bytes в том же чате не оплачивает
  vision повторно (cache hit — без события расхода). Кросс-чат-кеш запрещён
  (TH-5): ключ включает chat scope. Повторный tool call гасится существующим
  маркером `image_request_handled` → `skipped:already_handled`; replay
  (`reason="already"`) не анализируется в обоих путях.
- **Киль-свитч** `IMAGE_POSTGEN_VISION_ENABLED` (env-only, default ON):
  OFF → ни вызовов, ни новых полей — блок/JSON байт-в-байт прежние
  (доказано `test_kill_switch_off_byte_parity` и probe).
- **R17**: логи/события — только статус/код/размер/ms; bytes, base64, OCR и
  описания в логи не попадают (OCR живёт только в контексте Writer-а).

## Семантика статусов исхода (Writer)

| status | значение | право Writer-а |
|---|---|---|
| `ready` | реально распознанный финальный bitmap | описывать содержание ТОЛЬКО по данным этого блока |
| `no_text` | анализ прошёл, текста/описания нет | содержание не досочинять |
| `off` / `pending` / `rate_limited` / `unavailable` / `failed` / `unreadable` | подтверждённого визуального результата нет | короткое подтверждение отправки; содержания не утверждать |

Статусы `off/pending/...` передаются в контекст (а не просто отсутствуют),
чтобы Writer-у был явно виден запрет на описание, а не «догадка по молчанию».

## Совместимость и откаты

- Direct-блок сохраняет префикс `<image_result status="ok" delivery="sent">`
  и прежние строки (контракты существующих тестов/probes не сломаны:
  `test_cfg02b`, `test_soul1_capability_*`, `agent-checks-w2`).
- Tool JSON: аддитивное поле; при OFF-рубильнике контура — прежний payload.
- Откат: env `IMAGE_POSTGEN_VISION_ENABLED=false` (мгновенный, без рестарта
  деплоя — резолв per-call); холодный откат — revert кандидата.
- Каталог параметров: Δ = 0 (ClassVar, в `param_catalog` не входят).
