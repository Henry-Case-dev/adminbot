# REV-VISION-ADAPT — вердикт (адаптивный preprocessing Vision, КОРР №2)

Независимое ревью кандидата целиком (первая версия + упрощение по КОРР №2).
Read-only по коду; этот коммит — только данный документ.

**Кандидат (uncommitted поверх `df078406` = HEAD):** `services/image_normalize.py`
sha256_12 `5605a0aaab94`; `services/mca_vision.py` `d411392f9193`;
`services/postgen_vision.py` `e1256652e34c`; `config/settings.py` `7e6d7ff4a527`;
`tests/test_vision_adapt.py` `76d6663a4b8a`. `evidence/adapt/candidate-diff.patch`
байт-в-байт == `git diff HEAD` по 4 tracked-файлам (сверено мной; sha совпал).
Параллельный ADD-EXP-WIP в worktree (`services/direct_chat_service.py` и др.)
в дельту кандидата не входит; коммитить только `--only`.

## Проверки 1–11 (код + мои прогоны, не по отчёту)

1. **Удаление веток — подтверждено.** `long_enough`/`segment_trigger`/
   `strategy == "segments"`/`DOWNSCALE_STEPS`/`fallback_max_dimension`/
   `MCA_VISION_SEGMENT_TRIGGER_RATIO` в services отсутствуют (grep);
   утилиты `plan_segments`/`dedup_lines`/`merge_segment_analyses`/
   `segment_plan`/`crop_to_jpeg(_async)` сохранены; из дефолтного пути не
   вызываются (единственные ссылки — определения + тесты; pipeline-хиты
   `segment_plan` в `pipeline_events/analytics` — чужой summary-контур).
2. **Решение — только MIME/размер/пиксели/payload/лимиты/ответ.** `plan_vision`
   и `optimize_to_fit` читают только len/mime/w/h/limits; `_source_flags`
   (alpha/n_frames) — формат-свойства, санкционированные директивой. Формы/
   контента нет.
3. **Этап A — в основном подтверждено, НО см. NF-1.** Нет выигрыша → None
   (тест+код); 0 перекодирований при fits (byte-parity + «кодек не должен
   вызываться»); EXIF baked (pillow); метаданные срезаны. Прозрачность→PNG и
   анимация→skip работают только на pillow-бэкенде; на ffmpeg-бэкенде
   (документированная прод-конфигурация) PNG-ветка падает ImportError (NF-1).
4. **Этап B — подтверждено.** Пропорции (тест, отклонение <0.06), масштаб от
   фактического payload, ≤3 попытки (A + 2×B), floor 256, 1024-хардкода нет
   (тест «>1024»); prep-pixels клампится в шагах. Нюанс (non-blocking):
   ранний Stage A-return проверяет только payload — мягкий prep-cap не
   применяется, если копия влезает по байтам (кап объявлен мягким).
5. **Retry — ≤1/меньшая/неидентичная/401/403/429/сеть/5xx — ОК; НО произвольный
   400 ретраится (NF-2).** `_retryable_provider_rejection` = `startswith`
   http_400/413/415/422 без проверки класса: зонд показывает 2 вызова на
   bare-400 «unknown parameter», «model_not_found», «context length».
6. **Лимиты провайдер-агностичны.** Ручки settings/env; `REQUEST_MAX_BYTES=0`
   → original (тесты); хардкода OR/Gemma нет (grep).
7. **Оригинал неизменен; копия не подменяет оригинал.** Вход не мутируется
   (byte-parity, snapshot-тест); в хранилище сохраняется только анализ,
   `content_hash` — от оригинала; A/B локальны (Pillow/ffmpeg), без LLM.
8. **Тесты.** RED `9f/22p` (red-korr2.txt — старый код со `segments`,
   `segment_trigger_ratio`, `fallback_max_dimension`; воспроизведён по
   содержанию) → **GREEN 32/32** (мой прогон `py -3 -m pytest
   tests/test_vision_adapt.py`). Полный 43-файловый кластер в evidence не
   зафиксирован списком; я перепрогнал **20 файлов / 575 тестов** (adapt 32,
   postgen+core+dl-fix 113, mca19 A–G+rework 116, param_catalog+cfg03 50,
   unified/image-gen/image-context/cfg02a/b 264) — **0 failed**. Негатив
   «200, но текст потерян» есть и зелёный; utility-тесты фрагментации есть (3).
9. **Метрики.** Мой прогон `TestFixtureMetrics`: 8 запросов / 7 кейсов;
   long_screenshot — 1 запрос, OCR 24/24; strict-провайдер — 2 запроса
   (bounded retry 413); max ms 172; delivered/honesty = 1.0. `metrics.json`
   воспроизводим (ms ±2 — межпрогонная дельта). Фикстуры честно отделены от
   live (live → RFL).
10. **Дисциплина.** Дельта == 5 заявленных файлов + evidence; чужие файлы в
    патч не входят; `config/settings.py` — только свои ручки; catalog-пины
    (REGISTRY 579, cfg03) зелёные. Примечание: F8-registry тест сейчас падает
    из-за чужого ADD-EXP-WIP (`NameError: threading` в
    `direct_chat_service.py:1612`) — к кандидату не относится, но фиксирует
    необходимость `--only`.
11. **postgen-делегирование — подтверждено.** Контракт статусов/detail/дедупа
    сохранён (код дедупа не тронут; постген-наборы в 113 зелёных;
    TestDelegationParity).

## Блокеры

**NF-1 (High, prod-путь).** На ffmpeg-бэкенде (Pillow отсутствует — так
описывают окружение собственные докстринги/дизайн-ноты, и Pillow нет в
`requirements.txt`) **любой PNG, требующий оптимизации, падает ImportError**:
`optimize_to_fit` при `mime == image/png` и `codec != pillow` ставит
`prefer_png=True` → `_encode_png` → `from PIL import Image` → ImportError;
исключение не перехвачено (нарушен контракт «никогда не бросает»), из
`analyze_adaptive` уходит в job → `vision_failed`. Это ровно целевой кейс
директивы (длинный скриншот PNG). Мой зонд (PIL заблокирован, codec=ffmpeg):
`optimize_to_fit(3.07 МБ PNG)` → `RAISED ImportError`; `analyze_adaptive` →
`RAISED ImportError`, calls=[] (ни одного запроса), событие
`vision_adapt … error=ImportError`. Побочно: на ffmpeg-бэкенде не работают
гарды прозрачности/анимации (`_source_flags` → (False, False)), т.е.
анимированный GIF > бюджета молча «сплющится» в JPEG — вопреки «анимация →
пропуск». Мини-фикс: `prefer_png` включать только при `codec == "pillow"`
(ffmpeg-PNG — JPEG-путь, как и задумано в комментарии `_source_flags`),
`_encode_png` сделать fail-open (ImportError → None), GIF без pillow —
пропуск оптимизации. Recheck: новый тест с `_pillow_available=False` +
ffmpeg: PNG → без исключения (original/JPEG), GIF → без «сплющивания»;
`tests/test_vision_adapt.py` + postgen-наборы зелёные.

**NF-2 (Medium, явное требование директивы).** «401/403/429/сеть/произвольный
400 — без повтора»: код ретраит **любой** 400 (`_ADAPT_RETRYABLE_PREFIXES` =
startswith `http_400`, класс ответа игнорируется), хотя дизайн-нота
обязывает «явный image/size/format-класс, прочие 400 — без повтора», а
`classify_rejection` уже даёт класс. Зонд: bare-400 «unknown parameter: foo»,
400 «model_not_found», 400 «context length» → по 2 вызова. Мини-фикс: для
`http_400` требовать подтверждённый класс (`/size`, `/pixels`, `/format`,
`/image_rejected`); 413/415/422 — как есть; тест «bare-400 → 1 вызов»
(существующий 400+«image too large» останется зелёным — там класс `/pixels`).

## Сопутствующее (в том же фикс-поезде, дёшево)

* Мёртвые/вводящие в заблуждение упоминания `segments` в дефолтном пути:
  комментарий `process_asset_job` («длинные скриншоты фрагментируются») и
  докстринг `postgen_vision._analyze_uncached` («original/optimize/segments»)
  противоречат КОРР №2 — убрать/уточнить.
* `aggressive` в `optimize_to_fit(_async)` — мёртвый параметр (никем не
  передаётся, в теле не используется); переменная `encode` в `optimize_to_fit`
  не используется.
* Докстринг `optimize_to_fit` «возвращает только копию МЕНЬШЕ оригинала» — на
  sniffed-None (декод-фоллбэк) пути не соблюдается (вызывающий гардит) —
  уточнить формулировку.

## Леджеру (рекомендация)

| Строка | Решение |
|---|---|
| VISION-ADAPT / КОРР №2 (единый поэтапный preprocessing) | код-половина → **V** после NF-1/NF-2; иначе Needs Fixes |
| Live-метрики (латентность, доля успеха, реальный OCR длинного скриншота, калибровка `REQUEST_MAX_BYTES`/`PREP_MAX_PIXELS`, фактический кодек) | **RFL postdeploy** (агентские проверки, PET; owner-гейт не нужен) |
| Pre-deploy чек (уточняет NF-1) | DevOps: `python -c "import PIL"` в прод-venv — если Pillow есть, NF-1 латентен, но фикс всё равно нужен (контракт «не бросает») |
| Сверка КОРР №1→№2 | выполнена: классификация/форма/обязательная фрагментация удалены, unknown-budget, без 1024; расхождения — NF-1/NF-2 |
| Гейт | pre-binding допустим (кандидат uncommitted; привязка к sha256 файлов выше); релизная привязка (`check --stage review/release --candidate <sha>`) — на релизном этапе |

## Вердикт

**Needs Fixes** — NF-1 (ffmpeg+PNG ImportError, целевой прод-кейс) и NF-2
(произвольный 400 ретраится вопреки директиве) блокируют; остальное
(удаление веток, единый конвейер, гарды Этапа A/B, ≤1-лимиты, unknown-budget,
оригинал/копия, метрики, дисциплина, postgen-делегация) подтверждено кодом и
независимыми прогонами. Оба фикса локальны (одна-две правки + тесты).
