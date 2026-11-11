# Deploy 2.58.191 — инициатива/мемы: интерфейс исправления (пять осей, идентичность попытки, обзор)

Адресат: **production** (192.255.209.205, `/var/www/admin_bot`).
Причина выкладки: два независимо одобренных кандидата — корректива интерфейса
инициативы/мемов (`init/meme-axes`, head `726736ee`) и уточнение области
ремонтного инструмента (`fix/memory-grounds-provenance`, `10ab50b5`).
Схема БД не меняется (v47), новых флагов/настроек нет.

## 1. Привязка кандидата

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.191` = `a6884ad7fa7b74841dd7a908be3b3bed405dc844` |
| База релиза | `7c3c01b2` (2.58.190) |
| Кандидат 1 | `init/meme-axes` head `726736ee` (база `c087253d`, 2.58.188) — 6 коммитов |
| Кандидат 2 | `fix/memory-grounds-provenance` head `10ab50b5` (tool-only) |
| Релизный коммит | `a6884ad7` = черри-пики кандидатов + бамп версии (30 файлов, 31/31) |
| Предыдущий прод | 2.58.190 @ `7c3c01b2` |
| MUTABLE_WORKTREE_REQUIRED | **no** — иммutабельный checkout по SHA, `git status` на сервере чист |
| Repo write scope выкладки | `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 24 py-пина + 4 js-пина |

Черри-пики (в порядке применения): `400021cc`, `2d0dc10a`, `4c59a483`,
`d58fbb56`, `d55abf0d`, `726736ee`, затем `10ab50b5`. Конфликтов не было,
`git` выполнил авто-слияние в `web/app.js` и `web/index.html`.

**Аддитивность слияния доказана дважды:**

1. Построчно: все `+`-строки диапазона `c087253d..7c3c01b2` (2.58.186–190) и
   `c087253d..726736ee` присутствуют в `HEAD` — потерь 0 (`web/app.js` 344/1145,
   `web/index.html` 25/213, сервисы 0/298+1059+64+8+72+59).
2. Патч-идентичность: тело патча `726736ee → a6884ad7` для `web/app.js` и
   `web/index.html` **побайтово равно** телу патча `c087253d → 7c3c01b2`
   (358 и 42 строки, sha256 тел `6d6939c60d124ef4` и `3a2ea392f46894b0`).
   То есть релизные `app.js`/`index.html` = одобренный кандидат + ровно дельта 2.58.186–190.

**Состав дельты `7c3c01b2..a6884ad7` (54 файла):**

| Источник | Файлы |
|---|---|
| `init/meme-axes` | `services/initiative_diagnostics.py`, `services/initiative_observer.py`, `services/meme_initiative.py`, `services/publication_coordination.py`, `web/api/initiative_publications.py`, `web/app.js`, `web/index.html`, `web/static/app.css`, `tests/js/initiative_ui_rework_test.js`, `tests/ui_initiative_rework_e2e.py`, `tests/test_evol014_meme_initiative.py`, `tests/test_meme_init_diagnostics.py`, `tests/test_initiative_publications_api.py`, `plans/features/p0-init-meme-ux-diag/evidence/S3-OV/*` (8) |
| `fix/memory-grounds-provenance` | `tools/mca_lesson_grounds_repair.py`, `services/mca_experience.py`, `tests/test_evidence_grounds_persistence.py` |
| бамп версии | 30 пинов (`config/settings.py`, meta, 24 py + 4 js) |

Других файлов в дельте нет (0 неожиданных). Байт-в-байт с `7c3c01b2`:
`services/permissions.py`, `web/api/avatars.py`, `web/api/deps.py`,
`web/api/routes.py`, `services/direct_chat_service.py`,
`tests/fixtures/round1025/f8_baseline.json`.

DDL/миграций/схемных файлов в дельте нет; `services/database.py` не менялся;
новых `os.getenv`/`os.environ`/настроек не добавлено; `config/settings.py`
изменён ровно на одну строку версии.

`routes.py` не менялся → дайджест F11 **не** переутверждается:
`ROUTES_SHA256_F11` old = new = `4c7af646daa19023e8c3e1b6b8a2d414bf7af2b6d7ed90934ea267a543e877bb`
(файл байт-в-байт равен 2.58.190).

## 2. Преддеплойная валидация (на релизном worktree `a6884ad7`)

| Проверка | Результат |
|---|---|
| `tests/test_evidence_grounds_persistence.py` | **26 passed** |
| initiative/meme (16 файлов, `*initiative*`/`*meme*`) | **368 passed / 4 failed**; те же 4 падения, что и на базе `7c3c01b2` (**329 passed / 4 failed**) — все в `test_initiative_coordination.py` |
| JS-юниты инициативы/мемов | `INITIATIVE-UI-OK`, `MEME-UI-FIELDS-OK`, `SOUL1-W5-PANEL-OK`, `PIPELINE-INSPECTOR-OK` (exit 0) |
| JS-пины версии (hotfix 7/8/9/10) | 4/4 OK, exit 0 |
| inspector: step1/step2/step3_ui + step3 JS | **122 passed** (59/19/44) + `UR-F-STEP3-OK` |
| web/api (`tests/test_web*.py`, 68 файлов) | **1538 passed / 11 failed (1549)**; на базе `7c3c01b2` — тот же набор 11 падений, байт-в-байт |
| e2e-стенд `tests/ui_initiative_rework_e2e.py` | `failures=2` — те же 2, что на базе (снятие override → «источник не Исходный из кода») |

Классификация падений: все падения совпадают с базовой линией `7c3c01b2`
(проверено прогоном тех же наборов на отдельном checkout базы), новых нет.

## 3. Деплой

Один recon-прогон (assert до изменений) и один основной прогон по SSH-ключу
(root, port 22, без паролей и ретраев), по правилам AGENTS.md/fail2ban.

- `git fetch --prune origin` → `a6884ad7` есть; `origin/release/2.58.191` = `a6884ad7`.
- Снимок данных ДО выкладки: sqlite backup API → `/tmp/predeploy-258191.db`
  (**2 380 226 560 б**), read-back: `user_version 47`, `quick_check ok`,
  `smart_messages 2 078 982`, таблиц 130.
- `git checkout -B release/2.58.191 a6884ad7` → HEAD совпал, рабочее дерево чистое
  (кроме преднайденного `?? .cache/`).
- `systemctl restart admin_bot` в **2026-11-11T16:23:41Z**; healthz отдал
  `2.58.191` на первом же опросе.
- После рестарта: `ActiveState=active`, `SubState=running`, `NRestarts=0`.

## 4. Постдеплой (read-only)

- `HEAD` на сервере прочитан обратно: `a6884ad7fa7b74841dd7a908be3b3bed405dc844`.
- `GET /healthz` → `{"status":"ok","version":"2.58.191"}`.
- Журнал с момента рестарта: `TRACEBACK=0`, `CRITICAL=0`, `Unhandled=0`.
  Три строки ` ERROR `: два падения источника anticliche (wikipedia недоступна) и
  один `TelegramNetworkError: Request timeout` у aiogram — внешние условия, не
  относятся к дельте релиза.
- Один `Traceback` в журнале — `services/chat_params._load` (PG `fetchrow`),
  fail-open WARNING во время моего запроса. Код `chat_params` в релиз не входит
  (байт-в-байт с 2.58.190), пользовательского эффекта не было: ответ 200 с осями.
- Схема живой БД: `user_version 47`, `quick_check ok`, таблиц 130 — как до выкладки.
- Отданные ассеты: `/web/app.js` sha256 = `2d6938a6569a5715…` — **байт-в-байт**
  с релизным блобом; `/web/index.html` и `/static/app.css` отличаются от блобов
  ровно подстановкой `__APP_VERSION__` → `2.58.191` (проверено диффом, 71 и 12 строк,
  все — маркеры версии).

## 5. Настоящий пользовательский сценарий (данные прода)

`GET /api/initiative/mechanism-diagnostics` с подписанным TMA initData — по всем
трём чатам из `chat_profiles` (200, `schema_version=1`), плюс живой браузерный
проход по `#/modules/initiative` на отданной сборке.

Чат «Неистово супер крутые криэйторы гиперговна» (−1004482340693), «Обзор»:

| Ось | Текстовая инициатива | Мемы |
|---|---|---|
| Разрешено | **ВКЛ** — включено, глобальный выключатель | **ВКЛ** — включено, настройки мемов этого чата |
| Сейчас | может сработать сейчас — ничего не мешает | **ждёт: исчерпан суточный лимит (код: daily_quota_reached)** |
| Дальше | точное время не назначено — рассматривается на ближайшем проходе | не раньше 12.11 00:00 UTC (по сбросу суточного лимита) |
| Последняя попытка | 11.11 16:42 UTC · автоматически · пропущено · код: lease_held | 11.11 16:42 UTC · автоматически · пропущено |
| Последняя отправка | подтверждено · сообщение 10435 | подтверждено · сообщение 10472 |

Это и есть исходная жалоба: механизм **включён**, но не готов — рисуется
«ждёт: <причина>», а не «отключено». Второй чат «PERMsoc: кукярик»
(−1002661910336): текстовая — ВКЛ, «ждёт: мало сообщений»; мемы — ВКЛ,
«ждёт: кулдаун», последняя отправка подтверждена (1210056).

Сырые оси: `live-diagnostics-2.58.191.json`, кадр обзора:
`overview-chat-1280x950.png`.

## 6. Откат

`git checkout -B release/2.58.190 7c3c01b2 && systemctl restart admin_bot`.
Данные не откатываются: схема v47 не менялась, DDL=0, миграций нет;
снимок `/tmp/predeploy-258191.db` — только страховка.

## 7. Что осталось

Гейт `requirements_gate.py check --stage release` **не зелёный**:
`scoped S3-OV = 34 ошибки`, full = 152. Причина не в продукте:

1. строки S3-OV в карте стоят в `REVIEW` (одобрено, не `VERIFIED`) — поднимать
   их может только PM/Orchestrator после привязки постдеплойных доказательств;
2. `deployed_commit` в карте пуст;
3. строгая проверка требует доказательств, привязанных к `candidate_commit`
   карты (`726736ee`), а развёрнут `a6884ad7` — реконструированный кандидат;
   файлы корректива при этом совпадают побайтово (см. §1);
4. вне этого релиза остаются `P0IM-BAN-NOETA`, `P0IM-BAN-CONFLATE`, `P0IM-PB-*` —
   `PENDING` с названным остатком.

Дальнейший шаг — PM/Orchestrator: `deployed_commit = a6884ad7…`, привязка строк
S3-OV/S1-AXES/S2-ID к этим доказательствам, затем повторный прогон гейта.
