# CFG-FINAL — исполнительный план композитной приёмки (без нового кода)

**Лейн:** PM-CFG-FINAL-PLAN (план; read-only по коду/карте). Дата: 21.10.2026 (UTC+12).
**База:** прод **2.58.104 @ `8ea6ed4e`** (deploy VERIFIED), master `a9917abb`. Все волны 06/07A/07C-G/07D.5 Approved и задеплоены; хвосты (биндинг 07B/07C/06-RFL — лейн LEDGER-CFG-TAIL; CFG-03 Wave B) закрываются параллельно.
**Источники:** `source-cfg-addendum.md` ADD-0 (L9–14), ADD-1.C7 (L36), ADD-2 (L388–395), L3/L397; `requirements-map.json` slice=CFG-FINAL (15 items + ADD-0.Q/ADD-2.Q); `cfg-07-build-plan.md` §4; `plan.md` (строка 12); `prep-cfg-02b.md` §3.7/L168 (ADD-2.2); `prep-cfg-05.md` §2 (ADD-2.5 → CFG-FINAL); `prep-cfg-03.md` (582/F2/5 dead-handles); evidence-дерево `evidence/**`.

## 0. Что такое CFG-FINAL по-человечески

Это финальная сквозная приёмка всей CFG-дельты (CFG-01…07) **без нового кода и без повторного исполнения закрытых волн**: (1) регрессионный проход по уже VERIFIED-evidence, (2) технические postdeploy-пробы на текущем проде `8ea6ed4e`, (3) процесс-контроль ADD-0 и регрессии `current_task`, (4) итоговый отчёт со сквозной картой (ADD-2.8). Прецедент **CFG-04.B**: композит не закрывается частичными зелёными — только когда все подстроки VERIFIED и есть deployed-биндинг.

## 1. Таблица 17 строк CFG-FINAL: источник → тип проверки → evidence → чего не хватает

Типы: **COMPOSITE** = регрессия по VERIFIED-evidence (без перезапуска волн); **PROBE** = живой postdeploy-проб на 2.58.104 @ `8ea6ed4e` (технический); **REPORT** = отчётный артефакт. Owner_optional в слайсе **нет** (все 17 строк — инженерные; добровольные пункты владельца живут в `plans/owner_live_checks.md` §2/6/7 и в вердикте не фигурируют как обязательства).

| req_id (src) | Что требует источник | Тип | Существующий evidence (использовать) | Чего не хватает |
|---|---|---|---|---|
| ADD-0.1 (L9) | Очередь: CFG после существующих задач, автостарт, без переигрывания | COMPOSITE | `plan.md` §очередь; release-поезда 25893→25897→25898→25899→102/103/104; `workflow_state.md` | Фиксация порядка в отчёте (без переигрывания) |
| ADD-0.2 (L10) | Нет дублей (не второй SOUL-1/стекло/фактчек…), один owning-task + алиасы | COMPOSITE | `plan.md` §дедуп; алиасы ADD-1.T1–T7/C1–C7 в карте; `evidence/cfg-05/reuse-map.md`; `evidence/cfg-07b-reused/**` | Дедуп-аудит-заметка в bindings.md |
| ADD-0.3 (L11) | Immutable snapshot + SHA256 + append-only manifest CFG-01…07 | REPORT | `source-cfg-addendum.md` (398 строк, SHA256 `2ED43009…6B10`); карта 246+41, plan-гейт errors=0 | Пересчёт SHA (одна команда) + фиксация в отчёте |
| ADD-0.4 (L12) | Позднейшие решения владельца приоритетны; без разрушительного толкования | COMPOSITE | AGENTS.md standing rules; F3-тексты 20.10; `owner-decisions`/prep-брифы §6 | Пункт в отчёте: неразрушительность применена |
| ADD-0.5 (L13) | Раздельные статусы; owner-only E2E не «пройдено по мокам» | REPORT | Статусы карты; `owner_live_checks.md`; OWNER_E2E_PENDING-строки CFG-04 | Таксономия показана честно в итоговом отчёте |
| ADD-0.6 (L14) | Формат отчётов + финальная сквозная сверка | REPORT | release-отчёты (README/deploy.md поездов) | Сам итоговый отчёт (артефакт этого слайса) |
| ADD-1.C7 (L36) | Старт сразу после очереди, не ждать нового сообщения | COMPOSITE | `workflow_state.md`; реестр `progress_scope.json` | Фиксация в отчёте |
| ADD-2.1 (L388) | CFG-01: burst/cooldown hot-reload, конкурентность/рестарт, честный остаток | COMPOSITE + PROBE | `evidence/cfg-01/**` (README, red-green, e2e), тесты throttling; прецедент 2.58.97 | Проба на `8ea6ed4e`: effective-значения + hot-apply + остаток в трассе (без сообщений в реальные чаты) |
| ADD-2.2 (L389) | CFG-02: квота видна; частотный OFF default; per-user/chat; обложки не тратят user-лимиты; shared-ceiling честен | COMPOSITE + PROBE | `evidence/cfg-02a/02b/02c/**`; тесты `test_cfg02b_image_freq_limits`, `test_cfg02c_image_isolation` | Прод-проб (prep-cfg-02b L168): секция «Лимиты генерации» в отданных байтах, OFF default; платные генерации ≤2–3 в пределах квоты; заодно фактура для RFL CFG-02A×4 |
| ADD-2.3 (L390) | CFG-03: manifest на каждый параметр + honest unverified; B06/SOUL переиспользованы | COMPOSITE | `evidence/cfg-03/**`; `test_cfg03_param_audit.py` 16 passed; `review-cfg-03.md` Approved; каталог 582 | Wave B (R1-переэмиссия 582 + R2-сводка) VERIFIED — барьер G3; композит только сверяет |
| ADD-2.4 (L391) | CFG-04: save/dirty на узком экране/повороте/клавиатуре/safe-area; 1 CTA; композиция U01/HOTFIX цела | COMPOSITE + PROBE | `evidence/release-25897/acceptance/**` (live-matrix-digest, dirty-guard, bytes-identity, shots); CFG-04.B VERIFIED | Ре-проб харнесов (`harness/deployed_probe.py`, `dirty_guard_live.py`, `served_markers.py`) на `8ea6ed4e` |
| ADD-2.5 (L392) | CFG-05: OBSERVED_FIXED/REUSE_EXISTING; скриншот владельца + U08/SOUL приняты; без регрессии glass/фона; очередь не блокирована | COMPOSITE + PROBE | `evidence/cfg-05/**` (owner-observation.md, glass-invariant.json, reuse-map); CFG-05-Verify 8/8 VERIFIED | Один инвариант-чек на `8ea6ed4e`: `#lg-lens` 6298 байт / `scale="32"` + blob `polygon-background.js` = `c2ad97d4…` (git/HTTP, без нового исследования стекла) |
| ADD-2.6 (L393) | CFG-06: единый фактчек (provenance/time, широкий контекст, мало ложных отказов, реальные tools, Telegram-output без JSON/unknown; legacy/fallback — те же правила) | COMPOSITE + PROBE | `evidence/cfg-06/**` W0–W7; canary 4/4 PASS (06E.4/F.1/G.1/G.4) @ `7142ffcf`; 89 VERIFIED | Ребиндинг канарейки: `git diff --stat 7142ffcf..8ea6ed4e -- factcheck-файлы` пуст → байты равны; иначе точечный ре-проб; + прод-трасса `factcheck_run`/telemetry (06-RFL биндинг — LEDGER-CFG-TAIL, барьер G3) |
| ADD-2.7 (L394) | CFG-07: один голос Core; мат-переключатель factory ON + chat overrides; нет backstage в публичных маршрутах; защита цитат; delivery проверена | COMPOSITE + PROBE | `evidence/cfg-07a/**` (07a1-audit, 07a2, 07cg-*, 07d5-*, release-102/103/104); `evidence/cfg-07b-reused/**`; eval `add-exp/directives-fix` | Биндинг 07B (12 строк, evidence `29cc49ba`) и 07C (11 строк, коммиты `7c3a1350/f1e31d27/8cd2ca14/04593c8f`) — барьер G3; проб egress/delivery-трасс на `8ea6ed4e` (без машинных артефактов в отгрузках) |
| ADD-2.8 (L395) | Регрессии исходного current_task без повторов больших планов; итоговый status report: сквозная requirements-map, current_task→source/impl/test/live; owner-only видны без бесконечного ожидания | REPORT + COMPOSITE | `evidence/release-25897/pytest-full.txt` (3652 passed), release-25899 focused-регрессии | Финальный отчёт `cfg-final-report.md` + один targeted-регресс на master `a9917abb` (focused CFG/речь/UI-пины, НЕ полный повтор эпиков) |
| ADD-0.Q (L3) | Очередь строго ПОСЛЕ существующих задач, без нового свободного эпика | COMPOSITE | `workflow_state.md`; `progress_scope.json` | Фиксация в отчёте |
| ADD-2.Q (L397) | После дополнения — продолжать штатно при остатке обязательных задач | REPORT | `workflow_state.md` select_next | В отчёте: что осталось (хвосты/RFL/backlog) и что дальше |

## 2. Процедура исполнения

**Роли:** 1 Builder-композит (единственный писатель) + 1 Reviewer-вердикт. **Никаких новых писателей кода.** Write scope композита: `plans/features/cfg/evidence/cfg-final/**`, `plans/features/cfg/cfg-final-report.md`; Reviewer: `plans/features/cfg/review-cfg-final.md`. Код/тесты/чужой evidence — read-only. Карта `requirements-map.json` — НЕ в скоупе композита, пока работает LEDGER-CFG-TAIL (после его финиша биндинг строк CFG-FINAL выполняется штатным леджер-шагом этого же лейна).

- **Волна F1 (Builder-композит, серийные шаги):**
  1. `bindings.md` — финализировать §1: по каждой строке конкретные evidence-пути + SHA, проб/отчёт, дыра закрыта.
  2. COMPOSITE-проход: пересчёт SHA снапшота; дедуп-аудит (ADD-0.2); сверка таксономии статусов (ADD-0.5); регрессии current_task — один focused-прогон на `a9917abb` (ADD-2.8), без повторов больших планов.
  3. PROBE-пакет на проде `8ea6ed4e` (артефакты `evidence/cfg-final/probe-*.md|json`): ADD-2.1 (hot-apply/остаток), ADD-2.2 (байты секции лимитов, OFF default, ≤2–3 платных генераций в квоте), ADD-2.4 (re-run харнесов 25897), ADD-2.5 (glass-инвариант), ADD-2.6 (delta-канарейка + factcheck_run), ADD-2.7 (egress/delivery-трассы). Дисциплина: HTTP/healthz/логи/байты — приоритет; без тестовых сообщений в реальные чаты без отдельной санкции (прецеденты живых приёмок CFG-01/02x соблюдать); fail2ban: минимум SSH-коннектов, одиночный логин, без поллеров.
  4. `cfg-final-report.md` (ADD-0.6/2.8/2.Q): сквозная карта current_task → source/implementation/test/live; статусы по таксономии; owner-only проверки перечислены видимыми, НЕ блокирующими; что осталось/что дальше.
  5. Биндинг 17 строк карты (после финиша LEDGER-CFG-TAIL) + гейт review.
- **Волна F2 (Reviewer):** независимая сверка источника (ADD-0/ADD-2, все 17 исходных пунктов) vs runtime/evidence; проверка «нет частичных зелёных» (прецедент CFG-04.B), нет дублей прежних гейтов, все live-строки имеют deployed-биндинг. Вердикт → `review-cfg-final.md` → гейт release.
- **Гейты** (из корня репозитория, `py -3`):
  - план: `py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --stage plan`
  - ревью: `py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --stage review --slice CFG-FINAL --candidate <sha>`
  - релиз: `py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --stage release --candidate <sha> --deployed-commit 8ea6ed4e`
- **PASS:** G3 открыт; review/release EXIT 0; все 17 строк с candidate-bound evidence (реальные repo-пути; для live — артефакт проб на `8ea6ed4e`); Reviewer Approved; отчёт содержит сквозную карту и честный остаток.
- **FAIL (примеры):** композит-строка с evidence вида «волна Approved» без артефакта; канарейка/инвентарь привязаны к `7142ffcf`/579 без delta-доказательства; owner-only пункт помечен пройденным по мокам; частичный зелёный при непокрытой строке.
- **Честные условия:** не объявлять VERIFIED без deployed-биндинга (живые строки 2.1/2.2/2.4–2.7 — только артефакты на `8ea6ed4e` или байт-равенство с прод-байтом). WAITING_EXTERNAL/Human Gate для живых пунктов владельца **не создавать** — они добровольные по standing rule (`owner_live_checks.md` §2/6/7, PET_PROJECT 18.10/20.10); в отчёте — как видимая необязательная секция. После CFG-FINAL сессия продолжается штатно (ADD-2.Q), не «завершение по одному Approved».

## 3. Барьер G3 и проверка готовности одной командой

CFG-FINAL стартует только после VERIFIED всех инженерных строк: CFG-03 (Wave B: R1 582/R2), CFG-06 ×4 RFL (06F.6/06G.8/06J.6/06.B — биндинг канарейки), CFG-07B ×12 (UNIFIED-CORE evidence), CFG-07C ×11 (коммиты волн). Проверка готовности (из корня):

```
py -3 -c "import json;m=json.load(open('plans/features/cfg/requirements-map.json',encoding='utf-8'));rows=[r for r in m['items']+m.get('additional_requirements',[]) if r.get('slice') in ('CFG-03','CFG-06','CFG-07A','CFG-07B','CFG-07C')];bad=[r['req_id'] for r in rows if r.get('status')!='VERIFIED' and r.get('verification_tier')!='owner_optional'];print('G3:', 'OPEN' if not bad else 'BLOCKED '+','.join(bad))"
```

`G3: OPEN` + plan-гейт EXIT 0 → назначать Builder-композит. Пункты `owner_optional` (CFG-07D.1.OBS) G3 не блокируют. RFL CFG-02A×4/CFG-04×1 — не входят в G3: их фактура добывается пробами ADD-2.2/2.4 внутри композита, статусы строк — штатный леджер-шаг.

## 4. Риски

1. **Дубли с прежними гейтами** (ADD-2 прямо: «не дублировать прежние gates»): композит не перезапускает закрытые волны; каждая строка ссылается на существующий VERIFIED-артефакт + только недостающий binding/probe. Дедуп-аудит — обязательный шаг F1.2.
2. **Частичные зелёные** (прецедент CFG-04.B): ADD-2.x не закрываются, пока хоть одна подстрока 06/07/03 не VERIFIED; команда §3 — обязательный pre-check, повтор при возврате FAILED.
3. **Устаревшие привязки:** прод уже **2.58.104 @ `8ea6ed4e`** — все композитные прогоны и пробы биндить на deployed `8ea6ed4e`/master `a9917abb`. Канарейка привязана к `7142ffcf` (2.58.99) → обязателен delta-чек байт фактчек-файлов; инвентарь CFG-03 на 579 → принять только Wave B-переэмиссию на 582.
4. **F2 type-mismatch** (2 параметра) — вне scope: backlog с готовым рецептом (`prep-cfg-03.md` §1.6); композит не переоткрывает.
5. **5 dead-handle** — уже честно задокументированы (честные описания + failures F3/F4 DOCUMENTED); композит проверяет сохранение документации, не «молчаливый ремонт».
6. **Стоимость/безопасность:** платные генерации ≤2–3 в пределах квоты; ноль сообщений в реальные чаты без санкции; fail2ban-дисциплина деплой-канала; откат — lossless (`a9917abb`).
7. **Конкуренция за карту:** LEDGER-CFG-TAIL пишет `requirements-map.json` параллельно — композит ждёт его финиша перед биндингом строк; barriers согласованы, скоупы не пересекаются.

## 5. Handoff

Готово: посрезная таблица 17 строк с источниками и способом закрытия; процедура F1/F2; точные команды гейтов; критерии PASS/FAIL; G3 одной командой; риски. Human Gate не вводится. Следующее действие оркестратора: держать LEDGER-CFG-TAIL и CFG-03 Wave B до VERIFIED → выполнить команду §3 → при `G3: OPEN` назначить Builder-композит CFG-FINAL (scope §2), затем Reviewer.
