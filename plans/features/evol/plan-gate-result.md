# EVOL — результат plan-гейта и волновой план (PM, 30.10.2026)

## Гейт

```
python .venv/Scripts/python.exe C:\Users\main\.config\opencode\tools\requirements_gate.py \
  check --map plans/features/evol/requirements-map.json --stage plan --repo .
stage=plan inventory=304 manual=236 scoped=0 errors=0   → EXIT 0
```

- Источник: `plans/current_task.md` (EVOL_Adminbot_Epic_FINAL_2026-10-29.md), sha256 `54454df5…b745`, 908 строк — прочитан целиком.
- Карта: schema `openworkflow-coverage-v1`, `strict_evidence: false`, `slice_graph_path: slice-graph.json`.
- Покрытие: все **304** inventory-строки источника классифицированы (46 `required` + 235 `duplicate` + 23 `context`);
  236 manual-строк в `additional_requirements` (жирные абзацы, таблицы целевых схем, преамбулы разделов, решения
  владельца v0.7/v0.8/v0.9).
- Требования: `EVOL-001..045` + `EVOL-DoD` (раздел 12 целиком + организационная приёмка раздела 13; каждый из 40 DoD-
  пунктов проведён к owning-задачам в reason дублирующих строк).
- `live_required: true` только у **EVOL-010** и **EVOL-031** (postdeploy, agent-проверка прод-логов/телеметрии);
  owner live-checks нигде не являются блокерами (правило PET_PROJECT); `NOT_OBSERVED` допускается только для
  live-эффектов и внешних событий.
- Граф: 39 слайсов, схема `openworkflow-slices-v1`, без циклов; конфликтов write-scope нет (UI-слайсы сериализованы
  одной цепью из-за монолитного SPA-shell `web/index.html` + `web/app.js`).

## Волны и слайсы (см. slice-graph.json)

| Волна | Слайсы | Примечание |
|---|---|---|
| W0 | `EVOL-W0-AUDIT` | read-only аудит до изменения кода: завершение предыдущих задач, HEAD/БД/провайдеры, карта точек потребления |
| W1 (backend, параллельно) | `B-EMBED`(010, P0), `B-VISION-ADAPT`(011), `B-TELEMETRY`(013), `B-QUOTE`(015), `B-PROMPTREG`(016), `B-MEMCYCLES`(008/009), `B-SMARTCACHE`(031), `B-SETREG`(040); `B-FACTS`(006/007) после `B-EMBED` | ≤3 writer-лейна по выбору оркестратора |
| W2 | `B-PROMPTMIG`(012) → `B-PROMPTCONV`(018); UI-цепь: `UI-DESIGN`(022) → `UI-RESPONSIVE`(025) → `UI-NAV`(023) → `UI-HEALTHGLASS`(032, ← телеметрия 013) → `UI-CONTROLS`(043) → `UI-KEYBOARD`(044) → `UI-MOTION`(045) | UI-цепь = один писатель shell |
| W3 | продолжение UI-цепи: `UI-VISION-CHECK`(019) → `B-EXP`(020) → `UI-STATUS-WIDGETS`(001–005) → `UI-STORIES`(021) → `UI-SECTIONS-MOVE`(026) → `UI-MODULES`(027+036) → `B-INITFLAGS`(035) → `UI-AI`(028) → `UI-PROMPTHIST`(017) → `UI-PROMPLIB`(038) → `UI-SPEECH`(034+041) → `UI-INSPECTOR`(042) → `UI-MODELS`(039) → `UI-MEMORY`(029) → `UI-ACCESS-OTHER`(030) → `UI-SEARCH`(037) → `UI-CLEANUP`(024) | реальные join-барьеры: 001–005 ← 006–009; 028 ← 031+016; 037 ← 040 |
| W4 | `EVOL-F-MEMES`(014) | зависит от 016 (реестр промптов, литерал «Создай мем с шрифтом импакт:»), 035 (аудит Initiative), W0 (аудит image-gen), UI-платформы |
| W5 | `EVOL-UI-FULLDOD`(033) → `EVOL-RELEASE`(EVOL-DoD) | интеграция обоих чатов, все 45 ID, безопасный деплой, production read-only verification, отчёт с матрицей DONE/FAILED/NOT_OBSERVED |

Барьеры графа воспроизводят зависимости документа: 012/017/018 ← 016; 014 ← 016+035; 032 ← 013 (достоверные статусы);
033 ← 032 + вся UI-платформа; 026 ← 021; фундамент W1 перед разделами W3.

## Классификация архитектуры

- `ARCH_REUSE_CONFIRMED` (основной объём): `services/prompt_registry.py` / `prompt_factory.py` / `prompt_composer.py`
  (домен 016–018), `services/smart_cache.py` (031), `services/quote_resolver.py` + `canonical_*` (015),
  `services/memory_health.py` и mca_* (006–009, 020), существующий Vue SPA (`web/index.html`, `web/app.js`,
  `web/static/*.js`, `web/api/*.py`) для всех UI-слайсов; защищённые `glass-refraction.js`, `aurora-flow.js`,
  `polygon-background.js` — вне write-scope всех слайсов.
- `ARCHITECT_REQUIRED` (две точки, до старта соответствующих слайсов):
  1. **Контракт реестра промптов (016) и миграционный переход (018)** — новый общий интерфейс для всех точек сборки
     LLM-запросов (включая скрытые промпты в коде). Документ фиксирует модель данных и семантику приоритетов 1–5, но
     план миграции/обратной совместимости PG+SQLite и CI-механизм должен быть подтверждён Architect до реализации.
     Зависимые: 012, 017, 018, 028, 034, 038, 042, 014.
  2. **Механизм tint-в-материале для EVOL-032** — документ прямо требует выбрать технический путь после аудита
     текущего рендера («если прямого tint API нет … остановить внедрение до совместимого решения»). Нужен
     Architect-верdict о совместимом способе тонирования без изменения refraction/alpha/геометрии.
     Зависимые: 032 → 033, 045.

## Ограничения

- `candidate_commit` пуст — заполняется на review/release-стадиях; strict_evidence не включался (без обоснованной
  evidence-конвенции на старте; включение — отдельное осознанное решение с миграцией).
- Write-scope слайсов — плановые ожидания; фактические файлы Builder может уточнить через ограниченное обновление
  графа (у оркестратора), не через молчаливое расширение.
