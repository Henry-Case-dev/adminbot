# REVIEW-W6-BINDING — независимый аудит привязки W6 (кандидат `a5902b15`)

- **Вердикт: Needs Fixes** — 1 overclaim статуса (SOUL-17.4) + 2 мелкие согласованности (AMD.8.3 live_when, счёт в plan.md). Остальная привязка подтверждена.
- **Ревьюер:** REVIEW-W6-BINDING (read-only; этот файл — единственная запись; коммита нет).
- **Кандидат:** `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e`; карты/plan — на HEAD `d2b0fe7d`; карты в дереве == HEAD; W6-файлы дерева == кандидату (`web/app.js 401a40a5…` LF, `web/index.html 8d86cd1a…` LF, `app.css 761274ceaed1`, `speech.py d1fec786ee6b`, тест `5b61a663cf65`, сторож `68243a47f…` LF).
- **Область:** честность учётной привязки статусов/evidence (не повторное ревью UI W6).

## 1. Что проверено исполнением (мои прогоны, не переиспользование)

- Оба гейта повторены: вывод **построчно совпал** с транскриптами plan.md §W6 binding (main: 8 FAIL — только PENDING-строки, `errors=8`; amendment: 1 FAIL — 8.3, `errors=1`; exit 1 оба). Транскрипты достоверны.
- `tests/test_soul1_w6_speech_ui.py` → **22 passed**; `tests/test_webapp_teststand_guard.py` → **5 passed** (проверка «тестовый URL защищён» для 17.5);
  node `glass_probe` / `design_tokens` / `app_methods_dup_keys_guard` / `round1039` → OK на байтах кандидата.
- Байт-инварианты стекла воспроизведены независимо из коммита: polygon blob `c2ad97d446f5e7c7b72fb46d9bb560ae3777d6c3`; `#lg-lens` 6298 б. `5367ec4566fc…`; `--lg-*`/backdrop-filter в app.css — 104 строки `89cda50a6e61…`.
- `evidence/w6/ui-report.json`: failures=[], POST=16, shots=94, 8 viewport; pageOverflow=0/minTap=44/padding=12 везде; витрина 1→2→3→4 и сплит 1↔2 по заявленным брейкпоинтам. Цепочка «Все инструкции» реально исполняется в харнессе на **390 и 1440** (`run_interactions` только эти два viewport) — клайм «мобильный и десктопный» для AMD.6.2 подтверждён.
- Код-claims проверены по `git show` кандидата: `style_policy_view` действительно без `history`; index.html:7613 под `speechStyle.history`; advanced 7597–7606; карточка блока 7978–7986 (история + «Откатить»); `delivery.telegram_send=false, lessons_created=0` (speech.py:2203); фикстура `/reset` 2882→2835 снята настоящим эндпоинтом.
- PENDING-причины проверены в обе стороны: факты верны; ни одна PENDING-строка не является полностью доказанной (10.4/10.6 = W4-контуры; 11.0 — только одна цепочка из двух; 11.1–11.3 — раздел `#/ai/prompts` не проверялся; 16.5.1 — истории стиля нет и advanced поимённо не проверен; 16.5.2 — клавиатура/Save не проверялись).

## 2. Ledger аудита привязки

| Пункт | Статус | Примечание |
|---|---|---|
| Гейты verbatim (обе карты), exit 1 | VERIFIED | совпадение построчное |
| Привязка кандидата: 29 main (16 inv.+13 add.) + 8 amendment (7+1), candidate=SHA, deployed пуст | VERIFIED | в plan.md счёт главной карты неточен (см. R2) |
| VERIFIED-строки: main 19 / amendment 7 | 18+7 VERIFIED, **1 overclaim (17.4)** | клаузы проверены поштучно; sample по остальным ок |
| PENDING: main 8 | VERIFIED (причины фактичны, закрываемых нет) | |
| READY_FOR_LIVE: 10.P5, 11.4, AMD.8.3 | VERIFIED (8.3 — с замечанием R1) | 10.P5/11.4 postdeploy — корректно |
| Evidence shape (candidate_commit/ref/observation/type) | VERIFIED | BAD=0 по всем 37 строкам; наблюдения информативны и выборочно истинны |

## 3. Findings

### B1 — БЛОКИРУЮЩИЙ overclaim: SOUL-17.4 (`requirements-map.json`, `items SOUL-17.4`, status=VERIFIED)

- **Клауза acceptance:** «…**проверены производительность на Android и Windows**, reduced-motion, умеренный overdraw…».
- **Что доказано:** Windows/desktop-Chrome (включая мобильный размер 390: p50/p95 16.7/16.9, паритет с Tier B, 0 longtask), токены, reduced-motion, fallback, overdraw; фолбэк/контраст — measured.
- **Что НЕ доказано:** производительность на реальном Android. review-tiera, item 6: «Реальный mid-range Android GPU — только устройство»; раздел «Что может подтвердить только реальное устройство» #1: GPU-цена 16–17 слоёв `backdrop-filter:url()` на mid-range Android/Telegram WebView «мой и лейновый замер только desktop Chrome»; review-tiera-strengthened §9.1 — то же. Собственное наблюдение привязки это признаёт («реальный Android/Windows GPU-цена объявлена остаточным риском на устройство»), но статус стоит VERIFIED.
- **Минимальная честная коррекция:** status → `PENDING` (live_required/live_when не трогать), reason: «Токены/reduced-motion/overdraw/fallback и перф на Windows/desktop-Chrome (вкл. 390) подтверждены (review-tiera ledger 4–6, review-tiera-strengthened 3/5/6/7). НЕ подтверждена производительность на реальном Android: GPU-цена 16–17 слоёв backdrop-filter:url() на mid-range Android/TMA WebView — “только устройство” (review-tiera item 6 / раздел устройства #1; review-tiera-strengthened §9.1). До замера на реальном устройстве строка открыта.» Evidence оставить (документирует уже проверенную часть) — так строка присоединится к device-группе 10.P5.
- Альтернатива (только по явному решению Orchestrator/владельца, если Android-замер признаётся postdeploy): READY_FOR_LIVE + live_when=postdeploy по образцу 10.P5. Минимально — PENDING+reason.

### R1 — мелкая согласованность: SOUL-AMD.8.3 (`requirements-map-amendment.json`)

- Статус `READY_FOR_LIVE` — честный (это и вердикт ревьюера «за канарейкой, flag ON»; VERIFIED не объявлено; gate-краснота зафиксирована verbatim). **Не понижать.**
- Но поле `live_when` = `preprod` противоречит и собственному reason («живая генерация не проверяема до канарейки»), и plan.md L298 («10.P5/11.4/8.3 закрываются после деплоя/канарейки (postdeploy)»). Мини-правка: `live_when` → `postdeploy` (status/reason без изменений; release всё равно потребует live/production evidence + deployed==candidate). Либо — если Orchestrator сознательно оставляет красный review-сигнал — не менять, но тогда L298 должен не называть 8.3 postdeploy.

### R2 — мелкая неточность: plan.md §W6 binding

- «main 29 (17 inventory + 12 additional)» — фактически **29 = 16 inventory + 13 additional** (items: 10.0–10.6, 11.0, 16.5.0, 17.0–17.6 = 16; additional: EXEC.14, 10.P1–P5, 11.1–11.4, 16.5.1/2, 17.P1 = 13). Одна правка числа; остальное в §W6 binding (цепочка вердиктов, цитаты review-w6, счётчики 19/7/8/2, `deployed_commit` пуст) — подтверждено.

### Non-blocking (фиксирую, не блокирует)

- **SOUL-17.3**, клауза «нет flicker и сброса selection»: прямой пробы нет; закрыто структурно (маркер `round1025_design_tokens_test.js`: «blur/viewport не анимируется», T-2541 — зелёный на кандидате; рефракция статична; textarea/таблицы без blur — ledger 3) + стабильность кадров A1/A2=0. Рекомендация: одна строка в evidence со ссылкой на маркер — можно совместить с правкой B1.
- В 17.0/17.1/17.2/17.3/17.4/17.5/17.6/EXEC.14 основной ref `glass-and-ui-suites.txt` — прогон полосы до fix-pass; те же сьюты перегнаны на финальных байтах (`fix-pass-suites.txt` §FIX-W6-EOL/§FIX-W6-LESSON) и повторены ревьюером (RECHECK-W6-2). Утверждение истинно; можно дополнить ref для чистоты.
- SOUL-17.2 «читаемый fallback на неподдерживаемых WebViews» подтверждён в WebKit-подобном контексте (0 линз, 16×reason, downgraded=16; контраст Tier B измерен); реальная читаемость на iOS — заявленный device-only остаток (strengthened §9.2), не overclaim строки, но не должен трактоваться как закрытый — учитывать вместе с B1 at postdeploy.

## 4. Следующее действие (для Orchestrator)

1. Внести B1 (17.4 → PENDING + reason), R1 (8.3 live_when=postdeploy, либо правку L298), R2 (число в plan.md), при желании — non-blocking заметки; перезапустить оба гейта (ожидаемо: main errors=9 только PENDING; amendment errors=0 при READY_FOR_LIVE-строке).
2. После правки — реторн на recheck этого файла (связка «кандидат a5902b15 + карты d2b0fe7d^…» уже проверена; повторно проверятся только изменённые поля).

*Баунд: этот вердикт относится к кандидату `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e` и картам на `d2b0fe7d`; любое изменение карт/кандидата аннулирует затронутые пункты.*


---

## RECHECK (C=`6fc986eb`, D=`a5e3e586`) — вердикт: **Approved**

- **Кандидат:** `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e`; карты/plan — HEAD `a5e3e586`; дерево == HEAD по всем 3 файлам D и по всем 8 файлам C.

**C — tails (`--name-status` = ровно 8 заявленных файлов; worktree == C == HEAD по каждому):**
- Два NOTE-расширения allowlist (A3-bounds `test_unified_image_request_round1026.py` + `TestBounds` в `test_tool_coordinator_round1026.py`) — диффы читал: по одному hunk на файл, только добавление `web/api/speech.py`; предикат `not any(...)` и структура прочих проверок не ослаблены, записи `glass-teststand.*` из allowlist по-прежнему удалены (возврат страницы в `web/` валит тест), `test_no_ddl_in_touched_sources` и summary-инварианты не тронуты.
- Факты NOTE подтверждены независимо: `web/api/speech.py` — NEW роутер с **21** маршрутом (посчитал декораторы `@speech_router.*`), регистрация — `web/app.py`; `web/api/routes.py` **не менялся** (байты идентичны `c8cf77a5` / `a5902b15` / HEAD / дереву, sha256_12 `989779c65128`) — byte-freeze держится; offender против baseline `e8646af` ровно один — `web/api/speech.py` (мой пересчёт: 24 `web/`-пути в диффе; при удалении speech.py из allowlist остаётся ровно 1 непокрытый — speech.py; с ним 0); все прочие web-пути санкционированы ранее.
- Прогоны (py -3): оба NOTE-файла — **87 passed**; 7-file set — **200 passed / 0 failed** (вкл. `test_disk_retention_deploy_backups.py`). Кросс-проверка `.venv` на двух NOTE-файлах — тоже **87 passed** (интерпретатор-стабильно).
- `services/disk_retention.py`: `prune_deploy_backups(directory, *, keep=2)`, `DEPLOY_BACKUP_PATTERNS=("pre_t*.db",)`, под `_retention_enabled()`, боевых вызовов нет (только тест) — соответствует уже закоммиченному тесту (`c2775a54`) и заявленной семантике; дерево == commit.

**D — правки привязки (3 файла: main map, amendment map, plan.md):**
- Единственные дельты против `d2b0fe7d`: main W6 `SOUL-17.4` `VERIFIED→READY_FOR_LIVE` (+`live_when=postdeploy`, reason заполнен; evidence не тронут — всё на `a5902b15`); amendment `SOUL-AMD.8.3` только `live_when=postdeploy` (статус/evidence сохранены); план — счёт исправлен на «16 inventory + 13 additional» + блок «Corrections (REVIEW-W6-BINDING)» с verbatim-гейтами. Иных W6-дельт статусов нет (проверил diff по обеим картам).
- Гейты (мой повтор, кандидат `a5902b15`): amendment `errors=0` **EXIT=0**; main `errors=8` **EXIT=1** — тот же PENDING-набор (10.4/10.6/11.0/11.1/11.2/11.3/16.5.1/16.5.2); 17.4 больше не в FAIL (принят READY_FOR_LIVE+postdeploy).

**Остаточные заметки (не блокируют):**
- В нарративе §W6 binding остались «состояния до правки» в двух списках («READY_FOR_LIVE (main 2)», «Переведены в VERIFIED (main, 19) … SOUL-17.0–17.6»); Corrections №1 явно помечает первый список как прежний и фиксирует 17.4→READY_FOR_LIVE — противоречие раскрыто, при следующей правке плана стоит снять оба.
- Из исходного ревью (не блокирует): 17.3 «нет flicker/сброса selection» — косвенная опора (маркер T-2541 + статичная рефракция); ref `glass-and-ui-suites.txt` — pre-fix прогон, финальные прогоны на байтах кандидата в `fix-pass-suites.txt`.

**Вердикт RECHECK: Approved** в границах кандидата `a5902b15` и карт на `a5e3e586`. Предыдущий Needs Fixes закрыт: B1 (17.4) снят через READY_FOR_LIVE/postdeploy, R1 (8.3 live_when) и R2 (счёт) исправлены; overclaim'ов в исправленном состоянии не осталось.
