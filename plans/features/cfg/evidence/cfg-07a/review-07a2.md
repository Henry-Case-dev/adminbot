# REV-CFG07A2 — независимое ревью волны 07A-2 (анти-backstage контракт НЕ-фактчек канонов)

- **Ревьюер:** REV-CFG07A2 (leaf, read-only). Дата: 21.10.2026.
- **Кандидат:** незакоммиченное дерево поверх HEAD `476e11a5` (прод 2.58.100 `acc285d7` = предок).
- **Метод:** независимые прогоны и байт-сверки, не переиспользование евиденса Builder'а. Скрипты в `C:\Users\main\AppData\Local\Temp\opencode\rev07a2\` (probe/compare/scan), база для бейслайна — временный git worktree на чистом `476e11a5` (после проверки удалён, чист).

## Вердикт: **Approved** (волна; коммит — только по списку файлов волны, см. Гигиену)

## 1. Байт-сверка с продом (независимо, все 7 канонов — не выборка)

`git archive acc285d7 services` → скретч (хеш-контроль извлечения = git-блобам), импорт старых/новых модулей в раздельных процессах с привязкой прогона к дереву (маркерный чек + `__file__`):

- `PREV_*_CFG07A` (7 шт) == активные каноны `acc285d7`: **7/7 OK** (search 5950206a, youtube dd57d213, youtube_video 47e304d8, web c384282d, checkup 0ce06cb1, summary 4820a270, direct 0b853c37).
- Полный sweep ВСЕХ UPPERCASE-строковых констант 8 модулей: изменены ТОЛЬКО 7 активных канонов + их приватные базы (паттерн `_BASE`→`_BASE_FROZEN`) + `CHECKUP_FALLBACK_NOTICE` (FA-08, заявлено). Всё остальное — byte-stable: старые ступени PREV_R1021/R1022/R2020/R1023/MCA23/R1028, `BOT_KNOWLEDGE_INSTRUCTION` (hostile, фриз фактчека W3), STYLE_BLOCKS_SUFFIX/PREV, LEGACY_*. Добавления ровно заявленные: 7×PREV_*_CFG07A, FROZEN-базы, `BOT_KNOWLEDGE_INSTRUCTION_NEUTRAL`.
- `factcheck_prompts.py`: байт-идентичен (ни один атрибут не изменился) — W3-фриз цел; файл вне диффа.
- Активные каноны реально изменились: 7/7 CHANGED.

## 2. Fingerprint

- `factory_set_fingerprint()` пересчитан независимо на дереве: **037080375ac8** == `FACTORY_SET_SHA256_12`. На чистом HEAD — 64ec1c60e278 (подтверждено прогоном). 7 меток бампнуты (`*-cfg07a`): direct.base.tool_phase, summary.base.single, search/checkup/youtube/youtube_video/web.base.*. Трасса в комментарии константы полная (что и почему). Изменение сознательное, санкционировано процедурой (ADR-1013-3/C14-прецедент), не ослабление.

## 3. Маркер-скан активных канонов (корпус 07a1)

- Свои маркеры корпуса (SF-01..SF-16, FA-08): **0 хитов** в 6 не-Direct канонах; единственный hit — «бот-абьюзер» в системной роли Direct — **задокументированный residual вне скоупа корпуса** (SF-07 покрывает 6 канонов; сводка §1/§6; не потерян).
- PREV-ступени обязаны узнавать прод-байты: 7/7 хранят собственный маркер ✓ (обязанность узнавания C14).
- POSITIVE-контроли: PC-12 жанр checkup («жестко разъеби их», «поиздевайся»), формат торопливого письма — живы; `test_positive_controls_alive` (7 из 12 напрямую; PC-01/02/09/10/11 — словарные 07C-G, гварда в слайсе нет, диффом не задеваются).
- SF-09/13 Direct: честный слив «Признай косяк в саркастичной манере, но оставайся в рамках фактов.» — выдуманная механика и ярлык убраны; контракт-блок «СЛУЖЕБНЫЕ ПОМЕТКИ (НЕ ДЛЯ ОТВЕТА)» на месте; смысл/структура ответа сохранены (тесты Direct-канона зелёные).
- Машинная стадия Writer'а: `direct_l1.py`/`direct_execution.py` вне диффа; `build_l2_plan_block`/EvidencePack покрыты контрактом как данные.

## 4. Лестницы/миграции/suppress (поведенчески)

- `PROMPT_MIGRATIONS`: +7 ступеней `PREV_*_CFG07A → <новый канон>`; `ROLLBACK_MIGRATIONS`: все 7 ключей ведут на НЕПОСРЕДСТВЕННЫЙ прежний канон (ретаргет подтверждён диффом и тестами).
- Прогоны: `test_cfg07_backstage_contract.py` **59p** (лестница/узнавание/откат/migrate-идемпотентность/кастом-нетронутость, suppress(persisted)==канон байт-паритет для 5 маршрутов, honest-cleanup для checkup/summary/direct, OFF-паритет source="default", SF-14, POSITIVE, ностальгия-гард, humanized-note); `test_prompt_migrations` + `test_soul1_registry_legacy_removal` + `test_soul1_registry_completeness` + `test_de_robotization_round1021` — **142p**.

## 5. Прочие точечные

- SF-15: `rejected_note` — человеческие имена/формулировки, неизвестный код деградирует в «сейчас недоступно», пусто/None → ""; машинные пейлоады не тронуты. `test_asap7_direct_l1` (D15) зелёный.
- FA-06/G1: `contains_unchanged_token` + брак ДО отправки в worker (reason=unchanged_echo, в чат не уходит); точный детектор `is_unchanged_response` не менялся (spec §3.5.4). Тесты: контракт + `test_unchanged_echo_braked_not_sent` (REGRESSION) — зелёные.
- SF-14: тест `test_summary_l2_profanity_seam_closed_by_p0_priority` подтверждает: L2-канон НЕ правлен (sweep: SUMMARY_L2_WRITER_SYSTEM_PROMPT byte-stable), противоречие закрыто pre-existing P0-строкой `EXPRESSION_HEADER` (`mca_expression.py` вне диффа); §2-пины целы (`test_add_exp_expression` в прогоне 84p).

## 6. Тесты (мои независимые прогоны)

- Фокус: контракт 59p + suppress/реестр/миграции/де-роботизация 142p + route-coverage **18/18** + промпты всех маршрутов + direct/L1 + memory_core + nostalgia (unit+worker) 228p + samples-регресс (включая фаб-отпечаток `test_samples_factory_persist`) + expression 84p = **531 passed, 0 failed**.
- Транзиент: `test_unanswered_resolved_by_user_message` 1 раз упал standalone, затем 3× зелёный standalone + файл 27p + состав 228p ×2 — флак среды (WARN «chat layer unavailable»), не волна.
- Бейслайн 17f+8e: на чистом HEAD-ворктрие воспроизведены **t5150 ×5, mca01_tx, mca10b kill-switch, mca20 reason-codes** — падают и без волны (DB-среда). `outgoing_guard` ×2 — `telegram_send.py` вне диффа (aiogram 3.29.1 среды). 8 errors — UI e2e (браузерный стенд). Классификация Builder'а подтверждена выборкой 4 групп + составом.

## 7. Residual §6 (честно, не потеряны)

1. Hostility-хвост фактчека — W3-фриз CFG-06: подтверждено байт-идентичностью фактчека; persisted чистит suppress-правило 5 (тесты).
2. Identity Direct («бот-абьюзер» в СИСТЕМНОЙ РОЛИ) — вне скоупа SF-07, задокументирован (сводка §1-примечание, §6.4).
3. 07A.1 postdeploy effective-payload — после релиза (READY_FOR_LIVE-класс, не в этом слайсе); 07C-G public_speech_guard — следующий слайс.

## 8. Гигиена диффа

- Код-периметр волны ТОЧЕН: 12 services + 14 tests изменено + 1 новый контракт-тест + канон-доки (architecture.md/backlog.md — новые тексты канонов с аннотациями CFG-07A-2) + 3 evidence-файла. NB: в брифе/сводке «13 services/tests + 15 тестов» — фактические числа 12/14 (расхождение книжное, состав множеств совпадает с ожидаемым).
- **Дерево НЕ равно «476e11a5 + только волна»**: в дереве есть незакоммиченные ЧУЖИЕ остатки других полос — `plans/features/asap8-v6-3-live-correction/*` (map-reconciliation, requirements-map), `plans/features/samples-ux/requirements-map.json` (deployed_commit), `plans/features/cfg/evidence/cfg-06/w7-dispute-metrics.json` (latency 6→5), `plans/archive/mca-17c-.../evidence.md`, а также старый untracked-мусор (tools/_*, node_modules, package.json, .playwright-mcp, _upd.py, verification_cache.json). На поведение кандидата не влияет.
- `requirements-map.json` (cfg) Builder'ом не тронут ✓: строки CFG-07A.* — 11 шт (L337 контейнер-context + required L341–L348 + L376/L377), все PENDING.

## 9. Леджер-долг оркестратора (после коммита, по плану)

- Привязать candidate_commit и заполнить evidence/статусы строк CFG-07A.* карты cfg: L342, L344, L346, L347, L348 (закрыты этим слайсом — по evidence 07a2), L341 (postdeploy 07A-1), L343/L345/L376/L377 (07C-G/positive-классы), L337 контейнер. Часть строк останется открытой до 07A-1.final/07C-G — это план, не дефект.

## Инструктаж оркестратору на коммит

Коммитить ТОЛЬКО файлы волны: 12 services (`chat/checkup/summary/search/web/youtube_prompts`, `direct_capabilities`, `nostalgia_prompts`, `nostalgia_worker`, `prompt_migrations`, `prompt_registry`, `prompt_style_blocks`), 14 tests, `tests/test_cfg07_backstage_contract.py`, `plans/docs/canon/architecture.md`, `plans/docs/canon/backlog.md`, `plans/features/cfg/evidence/cfg-07a/07a2-{summary,bytecheck,tests}.md|txt` + `review-07a2.md`. НЕ захватывать: samples-ux/asap8/mca-17c правки, cfg-06 w7-метрику, tools/_*, node_modules, verification_cache.
