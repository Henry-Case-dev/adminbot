# P0 — LIVE-FINAL11 на кандидате `bd6d5fff` (read-only, без деплоя)

**Итог: PASS по девяти проверкам §5 и по мете (strict 0/16, реально снятая преамбула 1/16,
lexical_prefix_only 0/16).** Одно ожидание полосы не воспроизвелось: RAG-строка «40/39» —
фактически `40 → 4` (A/B) и `40 → 0` (C/D/E/F); код RAG кандидатом не менялся, набор
`graph_facts` живой и ротируется. Деплоя не было, прод не изменялся.

- **Кандидат:** `bd6d5fff54d664bf5cc66e647448c3950d778fc4` (`task/speech-p0-hotfix`),
  git-родитель `219d719e` (docs-only), продуктовый родитель `9828a8ad`.
- **База:** прод `534ac7dda6713fb407e0789fdddfa563251cdab4` (2.58.130), `/var/www/admin_bot`.
- **Стенд:** `/tmp/p0-final11/new`, локальный `git archive bd6d5fff` (529 записей, 514 файлов),
  `.env` и `local_database.db` — симлинки на прод; `PROBE_COMMIT` в корне; PG read-only
  (`transaction_read_only=on`), SQLite `mode=ro`; usage/events заглушены; ключи не печатались.
- **Один SSH-логин**, 462.5 с, 12:39:48–12:47:03 UTC (25.10). Неудачных auth/ретраев/поллеров нет;
  все SFTP/exec-каналы — в одном `paramiko`-соединении; `/tmp/p0-final11*` после сеанса: 0.
- **Self-check:** **PASS**, 22/22 флага `true` (`l2_meta_metric_split=true`;
  `invariant_0x0=false` — ожидаемо для research 1×1).
- **Привязка:** 14/14 sha256 на сервере совпали с локальными (8 пинутых модулей + harness
  `180f55f3…` + 2 обёртки + анализатор + 2 guard-скрипта); `stage_tgz_sha256=c3392a76…`.
  Пин `direct_chat_service.py` — `079284811debd0032406fac07c2c732e3e0ca138811ecf4105c8ebca966bb95b`.

## 1. Соединения (fail2ban-дисциплина)

| # | Время (UTC) | Что | Итог |
|---|---|---|---|
| 1 | 12:39:48–12:47:03 | один логин (ConnectTimeout 20, без agent/keys) → precheck → SFTP tgz+скрипты → sha/syntax → один серверный скрипт (self-check, 10 прогонов, анализ, guard) → SFTP результата → cleanup | **успех**, 10/10 `rc=0` |

Стенд: 10 прогонов × 2 повтора; L2 — `deepseek-v4-flash` @ `nano-gpt.com`, `max_tokens=2400`,
`temperature=0.7`; `new_E` — `deep_research` (L1 сам), остальные — по плану L1 / forced.

## 2. L1 (PASS)

| Прогон | `response_act` | `extent` | `structure` | попыток | `invalid` |
|---|---|---|---|---|---|
| raw A / raw B | research / research | normal / compact | answer / answer | 1 / 1 | — |
| eff A / eff B | research / research | compact / normal | answer / answer | 1 / 1 | — |
| forced A / forced B | research / research | normal / normal | answer / answer | forced | — |
| C / D / E / F | banter / emotional_reply / research / clarification | compact / compact / **detailed** / compact | chat / chat / **report** / chat | 1 / 1 / 1 / 1 | — |

Итог: raw **2/2**, effective **2/2**, forced **2/2**. `malformed=0`, `invalid=[]`, `fatal` нет,
`stage_errors={}`; `l1_attempts=1` у всех не-forced, повторов не было. `canon_source=code`,
код-канон **9588 / `cc020660ae03`**; PG-канон прода **8261 / `6c2ddc17c998`**,
`pg_matches_code=false` — преддеплойная ступень, миграция PG не входила в полосу.

## 3. Core, payload, закрывающий блок

| Прогон | Core | offset | analysis dir/writer | no_meta | quote | mode |
|---|---|---|---|---|---|---|
| eff_A, eff_B, new_E, forced_A, forced_B | **3294 / `ead77b2ab509`** | 3083 | 1 / 1 | 1 | 1 | serious / deep_research |
| new_C, new_D, new_F | то же | 3083 | 0 / 0 | 1 | 0 | casual |

- Core физически в system, ровно один блок, 8/8 прогонов; слои: `channel_contract` 3081,
  `core` 3294, `identity` 5048, `expression` 1069.
- `NO_META_STRUCTURE_TEXT` — 1× во всех 8; `QUOTE_FIDELITY_TEXT` — 1× в research-прогонах
  (deep_research/analysis block) и 0 в casual — по конструкции режимного блока, не пропажа.
- Закрывающий блок в user-части 1×, после `</Current_Question>`, последним; в system 0
  (`self-check`: `closing_once_per_payload`, `closing_last_after_current_question`,
  `closing_only_in_user_part`).

## 4. Мета: три метрики (16 ответов primary-набора)

Считалось после продуктового `strip_l2_meta_lead` и снятия неподтверждённых цитат.
**Strict — тот же регекс final9 (`ну|ладно|ок|…|разложу|разберу|…`), не ослаблен.**
Harness-метрика `meta_metric` из кандидата дала те же числа.

| Метрика | Значение |
|---|---|
| strict (final) | **0/16** |
| strict (raw, до guard) | 1/16 — `new_E#2`: «Давай разложу.» |
| product_announce (guard реально снял) | **1/16** — `new_E#2`, `announce_removed_count=1` |
| lexical_prefix_only | **0/16** |
| union (strict или announce) | 1/16 |

Оставшихся strict-строк **нет** — список пуст. E отдельно:

- `new_E#1`: raw и final первое предложение — «Ринтаро льёт ссылки на эджмоникс и русский
  свежачок как заведённый, каждый его второй пост — ютуб-ссылка с комментарием в духе вот
  пиздато стелит.» — преамбулы нет, guard не сработал.
- `new_E#2`: raw «Давай разложу.» → снято продуктовым guard (1 предложение), final первое —
  «**Ринтаро** — главный двигатель чата.»; тело после снятия не тронуто.

Анализатор: staged `analysis_final11.py` (`4fb65a72…`) считал strict split-регексом harness;
после сеанса он заменён на версию с точным final9 strict-регексом (`d599e46c…`), анализ
пересчитан на тех же скачанных raw. Harness `meta_metric` в raw дал те же **0 / 1 / 0**;
`manifest.json` фиксирует sha анализатора.

Преамбула `final10 E#1` («Ну давай, раз уж просят. Накидаю по свежим следам…») в этом live-сэмпле
не сгенерировалась. Её снятие доказано офлайн на том же дереве: `guard_check_final11.json` —
**20/20**, в т.ч. точная пара снимается **двумя** анонсами, тело байт-в-байт; содержательные
«Ну Макс, ты сам напросился.», «Накидаю тебе ссылку в субботу.», «Соберу вещи и поеду.» не режутся.
Старый набор `guard_check_final10.json` — 25/25.

## 5. Цитаты, нумерация, длины

- Цитаты: raw **32** → после guard **20**, **0 non-exact**; неподтверждённых нет, список пуст.
  Примеры оставленных точных: «старьё», «кринж» (E#2) — есть в переданных данных.
- Нумерация — **только E**, где пользователь прямо просил «с примерами»: E#1 — 4 пункта,
  E#2 — 10 (5 нумерованных + 5 буллетов); bold-ярлыки — только E#2 (7). В остальных 14 ответах
  нумерация/ярлыки — **0**.
- Длины: B — **327 / 883**; E — **1705 / 2653**; C — 411 / 247; D — 120 / 121; F — 267 / 283.

## 6. RAG, FREQ, alias, даты

- **RAG:** `rows=40` во всех 8; `after_self_filter/kept`: A/B — **4**, C/D/E/F — **0**;
  блок A/B — 475 симв. (`07e30e8155ae`), у остальных — пусто (`e3b0c44298fc`).
  Маркеры: 4 `(не подтверждено)` (A/B), 0 `[Бот]`, 0 `[чат]`, 0 `(предположение)`.
  Self-rank: 4 не-self строки (voice_transcript) получили rank<3 и помечены
  «(не подтверждено)»; в A/B 36/40, в C–F 40/40 строк — self-origin и отфильтрованы.
  **Ожидаемая строка «40/39» не воспроизведена**; фактически 40→4 и 40→0. Код RAG кандидатом не
  менялся (`direct_chat_service` изменён только в meta-guard); вероятная причина — ротация
  новейших 40 строк живого `graph_facts` (за сеанс БД выросла на ~311 КБ). Это наблюдение для
  Reviewer, не вывод о регрессии.
- **FREQ:** `frequent_text=true` 8/8; `occasional/off=false`; живой конфиг global и chat —
  `profanity=frequent`, `revision=2` (global updated 2026-10-22, chat 2026-10-20).
- **Alias:** uid `42115912` → **«Макс»** (chat и global), display «Гипербореец»; в D#2 живой
  ответ обращается «Да, Макс, надоел.».
- **Даты/выдуманные факты:** дат/годов/месяцев/дней недели — **0**. Конкретных вымышленных
  чисел/имён не найдено. Наблюдение: F#2 начинает «Да не было там никакого конфликта.» без
  RAG-источника (RAG у F пуст) и затем пересказывает обычные роли — это утверждение о прошлом,
  а не подтверждённый факт; Reviewer может счесть это содержательным замечанием.

## 7. Девять проверок §5 (дословно)

| # | Проверка | Факт | Итог |
|---|---|---|---|
| 1 | Прямой ответ без метавступления | strict **0/16**; единственная raw-преамбула `new_E#2` «Давай разложу.» снята guard; `new_E#1` сразу с «Ринтаро льёт ссылки…» | **PASS** |
| 2 | Нет навязанной структуры/нумерации | нумерация только E (4 и 10; просьба «С примерами»); в остальных 14 — 0; bold-ярлыки только E#2 (7) | **PASS** |
| 3 | Нет выдуманных дат | 0 дат во всех 16; F#1 «Да хуй его знает, я там не следил.» — без даты | **PASS** |
| 4 | Нет неподтверждённых цитат | raw 32 → final 20, **0 non-exact**; «старьё», «кринж» подтверждены переданными данными | **PASS** |
| 5 | Интерпретация не выдана за историю / self-echo | «я уже говорил» — 0; `[Бот]` — 0; 4 маркера «(не подтверждено)» (voice-факты) | **PASS** |
| 6 | FREQ настоящий, без few-shot | `frequent_text=true` 8/8; global/chat `profanity=frequent`, rev2 | **PASS** |
| 7 | Явный разбор подробно | E: `research/detailed/report`, `deep_research`, 1705/2653, analysis 1×1 | **PASS** |
| 8 | Обычный вопрос коротко | C 411/247, D 120/121, F 267/283; все `compact`, режимы casual | **PASS** |
| 9 | Core и индивидуальность | **3294**, `ead77b2ab509`, offset **3083**, 8/8, в system | **PASS** |

## 8. Безопасность (прод только читался)

| Параметр | До (12:39 UTC) | После (12:47 UTC) |
|---|---|---|
| git HEAD / dirty | `534ac7dd` / 13 | `534ac7dd` / **13** |
| `local_database.db` | 1 626 546 176 B, mtime 1792931904 | 1 626 857 472 B, mtime 1792932312 (пишет живой бот) |
| `…db-wal` / `…db-shm` | 4 223 032 / 32 768 | 4 457 872 / 32 768 |
| unit `admin_bot` | active, NRestarts=0, ActiveEnter 2026-10-24 21:03:19 UTC | то же |
| health loopback | 000 https / 308 http | те же |
| harness-процессы | 0 | 0 |

Записей в `/var/www/admin_bot`, рестартов, checkout, Telegram-вызовов и чтения ключей не было;
PG-сессия и SQLite — read-only по конструкции стенда. `pgrep -fc` в precheck один раз показал `1`
из-за собственной оболочки с текстом шаблона; в `prod_before/after.txt` — `stray=0`, все 10
прогонов завершились сами (`rc=0`), `/tmp` вычищен.

## 9. Что дальше (без деплоя)

1. **Reviewer/Orchestrator:** принять решение по RAG-ожиданию «40/39»: живой `graph_facts`
   ротируется, поэтому стенд даёт 40→4/0; если нужен стабильный RAG-критерий, его надо
   фиксировать на снимке БД, а не на живом наборе.
2. **Reviewer:** оценить F#2 («не было конфликта» без RAG-источника) как содержательное
   замечание, не как технический дефект кандидата.
3. Деплой `bd6d5fff` не начинать в этой полосе: решение о релизе — за Reviewer/Orchestrator;
   прод остаётся **2.58.130 @ `534ac7dd`**, rollback не требуется.

**Сырые данные:** `probes_final11/` — 10 raw JSON, `analysis.json/out`, `manifest.json`,
`guard_check_final10.json` (25/25), `guard_check_final11.json` (20/20), `selfcheck_new.txt`
(PASS), `stage_sha.txt`, `prod_before/after.txt`, `session.json`, `raw/exits.txt`.
Локальные скрипты сеанса — `OPENCODE_WORKFLOW_SCRATCH/p0-final11/`.
`@Orchestrator`
