# REL-2.58.155 — учёт релиза пакета версионирования промптов (PM)

Дата учёта: 04.11.2026 (UTC). Роль: PM — привязка требований и доказательств, не проверка сервера.

**Источник серверных фактов:** отчёт DevOps `plans/features/evol/release-258155-deploy.md`
(на момент учёта файл существует только как untracked в основном checkout
`C:\Code\Python\adminbot`; в ветке `release/2.58.155` и в `evol/impl` его нет).
PM прод не опрашивал: политика AGENTS.md (fail2ban) не разрешает лишние коннекты, а в этой
задаче они не требовались. Поэтому всё, что ниже в §1 и §3, — **дословная сводка фактов DevOps**,
а §2 — локальная git-проверка тождества содержимого (её PM выполнил сам).

## 1. Релиз и состояние сервера

| Параметр | Значение |
|---|---|
| Выложенный коммит | `f4a44167fa42fc0f23d681a76554246754172830`, ветка `release/2.58.155` (из `origin`) |
| База прода до релиза | `2de11dc0c3a836b44e047484a80ddb0425891ad0` (2.58.154) |
| Версия | `APP_VERSION = "2.58.155"` |
| Окно | 04.11.2026 06:50:22–06:50:43 UTC, рестарт `systemctl restart admin_bot`, MainPID 1867207 |
| `/healthz` | 200 loopback, 200 по SNI, 200 публично, `version=2.58.155` |
| Перезапуски/процессы | `NRestarts=0`, один процесс в cgroup |
| Схема | `PRAGMA user_version=41` — без изменений; DDL в релизе нет |
| Медиа | 66 файлов, без изменений |
| Журнал (210 строк) | 0 `Traceback`, 0 `CRITICAL`, 0 `ERROR`, 0 `database is locked`, **0 `activation_drift`** (на старте 2.58.154 их было 4), 0 ошибок записи промптов; только INFO (`pre_versioning capture`, `release applied`, `VisionMediaWorker._tick`) |
| Откат | `git checkout -B release/2.58.154 2de11dc0 + systemctl restart admin_bot`; DDL нет, журнал и тексты промптов сохраняются |

## 2. Тождество содержимого (проверено PM по git, локально)

Сравнение выложенного дерева `f4a44167` с одобренными кандидатами:

| Файл | Одобренный кандидат | `f4a44167` | Итог |
|---|---|---|---|
| `services/prompt_release_policy.py` | `87993f9d3f` (`254f5242`) | `87993f9d3f` | идентичен |
| `services/prompt_factory.py` | `610098414e` (`254f5242`) | `610098414e` | идентичен |
| `web/api/routes.py` | `dc8a3a6318` (`254f5242`) | `dc8a3a6318` | идентичен |
| `web/api/speech.py` | `8cdf1ce3de` (`254f5242`) | `8cdf1ce3de` | идентичен |
| `services/prompt_registry.py` | `dbf0b937b2` (`40cf25ea`) | `dbf0b937b2` | идентичен |
| `tests/test_prompt_field_audit.py` | `cfa4252acf` (`40cf25ea`) | `cfa4252acf` | идентичен |
| `tests/test_prompt_history_pagination.py` | `5886afcde5` | `5886afcde5` | идентичен |
| `tests/test_prompt_baseline.py` | `ea6fa6ad2d` | `ea6fa6ad2d` | идентичен |
| `AGENTS.md` (правило «Блокер релиза») | `f70ed268ea` (`40cf25ea`) | `f70ed268ea` | идентичен |
| `web/index.html` | `4c648efb03c4` (`217cde65`, S4 Approved) | `4c648efb03c4` | идентичен |
| `web/app.js` | `22267af731f5` (`217cde65`) | `22267af731f5` | идентичен |
| `web/static/app.css` | `17bfa2aa0cc7` (`217cde65`) | `98e96f1be61c` | **отличается**: пост-ревью правка z-index (`--z-panel: 90` вместо литерала 90; `.pv-result--sticky` 3 → 2). Независимого ревью этой правки в репозитории нет; в `evol/impl` этой правки тоже нет (`app.css` = `17bfa2aa0c`) |
| `docs/prompt-versioning-contract.md` | `a013ab10dd` (`40cf25ea`) | `0b87aa7c74` | отличается на 2 строки: документ сам фиксирует, что в 2.58.155 под аудитом 293 файла, а не 294 (новый `services/anticliche_sources.py` из пакета AC-DATA в этот релиз не входит; 72/71/0 не меняются). Та же поправка — в пине `test_evol018_prompt_audit.py` (`3e45910d86` против `23cb75c1cc`) |
| `docs/../README.md` | — | — | 1 строка (ссылка на правило) |

Замечание о байтах UI: DevOps снял на сервере `sha256sum` для `/web/index.html` = `4c648efb…` и
`/web/app.js` = `22267af7…` — они совпадают с одобренным кандидатом S4. Для `app.css` серверная
сумма в отчёте не снималась, поэтому «прод отдаёт именно эти байты CSS» не подтверждено.

## 3. Живые доказательства версионирования (read-only, initData владельца)

- `GET /api/prompts/catalog` → 200, `count=112`; `initiative.meme.joke → fac:2f30ca1f9a6b`, `initiative.meme.image → fac:f81fe7e4b505` — совпадает с байтовым эталоном.
- `GET /api/prompts/initiative.meme.joke/versions` (global) → 200, `entries=4` (2 ревизии + 2 активации), `page.has_more=false`, курсора нет, `journal_available=true`; в БД ровно 2+2.
- Пагинация: `page_size=2` → 2 страницы, 4 записи, **0 дублей**, `next_cursor` отдан на первой странице и отсутствует на последней; `total`/`page.size` не отдаются — контракт §3.4 `total_known=null`.
- Объём журнала в БД: **171 ревизия / 102 блока / 166 активаций**, максимум **10 ревизий на блок**. Ветка «>50 ревизий на блок» **NOT OBSERVED** (естественных данных такого объёма нет).
- `GET /api/prompts/initiative.meme.joke/baseline` → 200, `source="factory"`, `baseline=null`, `cleared_at=null`, `journal_available=true`, `capabilities={assign:true, clear:false, restore_baseline:false, restore_factory:true}`; событий `baseline%` в `prompt_activations` — **0**. Миграция baseline никому не назначила.
- Захват до включения версионирования: в 06:50:45 `pre_versioning capture | values=2` → `legacy_import` для `initiative.meme.joke` (чат 1, `rev:f501a080291c`, `539ceb6970ea`, 1357) и `summary.cover.style_id` (чат 1, `rev:ac2c44f1bd1f`, `cdd0c0d252d0`, 12), `outcome=recorded`, `detail=pre_versioning_import`. Историческая дата правки не подставлялась.
- Применение релиза: `release applied | release=evol-016-cutover | blocks=110 | changed=0 | retired=0` — **ни один текст не перезаписан**.
- Байты промптов до/после совпадают: `prompts.meme_joke` `2f30ca1f9a6b` (95 байт / 51 симв.), `prompts.meme_image` `f81fe7e4b505` (51 байт / 28 симв.), `prompts.meme_summary` отсутствует; чатовые override: `-1002661910336` joke `539ceb6970ea`/1357, image `11cf82f45c3a`/566; `-1004482340693` joke `4bc3425f2f3d`/261, image `11388ab3a936`/372.
- Одна правка текста в чате 1 была сделана **самим владельцем** в 04:47:01 UTC (до релиза): прежние байты `71303ff62029`/1363 сохранены ревизией `rev:99b88b0b89d7` с `reason=drift_recovery`. К агентам отношения не имеет.
- UI: `/web/index.html` 200 — 18 вхождений `prompt-version-card`, шаблон `#prompt-version-card-tpl`, `pv-grid`; `/web/app.js` 200 — 4 вхождения и обработка `next_cursor`. Playwright: заголовок «AdminBot — админка», Vue отрисован, 0 ошибок JS, панели в DOM.

## 4. Что живо НЕ доказано (честная граница)

1. Запись **новых** ревизий через каждый специализированный endpoint на живой БД: никто не писал в живые промпты — **NOT OBSERVED**.
2. История «>50 ревизий на блок» на проде — **NOT OBSERVED** (максимум 10).
3. Заводская поставка при **pinned** scope в проде — не запускалась.
4. Реальный Telegram WebView на устройстве владельца — не проверялся.
5. Серверная сумма `web/static/app.css` не снималась; на проде CSS содержит правку z-index без ревью (см. §2).

## 5. Находки этого учёта

1. **Метка «действует» в чатовой истории вводит в заблуждение.** История чата показывает заводской
   указатель (`fac:2f30ca1f9a6b`) как «активный», хотя фактически в чате действует текст владельца
   (override). Это документированное поведение контракта §3.2 (источник статуса — PG-значение, а не
   действующая ревизия самого журнала), и на этом старте `activation_drift` = 0, но формулировка в UI
   читается как «действует заводская версия». Владелец: follow-up среза PVR-S4 (UI-формулировка).
2. **Правка `web/static/app.css` вне одобренного кандидата.** `f4a44167` меняет z-index панели
   (`--z-panel: 90`, sticky 3 → 2) уже после S4 Approved; отдельного ревью-вердикта на эту правку нет,
   и в `evol/impl` её нет. Нужен либо узкий ревью-чек этой правки, либо осознанное принятие.
3. **Ветка релиза не влита в `evol/impl`.** `f4a44167` не является предком `04f77c74` и наоборот
   (общая база — `e52a06b2`); пакет набран черри-пиками поверх `2de11dc0`. Содержимое PV-слоя совпадает,
   но `app.css`, `docs/prompt-versioning-contract.md` и `tests/test_evol018_prompt_audit.py` на ветке
   релиза отличаются от `evol/impl`. Пока релиз не «впитан» (как делали для 2.58.152/153/154), следующая
   интеграция снова покажет эти файлы как дельту.
4. **Проверочные скрипты пишут в отслеживаемые файлы evidence.** `evidence/pvr-s1/capture_prompt_bytes.py`
   и мутационные пробы перезаписывают отслеживаемые `evidence/**` файлы; прогон на другом HEAD молча
   меняет зафиксированные байтовые снимки. Уже привело к расхождению `prompt-bytes-baseline.json`
   с текущим `direct.base.l2_writer` (`68f0233d` → `44736968`, отмечено в S5 Re-review 2, п.2).
