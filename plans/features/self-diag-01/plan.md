# SELF-DIAG-01 — план слайсов и очередь

**Эпик:** SELF-DIAG-01 (самодиагностика, доступ к собственному коду и runtime, прозрачность без выдачи секретов).
**Источники:** `plans/owner_inputs/2026-11-09-self-diag-01.md` (FINAL v2.0, 530 строк, sha256 `ba12833aebc259039c7c198f596346880639618d9eafdb2e76d8ede17d0eb400`) и поправка `plans/owner_inputs/2026-11-09-self-diag-access-matrix.md` (sha256 `9e5ab002527c59798a145178f58e0362e24c202921ea23227edc52f29038bb40`).
**Машиночитаемая карта:** `requirements-map.json` (strict_evidence, slice_graph_path) + `slice-graph.json`.
**D0-артефакт:** `plans/features/self-diag-01/d0-discovery.md`, sha256 `306C23E7182C5F223821412545358AAFDAAB72775B930B6B8B288301C8430831` (скопирован из release-worktree в основной checkout байт-в-байт).

## 1. Позиция в очереди

- SELF-DIAG-01 стоит **одним эпиком после VMQ-ONTO-01** (а тот — после активного MEMORY-08). Эпик не считается запущенным от факта записи ТЗ в `current_task.md`: активация — только явное решение оркестратора с учётом занятых лейнов.
- **Исключение — D1.** D1 (portable local log backend + удаление checkup-only Better Stack) является независимым P0 corrective и может выполняться раньше очереди эпика, если его файлы не держит другой Builder. Это исправление уже случившегося переноса VPS, а не часть новой функциональности эпика.
- D0 (discovery) уже доставлен; его строки остаются `PENDING` до независимого принятия Reviewer/PM — наличие файла не равно VERIFIED.

## 2. Волны и зависимости

```
D0 ─ D1 ─ D2 ─┬─ D3 ─┐
              └─ D4 ─┴─ D5 ─ D6 ─ D7
```

| Этап | Владелец | Зависит от | Режим | Файлы (write scope) |
|---|---|---|---|---|
| D0 | Architect + PM | — | read-only (plans) | `plans/features/self-diag-01/{d0-discovery.md,requirements-map.json,slice-graph.json,plan.md}` |
| D1 | Builder + Reviewer | D0 | writer | `services/system_logs_fetcher.py`, `config/settings.py`, `bot.py`, `web/app.js`, `tests/test_checkup_logs_portable.py` |
| D2 | Architect + Builder | D1 | writer | `services/roles.py`, `services/access.py`, `services/telegram_role_check.py`, `services/diagnostic_policy.py`, `services/output_projection.py`, `web/api/access.py`, `tests/test_diagnostic_policy.py` |
| D3 | Architect + Builder | D2 | writer | `services/diagnostic_collector.py`, `services/evidence_bundle.py`, `services/runtime_probes.py`, `services/tool_router.py`, `services/tool_schemas.py`, `services/memory_health.py`, тесты probes/bundle |
| D4 | Builder | D2 | writer | `services/source_reader.py`, `services/deploy_identity.py`, `services/capability_registry.py`, `tests/test_deploy_identity.py` |
| D5 | Builder + Security Reviewer | D2 | writer | `services/prompt_readback.py`, `handlers/prompt_readback.py`, `tests/test_prompt_readback.py` |
| D6 | Builder (UI) + Reviewer | D1, D3, D4, D5 | writer | `services/checkup_service.py`, `services/tool_loop.py`, `handlers/checkup.py`, `web/api/routes.py`, `web/index.html`, `tests/test_checkup_contract.py` |
| D7 | Reviewer + DevOps | D6 | writer (evidence/tests) | `plans/features/self-diag-01/evidence/`, `tests/test_self_diag_golden.py`, `tests/test_self_diag_delivery.py` |

**Параллельность.** Одновременно допустимы не более двух writes: D3 и D4 (непересекающиеся файлы). D5 стартует после D2 и не пересекается с D3/D4 по путям. D1, D2, D6, D7 — одиночные лейны.

**Сериализованные файлы.**
- `services/system_logs_fetcher.py`, `config/settings.py`, `bot.py`, `web/app.js` — только D1, до D2/D6.
- `services/roles.py`, `services/access.py`, `web/api/access.py` — только D2; D6 читает контракт, не меняет.
- `services/memory_health.py` — D3 и то только после интеграции MEMORY-08 (общий контракт метрик памяти).
- `services/checkup_service.py`, `handlers/checkup.py` — только D6; промпт и стиль не редактируются.
- `plans/features/self-diag-01/*` — D0 владеет картой/графом/планом, D7 владеет `evidence/`.

## 3. Барьеры (join)

1. **D2 и контракт evidence обязаны завершиться до выдачи защищённых данных.** Пока policy не принята и `SD1-EVD-04` не зафиксирован, D5 и D6 не получают доступ к `PROMPT_CONTENT`/`CHAT_SCOPED`-выдаче.
2. **D5 не стартует без D2** — иначе readback обходит policy.
3. **D6 стартует после фиксации контрактов D3/D4/D5** — UI не задаёт API.
4. **D7 выпускает релиз только после live evidence** по AC-01…AC-24 и 31 корнер-кейсу §15.

## 4. Неизменяемые инварианты

- `prompts.checkup_system_prompt`, его factory-версия, активная ревизия, ручные правки и история остаются **байт-в-байт**; выкладка не создаёт новую запись сохранения (AC-09, `SD1-D6-03`).
- Характер чекапа (язвительный, грубый, при необходимости матерный) не смягчается, второй стилистический Writer не появляется (`SD1-GRAL-02`, `SD1-D6-04`).
- Единственный новый специальный лексический вход — «чекап»; никаких regex/словарей фраз (AC-05).
- Только read-only: нет shell/SSH/SQL от модели, нет скрытых write-effects (AC-21).
- Credential values не выдаются никому через чат; матрица прав использует существующий ACL, параллельный не создаётся (`SD1-AMX-05`, `SD1-AMX-09`).
- Новые функции включаются при первом релизе по умолчанию; отсутствие прав/источника даёт `permission_denied`/`unavailable` (`SD1-GRAL-04`).

## 5. D1 — почему это независимый P0 corrective

**Что конкретно ломается после переезда VPS.** Текущий `services/system_logs_fetcher.py` устроен как каскад: сначала HTTP SQL-запрос в Better Stack, и только при его неуспехе — локальный журнал. Локальная часть вызывает `create_subprocess_shell("journalctl -u admin_bot -n 300 --no-pager")`, где `admin_bot` — имя unit **старого** сервера. На новом VPS (с 29.10.2026) unit/окружение другое, поэтому:

1. `journalctl -u admin_bot` либо не находит журнал, либо (при похожем имени) читает не тот экземпляр — и чекап печатает «ошибок нет» там, где их не видели, а не там, где их нет. Это ложноположительный «здоров», самый опасный класс дефекта для диагностики.
2. Первым источником остаётся внешний Better Stack: пока он отвечает, локальные логи не читаются вообще, а при его недоступности чекап деградирует по сетевой, а не по локальной причине. Диагностика зависит от стороннего сервиса и его кредов.
3. Shell-вызов собирает командную строку как строку — это и portability-риск (разные окружения, quoting), и выход за рамки «никакого shell».

**Почему это независимо от тела эпика.** D1 не требует ни policy (D2), ни evidence-контракта (D3), ни prompt readback (D5), ни нового UI. Он восстанавливает уже обещанное поведение чекапа («читает логи этого процесса») и удаляет поверхность Better Stack внутри чекапа. Внешний Better Stack как глобальный observability-транспорт (`services/betterstack_handler.py`, ingest в `bot.py`) не трогается. Поэтому D1 можно делать в безопасном окне, не дожидаясь очереди эпика.

**Точные файлы.**
- `services/system_logs_fetcher.py` — убрать SQL-first каскад и `create_subprocess_shell`; определить процесс и способ запуска, выбрать backend (systemd с фиксированным argv через `create_subprocess_exec`, container stdout/адаптер, standalone файл/stream), подтвердить принадлежность журнала, отдать `unavailable` при отсутствии прав.
- `config/settings.py` — удалить `CHECKUP_BETTERSTACK_SQL_*` и `CHECKUP_JOURNALCTL_CMD`-путь, оставить настройки лимитов окна/строк.
- `bot.py` — только DI/wiring чекапного fetcher; глобальный logging/ingest не менять.
- `web/app.js` (+ метаданные каталога настроек, если они живут рядом) — убрать checkup-only карточки/поля/индикацию Better Stack.
- `tests/test_checkup_logs_portable.py` — новые тесты портируемости и отсутствия сетевых вызовов.

**Acceptance evidence D1.**
- 0 сетевых запросов к Better Stack в реальном checkup runtime (сетевой trace, не grep).
- Корректное определение systemd-unit / container / standalone и отказ читать чужой или старый журнал; переименованный unit не даёт «ошибок нет».
- Честный `unavailable` при отсутствии прав, при этом остальная диагностика работает.
- Bare «чекап» по-прежнему отвечает: reply, cooldown, реакция, busy, тот же промпт и стиль.
- Список удалённых checkup-полей и сохранённых внешних интеграций в отчёте.

**Риски:** R1 — неверный источник журнала (лечится проверкой принадлежности процесса и явным `unavailable`); R1 — регрессия bare чекапа (лечится сохранением текущего handler-пути и тестами); R2 — пересечение по общим config/UI-файлам (лечится сериализацией: D1 владеет ими до D2/D6).

## 6. Покрытие источника

- `requirements-map.json`: 183 извлечённых строки источника (все классифицированы: 137 `required`, 46 `context` со ссылкой на несущие норматив строки — 0 `unassigned`), 53 ручные строки (`AC-01…AC-24`, `AMX-01…AMX-09`, прозаические обязательства §5/§6.3/§7.1/§8/§9.3/§10/§11/§13.2/§15/§18/§19).
- Итого 182 уникальных требования; владеющий этап ровно один.
- Распределение: D0 — 5, D1 — 17, D2 — 48, D3 — 36, D4 — 16, D5 — 18, D6 — 30, D7 — 12.
- Поправка владельца про управление доступами инвентаризована отдельными строками `SD1-AMX-01…09`; `amendment_ref` хранит точный адрес в файле поправки, `source_line` — нормативную строку эпика с тем же содержанием (единый `source_path` карты не позволяет валидировать второй файл).
- Внешние зависимости, при которых acceptance остаётся честным `unavailable`/`auth_unverified`, а не VERIFIED: `EXT-VPS-LOGS`, `EXT-TG-ADMIN` (см. `slice-graph.json`).

