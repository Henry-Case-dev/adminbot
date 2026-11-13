# I4 — Unmapped reason codes (binding evidence)

Стадия I4 (срез `S10-LEARNING-INCIDENTS`) эпика `SMART-EXECUTION-RELIABILITY-01`.
Реализация и тесты — Builder, независимое ревью — Reviewer, привязка карты —
PM/Orchestrator. Деплой не выполнялся; production не менялся.

* База: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199, deployed), ancestor HEAD = да.
* Ветка: `smart/i4-codes`; worktree:
  `WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-4634be53`.
* Кодовый коммит (CODE_SHA): **`4bf114007e1e9549609b2259403c89282e04b5aa`**
  (`services/mca_events.py` +26 строк — только расширение единственного
  `REASON_CODES`; `tests/test_smart_i4_reason_codes.py` +318 строк; пять
  легаси-пинов длины словаря `341 → 357` в пяти файлах).
* Требования карты: `SXR-I4-01` (source `plans/current_task.md`, §I4, строки
  12860–12888) и `SXR-I4-02` (`additional_requirements`, MAN-SXR-I4-02-1134/1136/1138),
  оба `live_required=false`, `live_when=preprod`.
* Границы записи: изменения только в `services/mca_events.py` и тестовых
  файлах. `services/mca_experience*.py`, `mca_incidents.py`, схема БД,
  миграции, планировщик, `config/settings.py`, пороги warning не менялись.

## 1. Установленная причина (owner §I4 + recon §8)

`build_event()` (FC-OBSERVABILITY-01) не теряет неизвестную причину: код вне
`REASON_CODES` заменяется стабильным маркером
`unmapped:<sha256(code)[:8]>` + WARN без сырого значения. Механизм исправен —
дефект был в **словаре**: producer-коды реальных эмиттеров отсутствовали в
`REASON_CODES`, поэтому прод писал маркеры вместо причин.

Recon 14.11.2026 §8 зафиксировал 8 маркеров; каждый декодируется в имя
producer-кода, реально присутствующего в emit-сайте (`emit_mca_event` /
`emit_cover_event` / `stage_event`):

| маркер из прода | producer-код | sha256(code)[:8] | emit-сайт |
|---|---|---|---|
| `18d14796` | `fresh_stream_lag` | `18d14796` ✓ | `mca_experience_jobs.py:3433` |
| `4f8aced7` | `detector_scan` | `4f8aced7` ✓ | `mca_experience_jobs.py:1776` |
| `a999e0fd` | `detector_fact_user` | `a999e0fd` ✓ | `mca_experience_jobs.py:1772` (шаблон `detector_{class}`) |
| `373cf2f7` | `tool_claim` | `373cf2f7` ✓ | `tool_router.py:4963` → `temporal_factcheck.stage_event` |
| `d07c353d` | `limit_unknown` | `d07c353d` ✓ | `summary_generator.py:3454` |
| `69e80269` | `archive_direction` | `69e80269` ✓ | `mca_experience_jobs.py:2534` |
| `38dc4799` | `archive_coverage` | `38dc4799` ✓ | `mca_experience_jobs.py:2673` |
| `54c94ee2` | `samples_selected` | `54c94ee2` ✓ | `mca_sample_library.py:1913` |

Recon §8 не декодировал шесть «дополнительных» маркеров (сверял sha8 с именем
события). Здесь они декодированы сверкой sha8 с кандидатными именами кодов
эмиттеров; совпадение всех восьми дайджестов и наличие того же литерала в
emit-сайте — независимое подтверждение (тест
`test_marker_digest_matches_producer_code` + этот аудит).

## 2. Что изменено

Только пополнение единственного словаря `services/mca_events.py::REASON_CODES`
(341 → 357). Классификация не переносится в словарь: исход/уровень остаются
у эмиттера.

| Код | Emit-сайт | Исход/уровень эмиттера | Класс |
|---|---|---|---|
| `fresh_stream_lag` | `mca_experience_jobs.py:3433` | `skipped` / WARN | штатный skip |
| `stale_belief` | `mca_experience_jobs.py:3460` | `skipped` / WARN | штатный skip |
| `lesson_contradiction` | `mca_experience.py:1987` | `skipped` / WARN | штатный skip |
| `detector_scan` | `mca_experience_jobs.py:1776` | `success` / INFO | информационный проход |
| `detector_preference` / `detector_correction` / `detector_fact_user` | `mca_experience_jobs.py:1772` (`detector_{class}`) | `success` / INFO | проход детектора |
| `archive_direction` | `mca_experience_jobs.py:2534` | `success` / INFO | проход архива |
| `archive_coverage` | `mca_experience_jobs.py:2673` | `success` / INFO | проход архива |
| `samples_selected` | `mca_sample_library.py:1913` | `success` / INFO | отбор примеров |
| `owner_reset_learning` | `mca_humor_feedback.py:969` | `success` / INFO | действие владельца |
| `anomaly_recovered` | `summary_generator.py:2904`, `:3402` | `success` / INFO | восстановление cover |
| `cover_context_missing` | `summary_generator.py:2911`, `:3411` | `skipped` / INFO | degraded публикация |
| `limit_unknown` | `summary_generator.py:3454` | `start` / INFO | наблюдаемый предел |
| `prompt_limit_exceeded` | `cover_style_jobs.py:3027` | `failed` / WARNING | реальный failed publish |
| `tool_claim` | `tool_router.py:4963` | `success` / INFO | tool-маршрут фактчека |

Второй реестр не создан: `REASON_CODES = frozenset(...)` для MCA-событий
существует только в `services/mca_events.py`; соседние наборы
(`cover_style_jobs.STYLE_REASON_CODES`, `direct_chat_service.REASON_CODES`,
`mca_dream_evidence.INTERNAL_REASON_CODES`, `safe_fetch.REASON_CODES`) —
pre-existing доменные словари других подсистем, коммит их не трогал и не
дублирует.

## 3. Покрытие owner §I4 и `SXR-I4-02`

| Требование | Проверка | Где |
|---|---|---|
| найти реальные producer-коды | 8/8 маркеров декодированы, литералы найдены в emit-сайтах | §1, `test_marker_digest_matches_producer_code` |
| корректный канонический код события | `reason_code` = сам код, не `unmapped:` | `test_restored_code_is_canonical_in_single_registry` (15 кодов) |
| согласованность существующего реестра | единственный `REASON_CODES`, без дублей; AST-мета-тест по эмиттерам семейства | `test_registry_has_no_duplicate_entries`, `test_producer_emit_sites_only_use_registered_codes`, `test_detector_class_family_is_registered` |
| сохранение диагностического смысла | реальные эмиттеры: `lag_rows`/`threshold` в `usage_json`, `status` cover, `stage` фактчека | `test_fresh_stream_lag_producer…`, `test_cover_*`, `test_factcheck_tool_claim…` |
| правильная классификация (skip ≠ failure) | skip: fresh/stale/lesson/cover_context (`skipped`, WARN или INFO); проходы: detector/archive/samples/owner_reset/anomaly/tool_claim (`success`); предел: `limit_unknown` (`start`); публикация сверх лимита: `prompt_limit_exceeded` (`failed`) | §2 + тесты исходов на реальных эмиттерах |
| нет утечки секретов/произвольного payload | коды — статические литералы; `usage_json` только числа; сырое неизвестное значение не попадает ни в событие, ни в WARN | `test_unknown_code_stays_unmapped_and_not_collapsed`, `test_fresh_stream_lag…` (`"message"`/`"text"` отсутствуют) |
| неизвестные не схлопнуты в один универсальный код | два неизвестных кода → два разных `unmapped:<sha8>` | `test_unknown_code_stays_unmapped_and_not_collapsed` |
| warning unmapped не удалён | `build_event` не изменён (WARN с event/marker/chars, без сырого значения); тест ловит ≥2 WARN | тот же тест (caplog) |
| второй реестр не создан | см. §2 | `test_registry_has_no_duplicate_entries` + grep |

## 4. RED → GREEN

RED на базе `d20a7f73`: откатывался только код словаря
(`git checkout d20a7f73 -- services/mca_events.py`), тесты оставались на месте;
дерево после прогона восстановлено (`git checkout HEAD -- …`, `git status` пуст).

| Прогон | База `d20a7f73` | Кандидат `4bf11400` |
|---|---|---|
| `pytest tests/test_smart_i4_reason_codes.py` | **22 failed, 10 passed** | **32 passed** |
| 5 файлов с пином длины `REASON_CODES` | **7 failed, 75 passed** | **80 passed, 2 pre-existing failed** |

На базе падают ровно контрактные проверки (нет кодов в словаре → `unmapped:`,
count-пины 341) плюс те же два pre-existing падения, что и на кандидате (§6).

Мутация (доказательство, что тесты не вакуумные): удаление одного литерала
`"fresh_stream_lag",` из словаря → `3 failed, 29 passed`; лог эмиттера
показывает ровно прод-маркер
`reason_code=unmapped:18d14796` при `outcome=skipped | level=WARN`.
После восстановления файла дерево чистое.

## 5. Прогоны (venv `C:\Code\Python\adminbot\.venv`, cwd = корень worktree)

| Набор | Результат |
|---|---|
| `tests/test_smart_i4_reason_codes.py` | **32 passed** |
| 5 файлов с пином длины (mca10b a, mca17c invariants, mca19 f, mca20 integration, mca20 rework1) | **80 passed, 2 pre-existing failed** (§6) |
| События/инциденты/излучатели: mca13 event contract, mca17 perimeter, mca17c oversight api, qnd event path, soul1 humor feedback, cover wave b, summary waves c/d, summary supervisor, mca16 a–f, stale-recheck hotfix | **356 passed, 1 pre-existing failed** (§6) |
| Остальные файлы, ссылающиеся на `REASON_CODES`, + набор I2 (asap8, evol020, evidence grounds, mod-acl m2) | **1313 passed** |
| `git diff d20a7f73..HEAD --check` | чисто |

## 6. Pre-existing падения (проверены на базе `d20a7f73`)

1. `tests/test_mca19_block_f_round1043.py::test_screen_map_and_registry_artifacts_regenerated` —
   `len(plans/docs/param-registry-round1025.tsv) == 645`, пин 644 (ключ добавлен
   другой волной, пин не обновлён). Падает идентично на базе.
2. `tests/test_mca20_rework1_f1_f2.py::TestValidatorStage::test_evidence_injection_stays_data_not_instructions` —
   ожидает `&lt;/evidence&gt;` в validator-промпте, текущая сборка evidence-секции
   не экранирует так. Падает идентично на базе.
3. `tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons` —
   известное pre-existing (docstring модуля содержит `graph_facts`), уже
   зафиксировано в `binding-i2-c5e63d9c.md` §7.

Все три — BACKLOG_ONLY, к кандидату отношения не имеют (код `mca_events.py`
их путей не касается). PM: дедуплицировать в `plans/backlog.md`.

## 7. Что осталось за рамками (честно)

* Аудит всего репозитория (293 модуля) нашёл ещё 6 литеральных `reason_code`
  вне словаря в **других** подсистемах: `graphrag_rebuild.py` —
  `retry_horizon_exhausted`, `auth_invalid`, `activation_failed`;
  `mca_vision.py` — `vision_type_disabled`; `memory_communities.py` —
  `cancelled`. В production-recon §8 они не наблюдались, в семейство I4 не
  входят, в этом кандидате не регистрировались (расширение затронуло бы
  другие подсистемы и потребовало бы отдельной классификации). BACKLOG_ONLY;
  решение о расширении — за PM/Orchestrator.
* Динамические коды (`f"detector_{class}"`, `reason`/`status`-переменные)
  статически не перечислимы полностью; тест покрывает закрытый набор классов
  детектора и AST-проверку литералов эмиттеров семейства.
* Production-проверка «после правки нет новых unmapped» (recon §10) —
  `live_required=false` у обоих требований; наблюдение возможно после
  контролируемого выката, обязательным до релиза не является.
* Effective configuration: словарь статический, флагов/чатовых настроек не
  участвует; тесты исполнялись на заводских значениях, feature-off сценариев
  у I4 нет.

## 8. Lineage и housekeeping

* Исходный коммит предыдущей сессии — `dbe20d8b` (код + тесты). Перед handoff
  из теста убрано одно тавтологичное утверждение
  (`classes <= set(values) | classes` → `classes <= set(values)`), коммит
  амендён: **`4bf11400`**. `services/mca_events.py` в аменде не менялся
  (`git diff dbe20d8b 4bf11400 -- services/mca_events.py` пуст).
* Промежуточные откаты кода/мутация выполнялись с восстановлением из Git;
  после каждого прогона дерево проверялось чистым. Секреты не печатались,
  production не затрагивался. Диагностические логи прогонов лежали во
  временном `WorkspaceData/runs/.../probe-d5bd027b77`; числа перенесены сюда,
  временный каталог закрывается при handoff (Reviewer он не нужен).
