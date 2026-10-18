# Мини-релиз **2.58.89** — REL-25889 (CFG-02A B1 + «Речь и характер» на мобильном)

Дата: 2026-10-18 (UTC: деплой 07:36–07:38). Ветка `release/fix-2.58.89`.
Статус: **задеплоен и живьём подтверждён** (healthz `2.58.89`, `NRestarts=0`);
live-строки карт не закрывались (леджер — отдельный проход).

## 1. Состав (изоляция)

| Роль | Значение |
|---|---|
| База (прод до релиза) | `c37b85779cc41ad716304024ebeea86ad4081071` = **2.58.88**, оси ON |
| Порт-коммит (12 файлов) | `119b1f7d…` — `git checkout` отревьюенных кандидатов |
| Bump-коммит (31 файл) | `d59fab94…` — **деплой-тип** (origin HEAD) |
| Артефакты (этот коммит) | отчёт + `evidence/release-25889/**` |
| Delta vs прод | **43 файла** = 12 payload + 31 bump (settings/README/F8-meta/24 py-пина/4 JS-пина) |
| UNCLASSIFIED | **0** (`isolation-classification.txt`) |
| Кандидаты | `83ecd202` (CFG-02A+B1, ревью R4 «биндинг подтверждён целиком»); `720be161` (speech, `bf6208f5`) — файлы == кандидатам byte-exact (`equivalence.txt`) |
| WG byte-equal | fullscreen-policy/glass-refraction/glass-probe/refraction-тесты/e2e — **байт-в-байт** |
| SOUL-набор | byte-equal проду, кроме намеренных дельт релиза (5 файлов) |

sha256_12 деплой-файлов (сверены локально и на проде, 25/25): app.js
`2757a25d663d` · index.html `f79f9ad58457` · app.css `d6b848cdecd0` ·
image_generation `db1d60cd4b54` · worker_budget `e18dab826da1` · tool_router
`70840e163e17` · settings `a6a2d1a8408b`; CFG-01-файлы byte-equal проду.

Предпосылка порта (проверено): прод == базе CFG-02A/speech (`2bc13f44`) по
каждому порт-пути; эти пути меняли только `669debfa` → `83ecd202` (B1) →
`720be161` — чужих хунков нет; `tests/test_webapp_js_unit.py` из брифа —
прод-идентичен (checkout no-op, зафиксировано в `equivalence.txt`).

## 2. Preflight (точное дерево ветки, логи в `evidence/release-25889/preflight/`)

| Проверка | Результат |
|---|---|
| `test_cfg02a_image_quota_ui.py` | **27 passed** |
| `test_speech_mobile_entry_contract.py` | **6 passed** |
| `test_webapp_js_unit.py` | **38 passed** |
| `test_soul1_capability_fallbacks.py` | **41 passed** |
| `node tests/js/round1024_image_module_test.js` | **IMAGE-MODULE-OK** |
| CFG-01 набор (3 файла) | **204 passed** |
| `test_soul1_*.py` (30 файлов) | **600 passed** |
| parity | **13 passed** |
| registry `--check` | **575 == REGISTRY** |
| frozen-check | **RESULT OK** |
| node guards | **87/87** |
| `ui_speech_mobile_entry_e2e.py` | **failures=0** |
| `ui_cfg02a_image_quota_e2e.py` | **RESULT: PASS** (6 скринов == кандидату byte-exact) |
| refraction / shell / fs e2e | **37 проверок OK** / **W2-SHELL-E2E-OK** / **12/12 PASS** |

## 3. Деплой (1 recon + 1 main SSH-коннект; `recon89.txt`, `deploy-run.txt`)

- A: прод до = `c37b8577` / `release/cfg1-2.58.88` / healthz 2.58.88 /
  `TRACKED_MOD=0` / `MAINPID=3275019` / `.env` оси 5/5.
- B/C: fetch+checkout `release/fix-2.58.89`; `NEW_HEAD=d59fab94…`;
  `TRACKED_MOD_AFTER=0`; `DELTA_FILES=43`.
- D: **25/25 sha256_12 == кандидатам**; маркеры: `APP_VERSION = "2.58.89"`,
  CFG-02A (`image_reserve_mode`=2, `image_quota_reset_note`=2,
  `data-image-quota-facts`=2, `imageQuotaFacts`=1, `imageQuotaValueValid`=2),
  speech (`data-speech-hub-entry`=1, `hubSpeechEntry`=1), CFG-01
  (`resolve_direct_chat_limits`=2), F8-meta HEAD `119b1f7d`.
- F: graceful-рестарт; T0-анкер `2026-10-18 07:37:01` (fail-fast, непустой);
  PID-анкер: новый `MAINPID=3359708`, `migrations: complete | user_version=36 |
  pending=[]`; **healthz 2.58.89** (loopback + HTTPS); журнал since T0:
  **ERR=0**, RUNTIMEWARN=0, GRACEFUL=2, POLLER=1; `NRestarts=0`.
- J: served app.js/app.css sha12 == диску; `PAGE_VER=15`; `SUBST_CSS=2`;
  `USER_VERSION (36,)`; оси `.env` 5/5; HTTPS `/web/` 200.

## 4. Живые пост-проверки (read-only; `post-check.txt`, `final-verification.txt`)

**(а) Версия/ресурсы:** `/web/` содержит 2.58.89 ×15 (raw `__APP_VERSION__` не
протёк); сервер отдаёт app.js `2757a25d663d`, app.css `d6b848cdecd0`; маршрут
подстановки `/static/app.css` → 2.58.89 ×2.

**(б) «Речь и характер» на мобильном:** в отданной странице
`data-speech-hub-entry` ×1, «Речь и характер» ×6; в app.js `hubSpeechEntry` и
маршрут `#/ai/speech` ×7. Интерактив: e2e-контракт запущен на **прод-байтах**
(webroot из live HTTPS, byte-identical) → **failures=0** на 320/390/1280; вход
видим (h=155@320 / h=134@390), клик → `#/ai/speech`, экран «Речь и характер» с
3 карточками разделов; навигация не переделана (5 карточек хаба, вторая дверь
в persona жива). Скриншоты реального Chrome — в evidence. Живой origin вне
Telegram открывает auth-гейт (initData), хаб не рендерится — интерактивная
проверка **внутри Telegram = owner-check** (не дефект релиза).

**(в) Витрина «Лимиты генерации»:** секция/подписи/поля фактов в отданной
странице и app.js (см. §3-D); `GET /api/config` → `limits.image_daily_limit` =
**60** (глобальное значение владельца, источник пуст = не chat-override),
DM-чат наследует 60. Настройки владельца не менялись (0 записей).

**(г) Оси SOUL:** gates **10/10 ON** (`/api/speech/overview`); `.env` 5/5 оси
не тронуты.

**(д) Журнал/миграции:** ERR=0, RUNTIMEWARN=0; миграции complete,
user_version=36 (Δ DDL=0).

**(е) CFG-01 не сломан (read-only):** global burst = **10**, cooldown
= **300.0**; DM-чат наследует 10/300; CFG-01-маркеры в деплой-байтах; набор
CFG-01 204 passed.

**Биндинг байтов:** `prod-payload-bytes.txt` — `/web/app.js`,
`/web/static/app.css`, `/web/` (с подстановкой) на живом HTTPS **байт-в-байт**
совпадают с деревом релиза.

## 5. Rollback

`release/cfg1-2.58.88` + graceful-рестарт (оси не трогаются); авто-откат в
скрипте не потребовался — healthz 2.58.89 получен с первого рестарта.
Путь R1–R3 остаётся штатным (не исполнялся).

## 6. Девиации (честно)

1. **Доп. файл к списку брифа:** включён `tools/ui_cfg02a_image_quota_e2e.py`
   (add-only инструмент из отревьюенного кандидата) — без него предписанный
   preflight `ui_cfg02a_image_quota_e2e.py` невоспроизводим из ветки; на
   рантайм не влияет, классифицирован как `cfg-02a-payload`.
   `tests/test_webapp_js_unit.py` из списка — no-op (прод-идентичен).
2. **F8-meta HEAD:** bump-скрипт сначала ждал в мете `c37b8577`; фактически там
   `e25163b7` (поле хранит payload-коммит прошлого релиза) — исправлено
   точечно на `119b1f7d`, проверено (`META_HEAD_LINE`).
3. **f3 (информационная, из 18 пост-проверок):** `GET /api/workers/budget` не
   содержит записи DM-чата (нет строк расхода за сегодня) → `image_usage`
   отсутствует; расход чата = 0 — не дефект, витрина берёт значение
   «расход 0» и не лжёт.
4. **Локальные прогоны e2e переписали default-скриншоты** в дереве ветки
   (shell-e2e, cfg-02a) — восстановлено до committed-состояния; скрины CFG-02A
   при этом байт-идентичны кандидату (детерминизм, `preflight-cfg02a-e2e-shots-sha.txt`).
5. Ветка несёт только код+тесты+evidence (как 2.58.87/2.58.88); карты
   (`plans/features/**` вне evidence) не трогались — леджер/`deployed_commit`
   отдельным проходом.

## 7. Остаток

* Интерактивные проверки **внутри Telegram**: дверь «Речь и характер»,
  витрина/управление квотой (реальная генерация) — owner-шаг.
* 6 live-строк CFG-02A (`READY_FOR_LIVE`, postdeploy) — закрывает леджер.
