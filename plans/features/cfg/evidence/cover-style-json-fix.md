# Cover Style Edit: почему вторая попытка падала в bad_json (issue 90)

## Факт из прод-лога (2.58.128)

```
2026-10-24 19:11:17 COVER_STYLE_SUBMITTED prompt_len=968 edit_route=image_api model=qwen-image-3-pro
2026-10-24 19:11:19 [cover_style_edit] provider 400 ... classified=prompt_limit
2026-10-24 19:11:19 edit failed reason=prompt_limit
2026-10-24 19:11:19 COVER_STYLE_SUBMITTED prompt_len=759 status=retry
2026-10-24 19:14:22 edit failed ... reason_class=bad_json reason=bad_json latency_ms=183239
2026-10-24 19:14:22 COVER_STYLE_FAILED reason=bad_json fallback=style_failed
2026-10-24 19:14:24 PUBLISH_RICH_COMPLETE message_id=1175182 status=degraded
```

- Первая попытка 968 симв. → провайдер 400 «prompt is too long for Qwen
  Image 3 Pro», классифицировано `prompt_limit`.
- Retry 759 симв. → 2xx через 183 c (нормальное время рендера), но
  `_extract()` ждал только `data[0].b64_json` или `data[0].url`; ответ не
  совпал (бинарный `image/*` или иной JSON-конверт) → `bad_json`.
- `bad_json` не transient → повтор не выполнялся; стадия стиля завершилась
  fail-soft, опубликована Base-обложка, статья ушла RichMessage.

Точный content-type/тело 2xx не логировались — это отдельный дефект
диагностики.

## Исправление

`services/cover_style_edit.py`:
- `_extract()` принимает:
  * бинарный 2xx с `content-type: image/*` или magic bytes PNG/JPEG/WebP/GIF;
  * `data[0].b64_json`/`b64`/`image_base64`;
  * `url`/`image_url`/`image`;
  * конверты `data/output/images/result` (dict/list/str, включая data URL).
- `_download()` принимает те же конверты, не падает на dict-моках.
- Для неразобранного 2xx пишется R17-safe `response_diag`: status,
  content-type, body_len, имена верхних JSON-ключей, request_id. Без тела,
  байтов, промптов и ключей.
- `cover_style_jobs` сохраняет `provider_meta` (route/provider_error/
  response_diag/prompt_limit/prompt_limit_unknown) в job meta — причина
  видна в аналитике.

## Тесты

`tests/test_cover_style_edit_extract.py` — 9 тестов: binary CT, binary magic,
b64, url, output/images, empty data, `edit_image` binary success, safe
diagnostics. Профильный набор `cover_style/cover_prompt/extra_cover/asap4`
— 79 passed.

## Остаток

- Первая попытка **5/5** за 30 ч получает 400 prompt-limit: компилятор
  систематически выше лимита qwen-image-3-pro. Это отдельная оптимизация
  (safe ceiling/персист learned limit), не причина `bad_json`; после фикса
  retry должен опубликовать styled cover, но первый paid call всё ещё
  тратится.
- Точный конверт ответа провайдера остаётся неизвестным; фикс покрывает
  наблюдаемые варианты, диагностика покажет факт при следующем сбое.
