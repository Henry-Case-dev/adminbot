# REV-POSTGEN-DIAG — вердикт (диагностика/фикс пост-генерации Vision)

Независимое ревью. Read-only; этот коммит — только данный документ.

**Кандидат (uncommitted поверх `2462fdb9` = HEAD):** `services/image_normalize.py` (новый) sha256_12 `6d847987b273`; `services/mca_vision.py` `88f777b09dba`; `services/postgen_vision.py` `64b349b0bea7`; `config/settings.py` `0b61b24a95c7`; `tests/test_postgen_diag.py` (новый) `9084477b46e9`. Хеши сверены в дереве и в изолированном worktree.

## 1. Рут-цепочка — подтверждена
ACCEPTANCE-94 (evidence/release-25894): b1 `byte_size=131641` → ready; b2 `[image] generated … bytes=939495` (base64 ≈1.21 MB), 40 с позже — `image_postgen_vision ts=1792401074 outcome=failed reason_code=vision_failed`, при `IMAGE_GENERATION_COMPLETE ts=1792401072.132` (≤1.9 с — таймаут исключён); spy `vision_transport_calls=2` (`e-economics.json:315`, хук `accept94_base.py:477`) = проба b1 + пост-ген b2 ⇒ **вызов b2 дошёл до провайдера**; валидатор/декодер исключены локальной репродукцией (`repro.json`: 939K JPEG проходит sniff/validate). Маскировка: `VisionError.detail` не сохранялся, а лог шёл с префиксом `[postgen]` мимо журнал-фильтра `[vision]`. Класс: **провайдерский non-2xx на тяжёлом payload**.

## 2. Класс `vision_unreadable` — подтверждён и исправлен
Сниффер: пропуск легальных fill-байтов `0xFF` между маркерами (десинхронизация скана → ложный отказ на реальном JPEG); `validate_or_normalize` (только после `vision_unreadable`) — декод-фоллбэк (TIFF и пр.); `detail` теперь доезжает до stage-события (`_finish_analysis_or_job(..., detail=)` → `error_json`) — «6 unreadable без класса» больше не повторится.

## 3. image_normalize — подтверждено кодом
Pillow → иначе ffmpeg (bounded temp-файл: TIFF из pipe не читается — задокументировано и проверено), потолок стороны `MCA_VISION_NORMALIZE_MAX_DIMENSION`=1024 (без апскейла), pixel-guard `MCA_VISION_MAX_PIXELS`, fail-open (нет кодека/не декодируется/рубильник OFF → None), R17 (только кодек/размеры), `asyncio.to_thread` — event loop не блокируется. ffmpeg в проде вероятен (видео-контур); при отсутствии — честная деградация.

## 4. postgen retry — подтверждено (мой e2e-зонд)
Ровно один retry только на image-class отказ (400/413/415/422 или явный `/image_rejected`), только при **строго меньшем** payload и остатке бюджета ≥3 с; общий deadline обеих попыток; финальный отказ несёт detail последней попытки. 500 → честный `failed` без retry. `detail` — в outcome, событии (`error_json`), логе с префиксом `[vision] postgen`. Мой зонд: TIFF → fallback → `image/jpeg 8×8` (rescue); 400 → retry → ready, calls=2, payloads `[40867 → 17247]` (строго меньше); 500 → `failed vision_failed http_500`, calls=1 — совпадает с `e2e-probe.txt`.

## 5. Тесты — перепрогнаны
- GREEN нового файла: **27/27** (`py -3` — как в evidence; нюанс среды: в `.venv` нет PIL → 26+1 skip, поэтому канонический интерпретатор — глобальный `py -3`).
- RED: архивный **25f** — 25-тестовая редакция (состав сверен: 3 sniff + 4 normalizer + 5 validate + 6 provider + 6 retry + 1 log); мой прогон финальной редакции без модуля и без кода — **24f/3p** (расхождение объяснимо: +2 ffmpeg-теста добавлены после RED; 3 parity-теста проходят и на базе).
- Кластер-спот (18 файлов: postgen/mca19 A–G/rework/p0v-core/vision-dl/media_download/tool-router/tool-schemas/addtr-tools/entry/unified-image/image-generation): **418 passed, 0 failed**. Полный 41-файловый кластер (1131) буквально не сверяем — список файлов в evidence не зафиксирован (нюанс, не блокер).

## 6. Дисциплина
Периметр = 5 файлов + evidence; чужая незакоммиченная CFG-03-дельта (`services/param_catalog.py`, `plans/docs/param-registry-round1025.tsv`, `tests/test_round1025_f8_registry.py`) **не тронута**; f8-шум доказанно чужой: `git show HEAD:services/param_catalog.py` sha12 `ad109003b936` == пин теста, диск отличается (их in-flight правка). Мой коммит — только вердикт.

## Леджеру (рекомендация)
- `P0V-PIPE-CONTEXT` (и связанные пост-ген строки): остаются **READY_FOR_LIVE** до живого повтора с одной генерацией — в журнале ожидаем `[vision] postgen | … | detail=…` (или `error_json.detail`); при image-class 400 — `retry` и (при успехе) `ready` с описанием фактического bitmap.
- Observability-note: новый класс `[vision] postgen detail` + `error_json.detail` в событиях (маскировка прод-класса устранена); incoming-класс также виден в stage-событии.
- Постген-строки add-tr — закрывать по своим критериям после live.

## Вердикт
**Approved.** Рут доказан прод-фактами, фикс минимальный и bounded (без второго пайплайна), RED/GREEN и e2e воспроизведены, дисциплина чистая; live-половина — postdeploy.
