# CFG-FINAL — bindings.md (финализация §1, волна F1)

Лейн: CFG-FINAL-F1 (Builder-композит, единственный писатель). Дата: 21.10.2026.
База: прод **2.58.104 @ `8ea6ed4e`** (deploy VERIFIED), master `a9917abb`
(доки; runtime-дельта к деплою пуста), map-candidate `d860a529` (конвенция
dd6acf83; ancestor of deployed — проверено merge-base). План-гейт: EXIT 0
(inventory=246 manual=42 errors=0, повторено 21.10). Артефакты волны — в этой
папке; sha256 — `SHA256SUMS.txt`. Барьер G3 на старте: BLOCKED
(CFG-06F.6/06J.6/06.B + CFG-07D.6) — **все четыре закрыты этой волной** (см. §4).

## 1. Байт-привязка волны

| Факт | Доказательство |
|---|---|
| Runtime-дерево == deployed `8ea6ed4e` | `probe-delta.json`: `runtime_delta_8ea6ed4e_to_HEAD_nonplans=[]`; 12 файлов — sha-совпадение |
| `a9917abb` содержит деплой | `git merge-base --is-ancestor 8ea6ed4e a9917abb` → 0; diff 17 файлов — только plans/ |
| Канарейка-база `7142ffcf` ⊂ деплой | merge-base → true; дельта фактчек-семьи = 3 файла (orchestrator +153/−12 = CFG-07C-G guard; service +23/−2 = 07D.5; settings = bump) → **точечный ре-проб выполнен**, не ребиндинг |
| SHA снапшота ADD-0.3 (пересчёт) | sha256(`plans/features/cfg/source-cfg-addendum.md`)@deployed = `2ed43009…6B10` == map source_sha256; 398 строк |

## 2. COMPOSITE: сводка регрессии по VERIFIED-evidence (без перезапуска волн)

### ADD-2.6 (CFG-06 — единый фактчек): req → evidence → статус
| Компонент | Существующий VERIFIED-evidence | Статус |
|---|---|---|
| suitability/planner (мало ложных отказов, осмысленные запросы) | `evidence/cfg-06/w2..w7` (W0-audit…W7-acceptance, 89 VERIFIED строк; review-cfg-06 Approved; recheck R1/R2) | VERIFIED |
| широкий контекст (wide_context/dispute) | `w7-dispute-metrics.json` (260 сообщений, attribution_ok) + `tests/test_factcheck_context_cfg06.py` | VERIFIED |
| реальные tools / EvidenceMap | canary 20.10 `evidence/cfg-06/canary/` (06G.1/06G.4 PASS @7142ffcf) + ре-проб F1 (`canary/run-g1.json`: Tavily ok, EvidenceMap→hrefs) | VERIFIED |
| temporal | MCA-20-контур + `temporal_intent_present` в re-пробе | VERIFIED |
| attribution | `w7-dispute-metrics.json` + S6 re-run (`probe-dispute-w7.txt`: 8 passed) | VERIFIED |
| Telegram-output без JSON/unknown + egress | W5/W6 + egress-инварианты; re-проб g1/g4 `no_service_markers`/`no_admin_tokens` = true | VERIFIED |
| legacy/fallback — те же правила | W7 S7 (fallback честный) — re-run зелёный | VERIFIED |
| **Дельта-биндинг канарейки к 8ea6ed4e** | `canary/README.md` + `run-g1/g4/e4.json` (ре-проб на deployed-байтах; guard-швы: 0 событий на чистых текстах) | **закрыто F1** |

### ADD-2.7 (CFG-07 — один голос Core): req → evidence → статус
| Компонент | Существующий VERIFIED-evidence | Статус |
|---|---|---|
| один голос Core (персона-реплика → Verbalizer/Writer) | `evidence/cfg-07b-reused/**` (UNIFIED-CORE absorption G0) + `add-exp/evidence/unified-core/` (16 трасс, route-coverage 18) | VERIFIED |
| мат-переключатель factory ON + chat overrides | `design-add-exp.md` + `test_add_exp_expression.py` (36) | VERIFIED |
| нет backstage в публичных маршрутах | `test_cfg07_backstage_contract.py` (CONTRACT; зелёный в F1-регрессе) + `07a2-bytecheck.txt` (25/25) | VERIFIED |
| защита цитат/фактов (guard не меняет факты) | `07d5-summary.md` (202 POSITIVE → 0 ложных) + `test_cfg07_guard_07d5.py` 41 CONTRACT | VERIFIED |
| delivery проверена | release-102/103/104 (postdeploy wiring) + F1 e4 re-run на 104 (4/4) + guard-швы 9 вызовов (`07d6-corpus-probe.json` route proof) | VERIFIED |
| **Биндинг 07B (12 строк) и 07C (11 строк)** | `evidence/cfg-07/bind-tail.md` @fff68d76 (review-tailbind Approved) | VERIFIED (леджер) |

### Прецедент CFG-04.B соблюдён
Композитные строки ADD-2.6/2.7 не закрыты частичными зелёными: барьер G3
(§3 плана) был BLOCKED ровно 4 строками; канарейки 06-F-хвоста и корпус
07D.6 исполнены в этой же волне ДО биндинга композитных строк (§4).

## 3. PROBE-пакет на проде (2.58.104 @ 8ea6ed4e)

| Проба | Артефакт | Результат |
|---|---|---|
| ADD-2.1 (CFG-01): effective + hot-apply + остаток | `ssh/probe-f1-summary.json` + `ssh/run-f1-scrubbed.log` + `ssh/probe_f1.py` | **PASS**: флаг v2 hot=true; burst 10→2 (API 200, bot_settings=2, PG fresh-read) → allow×2 → третий **отказан** (wait 299.99s, remaining 300.0 из слота) → restore 10 (PG=10, fresh admission); NRestarts=0 (PID 29475 до/после); синтетический слот удалён |
| ADD-2.2 (CFG-02): секция лимитов + OFF default | `probe-prod-104.json` §add22 | **PASS**: «Лимиты генерации» в отданных байтах (5 хитов app.js@deployed-sha db8457cafa9b == прод-отдача), изоляция «Пользовательские изображения»/обложек видна; factory `IMAGE_FREQ_LIMIT_ENABLED=False`; на проде hot `limits.image_freq_limit_enabled="False"` (SSH state) |
| ADD-2.2 платные генерации | — | **не выполнялись (0 из ≤2–3)**: генерация на проде требует доставки в реальный чат — запрещено; квота/гейт до провайдера покрыты тестами на deployed-байтах (`regression-focused.txt`: cfg02b/c зелёные) + VERIFIED-приёмка волны 02x. Честный остаток, не PASS-подмена |
| ADD-2.4 (CFG-04): re-run харнесов 25897 | `probe-prod-104.json` (deployed_probe: healthz/байты/маркеры; served markers 1-в-1 с rel97: PAGE_VER=15, STICKY=12, SAVE_IND=1, TECH_KEY=21, KB_OFFSET=14, SAFE_AREA=17; SUBST=2 строки) + `dirty-guard-104.json` (native confirm, PASS) | **PASS** |
| ADD-2.5 (CFG-05): glass-инвариант | `probe-prod-104.json` §add25 + `lens-dom-104.json` | **PASS**: git blob `web/static/polygon-background.js` = `c2ad97d4…` (== план), отдача == git (157874dfab7b), не менялся с 99f5672c; живой DOM: `#lg-lens` present, outerHTML **6251 == базовому cfg-05**, scale="32" |
| ADD-2.6 (CFG-06): дельта-канарейка | `canary/**` (g1 PASS 13/13, g4 PASS 14/15 c честной published_at=None, e4 4/4, guard-швы 0 событий; W7 8/8) | **PASS** (ограничения — в `canary/README.md`) |
| ADD-2.7 (CFG-07): egress/delivery-трассы | `07d6-corpus-probe.json` route proof (9 guard-швов, delivery-guard) + канарейка (машинных артефактов в отгрузках нет: no_service_markers) + `regression-focused.txt` (guards 88 + route-coverage) | **PASS** |
| ADD-2.8 focused-регресс на master-байтах | `regression-focused.txt` | **535 passed, EXIT 0** (CFG-01/02/03/06/07 семьи + guards + backstage + route-coverage; полный повтор эпиков не запускался) |

## 4. Барьер G3 — закрытие 4 блокеров

| Строка | Было | Чем закрыто |
|---|---|---|
| CFG-06F.6 | READY_FOR_LIVE | Дельта-канарейка на deployed-байтах @8ea6ed4e (флаг ON): stage-trace + verdict разделением CODE/TEST/LIVE (`canary/README.md`, `run-g1/g4.json`) |
| CFG-06J.6 | READY_FOR_LIVE | Диспут-E2E на deployed-байтах: S6 (спор 260 → предмет из хронологии, автор сохранён) + сквозной pipeline (g1/g4) — `probe-dispute-w7.txt`, `canary/run-g1.json` |
| CFG-06.B | READY_FOR_LIVE | Композит S1–S8 8/8 на deployed-байтах + egress-инварианты ре-проб (g1/g4: no_service_markers, hrefs из EvidenceMap) — `probe-dispute-w7.txt`, `run-g1/g4.json` |
| CFG-07D.6 | PENDING | Корпус ДО/ПОСЛЕ: `07d6-corpus-probe.{md,json}` — 7/7 скриншот-класса воспроизводятся на 29cc49ba и нейтрализуются на 8ea6ed4e (флаг v2=true); prompts-версии и SHA подтверждены; PASS |

Живые осмотры владельца (реальные чаты/устройства) — добровольные
(`owner_live_checks.md` §2/6/7, PET-правило 18.10/20.10), в вердиктах
не фигурируют как обязательства.

## 5. Дедуп-аудит (ADD-0.2) и таксономия (ADD-0.5)

- **Дубли:** CFG-дельта не создаёт второго owning-task: фактчек остаётся
  единым контуром (v2-оркестратор; CFG-06 — его приёмка), стекло — SOUL-ветка
  (CFG-05 = OBSERVED_FIXED/REUSE_EXISTING, `evidence/cfg-05/reuse-map.md`),
  speech — UNIFIED-CORE (07B = absorption G0, `evidence/cfg-07b-reused/**`),
  throttle/config — существующие hot-config/chat_params (CFG-01 reuse-map в
  README §2), лимиты изображений — существующий каталог (CFG-02A/02B/02C).
  Алиасы ADD-1.T1–T7/C1–C7 в карте указывают на один owning-task каждый.
- **Таксономия статусов (ADD-0.5):** в отчёте `../../cfg-final-report.md`
  статусы разделены: CODE/TEST-VERIFIED (тесты на deployed-байтах),
  LIVE-VERIFIED (deployed-пробы F1: HTTP/SSH/канарейка), OWNER_E2E_PENDING —
  только добровольные owner-пункты (`owner_live_checks.md`), ни один
  обязательный пункт не помечен пройденным по мокам.

## 6. Incidental findings (не блокеры)

1. **Narrator-канон** (`SUMMARY_NARRATOR_SYSTEM_PROMPT`, активен:
   summary_generator:4063) несёт identity-фразу «токсичный…бот-абьюзер…
   завсегдатай двача» — вне корпуса SF (17 SOURCE_FIX) и 7 маршрутов 07A-2.
   Классификация: related-nonblocking, кандидат в backlog (не обязанность
   07D.6/07A). Зафиксирован в `07d6-corpus-probe.json` (per-holder).
2. **`keys.image_api_key` в hot-настройках прода** — живой ключ провайдера
   виден в bot_settings (ожидаемая архитектура ключей; в артефакты F1 не
   попадал — запрос отфильтрован, логи скраблены; первая сессия выводила
   ключ в консоль — файл перезаписан, проверено `check_leak`: 0 вхождений).
3. Усечённый URL Tavily (canary 20.10, related-nonblocking) — сохранился как
   существующий контракт агрегатора; в F1-пробах не воспроизводился.
