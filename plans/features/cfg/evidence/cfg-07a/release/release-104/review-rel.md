# REV-REL-258104 — независимое ревью релизного поезда 2.58.104

**Вердикт: Approved** (push + deploy). Дата: 21.10.2026. Ревьюер: REV (lane REV-REL-258104).

## Привязка кандидата

- Поезд: `8ea6ed4e016cf8fbb23e1447cb02503c54131650` (HEAD master), предок-прод: `79df9f5d` (merge-base подтверждён, цепочка линейна: 79df9f5d → 2a3e4fc9(bump .103) → ce77b2c4 → d860a529 → dd6acf83 → 04593c8f → 8ea6ed4e).
- `d860a529` (guard-словарь+тесты): numstat vs родителю ce77b2c4 = public_speech_guard 243+/5-, test_cfg07_guard_07d5 653+, 07d5-summary 162+, map 10 — **1:1 с review-07d5-r2** (Approved, ревью вело uncommitted-дерево).
- `04593c8f` (runtime core, **ревьюился впервые, по существу**): ровно 3 файла (factcheck_service +25, negative_constraints +86/-10, prompt_style_blocks +14).
- `dd6acf83`: только леджер CFG-07A. `8ea6ed4e`: bump 31 файл, +33/-33.
- Гейт: `requirements_gate.py check --stage review --slice CFG-07A --candidate d860a529...` → **EXIT 0** (inventory=246, manual=42, scoped=12, errors=0).
- Дерево: git status чист по коду (только foreign plans/docs/scratch).

## Runtime core 04593c8f — проверка по существу (новое ревью)

1. `_metatext_retry_reason()` (factcheck_service): единственный V2-гейт — тот же `pipeline_v2_enabled()` (hot `flags.factcheck_pipeline_v2` → env → False, never raises); двойной fail-soft, никогда не бросает. Runtime-пробы: default OFF → `None` (байт-паритет); свежий процесс env=1 → callable; честное ограничение («проверил — не нашёл подтверждений») → None (не вычищается); дословные формулы → None (идут в детерминированный срез, бюджет retry не тратится).
2. `verbalize_validated(metatext_reason=...)`: OFF (`None`) — новых ключей stats нет, early-return/`better`-кортеж вырождаются в прежнюю семантику (проверено чтением + тестами байт-паритета). ON: ровно ≤1 metatext-повтор (`metatext_retry_used`) из общего bounded-бюджета (max_retries 2/1 на двух call-site не изменились), приоритет metatext→form→numeric→cliché; при неудаче — `metatext_fallback=True` + `strip_guard_findings` (идемпотентный срез, FA-08 покрыт через `_MACHINE_STRIP_RES`). Kill-switch `SYSTEM2_VALIDATOR_LOOP_ENABLED=false` нетронут. Другие вызывающие (direct_chat ×2, summary_generator ×1) не передают metatext_reason → паритет.
3. `METATEXT_RETRY_SYSTEM_PROMPT`: +14 строк аддитивно, существующие блоки не тронуты (диф проверен), R17 — подставляется код причины, не приватный текст.
4. FA-08: детектор/strip живут в public_speech_guard (d860a529, отревьюван); интеграция в negative_constraints — деградационный срез `_metatext_strip`, консистентна.
5. Сеть: grep поезда `79df9f5d..8ea6ed4e` (services/) на requests/httpx/aiohttp/urlopen/bot.send — **0 попаданий**, 0 новых отправок.
6. Импорты: `Callable` импортирован; циклический импорт orchestrator внутри функции — только runtime, безопасно (тесты + импорт-проба).

## Тесты (все на HEAD `8ea6ed4e`, интерпретатор .venv aiogram 3.31.0)

- test_cfg07_guard_07d5.py: **41 passed** (собрано 41).
- Фактчек-семья orchestrator/gate/context/planner/renderer/service + route-coverage 18 + negative_constraints + anticliche + help-sync 24 + JS-unit 38: **346 passed, 0 failed**.
- pins24 (24 пин-файла бампа): **868 passed, 0 failed** — подтверждено независимо.
- F8 registry: 29 passed (582 == REGISTRY, delta 171); settings import: APP_VERSION=2.58.104.

**Примечание по среде (не дефект поезда):** прогон под глобальным `py -3` (aiogram 3.29.1 < 3.30) даёт 1 фейл `test_summary_publish_integration…test_on_l1_not_usable_level2_l2_publishes_article` — `_rich_media_supported()` честно возвращает False → plain-путь. Бисект в worktree (`79df9f5d`/`dd6acf83`/`04593c8f`) показал тот же фейл на базе → пре-существующая чувствительность к версии aiogram интерпретатора, НЕ регрессия поезда. Под .venv (3.31.0) — 868/868. Worktree убраны, мусора нет.

## Бамп 8ea6ed4e

31 файл == SET EQUAL с процедурой 103 (Compare-Object: 0 различий); +33/-33; settings/README/meta/24 py/4 js пины 2.58.103→2.58.104; F8-meta HEAD=`d860a529` (кодовая линия; фактический HEAD 8ea6ed4e — docs поверх, прецедент 103); stale-пинов 2.58.103 в settings/README/meta нет (2.58.103 осталась только в plans/evidence — история, корректно); ΔDDL=0 (db/ migrations/ *.sql — 0 строк); Δ внешних зависимостей = 0.

## Безопасность/паритет

- 0 сетевых отправок в новом коде (grep, п.5 выше).
- V2-гейт един: единственное новое место чтения рубильника — `_metatext_retry_reason`, тот же `pipeline_v2_enabled`.
- OFF default → поведение прод-2.58.103 байт-в-байт (детектор не вызывается).
- Прода: деплой только после push; postdeploy-наблюдение 07C.6-стиль (детекторы/retry), healthz 2.58.104.

## Леджер CFG-07A (dd6acf83)

Slice CFG-07A: 10 строк VERIFIED + CFG-07A.F (additional) VERIFIED + CFG-07D.1.OBS owner_optional (READY_FOR_LIVE, owner_policy_ref=plans/owner_live_checks.md, engineering-парта CFG-07D.1 VERIFIED, live_required=false) — standing rule соблюдён; gate EXIT 0 errors=0. CFG-07A.1: VERIFIED, live_required=true, note привязан @ deployed 2a3e4fc9 (2.58.103).

## Rollback

- Граница отката поезда 104: `release/fix-2.58.103` = `79df9f5d` — создать при push (ветки ещё нет; предшественник release/fix-2.58.102 = a3535b68 на origin).
- ΔDDL=0 → откат cold git-уровня без миграционных последствий; софт-выключение 07D.5 = env `FACTCHECK_PIPELINE_V2_ENABLED=false` (детекторы/v2-контур не активны).

## Постдеплой (после деплоя — оркестратор/DevOps)

1. healthz: `{"status":"ok","version":"2.58.104"}` (loopback + внешний 443).
2. Фактический deployed SHA = 8ea6ed4e (immutable-commit deploy с origin/master).
3. 07C.6-стиль наблюдение: детекторы FA/MB + metatext-retry на прод-байтах (v2-контур; при OFF — подтверждение отсутствия новых telemetry-ключей).
4. **Леджер-хвост (обязательный)**: привязать CFG-07A.1 note → `VERIFIED @ deployed 8ea6ed4e (2.58.104)` + top-level `deployed_commit` → фактический; затем `requirements_gate.py check --stage release --candidate 8ea6ed4e --deployed-commit 8ea6ed4e` → EXIT 0 перед закрытием.

## Итог

Блокеров нет. Все обязательные приёмочные элементы волны 07D.5 + поезда 104 подтверждены на точном кандидате `8ea6ed4e` (тесты, оффлайн-гварды, гейт, OFF-паритет, 0 сеть, ΔDDL=0, SET EQUAL бампа). Единственное незначащее расхождение — артефакт интерпретатора ревью-обвязки (aiogram), задокументирован выше.
