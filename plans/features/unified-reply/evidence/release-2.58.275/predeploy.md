# Release 2.58.275 — predeploy verification (НЕ ЗАДЕПЛОЕНО)

Итог: **BLOCKED_PREDEPLOY.** Продуктовая часть собрана, версия поднята, обязательные проверки пройдены,
но релизный кандидат даёт **2 новых падения тестов** относительно прода (`731a7e51c` = 2.58.274).
Оба — устаревшие оракулы тестов под одобренное изменение канона/шва, не дефект продукта; тем не менее
релизный бар этого проекта («candidate-only падений = 0», см. `p0t-reply-01-2026-11-28/implementation.md`)
они нарушают, а правка — тестовая и требует независимого ревью, которого у DevOps нет.

- Собранное дерево: `12c5fc97a` (tree `e15e3b935ba9be20829b2033bf3ac2a79b78de95`), version 2.58.275, `dirty_tracked=0`.
- Прод не менялся: `731a7e51c` = 2.58.274 (ни одного деплой-подключения к серверу не сделано).
- Интерпретатор всех итоговых прогонов: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`.

## 1. Обязательные проверки

| проверка | команда | результат |
|----------|---------|-----------|
| version-контракт | `pytest -k version -q` (`raw/version-contract.txt`) | **1 failed, 207 passed** — `test_status_section_ui_merge_round1019::test_mode_version_line_removed`; **предсуществующий**: тот же node-id красный на проде 2.58.274 (в отчёте 2.58.274 — в числе 3 известных), `web/index.html` и сам файл теста побайтово равны проду |
| P0T suite | `pytest tests/test_p0t_reply_target.py -q` | **16 passed** |
| routes-контракт (новый модуль barriers) | `python -m tests.routes_contract --check` (`raw/routes-contract-check.txt`) | `CHECK OK ... соответствует web/api/routes.py` |
| параметрический реестр | `tools/gen_param_registry_round1025.py --check` (`raw/registry-check.txt`) | `CHECK OK: реестр 668 == REGISTRY, карта полна, R17-чисто` |
| collection | `pytest --collect-only -q` (`raw/collect-only.txt`) | exit 0, **23858 collected** |
| канон/печати | app import (`raw/canon-identity.txt`) | `seal_integrity() == {}`, `factory_set_fingerprint() == 1c03efc3e98b` (== const), sha12 active **`64a80fb8c4ff`**, len **21617**, R4 присутствует, R3-секция и сужение «относится к инициативе» отсутствуют, `is_known_canon(active) is True` |
| схема/DDL | `git diff 731a7e51c HEAD -- services/database.py database migrations` | пусто |

## 2. Батчи и атрибуция падений (кандидат `12c5fc97a` vs база `731a7e51c`, один и тот же интерпретатор)

| набор | файлов (канд/база) | кандидат | база | новых |
|-------|--------------------|----------|------|-------|
| direct/decision/rlr | 32 / 32 | 25 failed, 904 passed (`raw/venv-batch-direct.txt`) | 23 failed, 906 passed (`raw/base-venv-batch-direct.txt`) | **2** |
| reply/unified/ur | 48 / 45 | 5 failed, 1039 passed (`raw/venv-batch-reply.txt`) | 7 failed, 1027 passed (`raw/base-venv-batch-reply.txt`) | 0 |
| context/бюджеты L1 | 7 / 7 | 1 failed, 189 passed (`raw/venv-batch-context.txt`) | 1 failed, 189 passed (`raw/base-venv-batch-context.txt`) | 0 |
| пины + новые сьюты | 26 / 19 | 5 failed, 521 passed (`raw/venv-batch-pins-new.txt`) | 9 failed, 424 passed (`raw/base-venv-batch-pins-new.txt`) | 0 |
| канон/фабрика/доставка (широкий) | 227 / 223 | 125 failed, 6057 passed, 7 skipped, 2 errors (`raw/venv-batch-canon-rest.txt`) | 129 failed, 6027 passed, 7 skipped, 2 errors (`raw/base-venv-batch-canon-rest.txt`) | **2** (те же) |

Широкий набор = все тест-файлы, упоминающие канон/фабрику/seal/delivery/l1_plan (`raw/canon-batch-files.txt`,
236 файлов; 6 файлов, запускающих подпроцессы, из него исключены и проверены отдельно — см. §4).

Разница наборов базы меньше по числу файлов, потому что 4 новых тест-файла (P0T/UR-B/VMQ) на проде не существуют.

**Дельта кандидата к проду:** ровно 2 новых падения (§3); 6 прежних падений релиз лечит
(`asap2_clar_contract::test_34`, `expression_isolation_followup::test_fingerprint...`,
`p0_prompts_core::test_factory_fingerprint...`, `soul1_composer_parity_off::test_p4...`,
`ui_verbilizer_tabs_round1023::{test_stage_prompts_from_cache,test_direct_empty_planner_falls_back}`).

## 3. БЛОКИРУЮЩИЕ находки (candidate-only, воспроизведены на самом кандидате P0T)

### F-275-01 — устаревший пин-слепок канона L1
`tests/test_direct_l1_corrective_r1.py::test_l1_rules_positive_criteria_present`

- Прод `731a7e51c`: PASSED (`raw/attribution-prod-731a7e51c.txt`); кандидат P0T `1353a5131`: FAILED
  (`raw/attribution-candidate-p0t.txt`); собранный релиз: FAILED (`raw/attribution-release-2.58.275.txt`).
- Причина: тест собирает канон конкатенацией исторических секций и сравнивает с `DIRECT_L1_PLANNER_SYSTEM_PROMPT`.
  P0T перевёл активный канон R3 → R4, но этот файл не входил в пиновый набор кандидата (в его evidence
  «кандидатских падений = 0» проверялись 16 других файлов).
- Предлагаемая правка (проверена локально, откачена): `raw/proposal-fix.diff` — ввести промежуточный `_p0gm`
  и `.replace(cp._DIRECT_L1_PARTICIPATION_R3, cp._DIRECT_L1_PARTICIPATION_R4)` — ровно тот приём, который
  P0T применил в `tests/test_direct_l1_l1d_contract.py`.

### F-275-02 — оракул R-08.20 привязан к `reply_to`, смысл которого изменён
`tests/test_rlr_proof_restart.py::test_marker_is_written_before_delivery_not_after`

- Прод: PASSED; кандидат P0T и релиз: FAILED (`assert observed == [True]` → `[False]`).
- Причина: тест перехватывает `_send_direct_answer` и читает маркер как `check_update_seen(cache, chat, reply_to)`.
  По P0T план модели (llm/repair) без `delivery=reply` больше не привязывается → `reply_to = None`,
  и проба ищет маркер по `None`. Сам маркер пишется как раньше и ДО отправки:
  `services/direct_chat_service.py:5889` `mark_update_seen(self._cache, chat_id, _trigger_tg_id, ...)` —
  требование R-08.20 («маркер до доставки») не нарушено, оракул измерял не тот ключ.
- Предлагаемая правка (проверена локально, откачена): в пробе использовать id триггера (`1411`) и
  зафиксировать новое поведение `reply_to is None` для плана без `delivery`.

**Проверка предложения:** с применённым `raw/proposal-fix.diff` — `5 passed`
(`raw/proposal-validation.txt`); правки откачены (`git status` пуст), в ветку не коммитились.

## 4. Отдельно проверенные подпроцессные тесты (venv, изолированно)

`test_round1025_f8_registry::test_check_subprocess_exit_zero`, `test_bgs0304_residual_contracts::test_owner_prompts_phrase_does_not_open_prompt_registry`,
`test_mca10b_...::test_blockE_f8_check_green_and_baselines`, `test_mca18_...::test_mood_ttl_env_override_read`,
`test_smart_exec_selfdiag::TestDeployManifestIdentity` (4), `test_summary_deploy_round1026::TestBounds` (2),
`test_ur_f_inspector_step3_ui::TestLiveViewports::test_mobile_and_desktop` — **15 passed** на кандидате.
Под глобальным интерпретатором эти же тесты падали с `OSError: [WinError 50]` — артефакт окружения,
не свойство релиза.

## 5. Что НЕ проверено

- Живой выбор цели моделью в реальном много-медиа ходе — недетерминизм LLM, синтетикой не форсировался.
- Effective-канон и остальные прод-проверки (`64a80fb8c4ff` в активном каноне, healthz, NRestarts, журнал,
  свободное место, rollback dry-run) — **не выполнялись**, потому что деплой не начинался.
- Полный прогон всех 23858 тестов не делался; охват — 236-файловый канон/шов-набор + 4 целевых батча,
  выбранных по фактически изменённым продуктовым файлам (5 файлов).

## 6. Замечания к процессу релиза

- Входная гипотеза «кандидаты мержатся без конфликтов (merge-tree проверен)» **не подтвердилась**:
  24 конфликта version-литералов P0T+barriers, разрешены механически (см. `assembly.md` §2). Это
  самостоятельный предмет для независимой проверки.
- Пины версии в 24 тест-файлах заменены на `tests/version_contract.py`, поэтому bump затронул 5 файлов
  вместо 29 — это ожидаемый эффект ветки barriers, а не пропуск bump.
