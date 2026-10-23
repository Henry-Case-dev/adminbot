# CFG-FINAL — независимый ревью-вердикт F2 (LEAF_CFG-FINAL-F2, read-only)

Дата: 21.10.2026 (UTC+12). Ревьюер: независимый (Review). Кандидат: **ceb3e437**
(HEAD; diff vs 1c2fe2fa — только plans/). Прод: **2.58.104 @ 8ea6ed4e**
(deploy VERIFIED). Map-candidate конвенции: d860a529 (ancestor of deployed,
merge-base проверен). Вердикт: **Approved** (слайс CFG-FINAL).

## 1. Таблица проверок (по брифу — фактически, не по описанию)

| # | Проверка | Метод | Результат |
|---|---|---|---|
| 1 | Композит не частичный (CFG-04.B) | Сводная таблица ADD-2.6/2.7 (bindings §2) сверена построчно с существованием базового evidence: cfg-06 w2..w7 + canary 20.10, cfg-07a (07d5-summary, 07a2-bytecheck, 07cg-dictionary), cfg-07b-reused/add-exp unified-core, cfg-03 inventory 582, cfg-01/02a README, release-25897 — все пути существуют; маршруты фактчека (planner/suitability/wide_context/verdict/temporal/attribution + один голос/guards/delivery) покрыты строками | OK — композит без частичных зелёных; G3-команда плана: **G3: OPEN** (воспроизведено) |
| 2 | Канарейки реальны | run-g1/g4: реальные латентности (LLM 9–15 с), живой Tavily-каскад с «грязной» выдачей, EvidenceMap→hrefs 1:1, mca_events-логи, wall 34.8/30.6 с; g1 13/13 true, g4 14/15 (publication_date_extracted=false — честная деградация 06E.7); e4 4/4 бесплатно; guard_observations.count=0 в обоих платных прогонах; FakeBot (canary_final.py L75/L295+, нулевые сетевые отправки), chat_id -100999000701 синтетический; CODE/TEST/LIVE разделены (README + отчёт §3); 2 платных прогона (4 LLM-вызова) в бюджете ≤2–3; флаг v2 hot=true — SSH-факт (probe-f1-summary.json state_pre/post) | OK — 0 сообщений в реальные чаты |
| 3 | 07D.6 корпус ДО/ПОСЛЕ | 07d6-corpus-probe.json: before=29cc49ba (2.58.98), after=8ea6ed4e + guard sha bfcfa213eb59; 7/7 core-классов BEFORE_reproduced=true → AFTER_neutralized=true (MB-01: «по моим логам» вырезан, остальной текст сохранён); доп. слой 4/4; FA-17 renderer-экранирование; route-байт-пруф: 7142ffcf без guard → 8ea6ed4e guard импортирован + 9 outbound-вызовов + metatext-retry; canon 39 проверок, unexplained=**0**; privacy: masked digest only (06F.1), длинных приватных фрагментов в JSON нет (скан >300 симв. — 0) | PASS |
| 4 | СЕКРЕТ-СКАН (обязательный) | git grep по 10 паттернам (sk-, Bearer, api_key=, token=, ghp_, gho_, xox*, AKIA, eyJ, AIza, tvly-) по evidence/cfg-final/** и cfg-final-report.md @ceb3e437 → 0 вхождений; расширенный скан всего коммита → только дамми-токены старых тестов и ложные срабатывания «ta**sk-**supervisor»; run-f1-scrubbed.log: api_key/token/sk-/Bearer — 0, hex-строки — только публичный HEAD-sha; скрипты без хардкода кредов (env only); инцидент «ключ в консоли»: keys.image_api_key в артефакты не попал (в hot-дампе запрос отфильтрован) | **0 утечек** |
| 5 | Гейты | plan: **EXIT 0** (inventory=246 manual=42 errors=0); review --slice CFG-FINAL --candidate **d860a529(full)**: **EXIT 0** (scoped=17 errors=0) — воспроизведено; с ceb3e437/коротким sha → FAIL «candidate mismatch» — структурно (см. §2); release --candidate d860a529 --deployed 8ea6ed4e: EXIT 1, errors=408 — интерпретация в §2; доп.: review CFG-07C EXIT 0 (scoped=12) — клейм Builder воспроизведён; git diff 8ea6ed4e..ceb3e437: **non-plans файлов нет** (250 файлов — только plans/) | см. §2 |
| 6 | Карта: 17/17 + alias + 07D.6 | CFG-FINAL: 15 items + ADD-0.Q + ADD-2.Q = **17, все VERIFIED**; выборочно 6 строк с sha-верификацией артефактов: CFG-06F.6 (static @5af56d8 + production run-g1 @d860a52 — SHA-OK), CFG-06J.6, CFG-06.B, ADD-2.6, ADD-2.7, CFG-07D.6 — artifact_sha256 совпадают; единственный SHA-MISMATCH (CFG-06J.6 static w7-dispute-metrics.json) — записанный sha == файл **на закоммиченном кандидате 5af56d8** (файл дополнялся позже): биндинг легитимен; 07D.5 alias live: CFG-07.B evidence 07d5-summary @d860a52 — присутствует | OK |
| 7 | Целостность evidence | SHA256SUMS.txt: 15/15 файлов совпадают | OK |

## 2. Release-вердикт: PASS (инженерно) + структурный residual гейта (не блокер живого релиза)

- **Байт-равенство:** runtime-дерево HEAD ceb3e437 == deployed 8ea6ed4e
  (probe-delta.json: non-plans delta=[], 12 файлов sha 1:1; независимо
  воспроизведено: diff 8ea6ed4e..ceb3e437 — только plans/). Деплой жив
  (healthz 2.58.104, bytes identity, 0 ERR/CRIT с T0), откат lossless.
- **Структурный residual:** `--stage release` требует
  candidate==deployed==map.candidate_commit, а карта по принятой конвенции
  dd6acf83 держит candidate=d860a529 (пер-волновые биндинги evidence @5af56d8b/
  0282fe4/83ecd20/…; перебиндинг запрещён review-tailbind, тот residual уже
  классифицирован там как структурный, не фактический). Значит EXIT 0
  release-гейта при этой карте недостижим ни с каким кандидатом. Субстанция,
  которую защищает гейт (деплоятся проверенные байты; deployed_commit записан;
  evidence реальные), независимо подтверждена. Требуется штатное решение
  Orchestrator/DevOps по конвенции мульти-волновых карт (или точечная докрутка
  гейта) — вне скоупа F2.
- **Честные хвосты (не блокеры релиза):** 4 mandatory postdeploy-канарейки
  CFG-02A.3/4/5 + CFG-02.AC1 (разрешение/отказ **реальной** генерации в реальных
  чатах — агентам запрещено) остаются READY_FOR_LIVE; инженерные половины
  зелёные (контракты-тесты + прод-пробы ADD-2.1/2.2). 3 owner_optional
  (CFG-04D.4, CFG-06G.8, CFG-07D.1.OBS) — с валидными engineering_req_ids.
  Наблюдение телеметрии продолжается.

## 3. Incidental (не блокеры)

1. План ADD-2.5 ожидал «6298 байт» — это сырой блок в index.html; замер F1
   6251 — DOM outerHTML и **равен** базе cfg-05 (glass-invariant.json
   `outer_html_len_both: 6251`). Разные слои замера, противоречия нет.
2. probe-dispute-w7.txt без штампа времени/коммита — компенсируется
   probe-delta.json (05:57Z) и regression-focused.txt (05:58:29Z, то же дерево).
3. Backlog F2 type-mismatch ×2, narrator-канон, 5 dead-handle — задокументированы
   в отчёте §4, вне скоупа.

## 4. Итог

**Approved** — слайс CFG-FINAL (композит + канарейки + 07D.6 + отчёт + карта).
Release инженерно PASS на 8ea6ed4e; финальное закрытие эпика — после штатного
решения по release-конвенции гейта и леджер-шага RFL-строк (план §3).
