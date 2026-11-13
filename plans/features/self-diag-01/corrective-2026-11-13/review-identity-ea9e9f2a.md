# Независимое ревью: SELF-DIAG-01 corrective identity/manifest + counters

## Область и привязка
- Candidate docs/HEAD: `6639baa35c276e97544a9f93e3e7da1808209b59`; code corrective: `ea9e9f2a1dc8b04bb82607acf9939bdefa3c16be`; base: `234776589c934024ed0e8dceba189fb9d70d3215`.
- Worktree: `self-diag/identity`, `WorkspaceData/worktrees/c742e4de9e92c489/self-diag-01-0ccfa8fbf52b-cf77b5ba`; чистый до ревью и после проверок. Production не использовался, код/настройки не изменены.
- Источник требований: owner input §6 и `architecture-corrective.md` из docs-линии `C:\Code\Python\adminbot`; binding кандидата прочитан отдельно. Scope: producer/identity/counters; остальной SELF-DIAG-01 не утверждается.

## Ledger
| Проверяемое поведение | Статус | Основание |
|---|---|---|
| В base отсутствовал producer `.deploy/release.json` | VERIFIED | `git grep` по base: читатель в `services/deploy_identity.py`, записи только в тестах; README описывал pull+restart, legacy deploy script работал с устаревшим VPS и писал `deploy_result.json`; base `.gitignore` не игнорировал `.deploy/`. |
| Schema-1 producer, atomic replace, dirty tracked rejection, previous/rollback, dry-run | VERIFIED | `tools/release_manifest.py`; `tests/test_release_manifest.py`; целевой pytest. Изолированный CLI dirty-tree challenge отказал и не создал manifest. |
| restart идёт только после успешной записи; deployed SHA не подменяется checkout без manifest | VERIFIED predeploy | `main()` выполняет build -> write -> затем optional restart; тесты утверждают `no_manifest`, `deployed_sha is None`, `checkout_sha == HEAD`; dry-run на кандидате вывел предполагаемый manifest и не создал `.deploy/release.json`. Реальный systemd restart не запускался. |
| Identity: согласованное состояние, mismatch и unknown/no_manifest | VERIFIED predeploy | Тесты проверяют `verified_deployed`, `mismatch/sha_conflict`, `process_predates_deploy`, dirty state, отсутствие manifest. Probe маппит mismatch в degraded, healthy false; local_unverified в healthy None; facts сохраняют effect/previous SHA. |
| Honest counters journal/Telegram/STT | VERIFIED в тестовом контракте | Assertions в `TestCounterHonesty`: отсутствие наблюдений -> null/not_checked + reason; измеренный ноль только после наблюдавшихся ring records или успешного пустого ledger read; STT без voice rows -> failed/pending null. Read failure остаётся unavailable. Используются текущие ring/ledger/DB readers, новой телеметрии/DDL нет. |
| Production manifest/effective identity и влияние на production | UNVERIFIED | Доказательство появится только после ближайшего штатного релиза с запуском producer и реального runtime observation. Сейчас это не VERIFIED и не блокирует predeploy review данного slice. |
| routes `branch`/`source` projection | BACKLOG_ONLY, вне §6 | `_self_diag_payload` читает отсутствующие top-level поля, тогда как producer identity кладёт branch в `local_identity` и источник не экспортирует под `source`. Это влияет на отображение branch/source, но не на deployed_sha/checkout_sha/healthy/counters. Не блокирует текущий контракт. |

## Проверки
- `py -3 -m pytest tests/test_release_manifest.py tests/test_deploy_identity.py tests/test_diagnostic_probes.py tests/test_self_diag_golden.py -q`: 165 passed. Pytest показал два предупреждения о неизвестных настройках `timeout`, `timeout_method`; эти timeout-механизмы данным окружением не подтверждены.
- `py -3 -m pytest tests/test_diagnostic_probes.py -q -k 'logs_errors or telegram_delivery or stt or deploy_identity'`: 18 passed, 50 deselected.
- Builder claims (не засчитываются как мои прогоны): producer/identity 20/58, 555 tests in 16 files, RED 10 on base. Их assertions просмотрены выборочно и сверены с фактическим контрактом; полный набор 555 независимо не запускался.
- Независимый counterexample: в отдельной managed-копии изменён tracked `.gitignore`; `tools/release_manifest.py --repo-root <copy>` завершился сообщением `tracked working tree is dirty...`, manifest отсутствовал. Копия удалена после остановки процессов; candidate worktree остался чистым.
- CLI dry-run на точном candidate вернул HEAD `6639baa…`, schema 1, version `2.58.198`, previous null; `.deploy/release.json` в candidate не создан.
- Не запускались production API/SSH, `systemctl`, Telegram; не выполнялась вторая мутация. Ранее неподдержанные timeout-параметры pytest не являются проверкой таймаута.

## Три независимые опоры
- Implementation: просмотрены `tools/release_manifest.py` (tracked dirty guard, schema fields, temp+fsync+replace, write-before-restart), `services/deploy_identity.py` (`no_manifest`, source precedence, mismatch reasons) и `services/runtime_probes.py` (health/status mapping, counter readers). Код задаёт ожидаемые состояния без выдачи checkout за deployment proof.
- Test validity: прочитаны тела и assertions `tests/test_release_manifest.py` (producer/atomic/dry-run/dirty/rollback), `tests/test_deploy_identity.py` (no manifest/dirty/SHA/time mismatch) и `TestCounterHonesty` в `tests/test_diagnostic_probes.py`; assertions проверяют значения/side effects, не tautologies. Они не доказывают production effective state или реальный systemd restart.
- Independent challenge: tracked-file mutation в изолированной копии привела к rc=2/ошибке dirty tree и отсутствию manifest; dry-run на точном кандидате не создал файл. Наблюдаемое поведение соответствует контракту.

## Вердикт
**Approved** для predeploy corrective slice, только перечисленная область и точный candidate выше. Это не deployment/release acceptance и не DONE для родительского SELF-DIAG-01. Production manifest/effective identity остаются UNVERIFIED до наблюдения на ближайшем релизе.
