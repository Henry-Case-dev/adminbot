# VISION-ADAPT (КОРР №2) — design note: единый поэтапный preprocessing

Директива владельца №2 (упрощение): без классификации контента и формы; без
обязательной фрагментации в обычном пути; единый поэтапный механизм для всех
входов; лимиты — провайдер-агностичные; retry ≤1 только на подтверждённый
size/format-отказ; оригинал неизменен; честная ошибка вместо «успеха» с
плохим распознаванием.

## Модель лимитов (провайдер-агностично, всё конфигурируемо)

| класс | ручка (settings/env) | дефолт | роль |
|---|---|---|---|
| bytes | `MCA_VISION_REQUEST_MAX_BYTES` | 700 000 | бюджет СЫРЫХ байт запроса (payload ≈ ×4/3); **0 = лимит неизвестен** |
| pixels | `MCA_VISION_PREP_MAX_PIXELS` | 4 000 000 | мягкий потолок пикселей подготовленной копии |
| pixels (hard) | `MCA_VISION_MAX_PIXELS` | 25 000 000 | bomb-guard (не менялся) |
| format | `SUPPORTED_PROVIDER_MIMES` | jpeg/png/gif/webp | остальное — декод-фоллбэк (TIFF → JPEG) |
| context/size/pixels/format (ответ) | `classify_rejection()` | — | класс отказа из семантики ответа (R17-safe) |
| ceiling (опция) | `MCA_VISION_NORMALIZE_MAX_DIMENSION` | **0 = без потолка** | необязательный потолок копии (никакого жёсткого 1024) |
| budget | `MCA_VISION_ADAPT_BUDGET_SECONDS` | 90 c | общий bounded-бюджет анализа |
| утилита фрагментации | `VISION_IMAGE_MAX_DIMENSION`, `MCA_VISION_SEGMENT_MAX`, `MCA_VISION_SEGMENT_OVERLAP_RATIO` | 1600 / 8 / 0.12 | параметры НЕ-дефолтной утилиты `segment_plan` |

## Решение (только от MIME/размера/пикселей/payload/лимитов)

```
payload_chars = len(data)×4/3 + 256 ; pixels = w×h
fits = payload ≤ бюджет ∧ pixels ≤ prep_max_pixels ∧ mime ok
normalize OFF → original
лимит неизвестен (REQUEST_MAX_BYTES=0) → original  (адаптация по факт. ответу)
fits → original (0 перекодирований)
иначе → optimize (Этап A → Этап B)
```
Форма/контент (длинный/квадратный, фото/мем/скриншот) в решении НЕ участвуют.

## Этапы

- **Этап A** — уменьшение веса без изменения разрешения: перекодирование
  (JPEG q85; PNG `optimize` для прозрачных источников). Гарды: копия не меньше
  оригинала → не перекодируем; прозрачность (RGBA/LA/P+transparency) → PNG, не
  JPEG; анимация (`n_frames>1`) → оптимизация пропускается; ориентация EXIF →
  `ImageOps.exif_transpose` (baked), чтобы поворот не потерялся.
- **Этап B** — постепенный ресайз: масштаб от фактического payload
  (`scale ×= clamp(sqrt(budget/current), 0.35..0.9)`), ≤3 попыток, пропорции,
  floor `MIN_DIMENSION=256`, ограничение `prep_max_pixels` и необязательного
  потолка; максимум разрешения в рамках лимитов (без 1024-капа).
- **Retry ≤1** (`mca_vision`): только при `detail` = 400/413/415/422 или
  явном image/size/format-классе; копия строго меньше отправленной (×0.7 →
  ×0.5 от стороны); остаток бюджета ≥3 c; 401/403/429/сеть/прочие 400 — без
  повтора; повторный отказ → `VisionError` с `detail` (честная диагностика).

## Пути применения

- Входящие (photo/document, мемы, скриншоты): `process_asset_job` →
  `analyze_adaptive`; `recognize_image` → `recognize_target` → тот же путь.
- Пост-генерация: `postgen_vision` → `validate_or_normalize` →
  `analyze_adaptive` (контракт статусов/`detail`/дедуп сохранён).
- Вход: `download_telegram_file`/`fetch_external_image` → `validate_or_normalize`
  (декод-фоллбэк; валидные входы — байт-в-байт, без перекодирования).

## Утилиты (НЕ дефолтный путь, сохранены)

`mca_vision.plan_segments` / `dedup_lines` / `merge_segment_analyses`,
`image_normalize.segment_plan` / `crop_to_jpeg(_async)` — вызываются только
явно; в обычном распознавании не участвуют (тест
`test_pipeline_never_calls_fragmentation` это фиксирует).

## Наблюдаемость и честность

- Лог `[vision] adapt | strategy=… | reason=… | calls=… | status=… | bytes=…
  | pixels=… | ms=…`; событие `vision_adapt` (`error_json={strategy, reason,
  calls, error}`) — R17-safe.
- «200, но текст потерян» — метрика честности (OCR по строкам ground truth),
  а не «успех»; негативный тест и харнесс это фиксируют.
- Оригинал неизменен: вход не мутируется, копия не подменяет оригинал
  (тесты `test_original_single_call_byte_parity`,
  `test_optimized_copy_never_replaces_original`).

## Метрики после упрощения

См. `korr2.md` (7 кейсов, без фрагментации): analysis_delivered 1.0,
honesty 1.0, длинный скриншот 24/24 строк через A→B за 1 запрос (876 419
chars, 110 мс), единственный доп. запрос — bounded retry у строгого
провайдера (413).
