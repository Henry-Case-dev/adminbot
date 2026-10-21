# CFG-FINAL — итоговый отчёт эпика CFG (current_task, дополнение ADD-0/ADD-1/ADD-2)

Дата: 21.10.2026 (UTC+12). Эпик исполнен по дополнению ТЗ
`plans/features/cfg/source-cfg-addendum.md` (398 строк, immutable snapshot,
SHA256 `2ED43009…6B10` — пересчитано 21.10, `evidence/cfg-final/probe-delta.json`).
Очередь соблюдена: CFG стартовал **после** стоявших впереди задач (релизы
SOUL/P0/samples-ux; ADD-0.1/ADD-0.Q/ADD-1.C7), автостарт без ожидания нового
сообщения, переигрывания закрытых волн не было (ADD-0.2 — дедуп-аудит:
`evidence/cfg-final/bindings.md` §5). Позднейшие решения владельца приоритетны,
разрушительных перетолкований нет (ADD-0.4: standing rules 18.10/20.10).

## 1. Что доставлено (человечески, CFG-01…07)

| Блок | Что делает для владельца | Версии |
|---|---|---|
| CFG-01 | Правка «обращений подряд/кулдаун» в MiniApp меняет частоту ответов **без рестарта**; отказ с фактическим остатком и источником; переживает рестарт; анти-обход | 2.58.88–89 |
| CFG-02A/02B/02C | Секция «Лимиты генерации» изображений: дневная квота видна, частотный лимит **выключен на заводе**, per-user/per-chat, обложки сводок не тратят пользовательский лимит, shared-ceiling честен | 2.58.93–97 |
| CFG-03 | Аудит всех параметров: manifest на каждый параметр, честные unverified, UI-валидаторы; каталог 582 (working 568/14, inconsistencies=3 задокументированы) | 2.58.97–101 |
| CFG-04 | Формы настроек на узком экране: один CTA сохранения, safe-area один раз, панель над клавиатурой, dirty-guard с точным текстом, tech-key копируется | 2.58.97 |
| CFG-05 | Стекло: фикс поверх полигонального фона, без нового исследования стекла (REUSED_EXISTING; инвариант подтверждён на 104) | 2.58.97+ |
| CFG-06 | Единый фактчек: сначала решает, имеет ли смысл проверка, затем — реальные источники или честное ограничение; широкий контекст (споры 200+), temporal, attribution; Telegram-вердикт с проверяемыми ссылками, без служебных данных; legacy/fallback — те же правила | 2.58.99 |
| CFG-07 | Один голос Core; мат — переключатель Expression (factory ON, GLOBAL/CHAT); анти-backstage: ни логов, ни «аналитик подтянул», ни JSON в публичных ответах (детекторы + bounded retry + честная деградация); защита цитат/фактов | 2.58.100–104 |

Поезда: 2.58.93→97→98→99→102→103→104; текущий прод **2.58.104 @ `8ea6ed4e`**
(deploy VERIFIED, DDL=0, ERR=0, откат lossless на `2a3e4fc9`/hot-flag).

## 2. Сквозная карта ADD-2.8 (current_task → source → implementation → test → live)

| Строка | Тип | Source | Implementation/уже VERIFIED-evidence | Test (F1) | Live (F1, deployed 8ea6ed4e) |
|---|---|---|---|---|---|
| ADD-0.1/C7/Q | COMPOSITE | addendum L3/L9–14/L36/L397 | release-поезда 93→104, очередь в workflow_state | — | порядок зафиксирован здесь и в bindings §0 |
| ADD-0.2 | COMPOSITE | L10 | reuse-map'ы, алиасы карты | — | дедуп-аудит: bindings §5 |
| ADD-0.3 | REPORT | L11 | snapshot 398 строк | — | SHA пересчитан == map (`probe-delta.json`) |
| ADD-0.4 | COMPOSITE | L12 | AGENTS.md standing rules | — | применены (без канареек/гейтов) |
| ADD-0.5 | REPORT | L13 | таксономия карты | — | показана здесь §3 |
| ADD-0.6 | REPORT | L14 | release-отчёты поездов | — | этот отчёт |
| ADD-2.1 | COMPOSITE+PROBE | L388 | `evidence/cfg-01/**` VERIFIED | 535 passed | SSH-проба: hot-apply 10→2→10, отказ с остатком 299.99s без рестарта (`ssh/probe-f1-summary.json`) |
| ADD-2.2 | COMPOSITE+PROBE | L389 | `evidence/cfg-02a/02b/02c/**` VERIFIED | cfg02b/c зелёные | секция в отданных байтах, OFF default (factory+prod), isolation-маркеры; платные генерации 0/≤2–3 — честно (см. bindings §3) |
| ADD-2.3 | COMPOSITE | L390 | `evidence/cfg-03/**` + Wave B (582) VERIFIED | param_audit 16 | сверка состава (bindings §2) |
| ADD-2.4 | COMPOSITE+PROBE | L391 | `evidence/release-25897/**` + CFG-04.B | — | re-run харнесов: байты/маркеры 1-в-1 rel97, dirty-guard PASS (`probe-prod-104.json`, `dirty-guard-104.json`) |
| ADD-2.5 | COMPOSITE+PROBE | L392 | `evidence/cfg-05/**` (8/8 VERIFIED) | — | blob `c2ad97d4…`, served==git, DOM `#lg-lens` 6251/scale=32 (`lens-dom-104.json`) |
| ADD-2.6 | COMPOSITE+PROBE | L393 | `evidence/cfg-06/**` (89 VERIFIED + canary 4/4 @7142ffcf) | W7 8/8, фактчек-семья зелёная | дельта-канарейка на 8ea6ed4e: g1 13/13, g4 14/15 (честная published_at), e4 4/4 (`canary/**`) |
| ADD-2.7 | COMPOSITE+PROBE | L394 | `evidence/cfg-07a/**` + 07b-reused + release-102/103/104 | guards 88, backstage, route-coverage | 9 guard-швов на deployed, 0 событий на чистых текстах, машинных артефактов в отгрузках нет |
| ADD-2.8 | REPORT+COMPOSITE | L395 | release-регрессы поездов | focused-регресс 535 passed на master-байтах | этот отчёт + bindings |
| ADD-2.Q | REPORT | L397 | workflow_state select_next | — | §4 ниже |

## 3. Таксономия статусов (ADD-0.5) — честно

- **LIVE_VERIFIED (технически, deployed 8ea6ed4e):** ADD-2.1/2.2/2.4/2.5/2.6/2.7
  пробы, канарейки 06F.6/06J.6/06.B, корпус 07D.6 — артефакты
  `evidence/cfg-final/**` (HTTP read-only, SSH read-only+hot-apply с
  восстановлением, ре-пробы с моком Telegram; **0 сообщений в реальные чаты,
  2 платных генерации**).
- **CODE/TEST_VERIFIED:** весь фокус-набор (535) на байтах прода; полные
  прогонки эпиков не повторялись (ADD-2.8: «без повторов больших планов»).
- **OWNER_E2E_PENDING (добровольно, не блокирует):** живые осмотры владельца
  (`plans/owner_live_checks.md` §2/6/7) — режим мата, облёт фактчека/лимитов
  в личных чатах, приёмка стекла на устройствах. Ни один обязательный пункт
  не помечен пройденным по мокам.

## 4. Что осталось (честно) и что дальше

- **Вне слайса CFG:** SOUL-21 и прочие активные запросы владельца — ведутся
  своими эпиками; сессия продолжается штатно (ADD-2.Q), «завершение по одному
  Approved» не объявляется.
- **Backlog (с рецептами, не блокеры):** F2 type-mismatch ×2
  (prep-cfg-03 §1.6); narrator-канон identity-фраза (incidental F1,
  `bindings.md` §6.1); 5 dead-handle — задокументированы (F3/F4 DOCUMENTED).
- **Телеметрия наблюдения продолжается:** 0 событий speech_guard/egress/factcheck
  с T0 (журнал 21.10 чист: 0 ERR/0 CRIT/0 Traceback) — wiring доказан на
  байтах, флаговой трафик в окне отсутствовал (прецедент 07C.6).
- Дальше по карте: release-гейт CFG-FINAL (F2 Reviewer → DevOps), штатные
  хвосты леджера, плановые наблюдения постдеплоя.
