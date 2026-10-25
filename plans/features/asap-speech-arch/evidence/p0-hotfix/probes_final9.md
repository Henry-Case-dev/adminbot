# P0 — LIVE-META-CLASS на кандидате `e2d9b335`

- **LANE_ID:** `LIVE-META-CLASS` (DevOps, read-only live). Telegram не трогали, деплоя нет.
- **Время:** 2026-10-25 09:36:22–09:44:29 UTC (локально 21:36–21:44, UTC+12). **Один SSH-логин**, 490.7 с.
- **Кандидат:** `task/speech-p0-hotfix` @ **`e2d9b3357c29838bb89943f5df1f53587da2e639`**; прод-база `534ac7dda6713fb407e0789fdddfa563251cdab4` (2.58.130).
- **Прод до/после:** HEAD `534ac7dd`, dirty 13, `local_database.db` stat `1792920724 / 1625059328` → `1792921175 / 1625088000` (пишет живой бот; проба read-only: PG `transaction_read_only=on`, SQLite `mode=ro`). **Деплоя нет**, rollback не требуется.
- **Стенд:** `/tmp/p0-final9/new`, `git archive` ровно `e2d9b335` (529 записей / 509 файлов, 24 MB, sha256 **`a396167f…`**), `.env` и `local_database.db` — симлинки на прод, маркер `PROBE_COMMIT`.
- **Интерпретатор:** `/var/www/admin_bot/venv/bin/python` 3.12.3.
- **Привязка:** 8/8 модулей по sha256 (единственный изменённый — `direct_chat_service 738a3a49…`), harness **`d31a2875…`**, `harness_extra 227498af…`, `harness_effective 5c9fc4c5…` — серверные sha совпали с локальными.
- **Self-check:** **PASS**, EXIT 0, 26 флагов `true` (`core_full_not_truncated`, `code_l1_canon_*`, meta/quote guard, deterministic L1).
- **Режим:** read-only PG + SQLite `mode=ro`; Telegram/запись/usage не задействованы; ключи не выгружались.

## Дефект вспомогательного анализа (не продукта)

Первый локальный экземпляр `analysis_final9.py` был перекодирован при правке (PowerShell ANSI) и потерял кириллические литералы, поэтому его серверный прогон дал ложные `meta 0/16` и `RAG-маркеры 0`. Файл восстановлен из байт-в-байт копии final8, патчена только строка docstring; **анализ пересчитан локально на том же коммите** (привязка 8/8 модулей + harness). Итоговые `analysis.json/out` — исправленный прогон. Сырые JSON, `guard_check` и `meta_gap` не затронуты.

## Вердикт: FAILED — цель meta 0/16 не достигнута

| Проверка | Факт | Итог |
|---|---|---|
| L1 A/B research, raw-план | **1/2**: A `answer` conf 0.95, B `research` conf 0.90 | наблюдение |
| L1 A/B research, effective (путь сервиса) | **2/2** (оба `research`; fallback в этом прогоне не сработал — второй вызов уже дал research) | PASS |
| Forced A/B | **2/2** | PASS |
| Meta strict / с обращением | **1/16 / 1/16** | **FAIL (цель 0/16)** |
| Цитаты | raw 35 → final 21, **0 non-exact** | PASS |
| Core | **3294**, sha12 **`ead77b2ab509`**, offset 3083, **8/8** | PASS |
| RAG | rows 40 / kept 40, render real, block 2027; маркеры E: 17 `(не подтверждено)`, 12 `[чат]`, 0 `[Бот]`, 0 `(предположение)` | PASS |
| FREQ | `frequent_text=true`, occasional/off=false; global и chat `profanity=frequent` rev2 | PASS |
| Alias | uid `42115912` → **«Макс»** (chat+global); display «Гипербореец» | PASS |
| L1 canon | code **9588** `cc020660ae03`, PG 8261 `6c2ddc17c998`, `pg_matches_code=false` | ожидаемая преддеплойная ступень |
| E | `reply/research`, `detailed/report`, conf 0.85, 1980/2716, analysis 1×1, не silent | PASS |
| C/D/F | `answer` 301/239, `emotional_reply` 270/249, `explanation` 330/115, compact | PASS |
| Прочее | malformed 0, invalid `[]`, `stage_errors={}`, `extent_scrub_removed=0`, identity 5048 | — |

### Остаточная мета (блокер)

- **new_E repeat 2:** первое предложение после guard — **«Ну ок, смотри.»** (`announce_removed=false`, `filler_removed=false`); strict-счётчик видит его (`ну`), с обращением — тоже.
- **new_E repeat 1:** filler снял «Окей,», осталось **«Смотри.»** — та же класс-преамбула, но strict-счётчик её не ловит (нет в списке префиксов). Итого по классу — **2/16**, по strict — **1/16**.
- Офлайн-guard на точных прежних live-формах — **17/17 PASS**: final6 E1/E2, final7 E1/E2, final8 E2 (`Ну ок, давай разложу…`) снимаются ровно одним предложением, тело байт-в-байт; негативы («Макс, ты не злобный.», «Ну давай в субботу.», «Ладно, смотри: …», «Разберу твой вопрос: …», «Давай разложу факты: …») не режутся. Т.е. класс с мета-глаголом закрыт, но live-форма без глагола — нет.

### 9 проверок

1. Прямой ответ без метавступления — **FAIL** (strict 1/16, по классу 2/16; «Ну ок, смотри.» / «Смотри.»).
2. Нет навязанной структуры/нумерации — PASS: нумерация только в E (явная просьба перечислить темы; bold-заголовки 3/0, ярлыки 4/6), в остальных 7 прогонах 0.
3. Нет выдуманных дат — PASS (0 годов/месяцев/дат).
4. Нет неподтверждённых цитат — PASS (21/21 production-exact, 0 non-exact).
5. Нет выдачи интерпретации за историю / self-echo — PASS (0 «я уже говорил», 0 `[Бот]`, 17 `(не подтверждено)`).
6. FREQ настоящий, без few-shot — PASS (`frequent`, rev2, global+chat).
7. Явный разбор подробно — PASS (E 1980/2716, `detailed/report`, analysis 1×1).
8. Обычный вопрос коротко — PASS (C/D/F 301/239, 270/249, 330/115).
9. Core и индивидуальность — PASS (3294 / `ead77b2ab509`, offset 3083, 8/8).

## Находки и следующий шаг

- **F1 OPEN (блокер, Builder):** live-форма **«Ну ок, смотри.»** (и «Смотри.» после filler) — тот же класс ведущих анонсов, но без мета-глагола 1-го лица. Конкретный новый вариант: добавить в `_L2_META_ANNOUNCE_RE` ветку с концевым якорем
  `(?:частицы…)*(?:смотри(?:-ка)?|глянь(?:-ка)?)(?=[.!?…]*$)` —
  режется только голая преамбула; содержательные «Смотри, как он это сделал.» / «Смотри: факты.» не трогаются существующими gate'ами (нет `:`/тире/кавычек, ≤90 символов, остаток ≥20 букв). Тесты: позитивы «Ну ок, смотри.», «Окей, смотри.», «Ладно, смотри-ка.»; негативы с содержательным продолжением. После фикса — тот же harness (`--self-check`, `--use-code-l1-canon --repeats 2`) и strict meta 0/16.
- **F2 observation (L1):** raw-план A нестабилен (`answer` conf 0.95), production-effective 2/2 за счёт fallback-контракта; в этом прогоне fallback не понадобился (второй вызов уже `research`). Live-доказательство ветки fallback — final7; код не менялся. Reviewer: наблюдение, не блокер.
- **F3:** RAG-блок в этом прогоне другой по содержимому (sha per-case, 2027 симв.) — живой чат продолжил писаться между сеансами; маркеры реальные, `[Бот]` 0.
- **F4:** `pins.git=ERR` ожидаемо (git archive без `.git`); `mca_experience.list_lessons` traceback — известный шум стенда, `stage_errors={}`.

## Итог

- **FAILED.** Закрыты: L1 effective A/B 2/2, forced 2/2, quotes, Core, RAG, FREQ, alias, E, C/D/F, даты, структура, self-echo. **Не закрыто:** meta 0/16 (strict 1/16, по классу 2/16).
- **Deploy не выполнять.** Прод остаётся **2.58.130 @ `534ac7dd`**; изменений на проде нет, rollback не требуется.
- **Дальше:** Builder — F1 (+тесты), затем тот же harness на следующем кандидате; Reviewer — держать строку meta FAILED до 0/16.

## Raw

`probes_final9/`: 10 raw JSON + `.out/.err`; `analysis.json/out` (исправленный локальный пересчёт на том же коммите), `guard_check.json`, `meta_gap_check.json/out`, `selfcheck_new.txt`, `session.json`, `manifest.json`; скрипты `run_final9.py`, `analysis_final9.py`, `guard_check_final9.py`, `meta_gap_check_final9.py`, `harness_extra.py`, `harness_effective.py`, `build_tar_final9.py`.

- Архив `a396167f0a44db94c86124be623810989c46adfef40bd64ba207c417304210c4`; harness `d31a28759f479304301c8e8eeea3db653d170a8e9d6acdf96fd9b466fee308cc`.
- Секреты не выгружались; alias — только uid `42115912` и «Макс».
