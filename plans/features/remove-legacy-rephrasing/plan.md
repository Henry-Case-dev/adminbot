# REMOVE-LEGACY-REPHRASING v2.0 — план срезов

**Источник (дословный, неизменяемый):** `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md` (242 строки).
**Задача:** `remove-legacy-rephrasing-01`. **Карта:** `requirements-map.json`, **граф:** `slice-graph.json`.
**Статус:** планирование; ни одна строка не реализована и не проверена (все 162 обязательных строки — `PENDING`, `evidence: []`, `candidate_commit: ""`).

## Что это за коррекция

Владелец требует убрать не отдельный Form Guard, а первопричину: незапрошенное повторное литературное написание уже готового ответа, дополнительные попытки его «починки» и незаметную замену содержания после L2. Итог: у содержательного ответа Direct и Initiative ровно **один финальный авторский этап**; после него допустимы только технически необходимые детерминированные несмысловые преобразования.

Коррекция заменяет в пересекающейся зоне: UR-15 (post-L2 Form/Numeric/Format retry при обычном Writer), свободные retry-ветви BGS-04, детектор отрицаний BGS-04.10 — только там, где он охранял удаляемое свободное преобразование. BGS-01/02/03 подтверждены без изменений и исполняются, а не пересматриваются.

## Срезы и волны

| Срез | Волна | Зависит от | Обязательных строк | Наблюдаемый результат |
|---|---|---|---|---|
| RLR-01-ROUTE | W1 | — | 32 | Одна финальная логическая генерация на ход; plan/evidence до Writer, после — только разрешённые deterministic ops; `silent`/`react` без L2 |
| RLR-02-LEGACY | W2 | RLR-01 | 12 | Достижимого `tool-final → JSON → Verbalizer` нет; флаг/отключённый L1/failover его не возвращают |
| RLR-03-FORMCONTRACT | W3 | RLR-02 | 12 | Свободный чат больше не сравнивает итог L2 с tool-черновиком; явные трансформации и фактчек сохраняют узкий контроль данных |
| RLR-04-REROLL | W4 | RLR-03 | 38 | Ни одно семейство retry/guard не перегенерирует и не правит смысл готового текста |
| RLR-05-ADMIN | W1 (backend) / после UR-F·PVR (UI) | — | 11 | Старые ключи классифицированы и игнорируются; dead controls нет; промпты и версии не тронуты |
| RLR-06-OBSERVABILITY | W5 | RLR-04 | 10 | Трасса по `correlation_id` показывает операции, LLM-вызовы и `semantic_rewrite_count=0` |
| RLR-07-PROOF | W6 | все W1–W5 | 32 | Route matrix по HEAD, 21 сценарий R-08 в реальных конфигах, реальный LLM-прогон |
| RLR-08-DOD | W7 | RLR-07 | 15 | Все девять пунктов §10 подтверждены по кандидату; матрица и route matrix в отчёте |

Параллельных писателей максимум два: `RLR-01-ROUTE` и backend-часть `RLR-05-ADMIN`. Цепочка 01→02→03→04→06 сериализована намеренно — все пять срезов пишут `services/direct_chat_service.py`, а §9.3 прямо запрещает второго владельца этого файла.

## Обязательные правила записи

- `services/direct_chat_service.py` — один владелец за раз: 01 → 02 → 03 → 04 → 06.
- `services/negative_constraints.py` — сначала RLR-03 (граница «что считается трансформацией»), затем RLR-04 (удаление retry-петель).
- `services/evidence_policy.py`, `services/public_speech_guard.py` — только RLR-04.
- `web/**` — только RLR-05 и только после слияния UR-F/PVR.
- `tests/**` — срезы добавляют лишь свои `tests/test_rlr_*.py`; общий прогон и правки чужих тестов — RLR-07.
- `plans/features/remove-legacy-rephrasing/` — `migration-manifest.json` у RLR-05, `evidence/**` у RLR-07, `dod-report.md` у RLR-08.

## Архитектура

`ARCH_REUSE_CONFIRMED`: коррекция демонтирует существующее поведение и опирается на уже принятые контракты (TurnRequest/L1/L2 и ToolEvidence из UNIFIED-REPLY, `negative_constraints`, `evidence_policy`, `public_speech_guard`, `param_catalog`/`config_migrations`, `mca_trace`/`oversight`). Новых общих интерфейсов не замораживается: поля трассы аддитивны, migration manifest классифицирует существующие ключи. Если Builder упрётся в новую общую границу (новый статус ToolEvidence, новая версия схемы трассы, общий валидатор на несколько подсистем) — стоп и вопрос Architect.

## Доказательства

Каждая `VERIFIED`-строка на review-стадии получает candidate-bound evidence: `ref`, `observation`, `type`, `artifact_path` (реальный repo-relative файл), при стабильных отчётах — `artifact_sha256`. Плановые строки остаются `PENDING`. DONE не выдаётся по зелёным unit-тестам, внешнему документу, изменению boolean flag, комментарию `paraphrase disabled` или непроверенному деплою (R-09.5).

## Проверка

```
py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/remove-legacy-rephrasing/requirements-map.json \
  --stage plan --repo .
```

Ожидаемый результат: `stage=plan inventory=112 manual=77 scoped=0 errors=0`.
