# BGS-01 — evidence binding record (PM bookkeeping, срез BGS-01-PRIVACY)

Запись фиксирует, какие артефакты доказывают строки карты BGS-01-PRIVACY, и что
этими артефактами НЕ доказано. Это не второй ревью-вердикт и не замена Reviewer.

- Источник требований: `plans/owner_inputs/2026-11-05-behavior-gates-simplification.md`
  (SHA256 `4f5457440e958efd20c50f8031af97da9c9d7a1d25e3094ea4ea75e607ec7284`), §0, §2.
- Полосы: `ur/b-search` @ `5adaa21b` (BGS-01 §2.4, имя участника в запросе) и
  `bgs/factcheck-privacy` @ `1da5fefa` (снятие деперсонализации в фактчеке).
- Слияние: `ddebd607` (`1da5fefa` в `evol/impl`), затем `da6299e9` (`5adaa21b` в
  `evol/impl`). Итоговый проверяемый кандидат — **`da6299e9`**.
- Статус ревью: обе полосы приняты независимым Reviewer (Approved) — по сообщению
  координатора эпика. Отдельного файла вердикта в рабочем дереве нет; это
  зафиксированный пробел провенанса, а не доказательство, что ревью не было.

## Что изменено в коде (фактическое состояние `da6299e9`)

| Файл | Суть |
|---|---|
| `services/evidence_policy.py` | Удалены `BLOCK_PRIVACY`, поле `EvidenceContext.privacy_ok` и ветвь `privacy_ok → BLOCK_PRIVACY` из `allowed()`. Порядок проверок: RBAC → запрет сети → доступность провайдера → квота → SSRF. `EvidenceSkipReason.RBAC_OR_PRIVACY_BLOCKED` оставлен только как историческое имя reason-кода для старых записей. |
| `services/direct_execution.py` | Удалены структурный классификатор участника, словари тем и `SearchTask.blocked/blocked_reason`; `build_search_query` больше не имеет содержательного veto. Осталась legacy-константа `SEARCH_STATUS_LEGACY_PRIVACY_BLOCKED = "privacy_blocked"`, которой новые ходы не пользуются. `private_terms` в `_strip_sensitive` — документный параметр; payload-гигиена маскирует URL/телефон/почту/@mention/длинные ID. |
| `services/direct_l1.py`, `services/direct_chat_service.py` | Решение о поиске строится по информационной потребности (search-first UR-06); в описании политики больше нет privacy-ветви. |
| `services/factcheck_planner.py`, `factcheck_attribution.py`, `factcheck_orchestrator.py`, `tool_router.py` | Снят `_strip_privacy`: имя участника остаётся в клейме и в запросе; атрибуционный клейм передаётся тезисом (`with_claim_thesis`/`attribution_thesis`) вместо обезличенного `external_safe_claim`. |

## Тесты, на которые опирается привязка

- `tests/test_unified_reply_ur_b_no_topic_veto.py` — корпус из 21 ранее
  блокировавшейся реплики (`TestFormerlyBlockedCorpusSearches`) и пробы
  (`TestFormerlyBlockedProbesNowSearch`): ровно один реальный вызов провайдера,
  содержательный термин в запросе, `search_status=ok`, `claim_policy=claim_allowed`,
  `"privacy"` отсутствует в трассе. `TestNoClassifierLeft` требует отсутствия 17
  имён классификаторов/словарей и поля `privacy_ok`, а `TestTechnicalGatesRemain`
  проверяет явное «не ищи в интернете», отсутствие инструмента, silent/react и
  пустую формулировку.
- `tests/test_unified_reply_ur_b_search_first.py` — search-first ось для Direct и
  Initiative (`TestSearchAxisSchema`, `test_identical_schema_for_initiative_path`,
  `test_adaptive_mode_still_gets_real_search_first`), отдельный класс
  `TestNoTopicVeto`, payload-гигиена (`test_whole_chat_is_not_sent`,
  `test_ids_stripped_names_kept_and_search_happens`), честные статусы
  (`TestHonestStatus`: пустая выдача, таймаут, провайдер недоступен, отсутствие
  выдуманных источников) и приватно-безопасная телеметрия
  (`test_trace_fields_and_emission_are_private_safe`).
- `tests/test_unified_reply_ur_b_review_fixes.py` — технические skip-пути без сети,
  `search_called` не может быть `false` при реальном вызове, reuse без повторной
  сети.
- `tests/test_bgs01_factcheck_no_name_strip.py` — 9 тестов: имя участника в клейме и
  запросе, клейм-имя не удаляется, числа/отрицание/цитата не искажаются, у
  планировщика нет параметра `ctx`, предел длины запроса сохранён, маскирование
  секретов `safe_fetch` не затронуто.

## Прогон на `da6299e9` (локально, 05.11.2026)

```
py -3 -m pytest tests/test_unified_reply_ur_b_no_topic_veto.py \
  tests/test_unified_reply_ur_b_search_first.py \
  tests/test_unified_reply_ur_b_review_fixes.py \
  tests/test_bgs01_factcheck_no_name_strip.py -q
→ 127 passed
```

## Что этим не доказано

- `BGS-02-EGRESS`, `BGS-05-BUDGET`, `BGS-06-ADMIN`, `BGS-07-MATRIX`, `BGS-08-ACCEPT`
  не затрагивались: их строки остаются PENDING.
- Живой прод и реальный провайдер в этой привязке не участвуют; post-deploy
  проверка BGS-08.22 остаётся на release-стадию.
- Модель, ключи и внешняя доступность провайдера не проверялись: тесты идут через
  подменный провайдер без сети.
