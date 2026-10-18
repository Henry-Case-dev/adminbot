# P0V 2.58.91 — live acceptance (ACCEPTANCE-91)

Прод: **2.58.91**, HEAD **`f2a6248ae30d8e0b1878785bb6d1477f65e21c78`**
(`origin/master`), T0 **2026-10-18 20:11:46 UTC**, PID **3508490**.
Приёмка: **2026-10-18 20:27–21:08 UTC**. Один контролируемый harness-процесс
на проде (не polling-процесс): импортирует развёрнутые модули, шлёт реальные
Telegram-сообщения, ходит в реальные PG/SQLite и провайдеры. Сообщения —
синтетические апдейты от отдельного пользователя `990002001` в рабочем чате
`-1002661910336`; ответы бота — реальные, `message_id` ниже. Секретов в
отчёте нет.

## Итог

**VERIFIED полностью:** health-цепочка (тёплый повтор), канон «чекап»,
CFG-02B, factcheck с явным утверждением и зарегистрированным target,
доставка изображений (2 успешные генерации), восстановление настроек.
**FAILED/BLOCKED:** положительное распознавание Vision и postgen (провайдер
HTTP 429), worker-skip (36 за окно), неверный MessageRef в reply-на-фото,
холодный старт L1 (15 с fallback), извлечение claim из «это правда?».
Релиз стабилен (ERR/CRIT/402 = 0), откат по стабильности не требуется;
P0V-пункты не закрыты — нужен Builder/Reviewer и внешний провайдер.

## Таблица 1–9 (пять фактов на сценарий)

| # | plan / announced | tool_call | результат | Telegram delivery | статус |
|---|---|---|---|---|---|
| 1 | холодный старт: L1 timeout 15.047 с → `fallback=deterministic`, `capabilities` нет; тёплый повтор: `L1_PLAN capabilities=health`, conf 0.90, 2.23 с | холодный: нет; тёплый: `TOOL_CALL get_bot_health` | холодный: ответ без данных (1165609/1165610); тёплый: `TOOL_CALL_COMPLETE ok`, 2283 симв. | тёплый mid **1165629**; канон «чекап» 0g: **1165611** (фраза fallback) + **1165612** (отчёт 2279 симв.) | **VERIFIED (тёплый)** + cold-start finding |
| 2 | `POST /api/vision/test` (админ-TMA, loopback) | реальный probe провайдера | HTTP 200, 328 мс: `capability=rate_limited`, `reason=vision_rate_limited`, `detail=http_429`, `visible_reason=«Превышен лимит запросов провайдера»`, provider `openrouter.ai`, model `google/gemma-4-31b-it:free` | нет (диагностический API) | **BLOCKED_EXTERNAL** (честная причина) |
| 3 | own-media: `L1_PLAN capabilities=image_understanding` (6.6 с, 0.95); reply-на-фото: то же (6.5 с, 0.90) | `recognize_image`: own target **1165607** (фото); reply target **1165613** (ответ бота, **не фото 1165606**) | оба `disabled/vision_rate_limited`; asset-resolver: 1165613 `missing`, 1165606 `ok`, 1165607 `ok` | own mid **1165613** (186 симв., честный отказ); reply mid **1165614** (93 симв.) | **PARTIAL**: own MessageRef верный; reply MessageRef **неверный**; positive — BLOCKED_EXTERNAL |
| 4 | exact «бот, это правда?»: `capabilities=fact_check` (7.1 с, 0.95); explicit+registered: `capabilities=fact_check,web_search` (2.4 с, 0.96) | `fact_check` (exact claim = вопрос); `fact_check` + `execute_web_search` (registered) | exact: `unavailable/temporal_envelope_rejected`; registered: **`ready`, `factual_verdict=supported`, `temporal_status=old_but_valid`**, 23.6 с | exact mid **1165617** (229 симв., честно «не подтвержу»); registered mid **1165658** (441 симв., «Подтверждено…») | **VERIFIED (registered)**; exact «это правда?» — **PARTIAL** (claim extraction) |
| 5 | фраза «нарисуй…», image-модуль ON | pre-gate → `generate_image` (3 попытки провайдера) | gen1 — `provider_unavailable`; gen2/gen3 — `success` (699 302 и 558 659 байт) | gen1 text **1165619**; gen2 photo **1165620** + text **1165621**; gen3 photo **1165622** + text **1165623**; replay — 0 новых отправок/вызовов | **VERIFIED delivery** (2 успеха; 1 транзиентный сбой) |
| 6 | postgen включён (`enabled=True`, budget 20 с), вызывается на финальном bitmap | `image_postgen_vision` для gen2/gen3 | оба `rate_limited/vision_rate_limited`, `has_content=false`, описания нет | ответы gen2/gen3 честно: «подтвердить синий кораблик/зелёное яблоко не могу» | **BLOCKED_EXTERNAL** (положительное описание не проверено) |
| 7 | включаем штатно per-chat: `flags.budgets_enabled=true`, `limits.image_freq_limit_enabled=true`, burst=2, cooldown=120, mode=per_user | `image_freq_state.applied=true`, reason `ok`; 2 генерации списали заряды (reservations `1165619`, `1165621` committed) | третья попытка: `image_generate skipped cooldown`, provider_calls **0**, текст «снова можно через минуту с копейками» | mid **1165624** | **VERIFIED**; восстановлено: `enabled=false`, global 3/300/per_user; budgets=false; freq-ключи убраны |
| 8 | served bytes: `GET /web/` 200, `version_in_html=15` (= PAGE_VER 15) | — | `/static/app.js` 404 (страница использует vendor-скрипты + inline app); deploy evidence `SERVED_EQ_APP_JS=SAME`, `SUBST_CSS=2` | — | **PARTIAL/BOUNDARY**: браузера на сервере нет (`chromium/node/playwright` отсутствуют), локальный Browser Use не может подставить TMA initData без токена; UI-раздел покрыт candidate UI e2e |
| 9 | бюджеты/журнал | — | `image_calls` 2026-10-19: global/chat **1 → 4** (Δ3: 1 failed + 2 success), лимиты 200/60; reservations 2 committed, 0 errors; ERR/CRIT/Traceback/402 = **0**; `mca_errors=0`; `user_version=36`; HEAD не менялся, tracked mod=0 | — | **VERIFIED наблюдений** + finding worker-skip |

## Findings (что осталось живым)

1. **BLOCKER (внешний): Vision-провайдер HTTP 429.** OpenRouter
   `google/gemma-4-31b-it:free` стабильно отдаёт `rate_limited/http_429`
   (probe 20:29, все vision-медиа 20:25–21:07, postgen). Положительное
   распознавание и postgen-описание **не подтверждены**. Нужен рабочий
   совместимый provider/model (выбор владельца: другая модель/ключ или
   ожидание квоты) и повторная live-проба. Не выдавать за успех.
2. **BLOCKER (P0V-PIPE-WORKER): worker всё ещё пропускает тики.**
   `journalctl` since T0: **SKIPS=36** `VisionMediaWorker._tick ... skipped:
   maximum number of running instances` (20:17, 20:22, 20:27, 20:32, 20:37,
   20:40–20:47, 20:51–20:57, 21:02–21:07). Часть — в окнах harness, но
   пропуски есть и до/после (20:17–20:37). Health-отчёт тоже это фиксирует.
   Требование «worker без пропусков из-за занятого экземпляра» **не
   выполнено** → Builder/Reviewer.
3. **BLOCKER (ADTR-ENTRY/P0V): reply-на-фото даёт неверный MessageRef.**
   `recognize_image` target = `1165613` (ответ бота), а фото — `1165606`.
   Read-only resolver: 1165613 `missing`, 1165606 `ok`. При рабочем
   провайдере это был бы `missing` вместо распознавания. Own-media
   (`1165607`) — корректно.
4. **MEDIUM (L1 planner cold start).** Первые два health-запроса:
   L1 timeout **15.0 с** → `fallback=deterministic`, `capabilities` пуст,
   tool не вызван (1165609/1165610 — ответы без данных). Тёплый повтор:
   2.23 с, `health`, tool ok. Нужен прогрев/увеличенный timeout/повторная
   попытка; функциональность на повторе работает.
5. **MEDIUM (CFG-06 claim extraction).** Reply «бот, это правда?»:
   `fact_check` вызван, но claim = сам вопрос, target не в `smart_messages`
   (в проде observer его запишет) → `temporal_envelope_rejected`.
   Explicit claim + registered target: `ready/supported`. Для reply-фактчека
   нужно брать claim из target-сообщения, а не из вопроса.
6. **MEDIUM (UI per-chat state).** `GET /api/vision/state` не учитывает
   per-chat override: в рабочем чате `flags.vision_enabled=true`, а endpoint
   отдаёт `requested=false/vision_disabled` (глобальный флаг). Карточка может
   показывать «выключено» при включённом чате. `resolve_effective_state(chat)`
   в runtime даёт `requested=true/effective=false/pending`.
7. **LOW/транзиент:** gen1 `image_generate failed provider_unavailable`;
   gen2/gen3 успешны. Провайдер картинок восстановился; повторный tool call
   не дублировал (0 вызовов/0 отправок).
8. **LOW/наблюдение:** `database is locked` — 5 строк (20:40, 20:41, 21:03);
   часть вызвана вторым SQLite-писателем (harness). Это не самостоятельный
   ERR (ERR=0), но worker-skip частично коррелирует с локом.
9. **BOUNDARY (UI):** визуальный Browser Use на прод-странице не выполнен:
   на сервере нет браузера, локально нет TMA initData без токена. Served
   bytes (`version_in_html=15`, deploy `SERVED_EQ_APP_JS=SAME/SUBST_CSS=2`)
   + candidate UI e2e — доказательная граница.
10. **SCEN-B (ностальгия):** не запускался — окно не было «тихим»; не блокер.

## Затраты

- Генерации изображений: **3 попытки** (1 `provider_unavailable`, 2 success);
  `image_calls` global/chat 1→4, лимиты 200/60. Две картинки удалены после
  фиксации mid (1165620, 1165622); повторных платных вызовов нет.
- LLM (окно 20:38–20:47): `single` 27, `l2_writer` 9, `l1_planner` 7,
  `image` 2; factcheck follow-up добавил `temporal_verdict`,
  `temporal_validator`, `temporal_verbalize`. У большинства строк
  `price_known=false` — долларовую сумму не выдумываем.
- Vision: probe/анализы — внешние 429; положительных платных Vision-вызовов
  не было.

## Журнал / стабильность / откат

- Journal since T0 (epoch 1792354306): **LINES=1884, ERR=0, CRIT=0,
  Traceback=0, 402=0; SKIPS=36; VISION_RL=17; LOCKED=5; mca_errors=0;
  user_version=36**.
- Сервис: `MainPID=3508490`, `NRestarts=0`, `active/running`,
  healthz `2.58.91`; HEAD `f2a6248a`; tracked modifications **0**,
  untracked 13 (унаследованные).
- Откат не использовался. Готовые рубежи: `release/fix-2.58.90`
  (`3b02366e`, 2.58.90), `release/fix-2.58.89` (`d59fab94`),
  `release/cfg1-2.58.88`. Причина не откатывать: сервис стабилен, ERR=0;
  worker-skip и MessageRef — forward-fix, не деградация всего релиза.
- Временные настройки CFG-02B восстановлены: `enabled=false`, burst=3,
  cooldown=300, per_user, source=global; `flags.budgets_enabled=false`;
  freq-ключи удалены; synthetic throttle rows очищены.

## Следующие действия

1. **Builder/Reviewer:** worker tick (P0V-PIPE-WORKER), reply-to-photo
   MessageRef (ADTR-ENTRY), claim extraction для reply-фактчека, L1 cold
   start, per-chat `/api/vision/state`.
2. **Владелец/внешний провайдер:** рабочий Vision model/provider (текущая
   free-Gemma — 429) и повторная live-проба; после этого — положительное
   распознавание и postgen.
3. Карты **не закрывать**: это следующий леджер; P0V-пункты
   `P0V-PIPE-WORKER`, `P0V-PIPE-CONTEXT`, `P0V-DOD`, `P0V-SYMPTOMS`,
   `P0V-ARCH-ENDPOINTS`, `P0V-ARCH-SWITCH` требуют positive live evidence.

## Файлы

- `scenario-1-coldstart.json` / `scenario-1-retry.json`
- `scenario-2-vision-probe.json`
- `scenario-3-vision-freeform.json`
- `scenario-4-exact.json` / `scenario-4-explicit.json` /
  `scenario-4-registered.json`
- `scenario-5-generate.json` / `scenario-6-postgen.json`
- `scenario-7-cfg02b.json`
- `scenario-8-ui.json` / `scenario-9-economics.json`
- `journal-post.txt`, `postcheck.json`, `cleanup-restore.json`,
  `cleanup-deleted-images.json`, `pre-vision-state.json`,
  `pre-chat-overrides.json`, `recon.txt`, `summary.json`
- `harness/` — исходники контролируемых вызовов (live/followup/factreg/
  vprobe/postcheck). Runners с SSH-паролем в репозиторий не промотированы.

### Оговорки по доказательствам

- В первом прогоне поле `handled` было инвертировано в harness (handler
  вернул `None`=consumed); в JSON выставлено `true` по логам/отправкам,
  это не изменение продуктового результата.
- `scenario-5/6/7` в основном прогоне не сохранились из-за ошибки
  сериализации harness (Decimal) **после** всех реальных вызовов; файлы
  восстановлены из `summary.json`, `scenario-7-cfg02b-capture.json` и
  прод-леджера. Настройки восстановлены отдельным follow-up.
- Factcheck с зарегистрированным `smart_messages` — это fidelity-фикс
  harness: в проде observer регистрирует реальное сообщение пользователя.
  Без регистрации envelope честно отклоняет target. Синтетические строки
  `smart_messages` (1165655, 1165657) после прогона удалены; healthz
  `2.58.91` подтверждён повторно.
