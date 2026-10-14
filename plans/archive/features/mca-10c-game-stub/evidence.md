# mca-10c-game-stub — evidence (T-5068/T-5069)

**Дата:** 06.10.2026. **Статус:** T-5068 ✅, T-5069 ✅ (4/4 focused-тестов зелёные).
**Fingerprint:** worktree `C:\Code\Python\adminbot`, HEAD `main` на момент работ;
Δ этой фичи = 2 новых файла (+ этот каталог plans). `git status`: прочие
изменённые пути (`plans/docs/mca-round1027-arch-frames.md`,
`plans/workflow_state.md`, `tools/_ui_asap43_*`, `node_modules/`) —
pre-existing, этой фичей не создавались и не изменялись.

## Что реализовано

- **`services/mca_game_stub.py`** (NEW, T-5068) — изолированный неактивный stub §14.12:
  - `GameStubOutcome` — frozen-dataclass типизированного `not_implemented`-исхода
    (`status="not_implemented"`, `reason="game_stub_inactive"`, `implemented=False` —
    без поля значения/индекса, случайного результата нет);
  - `GameStub(random_source: RandomSourceService | None = None)` — публичная точка
    входа; DI-шов mca-10a (`RandomSourceService`, `services/mca_random_source.py:7–9`)
    типизирован под `TYPE_CHECKING` (0 runtime-импорта services/SmartModule);
    источник сохраняется и **никогда не вызывается** (0 draw/квоты/сети);
  - `await GameStub().run(action)` — единственный вход, всегда честный
    `not_implemented`; docstring: пометка «**Заготовка, не реализовано**», единственное
    намеренно неактивное исключение из «всё ON» (§2.18, `:39`), DI = будущий путь
    активации, без kill-switch (неактивность конструктивная, `requirements-map.md` §6 п.3);
  - нет: БД, scheduler, регистрации tools, Telegram handlers, UI, событий
    `mca_events`, kill-switch; reason-код локальный, канон `REASON_CODES` не расширен
    (canon 12 +0); **Δ DDL = 0, Δ каталога = 0** (F8 NOT_APPLICABLE).
- **`tests/test_mca10c_game_stub_round1042.py`** (NEW, T-5069) — 4 focused-теста (ниже).
- Ничего не регистрировалось, ничего не импортирует stub: bot.py / SmartModule /
  tool_router / handlers / coordinator не изменялись.

## Тесты — точные команды и результат

```
.venv\Scripts\python.exe -m pytest tests\test_mca10c_game_stub_round1042.py -v --no-header
→ 4 passed in 2.71s   (финальный прогон; после фикса ast-гейта TYPE_CHECKING)
```

| # | Тест | Покрывает |
|---|---|---|
| 1 | `test_stub_returns_not_implemented_without_side_effects` — вызов → `not_implemented`; `mca_events.pending_size()==0`; `REASON_STUB_INACTIVE not in REASON_CODES`; нет `value`/`index` | MCA10C-R3, canon+0 |
| 2 | `test_di_seam_accepts_real_source_without_invoking` — реальный `RandomSourceService()` принят в DI; touch-spy (счёт ЛЮБОГО доступа к атрибутам) = **0** | MCA10C-R2, R5 |
| 3 | `test_stub_runtime_imports_stdlib_only` — ast: runtime-импорты ⊆ {`__future__`,`dataclasses`,`typing`}; TYPE_CHECKING-шов не считается; 0 services/SmartModule | MCA10C-R1 |
| 4 | `test_grep_gate_zero_registration` — 0 упоминаний `mca_game_stub`/`GameStub`/`game_stub` в bot.py, services/ (вне stub), handlers/, SmartModule/, tools/, web/, config/ | MCA10C-R4, R5, A36 |

## Grep-gate (независимо от теста)

```
git grep -n "mca_game_stub\|GameStub" -- . ":(exclude)plans" ":(exclude)tests" ":(exclude)services/mca_game_stub.py"
→ exit 1 (0 совпадений в runtime-коде)
```

## Приёмка A36 (`current_task.md:917`)

Импорт и вызов stub → `not_implemented`, 0 сети/БД/событий/квоты (тесты 1–2:
нет db, spy=0, pending=0); в tool registry / меню / командах игровых действий
ничего нет (тест 4 + git grep). Существующие игровые команды не тронуты —
diff фичи не содержит ни одного изменённого runtime-файла (только NEW-файлы).

## Для T-5070 (Reviewer) / T-5071

- REGRESSION-база для Reviewer: до фикс-прогона был 1 красный (ast-гейт
  захватывал импорт под `TYPE_CHECKING`) — исправлен сам гейт теста, прод-код
  не менялся; финал 4/4.
- T-5071: stub на проде не активен — проверять по §20.2 `:1020` (0 игровых
  действий, 0 draw stub-происхождения); эффективное состояние верифицируется
  на `mca-release`.

## Verdict T-5070 (Reviewer, независимая проверка)

**Решение: Approved.** Release — DEFERRED_TO_RELEASE (складирован в Wave-4-поезд по решению Orchestrator): заготовка доезжает до прода со следующим деплоем, на текущем состоянии остаётся неактивной.

Проверено независимо (HEAD `44c6fd7`, uncommitted NEW-файлы):
- **Дельта чистая** — `git status --porcelain` + `git diff HEAD --stat`: изменены только pre-existing docs (`plans/docs/mca-round1027-arch-frames.md`, `plans/workflow_state.md`); код-дельта = ровно `services/mca_game_stub.py` + `tests/test_mca10c_game_stub_round1042.py` + этот каталог. Прочий untracked (`node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*`, `plans/verification_cache.json`) — pre-existing шум, фиче не принадлежит.
- **Модуль** — DI-шов mca-10a под `TYPE_CHECKING` (`RandomSourceService`, `services/mca_random_source.py:7–9`), frozen `GameStubOutcome`, `run()` → `not_implemented`/`game_stub_inactive` без side effects; runtime-импорты — только stdlib; reason-код локальный, канон `REASON_CODES` не расширен; R17 — секретов нет; kill-switch отсутствует (неактивность конструктивная).
- **Тесты запущены мной**: `.venv\Scripts\python.exe -m pytest tests\test_mca10c_game_stub_round1042.py -v --tb=short` → **4 passed in 2.75s**.
- **Grep-gate повторён** (`git grep -nE` с exclude plans/tests/модуля + `rg` по всем `*.py` дерева без node_modules): 0 совпадений — импорта/регистрации в bot.py/services/handlers/SmartModule/tools/web/config нет.
- **§14.12 (`current_task.md:718–728`)** соблюдён: изолированный модуль вне SmartModule, DI-only, `not_implemented` без случайного результата и side effects, 0 БД/scheduler/tools/handlers/UI, активным потребителем QRNG не является, квоту не расходует.

Блокирующих и инцидентальных находок нет. Следующий шаг: Orchestrator — T-5071 (release-проверка неактивности на `mca-release`, §20.2 `:1020`).