# P0 — RELEASE ACCEPTANCE PROBE `86ef2a64` (read-only, финальная приёмка перед деплоем)

**Вердикт: `FAILED`** — провален ровно один критерий: **№1 (meta) — 1/8 вместо 0/8**
(`raw_new_code_B.json` повтор #2, категория `announce`: «Ну давай, раз ты такой умный — сам посмотри на его сообщения выше.»).
Все остальные критерии (2–8) и вся безопасность — PASS. Деплой по этой пробе НЕ выполнялся и не разрешён до исправления.
Маршрут: application/поведение → Builder → Reviewer (это продуктовый текст L2 на hostile-ветке, не механика доставки).

- **Кандидат:** `86ef2a64d1a8ebba4b7738c7594e30ba3391c8a8` (`release/p0-2026-10-26`), worktree `adminbot-wt-rel-p0`.
- **База прода:** `534ac7dda6713fb407e0789fdddfa563251cdab4` (2.58.130), `/var/www/admin_bot`, после пробы не изменён.
- **Дата:** 26.10.2026, сеанс 07:12:13–07:16:43 UTC (328.5 с).

## 1. Подключения и стенд

| Параметр | Значение |
|---|---|
| SSH-подключения | **1** (paramiko, пароль из `deploy_commands.txt` в рантайме, ConnectTimeout 20, без ретраев); SFTP-каналы внутри той же сессии |
| Сценарий | upload tgz+скрипт → один `bash`-прогон → download 29 артефактов → cleanup; `EXEC_RC=0` |
| Staging | `/tmp/p0rel` из tarball `git archive 86ef2a64` (11 688 000 B, sha256 `6688b2266a25ac1c…`, 1502 файла); `.env`+`local_database.db` — symlink на прод; `PROBE_COMMIT` записан |
| Harness sha256 локально=удалённо | `fcd6d703d31d9bb2…` ✓; analyzer `de9783ce2f685d23…` ✓; 9 сервисных sha (16 hex) совпали с коммитом ✓ |
| `--ast-check` | `findings=0`, rc=0 |
| `--self-check` | **PASS 40/40**; L1-канон кандидата **9750 / `422e9d73d316`** (PG ещё `8261/6c2ddc17c998`, `pg_matches_code=false` — ожидаемо до миграции) |
| Fact-check unit-probe | `tests/test_factcheck_media_2026_10_25.py` **53 passed** (17.2 с), моки БД, запуск ДО создания symlink'ов — прод-БД недостижима для теста |
| Cleanup | `/tmp/p0rel*` удалены, `CLEANUP_RC=0`, остатков 0 |

## 2. Прогоны (все `--rag-source service`; новые — `--use-code-l1-canon`, `timeout 300`)

| Прогон | L1 act (raw=norm) | mode | predicate | invalid | rag_source | RAG block | dir/wr | closing | meta | L2, симв. |
|---|---|---|---|---|---|---|---|---|---|---|
| new_code_A (nat) | **research**/research, conf 0.7 | serious | true | — | service | 385 (3 строки, rerank ok 3/3) | **1/1** | 1×, user | 0/2 | 392, 464 |
| new_code_B (nat) | **hostile_rebuff**/hostile_rebuff | casual (tone annoyed, 0.95) | false | — | service | 371 (7→3, ok) | **0/0** | 1×, user | **1/2 ⚠** | 243, 650 |
| new_code_C (nat) | answer/answer, 0.95 | casual | false | — | service | 0 (`rerank_rejected`, correct=true) | **0/0** | 1×, user | 0/1 | 163 |
| new_forced_A | forced research | serious | true | — | service | 0 (`rerank_rejected`, correct=true) | **1/1** | 1×, user | 0/2 | 844, 350 |
| new_forced_B | forced research | serious | true | — | service | 608 (7→5, ok) | **1/1** | 1×, user | 0/2 | 537, 498 |
| old_A (baseline) | analysis/analysis (PG-канон) | casual | pred. нет (legacy) | — | service | 146 | 0/0 | нет конст. (legacy) | 0/2 | 325, 851 |
| old_B (baseline) | other/other (PG-канон) | casual | pred. нет (legacy) | — | service | 712 | 0/0 | нет конст. (legacy) | 1/2 (старое поведение) | 273, 603 |

`fatal`/`stage_errors` пусто во всех 7; `l1_attempts=1`; L2 `deepseek-v4-flash @ nano-gpt.com`, max_tokens 2400; PG `transaction_read_only=on` 7/7, SQLite `mode=ro`.

## 3. Критерии приёмки

| # | Критерий | Результат |
|---|---|---|
| 1 | Meta по 8 новым ответам A/B → **0/8** | **FAIL: 1/8** — `new_code_B` повтор #2, `announce` (текст выше); A 0/2, forced_A 0/2, forced_B 0/2; C отдельно 0/1; анализатор `de9783ce…` |
| 2 | L1: natural A → research; B — hostile-формулировка, честный отчёт; forced 2/2 | **PASS**: A=research ✓; B=`hostile_rebuff` (raw=norm, rewritten=false) — новый act R3-канона, в research не идёт, анализ честно выключен (0×0); forced 2/2 ✓ |
| 3 | Core 3294 / `ead77b2ab509` в system 5/5 | **PASS** 5/5 (baseline: старый 2507/`e62de1fcd7a2`) |
| 4 | RAG `rag_source=service`; пустой — только с `rag_empty_is_correct=true` + причина | **PASS** 5/5 service; пустоты: C и forced_A — `rerank_rejected` (осознанный пустой выбор реранка), `rag_empty_is_correct=true`, `rows_detail` в raw |
| 5 | FREQ из живого конфига 5/5 | **PASS** (`frequent_text=true` 5/5, baseline 2/2) |
| 6 | Payload 1×1 на research / 0×0 на answer; closing ровно 1× после `</Current_Question>` | **PASS**: research-прогоны 1×1 (3/3), answer 0×0 (2/2); closing `count_user=1, count_sys=0, after_cq=True, ends_with=True` 5/5 |
| 7 | Fact-check smoke (album+caption на первом элементе) | **PASS**: существующий unit-probe `test_factcheck_media_2026_10_25.py` — 53 passed, вкл. `test_album_caption_reaches_envelope_claim_text`; без записей в БД |
| 8 | Case C: выбор L1 + длина ответа | L1: **answer**, casual, neutral, 0.95; ответ **163 симв.** (1 повтор), meta 0/1, RAG пустой законный |

## 4. Безопасность

- SQLite: mtime/size до и после **идентичны** (`1792998108 / 1633939456`); PG read-only на уровне сессии (7/7 `pg_ro=on`).
- Прод dirty **13 → 13**; HEAD прода не изменился; юнит `active`, `NRestarts=0`, PID 611 до/после.
- healthz: **200** `{"status":"ok","version":"2.58.130"}` через `https://admin-bot.duckdns.org/healthz` (внешняя проверка; прямые `https://IP/healthz` и `:8000` наружу закрыты — через SSH-curl на 127.0.0.1:443 давал `000`, эндпоинт живёт на `:8000`/домене).
- Деплой не выполнялся; прод остался на 2.58.130; staging удалён.

## 5. Красные флаги

1. **Meta 1/8 (критерий 1, FAIL)** — первый ответ new_code_B чистый, второй на second-repeat начал с подводки-анонса «Ну давай… сам посмотри…». Это L2-текст на hostile_rebuff-плане (casual): директива NO_META в payload была ровно 1× (`no_meta_contract count=1, required=1`), т.е. контракт доставки нарушений не имеет — модель проигнорировала требование в разгромном тоне. Продуктовая правка промпта/канона → Builder.
2. Информационно: variance реранка — forced_A получил пустой RAG (`rerank_rejected`, законно) при том же запросе, что у A с 3 строками; поведение соответствует критерию 4, но живой нестабильности отбора стоит держать в поле зрения.
3. Информационно: baseline old_B дал meta 1/2 (старый код) — ожидаемое старое поведение, подтверждает дельту кандидата.
4. Мелочь: внешний curl на `https://IP/healthz` и `:8000` не отвечает (000) — рабочая точка проверки живости: duckdns-домен (200). Не дефект кандидата.

## 6. Доказательства

- Каталог: `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_release/` — 7 raw-файлов (`raw_*.json`), `meta_report.txt/json`, `summary_table.txt`, `closing_check.txt`, `pytest_factcheck.log`, `selfcheck.json`, `astcheck.log`, `remote_log.txt` (полный транскрипт сеанса), `run_probe.sh`, `SHAS256.txt` (sha256 всех 31 файлов).
- Staging tarball: sha256 `6688b2266a25ac1cc08b99db8f329352897b86b897cc5f715d1ff00acd292a10` (= `git archive 86ef2a64`).
- Прод-сессия: 1 соединение, 07:12:13–07:16:43 UTC, `EXEC_RC=0`, cleanup подтверждён.
