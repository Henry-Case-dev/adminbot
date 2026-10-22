# REVIEW REL-258108 (кандидат be60041f, база = prod 2.58.107 @ 3a178c6c), 22.10.2026, lane REV-REL-258108

**Verdict: Approved -> DevOps.**

## Состав (git 3a178c6c..be60041f, воспроизведено)
- Ровно 4 коммита: 60110e77 (harness-docs, без кода), 1cf0f400 (FIX: services/mca_vision.py strip-fence + 2 REGRESSION), 06b7ef4d (bindings 2 карт), be60041f (bump).
- Runtime-дельта = services/mca_vision.py ТОЛЬКО (+config/settings.py = токен APP_VERSION). web/ handlers/ migrations/ = 0. ΔDDL=0: собственный скан диффа (0 DDL-токенов) + ddl-check.txt (schema v37, perimeter NONE).
- Bump = 31 файл SET EQUAL proc-107; самостоятельно: все изменённые строки — только version/HEAD-токены (24 py-пина, 4 js-пина, settings, README, F8-meta HEAD=06b7ef4d).
- Гигиена: чужие dirty (285 файлов) ∩ коммиты поезда = 0 (сверка списков); секрет-скан полного диффа = 0 хитов.

## Фикс FIX-VISION-FENCE (1cf0f400)
- _strip_markdown_fence снимает ТОЛЬКО обёртку (первая строка-страж с тройным бэктиком + хвостовой тройной бэктик): содержимое не правится, далее строгий json.loads; невалидный/обрывок/голый страж без перевода строки -> честный failed/parse_error. Case-контроль: bare-JSON путь не изменён (валидный JSON не начинается с бэктика).
- 2 REGRESSION-теста воспроизведены: standalone 2 passed; полный test_mca19_block_b_round1043.py = 33 passed. RED на базе задокументирован (fence-fix-red-tests.txt: 1 failed) + before/after harness: before-w1-postgen.json postgen=failed/parse_error, heavy_frame=failed → w5-fence-fix.json postgen=ok (photo 518988B, доставка), heavy=ready GT 3/3 (ZEBRA77/QUARTZ88/LOTUS99). sha256 артефакта w5 совпадает с map (0fc8534d5a15).

## Гварды (воспроизведено мной, venv)
- F8 --check: CHECK OK 582==REGISTRY rc=0; F8-пины 29p; mca19 33p; fc_r1 22p; corrective (L1+expression+nostalgia) 25p; help-sync 24p; write_points 1p.
- node --check 4 js-пина OK (+ hotfix8 исполнением OK; syntax sweep 107/0 принят).
- Fingerprint: runtime factory_set_fingerprint() == c19d35a1c093 == константа (канонов в поезде нет) — воспроизведено.
- pins24 868p/0f принят; флейк 1f/867p проверен независимо: global py -3 = aiogram 3.29.1 (< requirements aiogram>=3.31.0), в venv 3.31.0 (InputRichMessage.model_fields.media=True) → 868/0. Диагноз interpreter-artifact верен. **Env-notice (не релиз-блокер):** все проверки/прогоны — только в .venv; глобальный py -3 для rich-publish тестов даёт ложный red.

## Privacy
- parse_analysis_payload: единственный прод call-site = VLM-анализ изображения (mca_vision.py:1575); _strip_markdown_fence больше нигде не используется. Suppress/custom_clean-контур (prompt_factory/prompt_registry) диффом не задет; test_cfg07a_f1_custom_suppress = 51 passed. OCR-текст по-прежнему только в data-канал (untrusted), инструкции не интерпретируются.

## Postdeploy-план (передаётся DevOps)
1. healthz == 2.58.108; blob-сверка прод-байтов services/mca_vision.py с be60041f.
2. Read-only сверка контуров OFF/DEDUP на прод-байтах (status=off, 0 vision; cache_hit, 0 vision) — без генерации сообщений в реальные чаты.
3. S-кейсы (S9 postgen-ready) = симуляция доставки в FakeBot на прод-байтах локально; 0 отправок в Telegram.
4. Rollback: ветка release/fix-2.58.107 (= 3a178c6c, создать при деплое); рестарт плановый. После волны — актуализировать deployed_commit/VERIFIED live-половин S9/P0V-06c и --stage release.

## Блокеры
Нет.
