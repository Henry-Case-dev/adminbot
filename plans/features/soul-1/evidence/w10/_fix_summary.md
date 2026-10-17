# W10 fix-pass (review-w10 F1–F5) — evidence

Источник: `plans/features/soul-1/review-w10.md`. Прогоны — реальный `DirectChatService` (L1-режим, моки только ввода/вывода), детектор — `services.direct_capabilities.detect_action_intent`.

## 1. Ложные генерации: BEFORE → AFTER

| case | текст | gen BEFORE | gen AFTER | verdict AFTER |
|---|---|---|---|---|
| f1_stem_art_flat | Бот, сделай уборку в квартире | 1 | 0 | — / none / no_action_intent |
| f1_stem_art_march | Бот, сделай план на март | 1 | 0 | — / none / no_action_intent |
| f1_stem_mem_memorial | Бот, сделай мемориальный пост про Петю | 1 | 0 | — / none / no_action_intent |
| f1_stem_art_flat2 | Бот, надо сделать уборку в квартире | 1 | 0 | — / none / no_action_intent |
| f2_self_draw | Бот, я сам нарисую мем, оценишь потом | 1 | 0 | — / none / create_image_self_action |
| f2_self_draw2 | Бот, подскажи идею мема, я сам нарисую | 1 | 0 | — / none / create_image_self_action |
| f2_quote | Бот, Петя сказал: нарисуй мем про двачеров | 1 | 0 | — / none / create_image_reported |
| f2_contradiction | Бот, нарисуй мем, но не рисуй | 1 | 0 | — / none / create_image_negated |
| f2_code_block | Бот, вот пример кода: ```python нарисуй мем про двачеров ``` | 1 | 0 | — / none / no_action_intent |
| f2_code_block_only | ``` Бот, нарисуй мем про двачеров ``` | 1 | 0 | — / none / no_action_intent |
| f2_forwarded | Бот, нарисуй мем про двачеров | 1 | 0 | — / none / create_image_forwarded |
| f2_longer_word | Бот, перерисуй схему в отчёте | 1 | 0 | — / none / no_action_intent |
| p1 | Бот, нарисуй мем про двачеров | 1 | 1 | create_image / high / create_image_command |
| p2 | Бот, сделай мем про двачеров | 1 | 1 | create_image / high / create_image_command |
| p3 | Бот, надо сделать мем про двачеров | 1 | 1 | create_image / high / create_image_command |
| p4 | Сделай картинку из этой ситуации | 1 | 1 | create_image / high / create_image_command |
| p5 | Нужна инфографика по этим данным | 1 | 1 | create_image / high / create_image_need |
| p6 | Давай изобразим это в виде комикса | 1 | 1 | create_image / high / create_image_command |
| p7 | Бот, нарисуй кота в шляпе | 1 | 1 | create_image / high / create_image_command |
| p8 | Бот, нарисуй | 1 | 1 | create_image / high / create_image_command |
| p9 | Бот, сгенерируй мем | 1 | 1 | create_image / high / create_image_command |
| p10 | Бот, создай картинку с котиком | 1 | 1 | create_image / high / create_image_command |
| p11 | Бот, нарисуй мем, если не сложно | 1 | 1 | create_image / high / create_image_command |
| p12 | Бот, перерисуй мем про двачеров | 1 | 1 | create_image / high / create_image_command |
| p13 | Бот, нарисуй мем про то, что Петя сказал вчера | 1 | 1 | create_image / high / create_image_command |

## 2. F3 (review-w10): shared-квота исчерпана, per-chat чистая

| комбинация | BEFORE | AFTER |
|---|---|---|
| global_exhausted_chat_clean | ready | quota_exhausted (image_shared_limit) |
| chat_exhausted_shared_clean | quota_exhausted | quota_exhausted (image_daily_limit) |
| both_clean | ready | ready (image_limit_ok) |

## 3. Пробы ревьюера на его harness (до/после)

* `probe4` (4 строки F1): gen [1, 1, 1, 1] → [0, 0, 0, 0]
* `probe2` (13 строк): файлы `_fix_reviewer_probe2_{before,after}.json` — все ложные 1→0, все настоящие остались по 1.
* `probe1` (25 строк): `_fix_reviewer_probe1_{before,after}.json` — изменились ровно 6 строк ложного семейства, остальные 19 без изменений.

## 4. Команды

```
.venv\Scripts\python.exe -m pytest OPENCODE_WORKFLOW_SCRATCH/w10-fix/probe_fix.py -q -s -p no:randomly
.venv\Scripts\python.exe -m pytest tests/test_soul1_capability_intent.py tests/test_soul1_capability_registry.py tests/test_soul1_capability_fallbacks.py -q -p no:randomly
.venv\Scripts\python.exe -m pytest -q -p no:randomly -p no:cacheprovider -k "image or direct or soul1 or tool_ or capability or asap7 or asap8 or mca or param or registry" tests
```

Итоги прогонов — в `_fix_w10_tests.txt`, `_fix_perimeter.txt`, `_fix_mutations.txt`, `_fix_detector_cost.txt`, `_fix_f3_demo.txt`.
