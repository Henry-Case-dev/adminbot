# VISION-ADAPT — NF-FIX (по вердикту REV-VISION-ADAPT = Needs Fixes `57f3ffe4`)

Кандидат: worktree поверх HEAD (без коммита). Фиксы строго по ревью
(`plans/features/p0-vision-universal/review-vision-adapt.md`), чужие файлы
(ADD-EXP-WIP, CFG-03) не тронуты. Прод/SSH — нет.

## NF-1 (High) — PNG-путь на прод-бэкенде (ffmpeg без Pillow)

**Было (воспроизведено зондом, `nf-probe-before` = вывод до фикса):**
`optimize_to_fit(long_png)` → `ModuleNotFoundError` (в `_encode_png` жёсткий
`from PIL import Image`); `analyze_adaptive` → исключение (нарушение контракта
«никогда не бросает»), job → `vision_failed`; анимированный GIF молча
«сплющивался» в один JPEG-кадр.

**Стало (фикс, `services/image_normalize.py`):**
1. `prefer_png = pillow and transparent` — PNG-ветка включается ТОЛЬКО когда
   Pillow реально доступен (`codec_available() == "pillow"`).
2. `_encode_png` — fail-open: `try: from PIL import Image, ImageOps /
   except Exception: return None` + внешний `try/except` на весь энкод
   (никогда не бросает).
3. Без Pillow (ffmpeg-бэкенд): `image/gif` и `image/webp` → пропуск
   оптимизации (анимацию не подтвердить декодером — не «сплющиваем»);
   `image/png` с альфой → пропуск, причём прозрачность определяется БЕЗ
   декодера — `_png_has_transparency()` (stdlib: color type 4/6 в IHDR или
   tRNS-чанк, bounded-скан); непрозрачный PNG → обычный JPEG-путь (Этап A/B
   работает и на ffmpeg).
4. `_source_flags`-докстринг уточнён (без Pillow → (False, False); остальные
   гарды — без декодера).

**Подтверждение зондом (PIL заблокирован, codec=ffmpeg), `nf-probe-after.txt`:**
```
NF1 optimize_to_fit(long_png):        OK -> (642015, image/jpeg 720x2592)
NF1 optimize_to_fit(transparent_png): OK -> None          (без JPEG-флаттенинга)
NF1 optimize_to_fit(animated_gif):    OK -> None          (анимация не сплющена)
NF1 analyze_adaptive(long_png):       OK ready calls 1    (исключений нет)
```

## NF-2 (Medium) — произвольный 400 ретраился

**Было:** `_retryable_provider_rejection` = `startswith("http_400")` без класса;
зонд: bare-400 («unknown parameter»), 400 «model_not_found», 400 «context
length» → по 2 вызова.

**Стало (`services/mca_vision.py`):**
```
413/415/422 → retry (по статусу);
400 → retry ТОЛЬКО при подтверждённом классе проблемы изображения
      (/image_rejected, /size, /pixels, /format из detail, т.е. из
      classify_rejection);
прочие 400 (bare/model_not_found/context/unknown parameter), 401/403/429/5xx,
сеть → без повтора.
```
**Подтверждение зондом:** bare-400 → **1** вызов; model_not_found → **1**;
context → **1**; «image too large» (класс `/pixels`) → 2 (retry ≤1); 413 → 2.

## Сопутствующее (в том же фикс-поезде)

- Комментарий `process_asset_job` и докстринг `postgen_vision._analyze_uncached`
  очищены от упоминаний `segments`/«фрагментируются» (КОРР №2).
- Мёртвый параметр `aggressive` удалён из `optimize_to_fit(_async)`; неиспользуемая
  переменная `encode` удалена.
- Докстринг `optimize_to_fit` уточнён: «меньше оригинала» гарантируется для
  известных снифферу форматов; на sniffed-None (декод-фоллбэк) — без гарантии,
  проверка на вызывающем.

## Тесты (RED → GREEN)

- Новые тесты (RED до фикса — `red-nf.txt`: **9 failed / 34 passed**):
  * `TestProdBackendNoPillow` (6): длинный PNG без исключения; непрозрачный PNG
    → JPEG-копия; прозрачный PNG → None; анимированный GIF → None;
    `analyze_adaptive` без краха (job доходит); батарея «никогда не бросает»
    (8 входов × оба бэкенда).
  * `TestRetryClassGate` (3 параметра + 2): bare-400/model_not_found/context →
    1 вызов; «image too large» → 2 (retry); bare-413 → 2 (retry).
- GREEN: `green-nf.txt` — **43 passed** (32 прежних + 11 новых/параметров).
- Постген-наборы (review-группа): `test_postgen_diag + test_addtr_postgen +
  test_p0_vision_fix_core + test_vision_dl_fix` — **113 passed**.
- Кластер-спот (23 файла: adapt/postgen/mca19 A–G/rework/unified-image/
  image-gen/image-context/cfg02a/b/soul1/tool/entry) — **765 passed**
  (`green-cluster.txt`).

## Инвариант «никогда не бросает»

Подтверждён двумя независимыми способами: (1) тест
`test_invariant_never_raises_battery` — 8 враждебных входов (пусто, мусор,
длинный PNG, прозрачный PNG, GIF, TIFF, fill-JPEG, мелкий JPEG) на обоих
бэкендах (Pillow и ffmpeg) → `optimize_to_fit` возвращает `bytes | None`, без
исключений; (2) зонд на симулированном прод-бэкенде (PIL заблокирован) —
`analyze_adaptive` завершается `ready` за 1 запрос вместо падения.

## sha12 после фикса

| файл | было | стало |
|---|---|---|
| `services/image_normalize.py` | `5605a0aaab94` | `b4f9f7a95d6d` |
| `services/mca_vision.py` | `d411392f9193` | `a768eac7387b` |
| `services/postgen_vision.py` | `e1256652e34c` | `232e65a4af41` |
| `config/settings.py` | `7e6d7ff4a527` | `7e6d7ff4a527` (без изменений) |
| `tests/test_vision_adapt.py` | `76d6663a4b8a` | `24f007fdd91e` |

## Остаток на live

Без изменений от `korr2.md`: реальная латентность/доля успеха/фактический OCR
длинного скриншота и фактический кодек прод-venv (DevOps-чек `import PIL`) —
postdeploy-проверки агентами (PET, owner-гейт не нужен); калибровка
`REQUEST_MAX_BYTES`/`PREP_MAX_PIXELS` — по факту живых ответов.
