# LEDGER CUT — samples-ux → кандидат `27b1165a` (LANE LEDGER-SAMPLES-UX)

Дата: 20.10.2026 (ночь). Кандидат: `27b1165aced5c54faf83845160509b1ad2307318` = samples-ux v2 `29b91004` (ревью Approved, review-samples-ux.md) + R1-фиксы (restore_factory_preview видит tombstoned +1 REGRESSION-тест `test_restore_preview_includes_tombstoned_factory`; бейдж «Используется» nowrap; bulk-Inspector why передаёт `category=`). `deployed_commit` сознательно пуст — samples-ux ещё не на проде. Карта и сводка НЕ закоммичены (коммитит оркестратор).

## Итог по 77 строкам карты

| Статус | Кол-во | Кто |
|---|---|---|
| VERIFIED (engineering) | **64** | все обязательные инженерные требования (29 manual + 36 items из 48) |
| PENDING (owner_optional) | **1** | SU-7.OWNER-OBS — добровольное наблюдение владельца (реальный MiniApp на телефоне, живой цикл правка→деплой); инженерные половины закрыты соседями (SU-7.OFFLINE / SU-6.REGRESS / SU-ACC.NOLIVE / SU-7.OWNERLIVE) |
| PENDING (context) | **12** | заголовки разделов L00009…L00116 — не требования |
| READY_FOR_LIVE | **0** | гейт на review допускает READY_FOR_LIVE только для `live_required=true, live_when=postdeploy`; в карте таких строк нет — все 64 инженерные строки VERIFIED с candidate-bound evidence |
| PENDING engineering / FAILED | **0** | — |

## Гейт requirements_gate (strict_evidence=true, slice-graph)

```
check --stage review --slice <S> --candidate 27b1165aced5c54faf83845160509b1ad2307318 \
  --map plans/features/samples-ux/requirements-map.json
```

| Slice | scoped | errors | EXIT |
|---|---|---|---|
| SU-MIGR | 8 | 0 | **0** |
| SU-SEED | 9 | 0 | **0** |
| SU-FEWSHOT | 10 | 0 | **0** |
| SU-UI | 23 | 0 | **0** |
| SU-ACCEPT | 15 | 0 | **0** (SU-7.OWNER-OBS исключён гейтом как валидный owner_optional) |

Каждая строка: status=VERIFIED + ≥1 evidence с `candidate_commit=27b1165a…`, непустыми `ref`/`observation`, repo-relative `artifact_path` (forward slashes) и `artifact_sha256` = Get-FileHash фактического файла (пересчитан при привязке; все 22 артефакта не изменены относительно кандидата — git status их не показывает как изменённые).

## Привязки по волнам (основные артефакты)

- **SU-MIGR** — `tests/test_samples_categories.py` (12 passed: ровно 3 категории, v37 аддитивные колонки/no-new-tables, миграция сохраняет данные и идемпотентна, режим поля не тегов) + `tests/test_mca17c_invariants_round1047.py` (8 passed, user_version 36→37) + reconciliation.md (a)/(b) аудит с file:line.
- **SU-SEED** — `tests/test_samples_factory_persist.py` (12 passed: tombstone→seed не воскресает, edit→seed→persists+метка, restore только по confirm, preview-список затрагиваемых, factory_seed_absent хранит данные владельца, revision_conflict без потери, единственный ручной seed-эндпоинт).
- **SU-FEWSHOT** — `tests/test_add_exp_expression.py` (36 passed: §2 байт-пины EPISODIC/FREQUENT, F3-тексты отсутствуют, off/inherit не тронуты, fingerprint 64ec1c60e278 стабилен) + `tests/test_unified_core_route_coverage.py` (18 passed) + `tests/test_samples_fewshot.py` (16 passed: блоки General/Humor/Expression, MAT только approved effective-режима, bounded 1–3/0 с причинами, 0 доп. LLM, честный why).
- **SU-UI** — `tests/test_samples_ui_e2e.py` + `tools/ui_samples_ux_e2e.py` (6 браузерных сценариев: 360/390/667×375/1280, overflow=0, console errors=0; DOM иерархия §4.1, отдельный экран редактора, заводская плашка/сравнение/restore) + 7 скриншотов `evidence/build/shots/*.png` + `ui-e2e-report.json` + `tests/ui_p0a_ux_speech_compact_e2e.py` (соседний контракт зелёный).
- **SU-ACCEPT** — `tests/test_samples_acceptance.py` (8 passed: сквозные изоляция/409/категории-payload/why/zero-live структурный тест) + `tests/test_soul1_w4_sample_library.py` (20 passed §6-регресс) + `plans/owner_live_checks.md` §7 (2 пункта внесены, не гейты) + review-samples-ux.md (Approved).

## Свежесть доказательств на кандидате

- 20.10.2026 повторный прогон на HEAD `27b1165a` (дерево чистое по коду/тестам): `pytest test_samples_{categories,factory_persist,fewshot,acceptance} + test_add_exp_expression + test_soul1_w4_sample_library + test_mca17c_invariants_round1047 + test_unified_core_route_coverage` = **130 passed**; `test_samples_ui_e2e.py` = **1 passed (6 сценариев)**.
- Исходный композит: build/README.md (47 samples + 136 регресс + e2e 0 failures) и review-samples-ux.md (130 passed, Approved на `29b91004`); R1-фиксы вошли в кандидата с заявленными перегонами «12+8+68+e2e green» (сообщение коммита), независимо подтверждено прогонами выше.

## Честные оговорки (не гэпы, зафиксированы в observations строк)

1. **PostgreSQL**: контур библиотеки SQLite-only by design (GEN-R4, memory-контур); PG-прогон N/A и честно помечен в observations SU-CAT.MIGRATE и SU-7.OFFLINE со ссылкой на reconciliation.md (f) и build/README.md — не «прогнали и забыли».
2. **SU-7.OWNER-OBS** остаётся PENDING — добровольное наблюдение владельца по `plans/owner_live_checks.md`; из review-гейта исключается штатно (validated owner_optional),release-гейт его тоже пропускает.
3. Ревью и композитные прогоны выполнены на `29b91004`; кандидат добавляет только 3 R1-фикса (дифф 4 файла, +42/−10) — доказательства обновлены перегоном на `27b1165a`.

## Инцидентальные находки

- В рабочем дереве есть чужие незакоммиченные изменения параллельных полос (`services/factcheck_orchestrator.py`, `tool_router.py`, `smartmodule_phrases.py`, `mca_events.py`, asap8/cfg-планы) — классификация: unrelated/параллельная работа; на 22 артефакта этой карты не влияет (все артефакты чисты относительно кандидата). Оркестратору на заметку при коммите.
- Непослованные ревью-рекомендации (b)1–3 закрыты в R1-коммите; (c) F8-bump избыточен — зафиксировано в review/reconciliation.

## Next (оркестратор)

1. Закоммитить карту + `evidence/` (включая эту сводку) отдельным docs-коммитом (код/тесты не трогать).
2. Штатный деплой по PET_PROJECT → `check --stage release --candidate 27b1165a… --deployed-commit <факт>`; после деплоя заполнить `deployed_commit` и продолжить очередь current_task.
