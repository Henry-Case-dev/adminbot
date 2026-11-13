# I3 — `experience.lesson_rejected` / `forbidden_effect` (binding evidence)

Стадия I3 (срез `S10-LEARNING-INCIDENTS`) эпика `SMART-EXECUTION-RELIABILITY-01`.
Реализация и тесты — Builder; независимое ревью — Reviewer; привязка карты —
PM/Orchestrator. Деплой не выполнялся, production не изменялся (только
read-only recon, см. §2). Approval/DONE не заявляются.

* База: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199, deployed).
* Ветка: `smart/i3-lessons`; worktree:
  `WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-5d94bdef`.
* Кодовый коммит (CODE_SHA): **`89a3716839f758afdf0ec9b6fff68a23013e97ab`**
  (`services/mca_experience.py`, +61/−11).
* Тестовый коммит (TEST_SHA): **`a3a6f1c41737cf79f494507ebc844e4ba7b2ec1c`**
  (`tests/test_sxr_i3_lesson_effects.py`, +260).
* Требования карты: `SXR-I3-01` (source `plans/current_task.md`, §I3, строки
  12827–12858), `live_required=false`, `live_when=preprod`.
* Границы: изменение только в `services/mca_experience.py` + новый тест.
  Схема БД/migrations/DDL, `mca_experience_jobs.py`, каталог рекомендаций,
  реестр событий, планировщик, пороги и production-конфигурация не менялись.

## 1. Что именно отклонялось (фактическое содержание)

Read-only recon production SQLite 13.11.2026 (UTC; схема 47): в `mca_events`
всего **389** событий `experience.lesson_rejected` с
`reason_code=validation_failed` и `usage_json =
{"reason_code":"forbidden_effect","lesson_type":"social_preference",
"origin_kind":"explicit"}` — **два** различных `lesson_id` (193 и 196
повторов, примерно каждые 15 минут; 2026-11-10T15:42:50Z —
2026-11-13T18:51:34Z):

| lesson_id | applicability (user id обезличен) | recommendation | status / origin |
|---|---|---|---|
| `85770c2c147c4d7b877c3c1d049ff350` | `user:<id> pref:memory.details_ignore` | канонический текст `explicit_user_preference` | `candidate` / `explicit` |
| `fafc559443444827ac4c5ff0332ea9b8` | `user:<id> pref:communication.ignore_unread` | тот же канонический текст | `candidate` / `explicit` |

Оба урока: `type=social_preference`, `scope=user_in_chat`,
`semantic_rule_key=explicit_user_preference`, `confirmation_count=1`,
`validator_version=NULL`. Durable provenance — active
`mca_experience_feedback` (`participant_correction`) с `signal_json`
`{"kind":"preference","preference":"memory.details_ignore",...}` (confidence
`high`) и `{"preference":"communication.ignore_unread",...}` (confidence
`medium`), `semantic=true`. Рекомендация в обеих строках — серверный канон
«При выборе формы ответа учитывать явно высказанное предпочтение участника в
его области действия.»; эффект-фраз в ней нет.

## 2. Путь генерации и диагноз

Путь (подтверждён кодом базы и полями production-строк):

```
LLM-экстрактор SEMANTIC_SYSTEM_PROMPT (pref_token «ключ.значение латиницей»)
→ parse_semantic_candidates_typed → _write_semantic_candidate
   (durable feedback, signal.preference)
→ _propose_batch P3: normalize_pref_token + pref_applicability
   = "user:<id> pref:<key>.<value>"
→ LessonService.propose (канонический recommendation, origin_kind="explicit")
→ _validate_and_activate (kind="explicit_preference")
→ LessonService.validate → _validation_failures → _forbidden_effects
```

`forbidden_effect` добавлялся единственной проверкой
`_forbidden_effects(recommendation, applicability)`: она склеивала
рекомендацию и applicability и искала свободные эффект-маркеры, включая
**голый `"ignore"`**, по всей строке. Applicability preference-урока —
машинный subject-идентификатор (`user:<id> pref:memory.details_ignore`), где
`ignore` — часть *имени предмета предпочтения*, а не императив обойти
контур. Обе строки падали только на этом совпадении.

Классификация владельческого списка:

| Гипотеза §I3 | Вердикт |
|---|---|
| модель генерирует неподдерживаемый effect | **нет**: `pref_token` соответствует закрытому нормализатору, рекомендация — канон |
| валидатор использует устаревший набор типов | **нет**: `social_preference`/`user_in_chat`/`explicit_preference` — действующие типы |
| расходится контракт генератора и потребителя | **да, в узкой точке**: свободный эффект-скан применялся к машинному идентификатору семантического контракта |
| origin/type неверно преобразован | **нет**: `origin_kind=explicit`, type/scope совпадают с контрактом |
| валидатор корректно отклонил запрещённое | **нет**: урок не меняет prompt/права/секреты/бюджет; ложное срабатывание |

`forbidden_effect` — законная защита, поэтому не удалена.

## 3. Минимальное исправление

`services/mca_experience.py`:

1. Точные машинные формы applicability (`user:<id> pref:<key>.<value>`,
   `tool:<token>`, `area:<topic>`, `humor_technique_context`) распознаются
   как subject-идентификатор (`_MACHINE_APPLICABILITY_RE`).
2. Рекомендация сканируется **полным** набором эффект-маркеров всегда —
   включая случаи с машинной applicability.
3. Свободный текст applicability (админская правка, смешанная строка)
   сканируется полным набором, как раньше.
4. В машинном токене голый `ignore` больше не считается эффектом, но
   сохраняется запрет связки `ignore` с системным объектом в любую сторону
   (`_MACHINE_EFFECT_RE`: system/prompt/instructions/rules/policy/
   permissions/secrets/budget/safety/guard) и сохраняется полный скан
   рекомендации.

Произвольные эффекты не разрешены: каталог рекомендаций и `propose`
не изменялись, `forbidden_effect` в `validate()`/`activate()` оставлен.

## 4. Покрытие §I3 и `SXR-I3-01`

| Обязательство | Проверка |
|---|---|
| восстановлено фактическое содержание | production recon §1: 2 урока, точные applicability/тип/origin/канон, 389 отказов |
| установлена причина | §2: ложный эффект-скан машинного subject-ключа; генератор/типы/origin корректны |
| законная защита не удалена | `_forbidden_effects` остаётся в `_validation_failures`/`activate`; тесты на эффект-фразы |
| допустимый урок проходит и сохраняется | `test_pref_lesson_with_imperative_substring_in_identity_key_applies` (4 формы, включая обе прод-формы), `test_candidate_pref_lessons_resume_to_active_on_review` (реальный `tick_experience_review` → `active`) |
| допустимое применение | `test_active_pref_lesson_is_selected_and_rendered`: отбор + блок промпта содержит рекомендацию и applicability |
| запрещённые эффекты по-прежнему отклоняются | `test_recommendation_level_effects_still_forbidden`: рекомендация, свободный текст, смешанная строка, машинные пары `ignore.rules`/`system.prompt`/`ignore_all_instructions`/`rules.ignore_all`/`prompt.ignore`; `test_free_text_contour_effect_in_applicability_is_rejected`: событие `lesson_rejected` с `reason_code=forbidden_effect` |
| тесты не подогнаны под два id | тесты не используют прод-`lesson_id`; параметризованы реальные формы инцидента + соседние R17-safe формы |

## 5. RED → GREEN (venv `C:\Code\Python\adminbot\.venv`, cwd = worktree)

RED на базе: тесты лежали в дереве, `services/mca_experience.py` откатывался
к `d20a7f73`; после прогона восстановлен.

| Прогон | База `d20a7f73` | Кандидат `a3a6f1c4` |
|---|---|---|
| `pytest tests/test_sxr_i3_lesson_effects.py` | **6 failed, 1 passed** (единственный passed — свободный эффект в applicability, который и должен отклоняться) | **7 passed** |
| 14 файлов lessons/experience (mca16 a–f, stale-recheck, lesson-strategy, asap8 d05/b02, soul1 w4, evidence grounds, evol020 + I3) | — | **226 passed, 1 pre-existing failed** |
| 11 связанных importer-файлов (asap7/asap8, mca01, mca05, mca17c, memory attribution, mod-acl m2/exp-fix, soul1 style) | — | **287 passed, 1 pre-existing failed** |
| `git diff --check d20a7f73..HEAD` | — | чисто |

Мутация (доказательство невакуумности): в машинной ветке отключён
contour-pair контроль → **1 failed, 6 passed** (`ignore.rules` проходит);
после `git checkout -- services/mca_experience.py` дерево чистое, HEAD
`a3a6f1c4`.

Пост-фикс probe (реконструкция прод-строк, `mode=ro` не требовался,
локальная БД): оба applicability `user:<id> pref:memory.details_ignore` и
`user:<id> pref:communication.ignore_unread` → `valid=true`, `active=true`,
`selected=true`, `rejected_events=0`; `true_effects_still_rejected` =
recommendation / mixed applicability / machine pair forward+reverse / free
text → все `true`.

## 6. Pre-existing падения (проверены на базе `d20a7f73`)

1. `tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons` —
   тест запрещает подстроку `graph_facts` в исходнике
   `mca_experience_jobs.py`, но docstring `_link_message_provenance` содержит
   `graph_facts.origin`. Падает идентично на базе; уже отмечено в
   `binding-i2-c5e63d9c.md` §7.
2. `tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer` —
   allowlist прямых `commit` устарел (`database.py` 207→230 и др.).
   Падает идентично на базе; наш diff не добавляет ни одного `commit`.

Оба — `BACKLOG_ONLY`, к кандидату не относятся. PM: дедуплицировать в
`plans/backlog.md`.

## 7. Effective configuration

- Поведение включают env-only гейты `MCA_EXPERIENCE_LESSONS_ENABLED`,
  `MCA_EXPERIENCE_REVIEW_ENABLED`, `MCA_EXPERIENCE_CONTEXT_ENABLED`
  (заводское значение ON); chat/global override к ним не применяется.
- Production фактически исполнял `experience.review` и эмитил уроки
  (389 событий, completed-job), т.е. гейты в проде эффективно ON; отдельного
  значения в recon не снимали.
- Тесты и probe исполнялись на заводских значениях гейтов; feature-off
  сценарий в I3 не проверялся (правка не меняет гейты).

## 8. Что осталось непроверенным (честно)

* Реальное восстановление двух уже лежащих в production candidate-строк —
  только после контролируемого выката: следующий `experience.review` должен
  перевести их в `active`. Сейчас production не изменялся; `live_required=false`.
* Живое применение урока в ответе чата (строка `mca_lesson_applications`)
  не проверялось: требует реального хода чата после выката.
* `experience.lesson_rejected` остаётся с общим `reason_code=validation_failed`
  и детальной причиной в `usage_json`; это существующий контракт, не менялся.

## 9. Recon и housekeeping

* Production: два read-only SSH-сеанса (key auth), SQLite
  `file:...?mode=ro` + `PRAGMA query_only=ON`; ни одной записи, рестарта,
  миграции или деплоя. Из вывода в evidence перенесены только коды/токены/
  числа; user/chat/message id обезличены, сырой текст сообщений не
  выгружался.
* Логи и probe: финальный probe запускался на HEAD с кодом `89a37168`
  в `WorkspaceData/runs/.../probe-b554bef8dd/`; числа перенесены в этот файл,
  каталог закрыт через `run-close`. Предыдущий прогонный каталог закрыт так
  же; сырые production-выгрузки удалены (содержали id). Reviewer сырые логи
  не требует — RED/GREEN и probe воспроизводятся тестом и скриптом.
* Worktree ветки `smart/i3-lessons` (кодовый/тестовый коммиты выше + evidence)
  сохраняется для Reviewer; удалять его до завершения ревью нельзя.
