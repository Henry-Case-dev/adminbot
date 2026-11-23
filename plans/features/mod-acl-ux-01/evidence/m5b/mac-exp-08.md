# MAC-EXP-08 — M5B shared review при GLOBAL OFF + CHAT ON

**Статус: REVIEW (RFL, live_required=preprod).** Не VERIFIED: production
live-пара GLOBAL OFF + CHAT ON / GLOBAL ON + CHAT OFF в этой задаче не
измерялась. Независимый Reviewer ещё не выносил вердикт.

## Binding

- База: production 2.58.237 `f40402660`.
- Ветка: `feat/m5b-exp-08`.
- Кандидат (код + тесты + evidence): `4b79360c7a324a0a385d1d3356a71edbd634d17d`.
- Diff: `services/mca_experience_jobs.py` +12 строк; один новый test-файл.
- M5A 3 REVIEW (`experience_diagnostics.py`), ACL/UI/embedding/DDL,
  `progress_scope.json`, `workflow_state.md` не затрагивались.
- Deploy/SSH/LLM/prod не выполнялись.

## Контракт

1. GLOBAL — наследуемый default, не запрет: GLOBAL OFF + явный CHAT ON
   обрабатывается shared review-worker'ом.
2. GLOBAL ON + CHAT OFF — выключен только этот чат; worker и semantic
   index продолжают работать, OFF-чат не обучается.
3. `review_enabled()` не блокирует job до выбора чата; решение принимают
   только аварийные env-оси K1/K3.
4. Capture, detector, semantic, proposal/resume используют единый
   `learning_enabled_for_chat` (M2.1 resolver); stored overrides не
   переписываются.
5. M5B не закрывает M5: `MAC-M5-01` остаётся PENDING (M5C/native question).

## Фактический gap и fix

До кандидата `_propose_batch` (P1 technical / P2 explicit / P3 preference)
и `_resume_incomplete` (candidate/validated) не проверяли per-chat
learning. При GLOBAL ON + CHAT OFF общий worker мог создать или
активировать урок из уже накопленных эпизодов/кандидатов выключенного
чата.

Fix — 12 строк в `services/mca_experience_jobs.py`:

- в каждом из трёх циклов `_propose_batch` перед `propose`/`reconfirm`:
  `if not await learning_enabled_for_chat(chat_id): continue`;
- в `_resume_incomplete` перед validate/activate: `scope_chat_id`
  проверяется тем же resolver; durable candidate не удаляется, только не
  активируется.

Других изменений кода нет. M5A semantic stage (completed/partial/
unavailable) и E-TRUNC/E-LAG (heartbeat/fencing, per-attempt counters,
bounded retry, fresh lane, tail retry merge) сохранены.

## RED / GREEN

RED на `f40402660` (detached worktree, новый test file):

```
FAILED test_global_on_chat_off_no_lessons_from_existing_episodes
assert lessons.get(-100, 0) == 0
assert 1 == 0        # урок выключенного чата создан
1 failed, 5 passed
```

GREEN на кандидате:

```
pytest tests/test_mod_acl_ux_m5b_shared_review.py -q
7 passed

pytest <M5B + M2 resolver/consumers/capability + M5A> -q
62 passed

pytest <18 related experience files> -q -k "not deep_sleep_not_mixed_with_lessons"
299 passed, 1 deselected
```

Mutation: удаление P2-gate в `_propose_batch` возвращает RED
(`{-200: 1, -100: 1}`); после восстановления 7 passed.

## Покрытие acceptance

| Элемент | Проверка |
|---|---|
| shared worker при GLOBAL OFF | `review_enabled` = True, job ставится и завершается `completed` |
| enabled scope | capture/detector/semantic создают данные только для CHAT ON; LLM prompt не содержит OFF-чат |
| GLOBAL ON + CHAT OFF | worker `completed`, уроки/LLM только для ON-чата; cursor OFF-чата drained без обучения |
| proposal/resume | explicit-эпизоды OFF-чата не создают урок; durable candidate не активируется |
| semantic | валидный candidate принимается только для ON-чата |
| retrieval | активный урок ON-чата возвращается `select_for_context`; у OFF-чата уроков нет (consumer-гейт для уже существующих уроков — `MAC-M2-01`, RFL) |
| stored overrides | GLOBAL OFF не переписывается в override чата |
| inert pass | GLOBAL OFF + все INHERIT: `completed`, LLM 0, feedback 0 |

## Evidence

- `evidence/m5b/contract.md` — контракт, gap, fix, RFL.
- `evidence/m5b/red-green.md` — RED/GREEN/mutation/static.
- `evidence/m5b/tests.json` — машиночитаемые тесты и проверки.

## RFL / limitations

1. **Live production**: фактическое поведение shared worker при реальной
   паре GLOBAL OFF + CHAT ON и GLOBAL ON + CHAT OFF (тик, job, данные,
   effective-state) не измерялось. `MAC-EXP-08` — `live_required`,
   `live_when=preprod`; статус остаётся REVIEW/RFL.
2. **Retrieval consumer gate**: positive retrieval ON-чата проверен.
   Гейт для уже существующих уроков OFF-чата относится к consumer-adapter
   `MAC-M2-01` (PENDING) и вне write scope этого кандидата; в M5B не
   менялся и остаётся RFL.
3. **M5C/M6** не начаты; `MAC-M5-01` PENDING (native question).

## Предлагаемая delta карты (не применена)

Builder не редактирует canonical `requirements-map.json` (это делает
Orchestrator после независимого review). Предложение:

```json
{
  "req_id": "MAC-EXP-08",
  "from_status": "PENDING",
  "proposed_status": "REVIEW",
  "candidate_commit": "4b79360c7a324a0a385d1d3356a71edbd634d17d",
  "candidate_branch": "feat/m5b-exp-08",
  "evidence": [
    {"type": "test", "artifact_path": "plans/features/mod-acl-ux-01/evidence/m5b/contract.md"},
    {"type": "test", "artifact_path": "plans/features/mod-acl-ux-01/evidence/m5b/red-green.md"},
    {"type": "test", "artifact_path": "plans/features/mod-acl-ux-01/evidence/m5b/tests.json"},
    {"type": "test", "artifact_path": "plans/features/mod-acl-ux-01/evidence/m5b/mac-exp-08.md"}
  ],
  "rfl": [
    "live GLOBAL OFF + CHAT ON / GLOBAL ON + CHAT OFF on production",
    "retrieval consumer gate for pre-existing OFF-chat lessons (MAC-M2-01 PENDING)",
    "MAC-M5-01 PENDING (M5C/native question)"
  ]
}
```

## Configuration

- Product key: `memory.experience_learning_enabled` (GLOBAL default).
- Chat override: tri-state INHERIT/ON/OFF, не переписывается.
- Emergency env-оси: `MCA_EXPERIENCE_LESSONS_ENABLED`,
  `MCA_EXPERIENCE_REVIEW_ENABLED` (K1/K3), в тестах включены.
- Тесты используют fake LLM и реальную SQLite-схему; внешние вызовы
  отсутствуют.
