# rerun_b — повторный сэмпл R3 (2026-10-25 11:56:33–12:01:14 UTC)

Второй прогон той же матрицы на том же кандидате `fe1e514a`, тем же стендом
(`harness` `a750a98368a7cbad…`, `analyzer` `de9783ce2f685d23…`), из отдельного
сеанса: **один ssh-логин**, стейджинг заново (`/tmp/p0c-int3`), 7 прогонов,
`MATRIX_DONE`, сессия закрыта, процессов не осталось.

Зачем: первый сэмпл (отчёт `../probes_final5.md`, коммит `e72be00a`, файлы — в родительской
папке) дал L1 natural `research` 2/2 и непустой RAG в `newC`. Повтор проверяет, устойчиво ли это.

Чем этот сэмпл отличается по факту:

| | сэмпл A (коммит `e72be00a`) | сэмпл B (эта папка) |
|---|---|---|
| L1 A / B | `research` / `research` | `research` / **`disagreement`** |
| RAG непустой | `newC` 951 симв. | `new_forced_B` 146 симв. |
| RAG пустой | 4/5 | 4/5 |
| мета кандидата | 0/9 | 0/9 |
| Core / FREQ / payload / closing | 3294/`ead77b2ab509` / true / 1×1 | то же |
| baseline RAG | 146 / `no_facts` | 146 / 146 |

Привязка: `stage_sha.txt` (кандидат, tgz sha `ac1991d88413a5ae…`, sha модулей), `sha_local.txt`
(локальные sha), `local_meta.json`. В raw `pins.git=ERR` — в стейджинге нет `.git`; модули сверены
по sha с worktree `fe1e514a`.

Файлы: `raw_*.json` (7), `*.out`/`*.err` (7+7), `exits.txt`, `MATRIX_DONE`, `stage_sha.txt`,
`selfcheck.out/.err`, `astcheck.out`, `run.log`, `precheck.txt`, `postcheck.txt`, `table_r3.txt`,
`analysis.json`, `sha256.txt`.
