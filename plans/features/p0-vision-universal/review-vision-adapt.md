# REV-VISION-ADAPT — вердикт (адаптивный preprocessing Vision, КОРР №2)

Независимое ревью кандидата целиком; read-only по коду. Этот файл — текущий
артефакт ревью: раздел RECHECK (актуально) + история раунда 1.

**Кандидат (uncommitted, поверх `df078406`; HEAD — docs-коммит ревью):**
`services/image_normalize.py` sha256_12 `b4f9f7a95d6d`;
`services/mca_vision.py` `a768eac7387b`; `services/postgen_vision.py`
`232e65a4af41`; `config/settings.py` `7e6d7ff4a527` (без изменений);
`tests/test_vision_adapt.py` `24f007fdd91e`.
`evidence/adapt/candidate-diff.patch` байт-в-байт == `git diff HEAD` по
4 tracked-файлам (сверено; sha совпал), в патче ровно эти 4 файла.
Параллельный ADD-EXP-WIP в worktree не входит в дельту кандидата
(его правка `mca_gates.py` — аддитивная `expression_examples_enabled`,
vision-функции не тронуты); коммитить только `--only`.

## RECHECK NF-1/NF-2 (кандидат `b4f9f7a9`/`a768eac7`/`232e65a4`/`24f007fd`) — **Approved**

Мои независимые зонды (не по отчёту Builder; PIL заблокирован meta-path
блокером, codec=ffmpeg = симуляция прод-бэкенда):

1. **NF-1 (ffmpeg+PNG ImportError) — закрыт.**
   * код: `prefer_png = pillow and transparent`; `_encode_png` fail-open
     (import + энкод в try/except → None); без Pillow `image/gif`/`image/webp`
     → пропуск, PNG с альфой → пропуск через `_png_has_transparency`
     (stdlib: color type 4/6 IHDR + tRNS-скан), непрозрачный PNG → JPEG-путь.
   * зонд: `_png_has_transparency` — RGBA(6)=true, opaque(2)=false,
     палитра+tRNS(3)=true (tRNS-чанк в фикстуре подтверждён);
     long PNG (3.07 МБ) → JPEG 720×2592, 642 015 B, меньше оригинала,
     **без исключения**; прозрачный PNG → None; animated GIF → None;
     `analyze_adaptive(long PNG)` → **ready, 1 запрос, 642 015 B, без
     исключений**; батарея 8 входов × оба бэкенда — исключений нет;
     `_encode_png` напрямую: PIL заблокирован → None, garbage → None,
     валидный RGBA → валидный PNG.
2. **NF-2 (произвольный 400) — закрыт.** 400 повторяется только при
   подтверждённом классе (`/image_rejected`, `/size`, `/pixels`, `/format`);
   413/415/422 — по статусу. Зонд: bare-400 «unknown parameter» → 1 вызов;
   400 model_not_found → 1; 400 context → 1; 400 «some other error» → 1;
   400 «image too large» → 2 (23667→9109 B, строго меньше); 413/415/422 →
   2; 500/429/401 → 1 (честные `http_500`/`vision_rate_limited`/
   `vision_unavailable`); повторный image-class отказ → 2 вызова,
   честный detail `http_400/image_rejected/pixels`.
3. **Сопутствующее — чисто.** `segments`/«фрагментируются»/`long_enough` в
   дефолтном пути отсутствуют (grep); `aggressive` (0 вхождений) и мёртвая
   переменная `encode` удалены; докстринг `optimize_to_fit` уточнён
   («меньше» — для известных снифферу форматов, sniffed-None — гард
   вызывающего). Ничего не сломано (спот-прогоны ниже).
4. **Регресс/дисциплина.** Мой прогон: adapt **43/43** (RED `red-nf.txt`
   9f/34p — новые NF-тесты падают на старом коде, состав совпадает),
   постген-группа **113**, mca19 A–G+rework **116**, image-наборы **264**,
   catalog/cfg03 **50** — итого **536 тестов, 0 failed** (полный 23-файловый
   кластер в evidence списком не зафиксирован — тот же нюанс, что и раньше).
   Дельта == 5 заявленных файлов + `evidence/adapt/**`; чужие ADD-EXP-файлы
   в патч не входят; CFG-роуты/каталог-пины не задеты (`settings.py` не
   менялся).

**Non-blocking (в леджер/backlog, не блокирует):** (а) `_adaptive_retry`
после подтверждённого image-class отказа конвертирует прозрачные источники
в JPEG — альфа на retry-пути не сохраняется (pre-existing, вне гардов Этапа A;
зонд: прозрачный PNG → JPEG 1.1 МБ, меньше); (б) `test_long_png_never_raises`
ассертит `codec == "ffmpeg"` без skipif — на машине без ffmpeg тест упадёт, а
не скипнется (портируемость; канонический env/прод имеют ffmpeg).

## Леджеру (рекомендация)

| Строка | Решение |
|---|---|
| VISION-ADAPT / КОРР №2 (единый поэтапный preprocessing) | код-половина → **V** (NF-1/NF-2 закрыты, 536 тестов зелёные, дисциплина чистая) |
| Live-метрики (латентность, доля успеха, реальный OCR длинного скриншота, калибровка `REQUEST_MAX_BYTES`/`PREP_MAX_PIXELS`, фактический кодек) | **RFL postdeploy** (агентские проверки, PET; owner-гейт не нужен) |
| Pre-deploy чек | DevOps: `python -c "import PIL"` в прод-venv (фактический кодек; на фикс не влияет) |
| Гейт | pre-binding по sha256 выше; релизная привязка (`check --stage review/release --candidate <sha>`) — на релизном этапе |
| Backlog-note | retry-путь и прозрачность (см. Non-blocking «а») — при следующем касании контура |

## История раунда 1 — **Needs Fixes** (коммит `57f3ffe4`, закрыто)

Найдено и затем исправлено: **NF-1** — на ffmpeg-бэкенде PNG-путь падал
ImportError (`_encode_png` требовал Pillow при `prefer_png=True` для PNG),
ломая контракт «никогда не бросает»; побочно — гарды прозрачности/анимации
не работали без Pillow. **NF-2** — ретраился любой 400 без проверки класса
(вопреки директиве «произвольный 400 — без повтора»). Остальные проверки
1–11 раунда 1 были подтверждены: удаление веток `long_enough`/`segments`/
`DOWNSCALE_STEPS`/`fallback_max_dimension` (утилиты сохранены, из дефолтного
пути не вызываются), решение только от MIME/размера/пикселей/payload/лимитов,
Этап A/B (гарды, ≤3 попытки, floor 256, без 1024), unknown-budget → original,
оригинал неизменен/копия не подменяет оригинал, метрики 7 кейсов
(8 запросов, OCR long 24/24, strict 2 запроса), провайдер-агностичные лимиты,
postgen-делегация, дисциплина.

## Вердикт

**Approved** (код-половина VISION-ADAPT/КОРР №2; родитель — не DONE до
postdeploy-метрик). NF-1 и NF-2 закрыты и подтверждены независимыми зондами
на симулированном прод-бэкенде; регрессий нет; live-метрики — **RFL
postdeploy**.
