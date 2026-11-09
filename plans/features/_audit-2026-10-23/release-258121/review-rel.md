# REV-REL-258121 — независимое релизное ревью поезда 2.58.121

- Lane: `REV-REL-258121` (read-only; записан только этот файл).
- Дата: 2026-10-24 11:49 +12:00.
- Кандидат: `a2feac65` (2.58.121). Tip ветки `release/2.58.119` — `999e547a`:
  docs-only поверх кандидата (README + `e2e-w4.txt`), код идентичен `a2feac65`.
- База поезда / прод: `9ed68ee8` (2.58.118). `merge-base --is-ancestor 9ed68ee8 a2feac65` = 0.
- **Вердикт: `Needs Fixes`.** Дефектов кода не найдено; блокируют формальную приёмку
  два процесса (PM-биндинг карты, явный деплой-шаг Core-патча) и одна честная
  FAILED-строка (EX-02). Деплой кода возможен как контролируемый после их закрытия;
  **parent не DONE**, финальный `release`-gate не пройден.

## 1. Состав поезда (20 коммитов, `9ed68ee8..a2feac65`)

| Фаза | Коммит(ы) в поезде | Состояние |
|---|---|---|
| Expression FREQUENT/budget | `09f56517` -> `466d4dfb` | код принят; **EX-02 FAILED** (см. §3) |
| Factcheck база (per-part/queries/OCR) | `b93f1557` -> `022ec0a1` | принято; `b93f1557` — обязательный предок (создаёт `test_factcheck_p0_fc.py`) |
| Checkup canon + Core | `9051e9fe` -> `0d98ea29` | принято; SP-01..SP-06 покрыты 544 passed |
| Factcheck review r2 (F1–F6) | `5b692967` -> `c43d0363` | **Approved** (`review-factcheck-r2.md`), F1–F6 закрыты |
| Prompts / freepseech / provenance / inspector | `3fcac03c` -> `ce376934` | код good; числа evidence исправлены (292/0, 1428/0) |
| Read-path stubs | `c9b47890` -> `a985af19` | включён, снимает 2 RED базы |
| FACTORY_SET переутверждение | `c3ed71a3` | `47f0d1eb8de4` подтверждён |
| Bumps 2.58.119/120/121 | `90915aec`, `913cdb27`, `a2feac65` | version-only, проверено |
| Withheld-фикстуры + owner byte-pin | `c0cfba4d`, `6613c883` | включены; 8 withheld не активируются |
| Realign снапшотов FREQUENT | `81864863` -> `cd0c4d1a` | тест-онли, легитимно (позднее указание владельца §6.3) |
| Initiative telemetry | `57efa10a` -> `d928708a`, `5d0f8a2a` -> `1058fb33` | принято; review-находки закрыты (проверено §2) |

## 2. Что проверено лично на `a2feac65`

- `pytest`: `test_factcheck_p0_fc` 28 + `test_p0_checkup_core_contract` 12 +
  `test_p0_prompts_core` 9 + `test_initiative_delivery_telemetry` 13 = **62 passed**;
  `parity` 13 + `asap3_hidden_limits` 16 + `speech_inspector_exact` 17 + initiative/events 109 =
  **155 passed**. Итого 217 passed, 0 failed.
- `FACTORY_SET_SHA256_12 == factory_set_fingerprint() == 47f0d1eb8de4`; 89 блоков;
  изменены ровно 4 фабрики: `checkup.base.system` `0f5fb7b8d25c`,
  `message.checkup_fallback_notice` `ba3fe05850c6`, `core.personality` `5597c09dd5f8`,
  `core.personality.compact` `8dbb8c10ddc6`. Runtime = константа.
- Telemetry-фиксы (подтверждены чтением кода и тестами):
  `len(REASON_CODES)=309` (+7 `target_*`), `entity_id->trace_id` только для
  `initiative_decided/sent/reacted`, `delivery:unknown` при пустой L1-форме,
  `corr:`/`trace_id` на cancelled-ветке, `react_target:` отдельно от `reply:`, `form:react`.
- Bump `1058fb33..a2feac65`: 66 изменённых строк; все — версии `2.58.120/121` и
  F8-meta HEAD-штамп `1058fb33`; неверсионных смысловых правок нет.
- ΔDDL: в диффе `9ed68ee8..a2feac65` по `services/ web/ config/ scripts/ tools/`
  нет `CREATE/ALTER/DROP/ADD COLUMN` — **deltaDDL=0**.
- Лестницы: Checkup `PREV_CHECKUP_P0_SYSTEM_PROMPT -> CHECKUP_SYSTEM_PROMPT`,
  rollback `CHECKUP -> PREV_P0 -> PREV_...` (2 ступени, не потеряны);
  Expression `prev_sha12 fcfcf6fcea09 -> next_sha12 4b4100524a22`,
  `rollback_profanity_frequent_text() == PREV`; Core — заводские v3/v4 +
  owner-preserving patch, отдельной PG-лестницы нет.
- Withheld: 9 классификаций (8 `legacy_incompatible` + 1 `identical_to_factory`);
  при `withheld` действует заводская редакция, PG-значение не перезаписывается.
- Старт: `bot.py:1381 migrate_prompt_canons()` — идемпотентно, кастом/withheld не
  перезаписывает, Checkup-ступень применится сама.

## 3. Блокеры

### B1. Core-патч активной редакции не выполняется ни рестартом, ни миграцией
Требование: после выката активная владельческая редакция `character.core` должна
получить абзацы «Как говорить о реальных событиях» и «Свобода речи» (freepseech),
с сохранением авторских байтов. Факт: `owner_preserve_core_full_patch` определён в
`services/prompt_migrations.py`, но **не имеет runtime/CLI call site** (только
определение, комментарии и тесты). `migrate_prompt_canons` идёт по
`PROMPT_MIGRATIONS` (prompt-registry ключи) и `character.core` не обрабатывает.
Значит предположение брифа «рестарт запустит owner-preserving патч» **неверно**:
без отдельного шага деплоя postdeploy-проверка «Core freepseech в активной редакции»
провалится. Минимальное исправление: включить в деплой-план явный вызов
`owner_preserve_core_full_patch` для активного `character.core`, затем read-back
байтов и проверка обоих абзацев; повторный прогон — no-op.

### B2. Карта P0 не связана с кандидатом — review/release gate красный
`requirements_gate.py check --stage plan` — **PASS** (inventory 202, manual 179, errors 0).
`--stage review --candidate a2feac65` по всем 8 срезам — **FAIL**:
`candidate_commit` пуст; все 202 позиции `PENDING` (138 required, 6 `live_required`),
включая офлайн-доказуемые. Наблюдённые FAIL-строки: FORENSIC 22, PROMPTS 37,
EXPRESSION 27, FACTCHECK 42, CHECKUP 49, CORE 49, OPS 11, ACCEPT 48 (дубли req между
срезами). Это работа PM, не Builder: привязать `candidate_commit=a2feac65`, внести
evidence по фазам, офлайн-строки `VERIFIED`, live-строки `READY_FOR_LIVE`,
EX-02 — `FAILED`. Без этого формального `Approved` нет.

### B3. EX-02 — FAILED, не маскировать
Реальная проба FREQUENT (dev-провайдер, 4 хода): marker доставлен 4/4, но мат в
собственной речи — 0/4; сравнительной матрицы OFF/OCCASIONAL нет. Требование
«привычная собственная речь» поведенчески **не доказано**. Это ограничение
модели/провайдера, не дефект кода; строка должна остаться FAILED, а не VERIFIED.
Деплой не блокирует (формулировка улучшена, поведение хуже не стало), но parent
не DONE; проверка — на проде/прод-модели после выката.

## 4. Не блокирует, но зафиксировать

- R2-N1..N4 (factcheck): бюджет 3 не покрывает число части; модельные `parts` могут
  дать контраст; тест каскада не проверяет передачу бюджета; fallback на `search_text`.
- `persona.checkup_language` legacy-фильтр может вырезать «человеческо-токсичный»,
  если владелец сохранит эту редакцию через UI; заводская/кодовая редакция отдаётся
  дословно. Нужен allowlist точных байт, если persisted-сценарий станет обязательным.
- W4 UI e2e: rc=1, 178 — число и структура (bottom-nav 76, touch 79, glass/H9 23)
  совпадают с базой 2.58.118; в дельте 2.58.120->2.58.121 нет `web/`. Артефакт снят в
  worktree `adminbot-wt258119` (сейчас `999e547a`), версия в логе не заштампована —
  привязка косвенная, но вывод «pre-existing» подтверждён диффом.
- 8 withheld (`legacy_incompatible`) останутся withheld; owner custom не
  перезаписывается, действует новая заводская редакция Checkup — это ожидаемо.
- Рабочее дерево основного репозитория грязное (PNG evidence); деплой — только с
  коммита `a2feac65`/`999e547a`, не с дерева.
- `tests/test_asap_w1_semantics.py` обновлён под позднее указание §6.3; это
  легитимная синхронизация снапшота, а не ослабление контракта.

## 5. Откат

- Точка прода: `9ed68ee8` (2.58.118), ΔDDL=0 — откат данных не нужен.
- По поезду: `a2feac65` (bump) -> `1058fb33` (телеметрия) -> `95803de0` (2.58.120) ->
  `41ba6bc6` (2.58.119) -> `81431843`/`9ed68ee8`.
- Checkup: `rollback_prompt_canons()` снимает 2 ступени (P0 -> прод-канон 2.58.118 ->
  CFG-07A); Expression: `git revert` + `rollback_profanity_frequent_text()`.
- Core: откат — `git revert` + Factory Default Core (owner-preserving патч не
  выполняется автоматически, поэтому откат данных не требуется).

## 6. Обязательные postdeploy-проверки

1. **Factcheck**: реальная составная новость (несколько частей/сущностей) — parts
   проверены раздельно; Tavily fail -> Exa ok в логах; `pipeline_version=tf3`;
   старая tf2-запись не отдаётся; изображение с OCR -> текст в claim; URL-less
   выдача -> `processing_failed`/`source_missing`, без `url=null`.
2. **Checkup**: 401 -> честный fallback (`journalctl` прочитан, не «сервис упал»);
   дословный блок «СУТЬ АНАЛИЗА»; обычная заглавная буква; Style Policy на выходе
   (тире по настройке чата); Full не примитивизирован.
3. **Core**: после явного B1-шага — «Свобода речи» и «Как говорить о реальных
   событиях» в **активной** редакции; авторские байты сохранены; повторный патч no-op.
4. **Withheld**: 8 значений остаются withheld; owner custom не перезаписан; Inspector
   показывает `withheld` и причину.
5. **Telemetry**: в `mca_events` у initiative-событий есть `trace_id`-корреляция,
   `delivery:`/`tgt:`/`addr:`, у manifest — `form:`/`reply:`/`react_target:`/`mismatch:`,
   `status=reply.text|react.react`, `config_version` непустой; `target_*` причины
   проходят whitelist.
6. **Регресс**: случайный чат-ход (Direct/Summary) без ошибок; журнал без
   CRIT/ERR/Trace; `/healthz` 200; версия/фабрика `2.58.121 47f0d1eb8de4`.
7. **EX-02** (не блокер выката, но не DONE): на прод-модели проверить, появляется ли
   мат в собственной речи при `frequent`; при 0 — оставить FAILED и вернуть вопрос
   Архитектору/владельцу, не подменять VERIFIED.

## 7. Ответ на вопрос «можно ли деплоить»

**Код `a2feac65` — да, контролируемо**, после: (1) PM-биндинга карты и зелёного
review-gate; (2) включения явного Core-патча в деплой-план (B1). После выката —
пункты §6; при провале Core/Checkup/factcheck — откат на `9ed68ee8`. Формального
`Approved for controlled deployment` в этой ревизии выдать нельзя: B2/B3 не
закрыты, parent не DONE.
