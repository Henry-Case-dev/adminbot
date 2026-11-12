# D3 B1 - независимое ревью исправления repo_origin

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `278c19e0bbe452a731cb6066102fbe9c47d34bd0`, docs `48fc1c630161aaeead20da98b93fe28b0e3f5ee6`.
База: approved D4-B `722ccfc522ba00a18dc74881913020151ac250aa`; предыдущий review `fd756738` - Needs Fixes (B1).
Worktree: `self-diag/d3`, `...-573654bd`; HEAD = docs-коммит.

**Вердикт: Approved для D3-исправления B1.** Критическая утечка credential-URL
закрыта на уровне источника: `flags.self_diag_repo_origin` больше не выходит из
probe как raw URL, только `owner/name`; невалидное непустое значение даёт
`effective=None` + `reason_code="invalid_repo_origin"`. Raw token не найден ни в
`facts.settings`, ни в bundle, ни в page, ни в tool-результате.

## 1. Что изменено

`git diff a4d2b5b8..HEAD` содержит только:
- `services/runtime_probes.py`: helper `_normalize_repo_origin_value` (вызывает
  существующий `services.source_reader.normalize_repo_origin`) и ветка для
  `flags.self_diag_repo_origin` в `_probe_config_effective`;
- `tests/test_diagnostic_probes.py`: `FakeConfigCache` + regression-тест;
- docs: новый binding-addendum и пометка предыдущего binding как superseded.
Других изменений кода/тестов/схем/роутера/кэша/сценария нет.

## 2. Реализация

`_probe_config_effective` для спорного ключа:
1. берёт значение из cache/hot как раньше;
2. прогоняет через `normalize_repo_origin` (owner/name, без scheme/host/userinfo);
3. при успехе кладёт только `owner/name`;
4. при непустом невалидном значении кладёт `None` и `reason_code`;
5. при пустом значении кладёт `None` без reason; исходная строка не возвращается.
`_CONFIG_KEYS`, формат остальных строк, статус `ok`, cache/scenario/tool-схемы не
менялись. Локальный import не создаёт нового парсера и не меняет D4-B-контракт.

## 3. Независимые входы

Через реальные `_probe_config_effective`, `DiagnosticCollector.collect("config.effective")`
и `ToolRouter.dispatch("inspect_runtime", ...)` (guard/output не маскируют факты):

| Вход | effective | reason | token в facts/bundle/page/tool |
|---|---|---|---|
| `https://user:SECRET-TOKEN-9988@github.com/Henry-Case-dev/adminbot.git` | `Henry-Case-dev/adminbot` | - | нет |
| `https://github.com/Henry-Case-dev/adminbot.git` | `Henry-Case-dev/adminbot` | - | нет |
| невалидный непустой (`not a repo origin`) | `None` | `invalid_repo_origin` | нет |
| пустая строка | `None` | - | нет |

Дополнительно проверены невалидные URL с токеном (один сегмент пути и три сегмента):
`effective=None`, `reason_code=invalid_repo_origin`, raw/token отсутствуют в page и
bundle. Это важный случай: токен не утекает даже когда URL не нормализуется.

Сценарий `incidents.investigate_incident` с тем же токеном: bundle содержит все 11
источников, включая `config:effective` с `effective="Henry-Case-dev/adminbot"`;
токена в bundle нет. Page честно сообщает `total_sources=11` и
`omitted_source_ids` для хвоста из-за бюджета (D3-поведение, не B1).

## 4. Тесты

- `pytest tests/test_evidence_bundle.py tests/test_diagnostic_probes.py -q` ->
  **80 passed**.
- Focused 35-file set (тот же, что в предыдущем review) -> **1325 passed**,
  1 Starlette/httpx warning; failure-строк нет.
- Новый тест прочитан: fake cache с token URL, проверка bundle/page/tool_out на
  отсутствие `SECRET-TOKEN-9988`, `user:SECRET`, `userinfo`; отдельно проверяется
  `page.sources[0].facts.settings[].effective == "Henry-Case-dev/adminbot"`.
  Негативные assertions сильные; положительная проверка `Henry-Case-dev/adminbot in
  tool_out` менее специфична (owner/name может прийти из identity), но прямая
  проверка строки настроек это компенсирует.
- **Independent mutation:** в отдельном worktree @ `48fc1c63` заменён вызов
  `normalize_repo_origin(value)` на возврат raw значения; regression-тест ->
  **1 failed** с токеном в bundle. Restore -> **80 passed**; worktree удалён.
- Два pre-existing RED воспроизведены на текущем кандидате:
  `test_addtr_tools_minifix.py::test_l1_seam_announce_then_execute_once`,
  `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`.
  Это не D3; BACKLOG.

## 5. Строки D3

- **SD1-EVD-12** - теперь REVIEW-eligible на unit-уровне: credential URL не
  попадает в facts/bundle/page/tool; redaction/permission/latency/reason поля
  присутствуют и покрыты тестами. Ранее блокировалось B1.
- **SD1-EVD-14** - теперь REVIEW-eligible на unit-уровне: сценарий собирает
  runtime/deploy/voice/STT/provider/scheduler/config/logs/incidents; config-источник
  нормализован и не содержит токен. Live voice/STT/provider остаётся D7.
- **SD1-EVD-01** - остаётся D6: explicit `handlers/checkup.py` wiring;
  `collect_for_checkup()` seam уже есть.
- **SD1-SEM-08** - остаётся live-LLM/D7; структурная проверка не заменяет live.
- Остальные D3-строки не менялись; их статус в карте остаётся PENDING до PM sync.

## 6. D6 / live / residual

- D6 должен добавить `prompt_readback`, checkup wiring и analytics/UI поверх
  текущего `inspect_runtime`; 17-й tool, `tool_schemas`/`tool_router` и
  `collect_for_checkup()` сохранить. Конфликта в текущем кандидате нет.
- Live VPS/GitHub/Telegram/journald/systemd/PSI/DNS, `commits_since_deploy=None` и
  linked-worktree `deploy.identity path_denied` не проверялись; это D4-C/D6/D7,
  не B1.
- UI/Playwright/Browser Use к D3 не применимы.
- `requirements_gate --stage review --slice D3 --candidate 278c19e0` возвращает
  PENDING по D3-строкам: карта ещё не синхронизирована PM. Это не дефект кода;
  Reviewer карту/progress_scope не менял.

## 7. Backlog / nonblocking

- BACKLOG_ONLY: два pre-existing RED (addtr L1 seam, tool_coordinator forbidden
  paths), подтверждены на кандидате и ранее на base `b6d7064c`.
- BACKLOG_ONLY (test hardening): durable-тест покрывает token URL, но не
  фиксирует отдельно invalid non-empty/empty и invalid-token URL; независимая
  проверка это подтвердила, критический security-контракт покрыт. Один небольшой
  parameterized regression был бы полезен, но не блокирует B1.
- BACKLOG_ONLY: page-бюджет сценария может опускать хвост источников; page честно
  отдаёт `total_sources`/`omitted_source_ids`, bundle содержит все источники.
- CRITICAL_OUT_OF_SCOPE: не найдено. B1 закрыт; новых in-scope дефектов нет.

## 8. Три опоры

- **Implementation:** прочитаны diff, `_probe_config_effective`,
  `normalize_repo_origin`, collector `_build`/render, tool dispatch; проверено, что
  raw URL не выходит из probe и не попадает в сериализуемые артефакты.
- **Test validity:** 80/1325 passed; assertions прочитаны; mutation с bypass
  нормализации дал RED, restore - GREEN; два pre-existing RED не изменились.
- **Independent challenge:** token URL, plain URL, invalid non-empty, empty и
  невалидные token-URL; bundle/page/tool/facts без токена; invalid даёт корректный
  reason; сценарий с токеном даёт чистый bundle и нормализованный config.

## 9. Итог

**Approved** для исправления B1 на `278c19e0` / docs `48fc1c63`. D3/self-diag DONE
не объявляются; EVD-12/EVD-14 REVIEW-eligible, EVD-01 - D6, SEM-08 - live;
карта/progress_scope требуют PM-синхронизации. Продуктовый код, настройки и прод
Reviewer не менял; деплоя не было; временные worktree/run закрыты.

