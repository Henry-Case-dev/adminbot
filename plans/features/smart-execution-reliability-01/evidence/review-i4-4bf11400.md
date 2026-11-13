# I4 - независимое ревью `4bf11400` (SXR-I4-01/02)

**Вердикт: `Approved`** для точного кандидата: код `4bf114007e1e9549609b2259403c89282e04b5aa`,
docs `42ce567572e7cdd9d4c178defe30026c541df90b`, база `d20a7f730715ba9e9cba7673c0557794979be339`
(ancestor HEAD = да), ветка `smart/i4-codes`, worktree
`WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-4634be53`.
Деплой не выполнялся; production, схема, настройки и чужие подсистемы не менялись.

## 1. Границы кандидата

`git diff --stat d20a7f73..HEAD`: 8 файлов, +519/-5:
`services/mca_events.py` (+26, только расширение единственного `REASON_CODES`),
`tests/test_smart_i4_reason_codes.py` (+318), пять легаси-пинов длины словаря
`341 -> 357` по 1 строке, evidence-файл. `git diff --check` чист.
DDL/миграций/`config/settings.py`/схемы/второго реестра MCA-кодов в diff нет.
`build_event()`/WARN-путь не изменены: добавление только внутри frozenset.

## 2. Implementation (что проверено в коде)

* Реестр: ровно одно AST-присваивание `REASON_CODES = frozenset(...)`,
  357 строковых литералов = 357 элементов, дублей нет, `unmapped:`-префиксов нет.
* 8 прод-маркеров независимо пересчитаны `sha256(code)[:8]` и совпали:
  `18d14796 fresh_stream_lag`, `4f8aced7 detector_scan`, `a999e0fd detector_fact_user`,
  `373cf2f7 tool_claim`, `d07c353d limit_unknown`, `69e80269 archive_direction`,
  `38dc4799 archive_coverage`, `54c94ee2 samples_selected`.
* Все 16 новых кодов проходят `build_event()` канонически (без `unmapped:`).
* Emit-сайты и классы сверены по коду: `fresh_stream_lag` skipped/WARN (`mca_experience_jobs.py:3433`),
  `stale_belief` skipped/WARN (`:3460`), `lesson_contradiction` skipped/WARN (`mca_experience.py:1987`),
  `detector_scan` success (`:1776`), `detector_{class}` success + закрытый набор
  preference/correction/fact_user (`:1772`), `archive_direction` success (`:2534`),
  `archive_coverage` success (`:2673`), `samples_selected` success (`mca_sample_library.py:1913`),
  `owner_reset_learning` success (`mca_humor_feedback.py:969`), `anomaly_recovered` success
  (`summary_generator.py:2904/3402`), `cover_context_missing` skipped (`:2911/3411`),
  `limit_unknown` start (`:3454`), `prompt_limit_exceeded` failed/WARNING
  (`cover_style_jobs.py:3023-3028`), `tool_claim` success (`tool_router.py:4962`).
  Штатный skip не превращён в failure; реальный failed publish остаётся failed.
* Утечки нет: коды - статические литералы; WARN содержит event/marker/chars,
  сырое неизвестное значение не попадает ни в событие, ни в лог; `usage_json`
  штатных эмиттеров - id/числа (`chat_id`, `lag_rows`, `threshold`), без текста.

## 3. Test validity (тела и утверждения, не только имена)

Новый файл прочитан целиком: 32 теста, утверждения проверяют реальный
`build_event`/реальные эмиттеры, а не копию реализации. Проверки негативные и
граничные: неизвестные коды не схлопываются (два разных `unmapped:<sha8>`),
WARN сохранён (>=2 записи, без сырого значения), skip-исходы проверяются как
`skipped` и не-ERROR, AST-мета-тест ловит незарегистрированные литералы
эмиттеров семейства и дубли реестра.

Независимые прогоны (venv `.venv`, cwd = worktree):

| Проверка | Результат |
|---|---|
| `tests/test_smart_i4_reason_codes.py` | **32 passed** |
| 5 файлов с пином длины `REASON_CODES` | **80 passed, 2 pre-existing failed** |
| Повтор после restore мутации | **32 passed** |
| `tests/test_mca13_event_contract_round1027.py` | 27 passed |
| `tests/test_mca17_perimeter_events.py` | 20 passed |

Pre-existing падения подтверждены независимо: `plans/docs/param-registry-round1025.tsv`
на базе `d20a7f73` содержит 645 строк при пине 644 (файл кандидатом не тронут);
второе падение - в validator-эвиденс-коде, который diff не затрагивает.
Третье (mca16 `graph_facts`) в мои прогоны не входило, воспроизведено Builder на
базе и относится к I2-набору; на кандидата не влияет.

## 4. Independent challenge (фальсификация)

* Мутация: удалён литерал `"fresh_stream_lag"` из реестра -> **3 failed / 29 passed**;
  лог эмиттера показал ровно прод-маркер `reason_code=unmapped:18d14796` при
  `outcome=skipped | level=WARN`; после восстановления sha256 файла совпал,
  `git status` чист, повторный прогон **32 passed**. Тесты не вакуумные.
* RED на базе: новые тесты против `d20a7f73` (тесты не менялись, словарь откатан)
  -> **22 failed / 10 passed**; дерево восстановлено побитово. Заявленный RED подтверждён.
* Неизвестные/backlog-коды (`vision_type_disabled`, `retry_horizon_exhausted`,
  произвольная строка) остаются разными `unmapped:<sha8>`, WARN срабатывает,
  сырое значение не публикуется; backlog-коды в реестр не добавлены.

## 5. Acceptance ledger (slice I4)

| Requirement | Статус | Основание |
|---|---|---|
| `SXR-I4-01` (5 source rows + 3 MAN rows) | **REVIEW-ready** | implementation/test/challenge выше; `live_required=false`, `live_when=preprod` |
| `SXR-I4-02` (MAN-1134/1136/1138) | **REVIEW-ready** | один реестр, WARN не удалён, неизвестные не схлопнуты (тест + probe) |

Это не финальная production-приёмка: карту/scope не менял, строки привязывает
PM/Orchestrator. Production-наблюдение «после правки нет новых unmapped» -
необязательное postdeploy-наблюдение, не блокер (оба требования preprod).

## 6. Backlog / вне scope (не блокер)

* Не зарегистрированы и в прод-recon §8 не наблюдались: `graphrag_rebuild.py`
  (`retry_horizon_exhausted`, `auth_invalid`, `activation_failed`),
  `mca_vision.py` (`vision_type_disabled`), `memory_communities.py` (`cancelled`).
  Решение о расширении - за PM/Orchestrator; в этом кандидате намеренно не тронуты.
* Pre-existing падения из §3 - в `plans/backlog.md` через PM (дедуп).
* Мелкое наблюдение: `prompt_limit_exceeded` покрыт AST-мета-тестом и проверкой
  эмиттера, но не отдельной canonical-проверкой в новом файле; на вердикт не влияет.

## 7. Не выполнялось / ограничения

Кросс-наборы Builder (`356+1`, `1313`) и `cover_style_wave_b`/`mca17_summary_instrumentation`
не перепрогонял: сервер рестартовал длинные прогоны; обязательные focused-проверки
(32, 80, мутация, RED на базе) выполнены полностью. Деплой/production не трогал.

## 8. Housekeeping

Диагностика: `WorkspaceData/runs/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b/probe-f2fde07411`
(логи pytest/мутации/probe; закрывается run-close). Worktree кандидата оставлен
для привязки/интеграции PM (KEEP, не удалён).