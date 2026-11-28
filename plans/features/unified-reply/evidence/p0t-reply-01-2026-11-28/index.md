# P0T-REPLY-01 — evidence index

- `architecture.md` — решение Architect (R4, лестница, seam, тесты/мутации).
- `implementation.md` — что реализовано, команды/результаты, мутации, паритет,
  честные ограничения.
- `raw/`:
  - `product.diff` — диф пяти продуктовых файлов;
  - `baseline-pytest.txt` / `candidate-pins.txt` — пиновый набор на базе/кандидате;
  - `baseline-new-suite-red.txt` / `candidate-new-suite.txt` — новый файл тестов
    на базе (RED) и на кандидате (GREEN);
  - `mutations.py` / `mutations.txt` — 6 мутаций (M1–M6), каждая RED; восстановление GREEN;
  - `candidate-batch-direct.txt` + `baseline-batch-direct-pair.txt` — Direct-батч (22 файла)
    и сверка набора падений на базе;
  - `candidate-batch-reply.txt` + `baseline-batch-reply-pair.txt` /
    `baseline-batch-reply-others.txt` — reply-батч (24 файла) и база;
  - `candidate-batch-context.txt` / `baseline-batch-context.txt` — контекст/бюджеты L1;
  - `verify-canon.txt` — печати/метки/`FACTORY_SET`, дельта R3→R4, known-canon, лестница;
  - `regression-set-compare.txt` — машинная сверка наборов падений candidate vs base;
  - `mutations.py` / `regen_evidence.py` — воспроизводимые генераторы evidence (не тесты).

Формат pytest-артефактов — только строки `FAILED/ERROR` + итог, без трейсбеков
(приватность и компактность); полные прогоны воспроизводимы командами из
`implementation.md` §3.
