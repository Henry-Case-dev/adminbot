# Релиз **2.58.95** — CFG-03 + POSTGEN-DIAG + VISION-ADAPT

Дата сборки кандидата: 2026-10-19/20 (UTC; по логам прогонов ниже).
Кандидат: **master-линия** (код-коммиты CFG-03 `df078406`, POSTGEN-DIAG
`61ecd034`, VISION-ADAPT `b20fe4f7`) + bump `35b8b455`; прод до релиза —
**`2.58.94 @ 9072347b`**.
Статус: **собран и проверен локально**; деплой и приёмка — отдельные шаги (§4).
Задача: LANE RELEASE-PKG-95 (релиз-пакет; без деплоя/SSH-записей).
Верификация — в **изолированном чистом worktree** от bump-коммита
(`OPENCODE_WORKFLOW_SCRATCH\release-25895\wt` @ `35b8b455`); главное дерево
для прогонов кандидата не использовалось. Незакоммиченная чужая ADD-EXP-WIP
(`web/api/speech.py`, `services/prompt_composer.py`, `web/app.js`,
`web/index.html`, тесты и др.) **не вошла ни в один коммит** этого поезда
(commit строго `--only`, набор = bump-набор прошлого поезда; после коммита WIP
в дереве сохранён без изменений).

## 1. Состав (что вошло)

| Линия | Коммит | Что это по-человечески |
|---|---|---|
| CFG-03 (код/аудит) | `df078406` | Полный аудит мини-апп-параметров: инвентарь **579** записей реестра с цепочкой потребителей (`runtime 552 / dynamic 13 / none 14`), `UI_missing=0` (включая `content_media` — синтетическая группа без вкладки), машиночитаемые артефакты (`inventory.json/tsv`, `audit-summary.json`, `blast-radius.txt`) + честные описания **5 «мёртвых» ручек** (`CHAT_LOCK_MAX_ENTRIES`, `CHAT_BUDGET_RESPONSE_RATIO`, `YOUTUBE_TRANSCRIPT_PROXY_LOCATIONS`, `..._RETRIES`, `DIG_GRAPH_HOP_DEPTH` — «Не влияет: значение сохраняется в конфиге, но рантайм его не читает»); TSV/meta переизданы; F8 re-pin `4886ff03…`; инструменты `tools/cfg03_param_inventory.py`, `tools/ui_cfg03_descriptions_e2e.py`; контракт `tests/test_cfg03_param_audit.py` (16). Каталог Δ = 0 (579). |
| POSTGEN-DIAG (код) | `61ecd034` | Диагноз живого дефекта ACCEPTANCE-94 (пост-генерация: 939 495 B → `image_postgen_vision failed/vision_failed`): провайдерский non-2xx на тяжёлом payload. Фикс: новый `services/image_normalize.py` (Pillow → ffmpeg, bounded, fail-open, R17) + `mca_vision.validate_or_normalize` (только после `vision_unreadable`), sniff-фикс легальных fill-байтов `0xFF`, `detail` доезжает до stage-события/`error_json`, `[vision] postgen` лог-префикс; ровно один bounded retry в `postgen_vision` (image-class 400/413/415/422, строго меньший payload, остаток бюджета ≥3 c; 500 — без retry). |
| VISION-ADAPT (код) | `b20fe4f7` | Адаптивный универсальный preprocessing для всех vision-вызовов: staged weight→downscale, provider-agnostic лимиты (`MCA_VISION_REQUEST_MAX_BYTES` = 700 000, `MCA_VISION_PREP_MAX_PIXELS` = 4 000 000, `..._ADAPT_BUDGET_SECONDS` = 90), bounded retry только image-class (400/413/415/422 + `/image_rejected`), БЕЗ классификации контента и формы, ffmpeg-safe (в т.ч. PNG с прозрачностью), событие `vision_adapt` + журнал `[vision] adapt | strategy=… | reason=… | calls=…`. |
| Bump/F8 | `35b8b455` | `2.58.94 → 2.58.95`: settings + README + F8-meta (APP_VERSION `2.58.95`, HEAD-штамп `b20fe4f7` — последний код-коммит поезда) + 24 py-пина + 4 JS-пина = 31 файл (+33/−33, версионно-чистый — `bump-verify.txt`). |

Ревью линий (все — **Approved**): CFG-03 `f8bb638d` (инвентарь 579, UI_missing=0
подтверждён спотом + синтетикой `content_media`; catalog delta=0; check 579;
16/256 зелёных; JS 88/0; e2e PASS; live 03.4/6/11/12 → RFL), POSTGEN-DIAG
`b2eebead` (корень доказан прод-фактами; мой e2e 3/3; GREEN 27, cluster spot
418; дисциплина чистая), VISION-ADAPT `57f3ffe4` **Needs Fixes** → RECHECK
`19f716a2` **Approved** (NF-1/NF-2 закрыты: ffmpeg+PNG safe, class-gated 400
retry; 536 тестов зелёные; live → RFL).

## 2. Дельта к проду (изоляция)

База = прод `9072347b` (2.58.94). Полная дельта после bump-коммита
(включая `plans/**`) = **146 файлов**; без `plans/**` — **39**
(`delta-non-plans.txt`):

- **5 runtime-файлов** — ровно они и есть вайтлист деплой-скрипта (любой
  другой runtime-файл в дельте = abort; сверка равенства множеств офлайн:
  PASS, `deploy-offline-check.txt`):
  `services/image_normalize.py` (**новый**), `services/mca_vision.py`,
  `services/postgen_vision.py`, `services/param_catalog.py`,
  `config/settings.py` (runtime-stat: 5 файлов, **+1052/−38** —
  `delta-runtime-stat.txt`);
- **30 файлов `tests/`**: новые `test_vision_adapt.py` (43),
  `test_postgen_diag.py` (27), `test_cfg03_param_audit.py` (16) + 24 py-пина +
  4 JS-пина (bump) + перепин `test_round1025_f8_registry.py` (CFG-03);
- **`tools/`** — новые `cfg03_param_inventory.py`, `ui_cfg03_descriptions_e2e.py`;
- `README.md` — bump-файл;
- плюс `plans/**` (107 файлов: F8-meta + TSV из CFG-03, evidence CFG-03
  (`plans/features/cfg/evidence/cfg-03/**`), evidence postgen-diag/adapt,
  docs/reviews линий и ADD-EXP-доки, накопленные параллельно).

ΔDDL = **0**: `services/database.py`, migrations-модули и `scripts/` в дельту
не входят (`ddl-check.txt`); `user_version` на проде остаётся **36**.
Δ каталога = **0** (REGISTRY 579; `--check` OK).

Sanity-файлы обязаны остаться байт-в-байт прод-2.58.94:
`web/static/fullscreen-policy.js` `96db06425079`,
`services/telegram_send.py` `e23bced2fdb8` — сверено (в дельте их нет,
побайтовое равенство подтверждено, `frozen-fingerprint.txt`).

## 3. Проверки кандидата (run-as-is, в изолированном worktree от bump-коммита)

| Проверка | Результат |
|---|---|
| Полный `pytest -q` (чистый прогон, без конкурентной нагрузки) | **9 failed / 14520 passed / 39 skipped** (737.70s); множество падений — **точное совпадение** с прогоном кандидата 2.58.94 (5×`t5150`, 2×`asap7_direct_settings`, 1×`mca01_tx_task_supervisor`, 1×`history_cli` worktree-env); env-флейк random_source не сработал; 39 skipped — только НОВЫЕ файлы поезда из-за отсутствия PIL в `.venv` (38×adapt + 1×postgen); баланс: 14473 + 86 новых = 14559 = 14520p + 39s (`pytest-attribution.txt`) |
| `tests/test_vision_adapt.py` (VISION-ADAPT контракт, канон `py -3`) | **43 passed** (`.venv`: 5p/38skip — PIL; `focused-venv-pil-skips.txt`) |
| `tests/test_postgen_diag.py` (POSTGEN-DIAG контракт, канон `py -3`) | **27 passed** (`.venv`: 26p/1skip — PIL) |
| Постген-кластер (20 файлов: postgen/adapt/dl-fix/p0v-core/mca19 A–G/rework/addtr/media_download/tool-router/tool-schemas/unified-image/image-generation) | **447 passed, 39 skipped (PIL), 0 failed** (спот ревью 18 файлов = 418 — надмножество) |
| `tests/test_cfg03_param_audit.py` (CFG-03 контракт) | **16 passed** |
| CFG-03-кластер (10 файлов: cfg03 + chat_params/direct_chat/persistent_throttling + cfg02a/b/c + f8) | **453 passed** |
| F8-пины: `test_round1025_f8_registry.py` | **29 passed** |
| F8-каталог: `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY** (R17-чисто, TSV/map идемпотентны) |
| speech/UI-наборы (7 файлов: soul1_w6_speech_ui, speech_mobile_entry, persistfix_speech_scope, mca08, ui_p0a_ux_speech, ui_speech_mobile_entry, p0_vision_ui_e2e) | **100 passed** |
| `tests/test_t5150_startup_migrations_round1046.py` | **5 failed / 2 passed** — пре-сущ. (тот же набор в прогоне 2.58.94) |
| **Прямое доказательство пре-сущ. на базе**: 4 файла падений на `9072347b` (отдельный worktree `wt-base`) | **9 failed / 63 passed** — ровно те же 9 ID, что на кандидате (`focused-base-pre-existing.txt`) |
| JS-sweep: `node tests/js/*_test.js` (88 файлов) | **88 файлов / 0 падений** |
| UI e2e (Playwright): `tools/ui_cfg03_descriptions_e2e.py` | **RESULT: PASS** (витрина честных описаний, `content_media`, mobile 390px без overflow, console errors = 0) |
| ΔDDL-check (дельта не трогает DDL/миграции) | **ΔDDL = 0** |
| Офлайн-сверка деплой-скрипта (hashes 9/9, вайтлист==дельта 5/5, BUMP==HEAD, upload) | **EXIT 0** |
| Bump-verify (каждая изменённая строка = только версия/HEAD-штамп) | **OK: 31 файл, 31 пара строк** |

Артефакты: `evidence/release-25895/**` (полный индекс — `README.md` там же).

## 4. Чек-лист пост-деплойной приёмки

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; дисциплина fail2ban: один recon +
один основной коннект, без ретраев; HTTP — `https://admin-bot.duckdns.org/healthz`.
Все проверки — read-only или контролируемые, **без лишних платных вызовов**.

**(a) CFG-03 Ф6 live — 03.4/.6/.11/.12 + R4.**
Источник сценариев: `plans/features/cfg/evidence/cfg-03/manual-checks.md` (R4).
- 03.4 hot (без рестарта): `limits.image_daily_limit` глобально → 1: генерация
  разрешена ровно 1 раз, вторая — отказ с фактическим остатком; вернуть 60.
  `flags.vision_enabled`: выключить в одном чате → анализ изображений в нём не
  запускается; включить → работает. (Reuse без повтора: `chat_burst_limit`/
  `chat_cooldown_seconds` — P0/CFG-01 live 2.58.88; `image_freq_limit_*` —
  CFG-02B live.)
- 03.6 витрина честности: 5 ручек с пометкой «Не влияет: значение сохраняется
  в конфиге, но рантайм его не читает» видны в мини-аппе с честным текстом
  (статические доказательства: `markers-candidate.txt`, e2e PASS §3).
- 03.11 негативы: неверный тип/значение по классам → честные 409/422 **без
  записи** (контракт в `test_cfg03_param_audit.py`; live — выборочно, 1–2 класса).
- 03.12 OFF/ON по маршрутам: выключение ручки → маршрут честно не выполняется,
  включение → работает (использовать безопасный `flags.vision_enabled`-сценарий).
- R4-остаток: живые hot-проверки — **агентские** (PET-правило: обязательные
  device-чек-листы владельца не создаются; см. manual-checks.md §2 — вопрос
  «выводить ли 5 ручек из UI» продуктовый и **не блокирует** релиз).

**(b) Живой повтор пост-генерации — ровно 1 генерация.**
Сценарий ACCEPTANCE-94-класса: временно поднять суточную квоту изображений
(снапшот → правка `limits.image_daily_limit`/per-chat override → восстановление
точно в исходное значение, образец — `evidence/release-25894/acceptance/harness/
accept94b_cover.py`), выполнить **ровно 1** генерацию изображения. Ожидание:
цепочка `[image] generated … bytes=…` → `[vision] postgen | … | status=ready`
(или `retry` при image-class 400 с последующим `ready`), `detail` виден в
событии (`error_json`) — «слепого» `vision_failed` без класса больше нет;
1 вызов vision на 1 генерацию (bounded), дедуп не сломан. Артефакты: строки
журнала + `rel95_final.sh` (`VISION_POSTGEN_JOURNAL`).

**(c) Vision-adapt live — реальный длинный скриншот-документ.**
Отправить в чат реальный длинный скриншот-документ (высокая сторона/вес выше
бюджета) → ожидание: маркер `[vision] adapt | strategy=… | reason=… | calls=…`
и/или событие `vision_adapt`, распознавание доезжает до контента; при
image-class 400/413/415/422 — ровно один retry со строго меньшим payload.
**Калибровка по живым ответам**: если провайдер принимает больший payload —
поднять `MCA_VISION_REQUEST_MAX_BYTES` (env-only) и/или
`MCA_VISION_PREP_MAX_PIXELS`; если отказывает по размеру/формату — не менять
(адаптивный путь сам пережмёт). Значения по умолчанию: 700 000 байт /
4 000 000 px; откат — `MCA_VISION_NORMALIZE_ENABLED=false` (OFF = прежнее
поведение, сниффер + честный отказ).

**(d) DevOps pre-deploy инфо (перед рестартом).**
`python -c "import PIL"` в прод-venv (`/var/www/admin_bot/venv/bin/python`) —
зафиксировать результат. Pillow есть → декод-фоллбэк идёт основным путём;
Pillow нет → фоллбэк на ffmpeg (в проде есть видео-контур), при отсутствии
обоих — честная деградация (fail-open, без падения). Дополнительно:
`which ffmpeg` на проде.

**(e) Уборка тестовых сообщений.**
Все тестовые сообщения/картинки приёмки удалить в чатах после прогонов
(правило владельца; прецедент — `accept91_cleanfinal.py`); evidence
(message_id/скрин) — до удаления.

**Базовые маркеры (обязательны к проверке):** `healthz` = `2.58.95` (loopback и
HTTPS), MainPID сменился; журнал since T0: `ERR/CRITICAL/Traceback = 0`,
`402 = 0` (`ERR_402` в `rel95_final.sh`), RuntimeWarning = 0; **SKIPS=0**
(«maximum number of running instances»); миграции `complete`, `user_version`
без изменений (Δ DDL = 0); served-bytes `SERVED_EQ_*=SAME`, `PAGE_VER=15`,
`SUBST_CSS=2`; маркеры поезда (CFG-03/POSTGEN-DIAG/VISION-ADAPT — в
`deploy_25895.py::D3_markers_25895` и `rel95_final.sh`); `LOCAL_BOT_API_MARKER`
≥1 (регрессия 2.58.94).

## 5. Откат

**Рубежи (по убыванию близости):**
- `release/fix-2.58.94` (`9072347b`, 2.58.94) — пред-релизная линия прода;
  **новый рубеж** (ветка создаётся при пуше; deploy: tree-restore при abort
  ДО рестарта, fallback — точный detach `9072347b`).
- `release/fix-2.58.93` (`b4d30cab`, 2.58.93) — **штатный рубеж авто-отката
  деплой-скрипта** (путь ПОСЛЕ рестарта при неполучении healthz 2.58.95 /
  пустом T0) — предыдущий рабочий релиз.
Abort ДО рестарта (вайтлист/дельта/хеши) отката не ждёт: `_tree_restore`
возвращает дерево к прод-линии 2.58.94 (без рестарта) — downgrade исключён.
Мягкие двери (без рестарта, env-only): `MCA_VISION_NORMALIZE_ENABLED=false`
(прежнее поведение vision-подготовки), прежние per-chat/env-переключатели
(CFG-02B, Vision, Direct) не меняются; CFG-03 — описания/аудит, поведенческих
флагов не вводит.

## 6. Риски/остатки (честно)

1. **`t5150` ×5 и остальные 4 пре-сущ. падения полного pytest** (итого 9):
   набор совпал побайтово с прогоном кандидата 2.58.94 (`pytest-attribution.txt`);
   **прямая проверка на базе `9072347b`** (отдельный worktree `wt-base`) дала те же
   9 failed / 63 passed (`focused-base-pre-existing.txt`); дельтой эти файлы не
   тронуты. Не регрессия.
2. **PIL в `.venv` отсутствует** → 39 skipped новых файлов в полном прогоне;
   канонические прогоны (`py -3`) дают 43 и 27 passed. **Пред-деплойный вопрос
   (d)**: проверить PIL в прод-venv — от этого зависит, какой кодек пойдёт
   основным (Pillow vs ffmpeg); оба пути fail-open.
3. **VISION-ADAPT live-половина** (RFL): калибровка `REQUEST_MAX_BYTES`/
   `PREP_MAX_PIXELS` по живым ответам провайдера — после первого реального
   длинного кадра (§4c); дефолты консервативны, retry bounded (≤1).
4. **POSTGEN-DIAG live-половина** (RFL): подтверждение «1 генерация → 1 bounded
   вызов postgen-vision, detail наблюдаем» — §4b (на ACCEPTANCE-94 живой повтор
   не проводился; код-контракт и e2e-зонд зелёные).
5. **CFG-03 продуктовый вопрос** (не блокирует, PET-правило): выводить ли 5
   честно помеченных ручек из UI — решает владелец при желании
   (`manual-checks.md` §2); текущее состояние честное и релизится как есть.
6. **Живые hot-проверки 03.4** — агентские, на релизном этапе (§4a); часть
   сценариев переиспользует P0/CFG-01/CFG-02B live-эвиденс (повтор не требуется).

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `…\release-25895\deploy_25895.py` — sha256_12 **`03d52c843908`**
  (T0-hardened clone `deploy_25894.py`/`4eb764c8ba0f`; все NF-фиксы сохранены:
  checked_out-гейт + tree-restore, set-equality вайтлиста, tree-restore к
  прод-линии 2.58.94, WARNINGS-summary, SERVED_EQ, один SSH-коннект;
  добавлено: `A2_user_version` (ΔDDL до/после), `D3_markers_25895` (маркеры
  поезда), `F6_journal_402`): A pre-state → B fetch origin/master
  (BUMP-ancestor gate) → C checkout + runtime-вайтлист дельты (5 файлов) →
  D sha256_12 (**9 артефактов**: 5 runtime + README + meta + 2 sanity) +
  маркеры поезда и регрессионные линии 2.58.94/93/92/91 → F restart + T0 +
  healthz 2.58.95 + журнал + `[local-bot-api]`-маркер + 402 → G served-bytes →
  J `rel95_final.sh`.
- `rel95_final.sh` — sha256_12 **`b912792903f4`** (read-only; маркеры поезда
  CFG-03/POSTGEN-DIAG/VISION-ADAPT с ожиданиями, `VISION_ADAPT_JOURNAL`/
  `VISION_POSTGEN_JOURNAL`, `ERR_402`, SKIPS-контроль, `USER_VERSION` (ΔDDL),
  регрессионные маркеры DL-FIX/CFG-02C/2.58.92/2.58.91, SERVED_EQ,
  PAGE_VER/SUBST_CSS, read-only `mca_media_analyses`, `/api/workers/budget`,
  `/api/vision/state`).
- Офлайн-сверка констант скрипта с кандидатом: `check_deploy_25895.py`
  (sha256_12 `3e6883288482`) — **EXIT 0** (hashes 9/9, вайтлист == дельта 5/5,
  BUMP == HEAD, uploads на месте) — `deploy-offline-check.txt`.
- Авто-откат ПОСЛЕ рестарта: `release/fix-2.58.93`; abort до рестарта →
  `_tree_restore` к прод-линии 2.58.94 (`release/fix-2.58.94`/`9072347b`).
- **Предусловие запуска:** `master` запушен в origin с bump-коммитом 2.58.95
  (B3 fail-closed, иначе прод не трогается); ветку `release/fix-2.58.94`
  создать/запушить при выкате (иначе tree-restore идёт fallback-detach'ем на
  `9072347b` — объект уже есть на проде).

## 8. Кандидат-фингерпринт

- tip master / bump-коммит: `35b8b455` (2.58.95) — дерево кандидата заморожено им.
- Последний код-коммит: `b20fe4f7` (VISION-ADAPT) = родитель bump-коммита и
  HEAD-штамп F8-meta.
- Прод-базис: `9072347b` (2.58.94); новый рубеж отката `release/fix-2.58.94`.
- sha256_12 9 артефактов `EXPECT12` — в `deploy_25895.py::EXPECT12` и
  `evidence/release-25895/frozen-fingerprint.txt` (+ полные sha256 там же):
  `services/image_normalize.py b4f9f7a95d6d`,
  `services/mca_vision.py a768eac7387b`,
  `services/postgen_vision.py 232e65a4af41`,
  `services/param_catalog.py 4886ff036b0e` (== f8 re-pin),
  `config/settings.py 1e534c6c15c3`, `README.md 28cdd3dfbd8d`,
  `meta 889a98e3c961` + sanity `96db06425079`/`e23bced2fdb8`.
- После сборки пакета master получает один plans-only docs-коммит (этот отчёт +
  `evidence/release-25895/**`) — runtime не меняется: дельта
  `9072347b..HEAD` по `config/services/web/handlers/bot.py` = те же **5 файлов**;
  bump-коммит остаётся ancestor HEAD (B3-гейт пройдёт).
