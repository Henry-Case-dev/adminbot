# P0C-INT — живой прогон кандидата `e0a46414` на проде

**Итог: FAILED.** Живая приёмка не получена: стенд кандидата падает на RAG-шаге
(`UnboundLocalError: llm`), из-за чего L2 не вызывается вообще. Это дефект
**стенда/кандидата**, а не прода: правок в `/var/www/admin_bot` не было.
Продуктовые факты, которые успели сняться до падения, — положительные (§4).

- Кандидат: `e0a46414` (ветка `task/p0c-int`); staged-дерево `e10c6949`.
  Проверено локально: `git diff --stat e0a46414 e10c6949` по коду пуст —
  разница только в `plans/.../evidence/p0-hotfix/int-fix.md`.
- База/прод: `534ac7dd`, релиз 2.58.130, `/var/www/admin_bot`.
- Снято: 2026-10-25 08:31–08:34 UTC (локально 20:31–20:34, UTC+12).
- Деплоя, рестартов, checkout, Telegram-сообщений и записей не было.

## 1. Биндинг источника (доказано на сервере)

| Что | Значение |
|---|---|
| staged commit | `e10c6949` (дерево кода = `e0a46414`) |
| staging | `/tmp/p0c-int/tree`, 443 файла, 16 MB (`tar` из `git archive`-набора: `.py`, `config/`, `probes_full/`, `info_text.md`) |
| `.env`, `local_database.db` | симлинки на `/var/www/admin_bot` (staging не копировал БД) |
| `probes_full/harness_probe_full.py` sha256 | `77b8a90faa3668b05bdb6d04cd7d0ea108e07b522ca26dec6b19de02f8468cf8` — совпал с локальным кандидатом |
| `probes_full/analyze_l2_meta.py` sha256 | `de9783ce2f685d23787d44a14b045f7d5d98c3d74677b854ff15503a957d43f8` — совпал с локальным |
| `services/direct_chat_service.py` sha256 (staged) | `3c9ecc4d82b3648686e38ee30bce2a8e29161a1f3255d33ec2dcca6a690cbe0a` |
| `services/mca_expression.py` sha256 (staged) | `f292ad43e733e1b29bf2a6292b0175f03d7c6cb3e4750f0aa90fab9d8342487d` |
| интерпретатор | `/var/www/admin_bot/venv/bin/python` |
| remote self-check | **PASS**, канон L1 `9288` / `23aae0c9499d` |
| PG-канон в БД | `6c2ddc17c998` (≠ код) — ожидаемо до миграции, `canon_source=code` |

## 2. Коннекты (честно: 3)

| # | Время (UTC) | Что | Итог |
|---|---|---|---|
| 1 | ≈08:29 (точно не зафиксирован) | staging + первый прогон | **Staging-ошибка**: SFTP-upload до `mkdir /tmp/p0c-int` → `FileNotFoundError`. Прогонов/LLM-вызовов нет, записей нет. |
| 2 | 08:31:35 → | тот же сценарий после локального фикса | До `/tmp/p0c-int` дошёл, self-check PASS, но `run.sh` исполнил только `newA` и оборвался (см. ниже). Канал завершился, лог обрывается после `rc_newA=0`; `out.tgz` не появился. |
| 3 | 08:33:51 → 08:34:03 | только чтение: `run.log`, `out/`, состояние прода, выгрузка `partial.tgz`, `rm -rf /tmp/p0c-int` | 12 с, всё снято и выгружено |

3-й коннект — вынужденный: без него не было бы ни safety-доказательств
(состояние БД/юнита после), ни самих raw-файлов. Повторных LLM-прогонов не
делал: дефект §3 воспроизводится в каждом прогоне и делает матрицу
бессмысленной. Между коннектами пауза ≥60 с, логин одиночный, без ретраев.

**Причина обрыва 2-го прогона — инструментовка коллектора, не прод:** лог
`run.sh` обрывается сразу после `rc_newA=0`, следующая строка
(`err_newA_bytes`) не записана; exit-status канала мой коллектор не
зафиксировал. Никаких команд, меняющих прод, `run.sh` до обрыва не выполнял
(только чтение БД и staging в `/tmp`).

## 3. Блокер: стенд не доходит до RAG и L2 (дефект кандидата)

`probes_full/harness_probe_full.py` в `_run`:

```
1030:  args.root, sq, question, window_text, hot, llm=llm,   # RAG-вызов
1072:  llm = _make_llm(args.root, result)                    # присваивание ПОЗЖЕ
```

Так как `llm` присваивается в той же функции ниже, Python считает его
локальным → на строке 1030 `UnboundLocalError`. Живой факт из `newA.json`:

```
"invalid": "rag_render"
"stage_errors": {"rag": "UnboundLocalError: cannot access local variable 'llm'
                        where it is not associated with a value"}
"rag": {"rag_source": "dump", "block_chars": 0}
"l2_chars": [], "l2_meta": {"flagged": null, "total": null}
```

Следствия:

1. **RAG-путь сервиса (`--rag-source service`) не исполняется ни разу** — это
   ровно тот пункт F4, который должен был закрыться живым прогоном.
2. `_run` возвращает `invalid=rag_render` до L2, поэтому **ни одного L2-ответа
   не сгенерировано**: критерий «0 из 8 без мета-вступления» измерить нельзя
   (`analyze_l2_meta.py --raw newA.json` → `TOTAL 0/0`).
3. Баг не зависит от `--root`: старые baseline-прогоны используют тот же
   файл стенда → упали бы так же.
4. `--self-check` этого не ловит: он не вызывает `_run`, а проверяет сборку
   payload/детектор статически. Локальный self-check тоже PASS (31 проверка),
   т.е. дефект проходит мимо «зелёного» контроля.

Воспроизведение локально без прода: статически видно, что первое чтение `llm`
(1030) стоит выше единственного присваивания (1072). Это merge-артефакт F4:
вызов RAG вставлен в `_run` раньше, чем существовавшая инициализация LLM.

**Что нужно от Builder + Reviewer (не DevOps):**

- поднять `llm = _make_llm(args.root, result)` выше RAG-вызова (или передать
  готовый `llm` в `_run` из `main`), чтобы `--rag-source service` реально
  исполнялся;
- закрыть слепое пятно: тест/self-check, который падает при несвязанном `llm`
  (например, прогон `_run` на стабе БД с проверкой
  `result["rag"]["rag_source"] == "service"`);
- после фикса — повторное ревью **точного** кандидата; затем DevOps повторяет
  ту же матрицу (5 новых + 2 старых) на том же стенде.

## 4. Что продукт уже показал на реальных данных (не PASS приёмки)

Из `newA.json` (реальный вопрос A из БД, окно 64 сообщения, PG read-only `on`):

| Факт | Значение |
|---|---|
| L1 план (естественный, не форс) | `reply / research / compact / answer`, mode `serious`, conf 0.85, 1 попытка, 2.6 с |
| канон L1 | код `9288` / `23aae0c9499d` (`pg_matches_code=false`, PG ещё старый) |
| **Core слой** | **chars 3294**, sha12 `ead77b2ab509`, `rendered=true`, `in_system=true`, revision `r8.ead77b2ab509` — совпало с ожиданием F6 |
| system | 14409 chars / `9889ce83d9f4`; 14 слоёв, из них отрендерены core/identity/response_plan/expression/style_policy_hint |
| payload | `directive=1, writer=1, no_meta=1`; `1x1=true`; plan-блок 1171 chars `d7ca1bd6f83e` |
| no-meta контракт | `applies=true, count=1, required=1, carrier=plan_block` |
| **FREQUENT** | `expression_check.frequent_text=true` (в чате и глобально `profanity=frequent`) |
| RAG | **не проверен** (см. §3) |
| L2/мета | **не проверены**: ответов 0, `0/0` |
| модель стенда | `deepseek-v4-flash` @ `nano-gpt.com` |

То есть продуктовые правки Core/FREQ/payload/L1 на реальном дереве выглядят
так, как задумано, но живая приёмка P0 (0/8 меты, RAG A≠B, case C, forced
research) остаётся **неподтверждённой**.

## 5. Безопасность: прод не изменён

| Проверка | До | После (08:33:51Z) |
|---|---|---|
| `local_database.db` mtime/size | `2026-10-25 08:30:51.522` / `1624875008` | то же самое |
| `...db-wal` | `08:31:35.249` / 4457872 | `08:33:43.688` / 4457872 |
| `...db-shm` | `08:31:24.145` / 32768 | `08:33:25.649` / 32768 |
| git HEAD | `534ac7dd` | `534ac7dd` |
| dirty count | 13 | 13 |
| unit | `active`, `NRestarts=0`, `ActiveEnter=2026-10-24 21:03:19 UTC` | то же |
| healthz c сервера | `http=308`, `https=000` | `http=308`, `https=000` |

Пояснения, без подгонки:

- Основной файл БД **не менялся** (mtime и размер идентичны). `-wal/-shm`
  обновил живой бот (он пишет в WAL постоянно); наш процесс открывал SQLite
  только `mode=ro`, PG — `SET SESSION ... READ ONLY` + `pg_read_only=on` в raw.
- `https=000` на `127.0.0.1` — TLS/SNI-особенность локального вызова, не
  показатель падения: `active`, `NRestarts=0`, журнал не прерывался, внешний
  `/healthz` и раньше не отвечал с рабочей машины. HTTP-проверка `308` —
  штатный redirect.
- Лишних процессов стенда не осталось (`pgrep` — только сам `pgrep`),
  `/tmp/p0c-int` удалён после выгрузки.

## 6. Побочные находки (не блокеры этой полосы)

1. `newA.err`: `[humor-feedback] lessons read failed: AttributeError: 'NoneType'
   object has no attribute 'db'` (2×). В стенде не инициализирован
   `mca_experience` store; ошибка перехвачена, но слой lessons в прогоне не
   участвовал — при живом прогоне это надо либо инициализировать, либо явно
   помечать `lessons_absent`.
2. Отчёт стенда печатает `rag_source: null` в summary (читает несуществующий
   top-level ключ), хотя в `rag.rag_source` значение есть. Косметика, но
   сбивает при чтении stdout.

## 7. Артефакты

`plans/features/asap-speech-arch/evidence/p0-hotfix/probes_final3/`:

| Файл | sha256 |
|---|---|
| `newA.json` | `a558ff132ee25fab4d59cc56ec071ca4ce06b5bc921d8dd61d3bdc344e6bdbd0` |
| `newA.err` | `806714a60d4d390a47c114b6afd7b901461ba384fcc14b0a08966e17cf4ff423` |
| `selfcheck.json` | `d47d1dd03b4557614809f6aad4d110ee6d449a6ebe143c96aeb887dfe9482246` |
| `run.log` | `c1b5d8a7fafcfc660aedfd9a05613e0483cc744d6aac4410482ce7802b8e9d85` |
| `stage_sha.txt` | `f36fe9f2e0775b8e837fd870c8abb039ec7532aad55943d1bc6563a4c67ac45c` |
| `db_before.txt` | `db549959ff87f2b12cd9de7ad8ec42f66ad9b578c06b46a33d75976c14049aaf` |
| `head_before.txt` | `3a60e44999bfe54f179f225e7aba151b5e3fdd6f3db078a478266b2a0a8b664d` |
| `dirty_before.txt` | `1a252402972f6057fa53cc172b52b9ffca698e18311facd0f3b06ecaaef79e17` |
| `unit_before.txt` | `9cfa8afc8637ebd8a0ff7dccba3720bc7c76b25edccfe4bb32872eec0a58378e` |
| `health_before.txt` | `599becd1acbfaba5f0894633c934bb3ca7add5b1ab45c1cf4c88c512b9271af2` |
| `state_after.txt` | `97f96fa192cefa10b1c6312fdd46fe86a1758acd639948a69a58999f197bd225` |

Локальные рабочие скрипты и логи сеансов:
`OPENCODE_WORKFLOW_SCRATCH/../p0c-int/` (`build_tar.py`, `run.sh`,
`run_p0c_int.py`, `session3.py`, `summarize.py`, `session.log`, `partial.tgz`).
Секретов в артефактах нет (`.env` не читался и не копировался, только факт
симлинка).
