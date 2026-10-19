# VISION-ADAPT (КОРР №2) — карта директивы, RED→GREEN, метрики

Кандидат (worktree, БЕЗ коммита — на ревью). База: HEAD `61ecd034` + дельта
этого лейна (КОРР №2). Чужие CFG-03-файлы не тронуты. Прод/SSH — нет.

## Файлы и sha12 (после NF-FIX, `nf-fix.md`)

| файл | sha12 | изменение |
|---|---|---|
| `services/image_normalize.py` | `b4f9f7a95d6d` | единый поэтапный механизм + NF-1: `prefer_png` только при Pillow, `_encode_png` fail-open, `_png_has_transparency` (stdlib) для PNG-альфы на ffmpeg, GIF/WebP на ffmpeg — пропуск; dead `aggressive`/`encode` удалены |
| `services/mca_vision.py` | `a768eac7387b` | `analyze_adaptive` без segments + NF-2: 400 ретраится только при подтверждённом image-классе (`/image_rejected`, `/size`, `/pixels`, `/format`), 413/415/422 — по статусу; комментарий job-пути очищен |
| `services/postgen_vision.py` | `232e65a4af41` | делегирование `analyze_adaptive`; докстринг очищен от `segments` |
| `config/settings.py` | `7e6d7ff4a527` | `REQUEST_MAX_BYTES` 0=неизвестен; `NORMALIZE_MAX_DIMENSION` 0=без потолка; ручка `SEGMENT_TRIGGER_RATIO` удалена |
| `tests/test_vision_adapt.py` | `24f007fdd91e` | 43 теста (КОРР №2 + NF-1/NF-2: прод-бэкенд без Pillow, батарея «никогда не бросает», класс-гейт 400) |

## Директива КОРР №2 → реализация → тесты

| # | требование | где | тесты |
|---|---|---|---|
| 1 | отменить классификацию контента и эвристики формы; `h≥2×w → segments` убрать | `plan_vision` (нет ветки формы), `analyze_adaptive` (нет segments) | `test_shape_does_not_affect_decision`, `test_no_segments_strategy_for_long_heavy`, `test_pipeline_never_calls_fragmentation` |
| 1b | утилиты фрагментации оставить, не удалять | `segment_plan`/`plan_segments`/`crop_to_jpeg`/`merge_segment_analyses`/`dedup_lines` | `TestFragmentUtilities` (3 теста) |
| 2 | решение — только MIME/размер/пиксели/payload/лимиты/ответ | `plan_vision`, `classify_rejection`, `detail` | `TestPlanStrategy` (7), `test_rejection_classes_from_response`, `test_detail_carries_rejection_class` |
| 3 | Этап A (вес без ресайза) + гарды; Этап B без жёсткого 1024, bounded | `optimize_to_fit` (`_source_flags`, `_encode_png`, `ImageOps.exif_transpose`, бюджетный масштаб ≤3 попыток) | `TestStageA` (4), `TestStageB` (3) |
| 4 | лимит неизвестен → оригинал, адаптация по ответу | `VisionLimits.budget_known`, `plan_vision` | `test_unknown_budget_sends_original`, `test_unknown_budget_tries_original_first` |
| 5 | retry ≤1 только size/format; 401/403/429/сеть — без повтора; повторный отказ — честно | `_retryable_provider_rejection`, `_adaptive_retry` | `TestAdaptiveRetry` (6: 400→меньшая копия; 500/429/401 — 1 вызов; сеть — 1 вызов; нет идентичного повтора) |
| 6 | гарантии: 0 перекодирований при допустимом оригинале; оригинал неизменен; копия не подменяет оригинал | `plan_vision` (original), вход не мутируется | `test_original_when_fits_and_no_codec_touch`, `test_original_single_call_byte_parity`, `test_optimized_copy_never_replaces_original` |
| 7 | метрики 7 кейсов без фрагментации; «200, но текст потерян» ≠ успех | `TestFixtureMetrics`, `metrics.json` | `test_fixture_set_metrics_and_honesty`, `test_negative_accepted_but_text_lost` |

## RED → GREEN (КОРР №2)

- RED (`red-korr2.txt`): **9 failed / 22 passed** — старый код ещё сегментировал
  по форме, не поддерживал unknown-budget и гарды Этапа A.
- GREEN (`green-korr2.txt`): **32 passed**.
- Кластер (`green-cluster.txt`): **1163 passed** — 43 файла (vision-adapt,
  postgen-diag, addtr-postgen, mca19 A–G, rework, p0v-core, vision-dl,
  media/download, mca23, unified-image, image-generation, cfg02a/b, soul1,
  image-context, tool-router/loop/schemas, entry-caption, mca11, addtr-tools).

## Метрики 7 кейсов (`metrics.json`, без авто-фрагментации)

| кейс | status | calls | OCR | ms | sent chars |
|---|---|---|---|---|---|
| long_screenshot (24 строки, 800×2880, PNG 3 МБ) | ready | 1 (A→B) | **1.0 (24/24)** | 110 | 876 419 |
| meme | ready | 1 (оригинал) | **1.0 (4/4)** | 0 | 42 775 |
| large_photo (3000×2200) | ready | 1 (A→B) | — | 171 | 612 959 |
| large_photo + строгий провайдер (413) | ready | 2 (retry ≤1) | — | 172 | 612 959 → 244 755 |
| tiff_document | ready | 1 (декод-фоллбэк) | — | 0 | 23 663 |
| fillbyte_jpeg | ready | 1 | — | 0 | 867 |
| small_photo | ready | 1 (оригинал) | — | 0 | 390 883 |

- **analysis_delivered_rate = 1.0**, **honesty_rate = 1.0**; запросов **8 на
  7 кейсов** (единственный доп. — bounded retry у строгого провайдера);
  max latency (моки) 172 мс.
- Честность «200, но текст потерян»: негативный тест (бюджет 200 КБ → глубокое
  сжатие) — строки не выдумываются, покрытие неполное; метрика OCR — по
  строкам ground truth.

## Что остаётся на живой путь (после выката; 1 генерация — по согласованию)

- Реальная латентность/доля успеха и фактический OCR длинного скриншота —
  по `[vision] adapt | …` и событию `vision_adapt` в проде.
- Калибровка `MCA_VISION_REQUEST_MAX_BYTES`/`PREP_MAX_PIXELS` под фактического
  провайдера (ручки есть; 0 = «лимит неизвестен» → оригинал + адаптация).
- Реальный TIFF/HEIC-документ → класс в `detail` (декод-фоллбэк/честный отказ).
