# BEHAVIOR-GATES-SIMPLIFICATION-01 — план работ

Источник: `plans/owner_inputs/2026-11-05-behavior-gates-simplification.md` (дословный снимок §6436–6697 `current_task.md`, 273 строки).
Карта требований: `requirements-map.json` (155 обязательных строк, 8 слайсов). Машинный граф: `slice-graph.json`.
Статус: **PLANNING ONLY** — все строки `PENDING`, `evidence` пуст, кандидат не зафиксирован.

## 1. Что решает эпик

Четыре класса ограничений владельца разведены окончательно:

| Класс | Решение | Слайс |
|---|---|---|
| Поведенческое вето (`privacy_blocked`, блок списка фраз) | удалить как препятствие мысли и поиску | BGS-01-PRIVACY |
| Смысловая постцензура (удаление предложения про цену, вырезание «по моим наблюдениям») | прекратить автоматическое вырезание | BGS-02-EGRESS, BGS-03-SPEECH |
| Настроенная владельцем форма (эмодзи, кавычки, стиль, частота) | сохранить, сделать проверяемой в UI | BGS-04-GUARD-SCOPE, BGS-06-ADMIN |
| Техническая целостность (SSRF, ключи, лимиты API, дедуп) | сохранить, не приписывать к «цензуре» | все слайсы, матрица BGS-07-MATRIX |

Решение владельца опирается на более позднее ТЗ и **отменяет** часть UNIFIED-REPLY: privacy-вето (UR-06/07/08) и обязательную обезличку запроса. Истории не удаляем — в карте unified-reply старые формулировки сохранены в `superseded_text`, рядом стоит `superseded_by: "BGS-01 (owner 2026-11-05)"`.

## 2. Волны и зависимости

```
W1 (параллельно, разные файлы)
├── BGS-01-PRIVACY      evidence_policy.py, factcheck_planner.py     [лейн ur/b-search, кандидат 1001514e]
├── BGS-03-SPEECH       public_speech_guard.py, outgoing_guard.py
├── BGS-04-GUARD-SCOPE  negative_constraints.py, style_policy.py, prompt_composer.py
└── BGS-06-ADMIN        param_catalog.py, chat_settings_seed.json  (только backend-дельта)

W2
└── BGS-02-EGRESS       depends_on BGS-01-PRIVACY  (общий services/evidence_policy.py)

W3
├── BGS-05-BUDGET       depends_on unified-reply:UR-C, UR-D  (direct_execution.py)
└── BGS-06-ADMIN UI     depends_on unified-reply:UR-F / PVR UI  (web/**)

W4  BGS-07-MATRIX       join по всем исполнительным слайсам
W5  BGS-08-ACCEPT       финальный join, реальные манифесты, Reviewer -> DevOps
```

Зависимости в графе продублированы явными рёбрами, чтобы `requirements_gate.py` мог отличить
намеренную сериализацию от случайного пересечения писателей.

### Правила сериализации (из `slice-graph.json`)

- `services/evidence_policy.py` — один писатель: BGS-01, затем BGS-02.
- `services/direct_chat_service.py` — только BGS-02; прочие call-site правки отдельным патчем после него.
- `services/direct_execution.py` — только BGS-05 и только после UR-C/UR-D.
- `services/negative_constraints.py` — только BGS-04.
- `web/**` — один писатель; UI-часть BGS-06 стартует после merge UR-F/PVR UI.
- Тестовые файлы закреплены за слайсами и не переиспользуются двумя писателями.

## 3. Состав слайсов

| Слайс | Требований | Риск | Ключевой наблюдаемый результат |
|---|---|---|---|
| BGS-01-PRIVACY | 18 | R0 | privacy-примеры доходят до реального поиска; новые трассы без `privacy_blocked`; RBAC/provider/SSRF/no-web целы |
| BGS-02-EGRESS | 16 | R1 | после L2 нет удаления содержательных предложений и повторного lookup; фактчек сохраняет claim→evidence |
| BGS-03-SPEECH | 13 | R1 | естественные фразы и цитаты возвращаются byte-preserving, маркеры чистятся, метатекст только наблюдается |
| BGS-04-GUARD-SCOPE | 16 | R1 | Form/Numeric/Format только при реальной трансформации или протокольной ошибке |
| BGS-05-BUDGET | 10 | R2 | пределы выведены из ёмкости модели и бюджета, усечение посередине отсутствует |
| BGS-06-ADMIN | 15 | R2 | нет мёртвых настроек, показан source/effective/consumer, трасса «до и после» |
| BGS-07-MATRIX | 28 | R1 | Conflict Resolution Matrix заполнена, расхождений без записи нет |
| BGS-08-ACCEPT | 39 | R2 | тесты + сценарии A-J на реальных манифестах + DoD |

Итого 155 обязательных строк (143 из экстрактора источника + 41 ручная, из них 29 — context).

## 4. Архитектурная классификация

`ARCH_REUSE_CONFIRMED_WITH_UNRESOLVED_ARCH_DOC`.

`arch/bgs-integration-contract.md` в этом worktree **отсутствует** (документ архитектора утерян при рестарте сервера).
План не выдумывает новых контрактов и опирается только на существующие: `evidence_policy.allowed/guard_egress`,
`ToolEvidence` из UR-B, `public_speech_guard`/`outgoing_guard`, `negative_constraints`/`style_policy`,
`param_catalog` + effective-config UR-20—22.

Триггер возврата к Architect: появление **новой общей границы** — нового значения `ToolEvidence.status`,
изменения схемы настроек, общего валидатора речи на несколько подсистем, новой семантики ledger/отправки.
PM такую границу не замораживает.

## 5. Доказательства

- Каждая закрытая строка: `ref` + `observation` + `type` (`test|ui|live|production|provider|static`) + `artifact_path` (repo-relative), для финальных отчётов — `artifact_sha256`.
- `strict_evidence: true` включён с самого начала: на review/release гейт проверит существование Git-объекта и артефакта.
- Сценарии A-J (BGS-08.8..17) требуют реальных L1/tool/L2/delivery манифестов, а не моков: смотрим запрос, число вызовов, tool result, L2 original, postprocess diff и доставленный текст.
- PET_PROJECT: деплой и прод-проверка после независимого ревью без отдельного согласования; `live_required=false` на стадии плана, post-deploy evidence (BGS-08.22) добавляется на release.

## 6. Что осталось непроверенным и почему

- BGS-02 физически не может идти параллельно BGS-01: общий файл `evidence_policy.py`.
- BGS-05 ждёт UR-C/UR-D; делать пересчёт бюджета на старом executor — значит создать вторую политику.
- UI-часть BGS-06 ждёт UR-F/PVR UI: `web/**` держит другой писатель, второй экран настроек запрещён источником.
- Owner live gate не блокирует завершение инженерной работы (§9, DoD п.7).
