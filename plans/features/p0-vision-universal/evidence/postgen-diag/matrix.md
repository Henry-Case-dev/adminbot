# POSTGEN-DIAG — диагноз `vision_failed`/`vision_unreadable` и минимальный фикс

Кандидат (worktree, БЕЗ коммита — на ревью). Вход: ACCEPTANCE-94
(`plans/features/p0-vision-universal/evidence/release-25894/acceptance/`,
коммит `5125bfa2`), прод 2.58.94 = `70659be3` (мой POSTGEN-коммит `948c2004`
входит в него).

## 1. Точная причина `image_postgen_vision=failed/vision_failed`

**Ветка кода** (`services/postgen_vision.py` → `mca_vision.analyze_image_bytes`):

```
analyze_image_bytes: non-2xx (≠401/403/429) → VisionError("vision_failed",
                     f"http_{status}")          ← ЭТА ветка
postgen_vision:      _REASON_TO_STATUS → status=failed, reason=vision_failed
```

Доказательства (цепочка, без домыслов):

1. **Локальный гейт пройден** — не наш валидатор: репродукция 908723 B /
   2042378 B JPEG → `sniff_image`/`validate_image_bytes` = OK (repro.json,
   кейсы `jpeg_939k_1024`, `jpeg_1_6m_1536`). Значит, `vision_unreadable`
   исключён.
2. **Таймаут исключён**: событие `image_postgen_vision` в 1792401074 при
   `IMAGE_GENERATION_COMPLETE` 1792401072.132 — ≤1.9 c на весь контур;
   наш bounded-timeout дал бы `pending/deadline_exceeded`, а не `failed`.
3. **Провайдер-ошибка, а не локальное исключение**: harness ACCEPTANCE-94
   ставит spy на `mca_vision._default_transport` (`accept94_base.py:474-481`)
   и сохраняет `vision_transport_calls` (`e-economics.json`) = **2** на весь
   прогон в harness-процессе. Ожидаемые вызовы в этом процессе:
   b1 — auto-проба capability (1 вызов; image-ступень 2xx, т.к. recognition
   в b1 = ready) + пост-генерационный анализ b2 (1 вызов). Итого 2 ⇒ **вызов
   b2 ДОШЁЛ до провайдера** и получил non-2xx; worker-анализ b1 шёл в
   процессе бота (worker в harness не стартует: `accept94_base.py:358`) и в
   счётчик не входит.
4. **Провайдер был жив и совместим**: b1 (131641 B JPEG, тот же chat/model
   `nvidia/nemotron-3.5-super-vl:free`, 40 c раньше) → ready с описанием.
   Отличие b2 — «тяжёлый» payload (939495 B → base64 ≈1.21 MB; см. repro:
   `image_b64_chars=1211655`).
5. **Маскировка**: в прод-событии/outcome оставался только `reason_code=
   vision_failed` — `VisionError.detail` (`http_<status>` + семантика ответа)
   нигде не сохранялся; журнал-фильтр ACCEPTANCE-94 ловил строки по «[vision]»,
   а мой лог шёл с префиксом «[postgen]» → строка `[postgen] vision | …`
   не попала в срез журнала. Это и есть «no class» в диагностике.

Итоговый класс: **провайдерский non-2xx на тяжёлом payload** (наиболее
вероятно 400/413 image-class: «image too large»/«invalid image»); точный
HTTP-статус в эвиденсе не сохранён — фикс делает его наблюдаемым.

## 2. Точный класс `vision_unreadable` (VISION_DL_STAGE=6)

Ветка: `download_telegram_file → validate_image_bytes` → `VisionError(
"vision_unreadable", detail)`; `detail` терялся на `_finish_analysis_or_job`
→ stage-событие `download/failed` без класса.

Репродукция (repro.json) дала воспроизводимый **ложный отказ на реальном
формате**:

| кейс | sniff | validate | Pillow | класс |
|---|---|---|---|---|
| JPEG с fill-байтом 0xFF перед SOF (легально по спеке) | **None (ложно)** | `vision_unreadable` | OK (декодирует) | **дефект сниффера** |
| TIFF (документ-фото) | None | `vision_unreadable` | OK | формат не поддержан |
| HEIC-магия | None | `vision_unreadable` | FAIL (нет декодера) | честный unsupported |
| усечённый JPEG (4 КБ из 512×512) | OK (по заголовку) | OK | FAIL | sniff-обманка (не ретраится) |
| WebP / PNG / обычный JPEG | OK | OK | OK | штатно |

Причина десинхронизации скана JPEG: fill-байты `0xFF 0xFF` (легальны)
трактовались как «маркер 0xFF» → длина сегмента читалась из следующих байтов
→ прыжок за EOF → `None`. Это и есть кандидат на прод-класс «реальные фото:
декод/формат».

## 3. Что изменено (по фактам, минимально)

| файл | sha12 | изменение |
|---|---|---|
| `services/mca_vision.py` | `88f777b09dba` | (a) сниффер JPEG: пропуск fill-байтов 0xFF; (b) `analyze_image_bytes`: `detail=http_<status>` + R17-safe класс ответа (`/image_rejected`, `/modality_refused`, `/model_missing`); (c) новый `validate_or_normalize` (декод-фоллбэк); (d) `download_telegram_file`/`fetch_external_image` используют его; (e) `detail` доезжает до stage-события (`_finish_analysis_or_job(..., detail=)` → `error_json`) |
| `services/image_normalize.py` (new) | `6d847987b273` | bounded нормализатор bytes→JPEG: кодек из окружения (Pillow → иначе ffmpeg через bounded temp-файл), потолок стороны, pixel-guard, fail-open, R17 (только размеры) |
| `services/postgen_vision.py` | `64b349b0bea7` | `PostgenVisionOutcome.detail`; `validate_or_normalize` на входе; РОВНО один bounded retry с нормализованным меньшим JPEG на image-class 400/413/415/422 (в остатке бюджета, ≥3 c); лог-префикс `[vision] postgen` (попадает в журнал-фильтры); `error_json.detail` в событии; generic-исключение → detail=класс |
| `config/settings.py` | `0b61b24a95c7` | env-only `MCA_VISION_NORMALIZE_ENABLED` (default ON) + `MCA_VISION_NORMALIZE_MAX_DIMENSION` (1024, min 64) |
| `tests/test_postgen_diag.py` (new) | `9084477b46e9` | 27 тестов: REGRESSION (fill-байты; маскировка провайдер-ошибок) + CONTRACT (нормализатор, фоллбэк, retry, kill-switch, лог-префикс) |

Не второй pipeline: провайдер/route/анализатор/лимиты — те же MCA-19;
нормализация — bounded ресайз/перекодировка того же кадра (retry только по
image-class отказу и только строго меньшим payload).

## 4. RED → GREEN

- RED (`red.txt`): 25 failed (контура/полей/retry нет; fill-байт JPEG
  отвергается; detail не сохраняется). Два тест-сайд дефекта, найденных при
  GREEN-итерации (стаб route-конфига; мок generic-исключения), исправлены в
  тестах — код фикса не ослаблялся.
- GREEN (`green.txt`): **27 passed**.
- GREEN-кластер (`green-cluster.txt`): **1131 passed** — 41 файл
  (postgen/mca19-блоки A–G/rework/p0v-core/vision-dl/media-download/media/
  native-media/mca23/unified-image/image-generation/cfg02a/cfg02b/soul1/
  image-context/tool-router/tool-loop/tool-schemas/entry-caption/mca11/
  addtr-tools).
- E2E-зонд (`e2e-probe.txt`): реальный direct pre-gate —
  (1) TIFF-исходник → фоллбэк → `<image_analysis status="ready">`;
  (2) провайдер 400 → retry: payload 361091 → 927 chars → ready;
  (3) провайдер 500 → честный `failed`, 1 вызов, `error_json.detail=http_500`.
- Репродукция (`repro.json`/`repro-output.txt`): 200→ready; 400→`http_400/
  image_rejected` (2 вызова, payload 1.21M→0.67M); 413/422→retry; 500/502→без
  retry, detail сохранён; 429→rate_limited; 401→unavailable; timeout/transport
  →unavailable с классом.

## 5. Внешний (чужой) дельта-шум в прогонах

- `tests/test_round1025_f8_registry.py` падает на пинах `param_catalog.py`
  и TSV — в дереве лежит **незакоммиченная дельта лейна CFG-03**
  (`services/param_catalog.py`, `plans/docs/param-registry-round1025.*`,
  `tests/test_round1025_f8_registry.py` правлен ими же). Доказательство:
  `git show HEAD:services/param_catalog.py` sha256[:12] = `ad109003b936` ==
  пин теста; диск = `c17e43c6c09c` (их правка). Файл F8 исключён из кластера
  выше; не мой scope.
- Один transient-прогон дал `test_cfg02b::test_catalog_keys_shapes`
  (`spec.type='float'` для `limits.image_freq_limit_cooldown_seconds`) — не
  воспроизводится (5+ повторов, включая тот же полный список → 1131 passed);
  относится к тому же чужому in-flight `param_catalog.py`. Зафиксировано
  честно, к моему диффу не относится (я `param_catalog.py` не трогал).

## 6. Остаток на живой повтор (по согласованию с владельцем)

- Одна живая генерация: в журнале ожидаем `[vision] postgen | … | detail=…`
  (или `error_json.detail` в событии) — точный HTTP-статус провайдера станет
  виден; при image-class 400 — ожидаем `retry` и (при успехе) `status=ready`
  с описанием ФАКТИЧЕСКОГО bitmap.
- Incoming-класс: следующая неудача `download` покажет `detail` в stage-событии
  (`empty image` / `not a supported raster image` / `unsupported format …` /
  `image exceeds …`) — точная ветка перестанет быть «без класса».
- Прод-venv: ffmpeg-бэкенд — прод-вероятный (видео-контур); если ffmpeg в
  prod отсутствует, фоллбэк деградирует честно (detail + прежний отказ),
  локально проверен оба бэкенда (Pillow и ffmpeg).
