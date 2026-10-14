# review.md — mca-asap-summary-hotfix (ASAP, round1027, MCA round 10.27)

- **Feature-ID:** `mca-asap-summary-hotfix`
- **Risk-Level:** R2 (prod-инцидент публикации саммари; задевает живой пайплайн Саммари и его
  интеграционные края, но Δ DDL=0 / Δ каталога=0 / 0 новых зависимостей / env-kill-switch)
- **Status: Approved**
- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (HEAD, master = origin/master)
- **Working-Tree-Hash (детерминированный manifest, 33 hotfix-файла, состояние ПОСЛЕ
  верифицированного восстановления EOL — см. «Прозрачность процедуры»):**
  SHA-256 = `c0f1634f47e2124a77801417f6fbfc1a5e32300016b4999fb1b8aacf7c2da928`
  (пер-файловые SHA256 первых 16 hex: `config/settings.py` d4c1827479df9a28,
  `services/summary_l2_writer.py` 22b9f6895f9b0954, `tests/test_summary_asap_hotfix_round1027.py`
  e0ed624cecce2908, `tests/test_summary_l2_writer.py` 96ace0bdde464502,
  `tests/test_tool_coordinator_round1026.py` 79a77b3d8966d4e2,
  `tests/test_round1025_f8_registry.py` c4edf4c43fbaa4c9,
  `tests/test_summary_deploy_round1026.py` a111745febe3a0f4,
  `tests/test_summary_publish_integration_round1026.py` c9e2fb0e1c353c80,
  README.md 8f70f84f45115ba7, plans/docs/param-registry-round1025.meta.md 55994f1e93855f11,
  + 4 JS round1025_hotfix7/8/9/10 + 19 py версия-пин-тестов; полный рецепт —
  `plans/reports/full_audit_results.md`, запись round1027-hotfix.)
- **Spec-Hash:** спецификация фичи (ASAP-режим, отдельного spec.md нет):
  `plans/features/mca-asap-summary-hotfix/tasks.md` SHA-256
  `c61f70b7a853ced55b1f0a12f76f5ea8e4b04406567547280f1c4bbc41e089d0` +
  `evidence.md` SHA-256 `562178d6f45ef59d7d536f6a8166f746008c47f2e4b6488ec206b8c67fa13665` +
  owner-блок `# ASAP` в `plans/current_task.md` (требование — строка 1882; файл SHA-256
  `eab376a452a9d71f3d4c6c6ebb1aa8f5c30b955d215546d7e229622fa9fead69`).
- **Git base и объём проверенных изменений:** base = HEAD `05bc870` (прод-базис 2.58.31).
  Рабочее дерево = pre-existing MCA-волна round1027 (~94 изменённых tracked-файла + untracked
  mca-модули) + ЭТОТ хотфикс. Ревью фокусировано на хотфиксе; mca-волна верифицирована
  на предмет НЕ-помех хотфиксу и консистентности её собственных пинов.

## Прозрачность процедуры (обязательная фиксация)

В процессе независимой верификации baseline-состояния была выполнена stash-проба
(`git stash push/pop` c последующим полным восстановлением). Проба выявила побочный
эффект: `core.autocrlf=true` перемотал все LF-рабочие копии modified-файлов в CRLF
(94 файла). Восстановление выполнено (обратное преобразование CRLF→LF всех изменённых
tracked-файлов) и верифицировано байт-точно: SHA-256 `web/api/routes.py` совпал с
freeze-пином mca-волны `f2ff90b6…` (тест `test_routes_file_unchanged` зелен),
JS-харнесс 48/48, полный pytest 9839/0. Два «упавших» теста, наблюдавшихся
на промежуточном (повреждённом пробой) состоянии, были артефактом пробы, а не
дефектами: `test_round1025_f8_registry::test_routes_file_unchanged` и два
JS-харнесса (`round1025_hotfix8_shell_aurora_test.js:111`, паттерн `data-glass="shell"\n`;
`round1026_s7_log_summary_filter_test.js:173`, паттерн `logLevel: function () {\n…`)
требуют LF-формы файлов, которая и является исходной. Финальные binding-хэши отражают
восстановленное (исходное) состояние.

## Хотфикс-дифф (проверенный объём)

- `services/summary_l2_writer.py` (+88): константа `REASON_TRIMMED_FOR_PUBLICATION`;
  `_trim_document_for_publication` (детерминированная обрезка «первые N абзацев» +
  бюджет RICH_MAX_CHARS снятием с конца; пусто → None fail-closed; метрики — только числа);
  `run_l2` — мягкий кап при trim ON обрезает, OFF — байт-в-байт прежний reject;
  `_log_complete` — `trimmed=1|no` в L2_COMPLETE + WARN-строка чисел.
- `config/settings.py`: `SUMMARY_L2_TRIM_ENABLED: ClassVar[bool] = _env_bool(..., True)`
  (env-only, вне dataclass-полей; остальной объём diff settings.py — mca-волна) +
  `APP_VERSION "2.58.31" → "2.58.32"`.
- `tests/test_summary_asap_hotfix_round1027.py` — НОВЫЙ, 10 тестов.
- `tests/test_summary_l2_writer.py` — обновлён `test_too_many_paragraphs` (trim ON) +
  новый `test_too_many_paragraphs_trim_off_fail_closed` (OFF → reject).
- `tests/test_tool_coordinator_round1026.py` — baund NOTE (`services/summary_l2_writer.py`
  санкционирован; остальной `services/summary_*` вне diff) + APP_VERSION-пин 2.58.32.
  (Изменения `web/api/routes.py`-пинов в этом и в deploy/publish-баунд-тестах —
  pre-existing mca-17a; пины консистентны с текущим routes.py — верифицировано.)
- Версия-пины `2.58.31 → 2.58.32` синхронно в 23 py-тестах + 4 JS-харнессах
  (rg: остаточных `"2.58.31"`-пинов в tests/ нет — только исторический комментарий).
- `README.md`: v2.58.32 + hotfix-запись; `plans/docs/param-registry-round1025.meta.md`:
  APP_VERSION 2.58.32.
- Артефакты: plans/features/mca-asap-summary-hotfix/{tasks,evidence}.md.

## Checks performed (независимо, не по заявлениям Builder)

1. **Полный pytest (собственные прогоны):** **9839 passed / 0 failed** (финальный прогон на
   восстановленном состоянии, ~229s; два предыдущих прогона дали 9839/0 и 9836/3 —
   «3 failed» были артефактом EOL-пробы, см. выше). Сфокусированно: hotfix-файл 10/10;
   связка hotfix+L2 52/52; срез S5/S6/S8/S9/deploy/coordinator/F8 342/342; байт-чувствительные
   freeze/JS-обёртки 63/63.
2. **JS vm-харнесс:** все 48 файлов прогнаны `node` индивидуально — **48/48, exit 0**
   (на восстановленном состоянии).
3. **`git diff --check`:** чисто (0).
4. **Runtime-репро прод-сценария (независимо):** 6 абзацев при капе 1 → `status=ok`,
   1 абзац, `trimmed_for_publication=True`, paragraphs_before=6/dropped=5; kill-switch OFF →
   `invalid/too_many_paragraphs`, document=None; 499 абзацев при капе 498 →
   `invalid/too_many_paragraphs`; прод-путь без `max_paragraphs` (резолв через
   `limits.max_summary_parts`) → ok/обрезка; APP_VERSION 2.58.32, trim default True.
5. **Контракт §99 не ослаблен (независимые вызовы валидатора):** абзац 950>900 →
   `invalid_paragraph`; 40×900=36000>32000 → `too_long` (fail-closed); 499 абзацев →
   `too_many_paragraphs`; цитата НЕ из пула пакета с именованной атрибуцией →
   `quote_attribution` reject; непроверяемая цитата без атрибуции → снятие кавычек
   (quote_unverified=1). Валидация выполняется ПОЛНОСТЬЮ до trim (trim принимает только
   уже-валидный документ; обрезка не может ввести невалидную цитату).
6. **Бюджетная петля trim:** 498×900-симв. абзацев при RICH_MAX_CHARS 32000 → kept=35,
   метрики согласованы; недостижимая ветка `keep=[] → None` исследована (cap=0 direct →
   fail-closed, артефакт reason="ok" — L-2); прод-путь закрыт клампом
   `resolve_l2_max_paragraphs` (≤0→6, ≥1, ≤498 — верифицировано кодом).
7. **Публикационная цепочка:** `_run_hybrid_l2` → `l2_result.usable` (только `ok`) →
   `_deliver_l2_rich` (rich_document_limits по ПОЛНОМУ тексту; обрезанный документ влезает:
   ≤498/≤32000; cover-провал → plain-фолбэк) / `_deliver_l2_plain` (`chunk_plain_blocks`
   ≤4096; HTML-провал → даунгрейд `format_plain_text`; 1 retry TelegramRetryAfter).
   Обрезанный документ не может застрять в «не публикуем».
8. **Граф-ветка:** `_compress_purge_extract_only`: `except GraphExtractDropped` → mark
   (очередь не стоит); `except Exception` (включая GraphExtractionError при LLMTimeoutError)
   → batch kept (НЕ помечен) → break → метод возвращает управление штатно.
   `compress_and_purge` (легаси-ветка): GraphExtractDropped → pass, прочие исключения →
   batch kept → break; GraphExtractionError не покидает эти методы — публикация в `_run`
   продолжается. GraphExtractDropped после 3 фейлов → ЯВНЫЙ mark (F1/ADR-1024-6 сохранён).
9. **Kill-switch:** `getattr(settings, "SUMMARY_L2_TRIM_ENABLED", True)` на ClassVar;
   `_env_bool` парсит `SUMMARY_L2_TRIM_ENABLED=false` → False; OFF-ветка байт-в-байт
   совпадает с прежним reject-кодом (сверка с HEAD-версией); Δ каталога=0 подтверждён
   рантаймом (fields=430, REGISTRY=473, GROUPS=102, TAB_RULES=21 — без изменений).
10. **R17:** новые логи (`L2_COMPLETE trimmed=…`, WARN `L2 trimmed_for_publication | …`) —
    только числа/ID/run_id, provider host-only; контент модели/секреты не текут.
11. **Версия-механика:** APP_VERSION 2.58.32 (settings:2130), README «Версия: v2.58.32»,
    meta-registry 2.58.32, 26 файлов пинов — согласованные; пин-тесты зелёные.
12. **Регресс mca-фич:** mca-волна файлами хотфикса НЕ задета; полный pytest (включая
    mca-тесты: mca01/02/04a/07/13, mca17a 70/70) и JS-харнесс — зелёные на итоговом
    состоянии; freeze-пины mca-волны (routes.py SHA) консистентны.

## Requirement/evidence coverage (цепочка «требование → фикс → тест»)

- Владелец (current_task.md:1882): «nanogpt не должен ломать весь пайплайн… Саммари
  срочно починить и деплой».
  → Диагноз независимо подтверждён: публикацию сорвал `too_many_paragraphs`
  (валидация контента, НЕ таймаут провайдера); граф-таймауты nano-gpt уже защищены.
  Замечание к трактовке: гибридный пайплайн по архитектуре НЕ имеет legacy-фолбэка
  (§106, ровно 2 LLM-вызова) — требование владельца «есть 100% рабочий фолбек»
  реализовано не третьим вызовом, а детерминированной обрезкой + существующими
  fallback-механизмами доставки (rich→plain, cover-error→plain). Трактовка адекватна
  интенту («публикация должна состояться») и зафиксирована в evidence.md.
- T-3918…T-3927 — все закрыты и независимо проверены (Checks 1–12).
- «Единичная L2-ошибка мягкого капа больше не отменяет публикацию» — устранено (репро 4).
- Жёсткий контракт §99 (498/32000/900), валидация цитат/атрибуции — не ослаблены (репро 5).

## Focused audit coverage

- Файлы хотфикса полностью прочитаны (не по diff-stat); соседние регионы
  (validate_l2_document, resolve_l2_max_paragraphs, слот §82, L2Result,
  _publish_plain_document, _publish_rich_document, chunk_plain_blocks) проверены на
  согласованность формата документа и лимитов.
- Интеграционные края: summary_generator._run (428: compress_and_purge безопасен;
  481: _run_hybrid_l2), summary_test_run.run_summary_test (без max_paragraphs → прод-резолв),
  summary_article_formatter (498/32000/900 — вне diff).
- Деплой-чувствительность: Δ DDL=0, Δ каталога=0, 0 зависимостей, env default ON →
  деплой без правок .env; откат env OFF + рестарт → байт-в-байт прежний путь (тест+репро).

## Counterexamples checked (попытки сломать фикс)

1. cap=0/отрицательный: resolve клампит; прямой `max_paragraphs=0` → fail-closed
   (публикации нет), артефакт reason="ok" — L-2, в проде недостижим.
2. Кап ≥ числа абзацев: trim не вызывается (условие len>cap).
3. Обрезка до атрибуции-валидации: невозможно — trim только после полного валидатора.
4. Бюджет после обрезки: документ уже ≤32000 до обрезки; обрезка только уменьшает;
   бюджетная петля — defense-in-depth (unit-проверена).
5. GraphExtractionError сквозь compress_and_purge: не эскалирует (код проверен).
6. Rich-канал с обрезанным документом: rich_document_limits по полному тексту — fits;
   иначе plain-фолбэк с полным текстом.
7. Kill-switch ON + trim выкинул всё (keep=[]): fail-closed None → invalid
   (недостижимо при реальных лимитах: title≤200 + абзац≤900 ≪ 32000).
8. Мягкий кап = жёсткий (hot=498): trim до 498 — валидатор и так пускает ≤498;
   эквивалент отсутствия обрезки.

## Blocking findings

НЕТ.

## Non-blocking debt (зарегистрировано, bounded)

- **L-HOTFIX-1 (Low):** README-счётчик «Тестов: 5946» = +10, фактический прирост тестов
  +11 (10 новых в новом файле + 1 новый OFF-сценарий). Косметика README; тестами не
  пинится.
- **L-HOTFIX-2 (Low):** константа `REASON_TRIMMED_FOR_PUBLICATION` объявлена, но в
  runtime не используется (маркер кладётся в metrics как `trimmed_for_publication=True`,
  reason остаётся `ok`); в недостижимой ветке trim→None при прямом `max_paragraphs≤0`
  `invalid_result` получает reason="ok" (status=invalid). Прод-путь закрыт клампом
  resolve_l2_max_paragraphs. Мелкая смысловая нестыковка для будущих правок.

## Unavailable checks

- Фактическое ТЕКУЩЕЕ hot-значение `limits.max_summary_parts` в прод-БД (bot_settings)
  и env `MAX_SUMMARY_PARTS` на сервере — вне сессии (доступа к прод-БД нет). Исторический
  read-only аудит прода от 06.09 (`plans/docs/prod-params-audit-2026-09.md`) показывал
  `limits.max_summary_parts=1`. Не блокирует: фикс корректен при любом значении
  (0/1/6/498 — все покрыты репро). Действие @DevOps после деплоя — evidence §6 п.1
  (рекомендуется выставить 6 — hot-ключ, без рестарта).
- Прод-верификация «следующее саммари публикуется» — только после деплоя
  (критерий evidence §6 п.4: отсутствие `L2_ERROR | reason=too_many_paragraphs`;
  при обрезке — строка `L2 trimmed_for_publication | paragraphs_before=…`).
- Живое репро прод-инцидента — невозможно и не требуется (unit/интеграция + runtime-репро
  покрывают механику).

## Вердикт для Orchestrator

**Status: Approved** — оба ревью-линза (требования/корректность + focused change audit)
независимо подтверждены на восстановленном состоянии: полный pytest 9839/0, JS vm-харнесс
48/48, `git diff --check` чисто, жёсткий контракт §99 не ослаблен, kill-switch точен,
граф-ветка не срывает публикацию, версия-механика согласована, mca-волна не задета
(её freeze-пины консистентны).

**Разрешение деплоя 2.58.32 — ВЫДАНО (@DevOps):**
1. Деплой штатный: `git pull --ff-only`, `systemctl restart admin_bot` (TimeoutStopSec=30).
   Правок .env/DDL/каталога не требуется (kill-switch default ON, env-only).
2. После деплоя проверить hot-ключ `limits.max_summary_parts` (аудит от 06.09 показывал 1)
   и выставить **6** (совпадает с L2-промпт-хинтом serious) — hot-ключ, рестарт не нужен.
   При значении 1 саммари публикуется, но одним абзацем (корректно, но коротко).
3. Откат: `SUMMARY_L2_TRIM_ENABLED=false` + рестарт = точный до-хотфиксный reject-путь.
4. Прод-верификация: следующее саммари в -1002661910336 публикуется; в логе нет
   `L2_ERROR | reason=too_many_paragraphs — не публикуем`; при обрезке видна
   `L2 trimmed_for_publication | paragraphs_before=… | kept=… | dropped=…`.
   Граф-таймауты nano-gpt могут продолжаться — они не влияют на публикацию
   (критерий «batch kept, pipeline continues»).
5. Внимание при коммите: рабочее дерево содержит незакоммиченную mca-волну round1027 —
   @Orchestrator должен отделить хотфикс от волны при коммите/пуше (хотфикс-файлы
   перечислены выше), либо согласовать единую волну осознанно; approval связан
   с указанными хэшами и не переносится на изменённое состояние.
