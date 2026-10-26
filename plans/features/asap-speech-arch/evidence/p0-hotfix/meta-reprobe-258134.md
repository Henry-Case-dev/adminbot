# META-RESIDUAL-REPROBE на проде 2.58.134 @ `076f7391` (read-only, реальный LLM, без Telegram)

**Вердикт: PASS — residual устранён на развёрнутом дереве: 0/6 мета-анонсов** (критерий lanes «если 0 анонсов во всех ответах → residual resolved, записать PASS»).

- **Развёрнутая версия:** `076f7391a01157bad106372d405d109085a78dbc` (2.58.134, прод HEAD подтверждён в начале и в конце сеанса).
- **Дата:** 26.10.2026, сервер UTC 20:28:27–20:31:02 (основной прогон 155.5 с).
- **Что проверялось:** остаточный анонс из release-пробы `86ef2a64` (1/8, `new_code_B` повтор #2, «Ну давай, раз ты такой умный — сам посмотри…» — `probes_release.md` §5.1). После неё DELTA-DEPTH (`8e8c8c27`, merge `d167d686`) добавил substance-строку в payload writer'а; NO_META остался announcement-only. Решает закрытие строки `CORE-META-INTRO-REMOVE` карты `requirements-map-p0-corrective.json`.

## 1. Стенд (read-only, без записи/рестартов)

| Параметр | Значение |
|---|---|
| Staging | `/tmp/p0mr` из `git archive 076f7391`; файлсет = полное дерево минус `plans/`, `media/`, `extra_images/`, `web/`, `tests/` (477 файла) + 4 raw-фикстуры негативного контроля анализатора (`probes_final2/raw_new_*.json` из того же коммита) = 481 файл; tarball sha256 `db17678200ba23e028a7d3607f2e54d8726f7c26f99aeb1b424ee759e11a0838` (7 399 672 B), sha на сервере совпал |
| Артефакт-пины stage=prod (16-hex) | `settings.py 10073eb7567e`, `direct_chat_service.py 5add3022e464`, `direct_l1.py 4ce9c972d5b0`, `prompt_style_blocks.py 7e67090aa59a`, `chat_prompts.py 0412d716ecac`, `response_extent.py 0ebead84bf30` — **6/6 совпали** (= пины деплоя DEPLOY-258134) |
| Harness | `probes_full/harness_probe_full.py` из коммита `076f7391`, sha256 `bafe0396282b01ef63c1604be4c507e2c21ce77174d824404f5f7f795d8f25d0` (локаль=удалённо ✓) |
| Analyzer | `probes_full/analyze_l2_meta.py` из того же коммита, sha256 `de9783ce2f685d23787d44a14b045f7d5d98c3d74677b854ff15503a957d43f8` (не менялся с R2; self-check на стенде **PASS**, негативный контроль 5/5 преамбул) |
| `--ast-check` | findings=0, rc=0 |
| `--self-check` harness | **PASS 44/44**; L1-канон кода **9750 / `422e9d73d316`** |
| SQLite | снапшот-копия прод-БД (`sqlite3` python-backup из ro-URI, 12 с, 1 639 641 088 B, sha16 `2edc12f86a16975b`), staging `local_database.db` → снапшот, работа в `mode=ro`; **прод-БД не тронут**: mtime/size до и после идентичны (`1793046469 / 1639636992`) |
| PG | `sources.pg_read_only = "on"` во всех прогонах (session-level READ ONLY) |
| Telegram | нет (стенд без бота) |

**SSH-сеансы (fail2ban-safe):** всего 3 одиночных логина `nik`, интервалы > 60 с, ноль ретраев/поллеров, ни одной неудачи auth:
1. 20:23:26Z — оборван **до** любых команд: локальная ошибка пути tarball (FileNotFoundError), connect закрыт штатно (4.1 с).
2. 20:25:09Z — upload ок, main rc=92: на сервере **нет CLI `sqlite3`** (rc=127) — в r3 использовался python-модуль, а не бинарь. Починка DevOps-механики: сценарий переведён на `$PY -c "import sqlite3…; src.backup(dst)"` (поведение продукта не затронуто), cleanup 100%, остаток 0.
3. 20:27:50Z — **полный прогон**: rc=0, download 18/18 артефактов, cleanup rc=0, остатков в `/tmp` 0.

Внешний `https://admin-bot.duckdns.org/healthz` — **200** `2.58.134` до и после (loopback-курл из SSH даёт 000 — известная особенность, рабочая точка — duckdns-домен). Прод после пробы: HEAD не изменён, dirty 13→13, unit `active`, **NRestarts=0**, MainPID 308006 до/после.

## 2. Прогоны (все `--rag-source service --use-code-l1-canon`; L2 `deepseek-v4-flash @ nano-gpt.com`)

| Прогон | Case | L1 plan/act (источник) | mode | no_meta | delta | RAG | Meta | Симв. | Первые предложения |
|---|---|---|---|---|---|---|---|---|---|
| mr_B_nat #0 | B (hostile-просьба «…проанализируй сообщения Ринтаро… заключение злобоный или не злобоный») | **deep_research/research** (llm, 0.7) | deep_research | 1×1, plan_block | 1×1+substance 1×1 | 7→5, rerank ok | **0/1** | 331 | «Да похуй, нормальный он. Не злобный.» |
| mr_B_nat #1 | B, повтор | deep_research/research (llm) | deep_research | 1×1 | 1×1+sub 1×1 | (тот же прогон) | **0/1** | 546 | «Ну, судя по логам, Ринтаро не злобный, а просто ебанутый на свою голову. Он не оскорбляет людей в чате…» |
| mr_A_nat #0 | A («Бот проанализируй мои сообщения в чате и скажи, я злобный?») | **serious/research** (llm, 0.85) | serious | 1×1 | 1×1+sub 1×1 | 3/3 ok | **0/1** | 460 | «Да хуй знает, Макс. Ты выглядишь как нормальный мужик, который заходит по рофлу…» |
| mr_A_nat #1 | A, повтор | serious/research (llm) | serious | 1×1 | 1×1+sub 1×1 | (тот же прогон) | **0/1** | 374 | «Макс, ты не злобный. Ты скорее раздражительный и нетерпимый к чужой глупости…» |
| mr_A_forced #0 | A, forced research | research (forced, 1.0) | serious | 1×1 | 1×1+sub 1×1 | пусто (`rerank_rejected`, `rag_empty_is_correct=true`) | **0/1** | 206 | «Да ну, злобный ты только когда просыпаешь свой кофе на клавиатуру…» |
| mr_C #0 | C («Слушай, а ты дождь любишь…», synthetic) | **casual/answer** (llm, 1.0) — режим не навязан | casual | 1×1 | **0×0 (req=0)** — delta-инструкция отсутствует | пусто (`rerank_rejected`, correct=true) | **0/1** | 250 | «Да не, дождь норм, пока ты дома и есть повод не выходить…» |

**Итог анализатора по всем 6 ответам: TOTAL 0/6** (`meta_report.txt/json`; отчёт строился по полным текстам, не только префиксам; `invalid`/`fatal` пусто во всех 4, `l1_attempts=1`).

## 3. Регрессии (все чистые)

| Проверка | Результат |
|---|---|
| Analysis-инварианты payload | research-прогоны `invariant_1x1=true` (3/3), C-answer `invariant_0x0=true` — счётчики 1×1/0×0 на месте |
| Core | **3294 симв. / `ead77b2ab509`, `in_system=true`** — 6/6 ответов (rev-метка `r8`) |
| DELTA-DEPTH | research: `DELTA_READY_INSTRUCTION_TEXT` 1×1 + substance 1×1 (носитель plan_block) — 3/3; casual/answer (C): delta **0×0**, required=0 — «инструкция отсутствует» подтверждена |
| Story echo | 5-граммные пересечения ответов с `<chat_lore>` — **0** во всех 6 |
| NO_META | контракт `count=1, required=1, carrier=plan_block` 4/4 прогонов (C включительно); нарушений нет |
| FREQ | `frequent_text=true` 4/4 прогонов из живого конфига |
| L1 | natural A → research ✓; forced 1/1 ✓; C → casual/answer (research-ложняк не взят) ✓; B → `deep_research/research` ×2 — **информационно**: в пробе `86ef2a64` та же реплика планировалась как `hostile_rebuff`; живая вариативность L1-маршрута, к мета-анонсу не относится (оба ответа чистые) |
| Реранн-вариативность | forced_A и C получили законно пустой RAG (`rerank_rejected`) при непустом у natural — тот же паттерн, что в `probes_release.md` §5.2, поведению соответствует |

Шум стенда (stderr, идентичен во всех прогонах, некритичен): graceful-fallback предупреждения read-only-контура — embedding cache (`attempt to write a readonly database`), `lessons read failed`, `graphrag touch/KNN → FTS fallback`, `no such module: vec0` (FTS5-fallback по R3). Критический путь не задет, `invalid` пусто.

## 4. Вывод для карты

Residual `CORE-META-INTRO-REMOVE` (мета-анонс на hostile/analysis-формулировке) на развёрнутом дереве `076f7391` **не воспроизводится**: 0/6, включая оба повтора ранее падавшей формы Case B. Строка может считаться закрытой и на деплое; для биндинга к deployed-кандидату PM может добавить evidence-entry: candidate `076f7391`, artifact — этот файл, observation «0/6 анонсов (вкл. 2 повтора Case B), анализатор `de9783ce…`, стенд из артефакта деплоя 6/6 пинов».

## 5. Доказательства (scratch, вне репо)

- Каталог: `OPENCODE_WORKFLOW_SCRATCH/tmp/meta-reprobe-258134/results/` — 4 raw (`raw_mr_*.json` с встроенным payload/счётчиками), `meta_report.txt`/`.json`, `selfcheck.json` (44/44), `astcheck.log`, `analyzer_selfcheck.log` (PASS), 8 stdout/stderr-логов, `remote_log.txt` (полный транскрипт основного сеанса).
- sha256 (полн. список в сеансе): `raw_mr_B_nat.json 1727d0c4…`, `raw_mr_A_nat.json 645b669b…`, `raw_mr_A_forced.json c1dba99d…`, `raw_mr_C.json dc5ed045…`, `remote_log.txt f59b19c8…`.
- Staging tarball: `…/meta-reprobe-258134/p0mr_probe.tgz` sha256 `db17678200ba23e028a7d3607f2e54d8726f7c26f99aeb1b424ee759e11a0838` (= `git archive 076f7391` минус heavy-каталоги + 4 фикс. анализатора, скрипт сборки воспроизводим).
- Сценарий/драйвер: `stage_meta_reprobe.sh`, `run_meta_reprobe.py`, `analyze_results.py` — там же.
- Cleanup: staging/OUT/DB/tarball/скрипт удалены (CLEANUP_RC=0, остатков 0); прод-БД и прод-HEAD не тронуты.
