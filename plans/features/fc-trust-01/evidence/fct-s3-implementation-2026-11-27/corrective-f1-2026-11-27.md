# FCT-S3-RETRIEVAL — корректива F1 (Builder, 27.11.2026)

Reviewer r1: `evidence/fct-s3-retrieval-2026-11-27/review-r1.md`, вердикт **NEEDS_FIXES**, единственная
блокирующая находка **FCT-S3-F1** (IN_SCOPE, HIGH). F2–F5 — backlog, не трогались.

- База/деплой: `9516c912554bb1062f62a63b6689f418c1cb5425` = 2.58.257.
- Предыдущий кандидат (где F1 воспроизведён): `2eb9f9b617a21428606436aacffb1119932f8f13` (tip `a2e554a86`).
- Новый кандидат: **`2c811d98b7257810c2fef5b61ce7b416798ccb40`**, ветка `feat/fct-s3-retrieval`.
- Контракт: `fct-s3-s4-contract-2026-11-27.md`, sha256
  `adb3bc325c4c4048d79d16b62f5b47c941a356ab4ee1c7b7953a5f3050630190`.

## 1. Причина и точечное исправление (3 места, один файл)

F1: при смешанных попытках (база/уточнение: `empty` ↔ `429`/`timeout`/`provider_error`) технический
исход claim схлопывался в `no_relevant_sources` / `insufficient_evidence`, `gap_note` — «подходящих
источников не нашлось», run-level `stop_reason` — `no_progress`. Нарушение §3.3 («технический код не
превращается в „источник отсутствует“/`insufficient_evidence`») и строки `FCT-301`.

Исправлено в `services/factcheck_planner.py` (write scope S3, никаких других файлов продукта):

1. `_technical_detail` (`:2485-2511`): убраны гейты `not (run.empty or run.irrelevant)` у
   `provider_timeouts` и `rate_limits` — техническая причина попытки больше не скрывается
   одновременной пустой выдачей.
2. `_finalize_claim` (`:2514-2648`, ветка попыток `:2554-2565`): при `attempts > 0` технический
   `status_detail` вычисляется ПЕРВЫМ; `no_relevant_sources` используется только если технических
   причин нет (`_technical_detail` вернул `search_not_started`). Ветка
   `elif run.empty or run.irrelevant:` перед технической удалена.
3. run-level `stop_reason` (`run_retrieval`, `:3218-3227`): отказы провайдера больше не маскируются
   одновременными `empty/irrelevant` попытками — `rate_limit` / `provider_timeout` /
   `providers_unavailable` выбираются по фактическим счётчикам.

Поведение после фикса (обе полярности, все три причины): `status_detail` = `rate_limit` /
`provider_timeout` / `provider_error`, `outcome=not_checked_technical`,
`reason_code∈{provider_unavailable, deadline_exceeded}`, `gap_note` — техническая фраза без «не нашлось»,
run-level `stop_reason` — `rate_limit` / `provider_timeout` / `providers_unavailable` (не `no_progress`).
Часть с displayable-evidence по-прежнему сохраняет содержательный статус при любом run-level лимите
(инвариант §5 не изменён; покрыт `test_claim_with_evidence_keeps_status_under_run_limit`).

## 2. RED на `2eb9f9b6` (до фикса)

Тот же модуль (52 теста: 45 прежних + 7 новых), отдельный detach-worktree на `2eb9f9b6`:

| Прогон | Результат | Raw |
|---|---|---|
| весь `tests/test_fc_trust_retrieval.py` | **7 failed, 45 passed** | `raw/red_f1_module_on_2eb9f9b6.txt` |
| только новые смешанные кейсы (`-k "mixed_attempts or technical_attempt_outranks"`) | **7 failed** | `raw/red_f1_mixed_on_2eb9f9b6.txt` |

Падения — ровно F1: `assert 'no_relevant_sources' == 'rate_limit' | 'provider_timeout' |
'provider_error'` для `empty→429`, `429→empty`, `empty→timeout`, `timeout→empty`,
`empty→provider_error`, `provider_error→empty` и `irrelevant→429`.

## 3. GREEN после фикса

| Прогон | Результат | Raw |
|---|---|---|
| `tests/test_fc_trust_retrieval.py` (45 + 7 новых = 52) | **52 passed** | `raw/green_slice_f1.txt` |
| контрактные наборы §8 (12 файлов) | **391 passed** | `raw/green_acceptance_f1.txt` |
| широкий набор S3-потребителей (40 файлов) | **1234 passed** | `raw/green_broad_f1.txt` |
| соседние контуры (mem_time_policy, unified-reply no_topic/review, self-diag golden/samples, direct_chat) | **310 passed** | `raw/green_consumers_f1.txt` |

**Предсуществующих red-ов нет** в прогнанных наборах. Полный `tests/` не запускался (объём
пропорционален затронутым контурам, как и в r1).

## 4. Мутации (21/21 KILLED)

18 прежних M-S3-01..18 перепрогнаны на новом кандидате + 3 новые, прицельно к трём исправленным
местам. Полный лог — `raw/mutations_f1.txt` (21 `KILLED`, 0 `SURVIVED`, 0 `PATCH_NOT_FOUND`).

| ID | Мутация | Убийца |
|---|---|---|
| M-F1-01 | вернуть claim-level `empty/irrelevant` перед технической ветвью | `test_mixed_attempts_keep_technical_claim_outcome` (6 failed) |
| M-F1-02 | вернуть run-level гейт `not (empty or irrelevant)` | тот же тест (6 failed) |
| M-F1-03 | вернуть гейт `not (empty or irrelevant)` у `provider_timeouts` | тот же тест (2 failed: timeout-кейсы) |

Остальные 18 — как в реализации (см. `raw/mutations_f1.txt`): каждая роняет свой целевой тест.

## 5. Замечания к тестам из r1 §3.2 (дешёвые, без изменения приёмки)

1. `tests/test_factcheck_fc_r1_fix.py::test_run_retrieval_ranks_and_fetches_primary`: вырожденный
   ассерт порядка заменён на различающий — фикстура обязана содержать ссылки с разным охватом частей
   (`max > min`), первая ссылка должна покрывать максимум частей и быть `primary` (CDC 2 части против
   wiki 1). При вырожденной фикстуре тест падает, а не проходит молча.
2. `tests/test_factcheck_resources.py::test_on_search_text_is_a_100k_portion_without_losing_tail`:
   удалён тавтологичный `full == portions[0] + "".join(portions[1:])`; вместо него проверяется, что в
   проекции не потерян ни один блок (`full.count("https://weather.example/") == 20`) вместе с прежними
   различающими проверками длины/`endswith`/`total_chars`.

## 6. Что не изменено / парки

- F2–F5 (backlog) не трогались: `cancelled`/`source_unreadable` узость, host-derived `material_role`,
  подписи новых кодов в рендере (S5), расширение `timeframe`-якоря.
- Продуктовые файлы вне S3 (оркестратор, `factcheck_service.py`, рендер, промпты, `web/**`,
  `config/settings.py`, `temporal_factcheck.py`, `safe_fetch.py`, `factcheck_attribution.py`) — ноль
  изменений; флагов/эндпоинтов/миграций нет.
- Деплой не выполнялся; прод, карты, `progress_scope`, очередь и Telegram не затрагивались.
- Effective-конфигурация прода и живая выдача провайдеров не перепроверялись (P-S3-6/P-S3-7).

## 7. Машиночитаемый блок

```json
{
  "slice": "FCT-S3-RETRIEVAL",
  "finding": "FCT-S3-F1",
  "status": "fixed_pending_rereview",
  "base_sha": "9516c912554bb1062f62a63b6689f418c1cb5425",
  "previous_candidate": "2eb9f9b617a21428606436aacffb1119932f8f13",
  "candidate_sha": "2c811d98b7257810c2fef5b61ce7b416798ccb40",
  "branch": "feat/fct-s3-retrieval",
  "changed_files": [
    "services/factcheck_planner.py",
    "tests/test_fc_trust_retrieval.py",
    "tests/test_factcheck_fc_r1_fix.py",
    "tests/test_factcheck_resources.py"
  ],
  "fixed_spots": [
    "factcheck_planner._technical_detail:2485-2511 (gates removed)",
    "factcheck_planner._finalize_claim:2514-2648 (attempts>0 -> technical first)",
    "factcheck_planner.run_retrieval stop_reason:3218-3227 (provider failures not masked)"
  ],
  "red": {"module_on_2eb9f9b6": "7 failed, 45 passed", "mixed_only": "7 failed",
          "raw": ["raw/red_f1_module_on_2eb9f9b6.txt", "raw/red_f1_mixed_on_2eb9f9b6.txt"]},
  "green": {"slice": 52, "acceptance": 391, "broad": 1234, "consumers": 310,
            "preexisting_reds": []},
  "mutations": {"total": 21, "killed": 21, "survived": 0,
                "new": ["M-F1-01", "M-F1-02", "M-F1-03"],
                "log": "raw/mutations_f1.txt"},
  "test_quality_fixes": [
    "fc_r1::test_run_retrieval_ranks_and_fetches_primary non-degenerate coverage ordering",
    "resources::test_on_search_text_is_a_100k_portion_without_losing_tail tautology removed"
  ],
  "backlog_untouched": ["FCT-S3-F2", "FCT-S3-F3", "FCT-S3-F4", "FCT-S3-F5"],
  "deploy": false,
  "telegram_messages": false
}
```
