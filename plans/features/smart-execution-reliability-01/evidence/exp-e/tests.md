# Проверки EXP-E-TRUNC / EXP-E-LAG

Worktree: `.../exp-e-trunc-lag-476956d0821c-5b46eb21`, branch
`fix/exp-e-trunc-lag`, code SHA `a5049c842` (review fixes B01/N01; база
предыдущего кандидата `ece1e1ca9`).
Python: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (3.12.0).
Production/SSH/LLM/live не выполнялись.

## Команды и результаты

1. Новый amendment-набор:

```
python -m pytest tests/test_exp_e_trunc_lag_amendment.py -q
11 passed in 6.84s
```

2. Релевантный Experience/смежный набор (18 файлов, включая SXR-I2,
   semantic checkpoint, B02, D05, blocks A–F, stale recheck, M2 consumers,
   humor, lesson strategy, new amendment):

```
python -m pytest <18 files> -q -k "not deep_sleep_not_mixed_with_lessons"
290 passed, 1 deselected, 1 warning in 38.90s
```

3. Review RED→GREEN B01/N01: см. `review-fixes-b01-n01.md`.
   RED `ece1e1ca9` — 2 failed (tail `[50,50,50]`; fresh не обработан при
   tail backoff); GREEN `a5049c842` — 11 passed.

Warning — `StarletteDeprecationWarning` (httpx), не связан с изменением.

3. Source-pin `test_mca16_experience_block_d_round1039.py` обновлён:
   `_semantic_llm_call` содержит единственный `generate(`;
   `max_output_tokens=budget`; `semantic_output_budget(`;
   `SEMANTIC_BATCH_MAX_TOKENS` отсутствует в модуле. Тест проходит в п.2.

4. Pre-existing baseline failure (не candidate):

```
base 56e2450d2:
python -m pytest tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons -q
1 failed in 23.89s
```

Причина — `graph_facts` в docstring, существующем в base; assertion
`"graph_facts" not in _jobs_src()`. К изменению не относится, не
исправлялось.

5. Синтаксис/дифф:

```
python -m py_compile services/mca_experience_jobs.py tests/test_exp_e_trunc_lag_amendment.py tests/test_mca16_experience_block_d_round1039.py
exit 0
git diff --check
exit 0
```

6. Plan gate (канонический planning checkout, где есть amendment map):

```
requirements_gate.py check --repo C:\Code\Python\adminbot \
  --map .../requirements-map-exp-amendment.json --stage plan
stage=plan inventory=15 manual=2 scoped=0 errors=0
```

7. RED/GREEN harness (`exp_e_repro_final.py`, fake LLM, SQLite):
   base и HEAD — см. `red-green.md` (A/B/C); production не затрагивался.

## Честные ограничения

- Реальный production-спад lag/throughput не измерен: нет деплоя в рамках
  задачи → `REVIEW/RFL`, не `VERIFIED`.
- Реакция конкретной production-модели на бюджет 8192 не проверялась
  (запрещены LLM/прод). Формула и bounded-путь проверены
  детерминированными тестами; реальная успешность батчей — post-deploy.
- Archive re-anchor для чата без `archive_start` не выполнялся: это
  сдвинуло бы основной курсор через 2M строк. Fresh-полоса сохраняет
  старый хвост и честный lag; историческое покрытие архива — отдельный
  RFL/backlog, не блокирует E-TRUNC/E-LAG.

## Артефакты

- `contract.md` — требования, границы, инварианты, статус.
- `implementation.md` — механизмы, формула, лимиты, production-математика.
- `red-green.md` — точные RED/GREEN выходы и карта тестов.
- `tests.json` — машиночитаемая сводка.
