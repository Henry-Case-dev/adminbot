# REV-REL-25889 — вердикт (релиз 2.58.89: CFG-02A B1 + «Речь и характер» на мобильном)

Независимое ревью. Read-only; этот коммит — только данный документ.
**Биндинг:** deployed `d59fab944bcb3eb0f5d3fa69101d8488da1c155b`; ветка `release/fix-2.58.89`, tip `3dfb48ef` (мой diff `d59fab94..3dfb48ef` = только A-доки: отчёт + `evidence/release-25889/**`; кода нет); прод-предшественник `c37b8577` (2.58.88).

## 1. Изоляция — подтверждено (пересчитал сам)
- Мой `git diff --name-status c37b8577 d59fab94` = **43**; классификация (`isolation-classification.txt`) перечисляет те же 43 (полное set-equality): **31 bump + 7 cfg-02a-payload + 3 speech-payload + 2 shared**; UNCLASSIFIED = 0.
- **12/12 payload-блобов == кандидатам** (проверены все, не спот): 7 → `83ecd202` (image_generation `c560e15d…`, tool_router `8ec679eb…`, worker_budget `7cdf9ea2…`, round1024_image_module_test, test_cfg02a_image_quota_ui, test_soul1_capability_fallbacks, tools/ui_cfg02a_image_quota_e2e `cc0a84c7…`); 3 speech + 2 shared (app.js `5e9cb25d…`, index.html `0656e0fc…`) → `720be161` (потомок `83ecd202`).
- WG 6/6 byte-equal prod↔head (fullscreen-policy/glass-refraction/glass-probe/refraction+probe тесты/WG-e2e). CFG-01 runtime 5/5 byte-equal (param_catalog, persistent_throttling, chat_params, direct_chat_service, handlers/direct_chat); frozen-check: нового ключа квоты в каталоге нет.
- Пины — чистая версия: спот diff (settings APP_VERSION 2.58.88→2.58.89; JS/py-пины — только строка версии). Секрет-скан: 5 совпадений — имя каталожного ключа `keys.image_api_key` и 4 заведомо фейковых плейсхолдера в тестах; креденшелов нет.

## 2. Preflight — мои перепрогоны (изолированный worktree @`3dfb48ef`)
Перепроверено **6** (спот ≥3 перевыполнен): cfg02a **27 passed**; speech-contract **6 passed**; capability-fallbacks **41 passed**; CFG-01 набор **204 passed**; registry **CHECK OK 575 == REGISTRY**; `node round1024_image_module_test.js` **IMAGE-MODULE-OK**.
Остальное переиспользовано по raw-логам (rc=0): webapp_js_unit 38; soul1-set 600; parity 13; frozen OK; node-guards 87/87; entry-e2e failures=0; ui_cfg02a_e2e RESULT: PASS (и мой чек cand-стороны: 6/6 sha12 скринов == PNG в `83ecd202`); refraction OK (37 проверок); shell OK; fs 12/12.

## 3. Живые факты — мои HTTPS-проверки + evidence
- Мой HTTPS: healthz `{"status":"ok","version":"2.58.89"}`; served `/web/app.js` sha12 **2757a25d663d** (1213835 B) == релиз-дереву; `/web/static/app.css` **d6b848cdecd0** (218391 B) == дереву; `/web/static/fullscreen-policy.js` `96db06425079` == дереву; `/web/` == index.html дерева с подстановкой `__APP_VERSION__`→`2.58.89` (sha12 `2121a1b09e2e`, 836709 B, «2.58.89» ×15, raw-плейсхолдеров 0, маркеры speech/quota присутствуют).
- По evidence (deploy/пост-логи): 25/25 sha256_12 на выкате; TRACKED_MOD_AFTER=0; DELTA_FILES=43; NRestarts=0; оси 5/5; SOUL gates **10/10**; CFG-01 не сломан (global burst 10 / cooldown 300, DM наследует; набор 204 passed); журнал since T0: ERR=0, RUNTIMEWARN=0; миграции complete, user_version=36, pending=[]; пост-прогон 17/18.
- Mobile-probe на прод-байтах (`post-prod-bytes-entry-e2e.json`): failures=[] notes=[]; 320/390/1280 — вход хаба видим (h=155/134/71), клик → `#/ai/speech`, экран «Речь и характер» с 3 карточками разделов, overflow=0; навигация хаба не переделана.

## 4. Девиации — приемлемы
1. `tools/ui_cfg02a_image_quota_e2e.py` в дельте: **приемлемо** — add-only инструмент, blob == кандидату `83ecd202`, ссылок из рантайма нет (только tools/отчёт/evidence), без него предписанный preflight невоспроизводим из ветки.
2. F8-meta: исправление `e25163b7`→`119b1f7d` **корректно** — мета хранит payload-коммит релиза; фактически: `c37b8577` нёс `e25163b7` (payload 2.58.88), `d59fab94` несёт `119b1f7d` (payload 2.58.89).
3. Восстановленные default-скрины: **ок** — в дереве релиза PNG витрины CFG-02A отсутствуют (не закоммичены по ошибке); reference-хеши кандидата подтверждены мной 6/6.
4. 17/18 постов (f3 информационная): **ок** — у DM-чата нет строк расхода → `image_usage` отсутствует, расход 0 отображается правдиво; глобальный бюджет (used=4/limit=200, source=env) виден; настройки владельца не менялись (0 записей).

## 5. Решения для леджера (точно)
- **cfg-карта:** `deployed_commit := d59fab94…` (сейчас `c37b8577`); `candidate_commit` не менять (`83ecd202`).
- **6 live-строк CFG-02A:** закрываемы по сделанным постам — **02A.1** (видимость и фактическое значение: маркеры отданных байтов + `limits.image_daily_limit`=60, source='' (global), DM наследует 60 + e2e на байт-идентичном webroot) и **02A.2** (реквизиты витрины: маркеры+e2e; оговорка f3 — принять как зафиксировано: расход DM=0 без строк). Остаются postdeploy (агентские, НЕ владельческие): **02A.3** (живой override/сброс/невалидный ввод), **02A.4** (реальное влияние правки без рестарта на разрешение/отказ генерации), **02A.5** (отказ при квоте до платного вызова), **CFG-02.AC1** (правка + переживание перезагрузки/рестарта + реальное влияние).
- **Speech:** добавить production-эвиденс-запись к **SOUL-AMD.6.3** (L00105; статус не менять): ref — `review-speech-mobile.md` §5.1 (RED/GREEN фикса, кандидат `720be161`) + `evidence/release-25889/post-prod-bytes-entry-e2e.json` (прод `d59fab94`: дверь видима 155/134, клик → `#/ai/speech`, 3 карточки). Внутри-Telegram взгляд — необязательная наблюдаемость, не гейт.
- **soul-карты:** `deployed_commit` не трогать (своя линия) — только указанная evidence-запись.

## Замечания (не блокирующие)
1. Отчёт §1: «SOUL-набор … (5 файлов)», фактически намеренных дельт **6** (`soul-byte-equal.txt`: image_generation, tool_router, worker_budget, app.js, index.html, app.css; `SOUL_FILES_WITH_DIFF`). Фактическая сторона полна; при следующем docs-проходе поправить число.

## Вердикт
**Approved.** Изоляция (43=12+31, все 12 payload byte-exact кандидатам), preflight (6 собственных перепрогонов совпали), живые байты (healthz/served/tree) и постдеплой-факты подтверждены; девиации приемлемы и документированы; блокирующих находок нет.
