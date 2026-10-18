# Релиз **2.58.90** — P0-хотфиксы (инициатива + ностальгия + сохранение SOUL-1 + UX «Речь и характер»)

Дата сборки кандидата: 2026-10-19 (UTC — по логам прогонов ниже).
Кандидат: **master-линия** (HEAD `01e1cc8d` + bump `2.58.90`); прод до релиза —
`2.58.89 @ d59fab94` (`release/fix-2.58.89`).
Статус: **собран и проверен локально**; деплой и приёмка — отдельный шаг (§4).

## 1. Состав (что вошло)

| Линия | Коммиты | Что это по-человечески |
|---|---|---|
| Ностальгия (P0B-NOST) | `ae9af516` | Бот снова умеет вспоминать прошлое **в живой беседе** (сценарий A — без требования 45 минут тишины), после затишья работает сценарий B с прежними паузами/защитой от навязчивости; джоб регистрируется всегда (OFF = честный no-op), дедуп и канон SOUL-1 Core сохранены. |
| Инициатива (P0A-INIT) | `f0bd29e2` + `3e044c8a` + `2af51eb6` | Наблюдатель стартует от живого хвоста переписки (курсор к последним ~6 ч / ≥200 строк), а не читает архив с нуля; отвечает адресно (per-reply), анти-флуд разделён, честное состояние «нет активного чата»; диагностика передаёт реальный контекст возможности (`build_opportunity_row`), а `scan_anchored` виден в событиях. |
| Сохранение (P0A-PERSIST) | `29a95173` | Корневой дефект «настройки не сохраняются»: chat-scope записи падали без пула PG (x10 мест), а ConfigCache врал (не читал PG). Теперь запись/чтение PG-first, честные 409/503 с человеческим текстом, работает по всем путям (Core meta/reset, humor/learning/inherited), значение реально доходит до зависимых механизмов. |
| UX (P0A-UX) | `01e1cc8d` | Раздел «Речь и характер» пересобран: иерархия (Характер → Манера речи → Правила письма → Дополнительно), компактная мобильная вёрстка, честное сохранение (dirty-рамка, «Не сохранено», sticky-кнопка, человеческие ошибки, черновик не теряется), защита от переноса правок чужому чату (cross-chat guard), техмусор убран из основного UI, метка «ностальгия» у нужного блока. |
| Леджеры/ревью (доки) | `2c916f35`, `d45194d4`, `72fa3323`, `4a4d3849`, `dea9e45b`, `5031ebf1`, `ebe10806`, `8cdddd57`, `3d97448e`, `3d0e3c7f`, `1ce011af`, `097e3653`, `57ff8c85` | Карты требований, леджеры P0A/P0B, ревью-записи (ностальгия/инициатива/минфикс/персист/UX), аудит-эвиденс. |

Ревью (по линиям, все Approved): `4a4d3849` (ностальгия, кандидат `ae9af516`),
`dea9e45b` (инициатива, `f0bd29e2`), `5031ebf1` (js-fix, `3e044c8a`),
`13729462` (минфикс диагностики, `2af51eb6`), `7356db49` (сохранение,
`29a95173`), `57ff8c85` (UX, `01e1cc8d`). Полный ревью-леджер P0A — `1ce011af`
(7V/6RFL), P0B-ностальгия — `72fa3323`.

## 2. Дельта к проду (изоляция)

База = прод `d59fab94` (2.58.89). После bump-коммита дельта (без `plans/`) =
**74 файла**:
- **44 файла P0-линий**: 18 код/UI (`services/` 13 + `web/` 5), 23 теста
  (включая новые контрактные/регрессионные), 2 инструмента
  (`tools/ui_soul1_w6_speech_e2e.py`, `tools/_p0_initfix_scope_ui_probe.py`),
  `AGENTS.md`;
- **30 файлов bump** (из 31 вне-плейн-файла): `config/settings.py`,
  `README.md`, 24 py-пина, 4 JS-пина; 31-й — `plans/docs/param-registry-
  round1025.meta.md` (APP_VERSION `2.58.90`, HEAD-штамп `01e1cc8d`);
- плюс `plans/**` (леджеры, evidence, карты — документация, не runtime);
- runtime-файлов, отличающихся от прода, ровно **19** (18 payload +
  `config/settings.py`) — деплой-скрипт это проверяет вайтлистом (любой чужой
  runtime-файл в дельте = abort).
Sanity-файлы (SOUL/CFG/Speech-мобильный слой) обязаны остаться байт-в-байт
прод-2.58.89: fullscreen-policy `96db06425079`, glass-refraction
`6a09d962d59d`, prompt_registry `a606bcafc1be`, image_generation
`db1d60cd4b54`, worker_budget `e18dab826da1`, tool_router `70840e163e17` —
сверено (дельта их не содержит).

## 3. Проверки кандидата (run-as-is, после бампа, до коммита)

| Проверка | Результат |
|---|---|
| Полный `pytest -q` (.venv) | **14240 passed / 9 failed** (628.7s; список — `evidence/release-25890/pytest-full.txt`) |
| js-sweep: `node tests/js/*_test.js` (87 файлов) | **87 файлов / 0 падений** (`evidence/release-25890/js-sweep.txt`) |
| `tests/ui_p0a_ux_speech_compact_e2e.py` | **failures=0, POST=21** (`ux-e2e-console.txt`, `ux-e2e.json`) |
| `tools/ui_soul1_w6_speech_e2e.py` | **failures=0, POST=16, shots=94** (`w6-console.txt`, `w6-ui-report.json`) |

Пояснения:
- **pytest, 9 падений** = 8 пре-существующих (`test_asap7_direct_settings` ×2,
  `test_t5150_*` migration-окна ×5, `test_mca01_tx_task_supervisor` ×1 — те же,
  что в `evidence/persist-fix/full-suite-post-fix.txt`) + 1 «новое по кейсу»:
  `test_mca09_intents_block_e_round1040.py::test_handle_initiative_sent_single_transport_chunks`.
  Оно **разобрано и атрибутировано**: пре-существующий вероятностный флейк
  **~5–6%** (зонд, N=100: база `8c88bbda` 5/100, HEAD 6/100 — тот же механизм
  `decision.intent_id=None`): draw mca-10b подменяет durable-intent кандидата
  form-кандидатом без intent_id, `mark_attempt` тогда не вызывается; тест и его
  ассерты P0-коммитами не менялись. Подробно — `evidence/release-25890/
  flake-attribution.txt`. Не блокер релиза; follow-up — пин draw в тесте.
  Историческое падение `test_mca12_stories_round1046::test_js_ui_suite` в этом
  прогоне **зелёное** (закрыто `3e044c8a`).
- **UX e2e**: сценарии §2/§4/§5/§6.4 (витрина 4 группы/10 карточек, компакт
  320–412, dirty/save, 409/503 честно, изоляция чатов) на реальных
  `web/index.html` + `app.js` + `app.css`; вывод — `evidence/release-25890/`.
- **W6**: полный SOUL-1 e2e «Речи и характера» (7 вьюпортов + интеракции на
  390/1440); запуск через обёртку (`w6_run.py`, scratch) со своим каталогом
  вывода — чужая evidence-зона soul-1 не затрагивалась (`git status` чист по
  `plans/features/soul-1/**`).

## 4. Чек-лист пост-деплойной приёмки (§4)

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; read-only-дисциплина fail2ban:
один recon + один основной коннект, без ретраев; HTTP — через
`https://admin-bot.duckdns.org/healthz`.

**(a) healthz+версия.** `healthz` = `2.58.90` (loopback и HTTPS),
`NRestarts=0`, `MAINPID` сменился, журнал since T0: ERR=0 (и
RuntimeWarning/«never awaited» = 0), миграции `complete`, `user_version` без
изменений (Δ DDL=0).

**(b) real-DB цикл по 10 шагам** (по каждому типу настроек: Core meta,
Style/Expression, блоки): реальная БД → открыть → изменить → сохранить
(реальный POST) → реальный ответ API → reread из хранилища (ревизия/
effective) → перезагрузка MiniApp → значение осталось → effective в
runtime (наблюдение конечных LLM payload Direct/Initiative/Factcheck/Summary
без рестарта) → вернуть исходное → **изоляция чатов** (второй чат не
затронут) → restore. Текст ошибок при инъекции (409/503) — человеческий,
ввод не теряется.

**(c) nostalgia live.** Журнал: `[nostalgia] scenario=A (живая беседа) |
chat=-1002661910336` (тик ≤60 мин + jitter после рестарта), следующая строка
воронки (`sent kind=year_back|golden` либо честная причина), новая строка
`nostalgia_log` по чату, `mca_events nostalgia_run` start+success; per-chat
`gates[nostalgia]=true` для `-1004482340693` (конфиг при релизе, PET — без
канареек) + тот же прогон воронки по второму чату. Принудительных
бессмысленных публикаций нет.

**(d) initiative live.** `scan_anchored≥1` / `stage=anchored` в событиях
наблюдателя, writer/recheck/sent-события (или честный `reason_code` стадии)
в воронке, снижение cursor lag; `/api/status` для выбранного чата отдаёт
данные (не `restricted`), global-вид — честное «чат не выбран»; read-only.

**(e) smoke ключевых маршрутов.** `/healthz`, `/web/`, `/static/app.css` —
200; отданные `app.js`/`app.css` байт-в-байт совпадают с диском
(`SERVED_EQ_APP_JS=SAME`, `SERVED_EQ_APP_CSS=SAME`); **PAGE_VER=15** — это
число СТРОК отданного `/web/` с версией (все подстановки `?v=2.58.90`: 3
CSS-link + 12 script src; НЕ «версия 2.58.90»), **SUBST_CSS=2** — число строк
отданного `/static/app.css` с версией (`@font-face`-url шрифта + строка-
комментарий про cache-bust); оси `.env` не тронуты; регрессионные маркеры
CFG-01/CFG-02A/speech-mobile живы.

## 5. Откат

**Штатный рубеж отката: `release/cfg1-2.58.88` (`c37b8577`, 2.58.88; tip
ветки `35789982` = этот bump-коммит + docs-коммит отчёта — runtime 2.58.88
идентичен)** — `git checkout release/cfg1-2.58.88` (checkout идёт по ветке,
не по коммиту) + graceful-рестарт (оси/данные не трогаются); в деплой-скрипте
это авто-путь при неполучении healthz 2.58.90 / пустом T0 (abort ПОСЛЕ
рестарта). Abort ДО рестарта (whitelist/дельта/хеши) отката не ждёт:
`_tree_restore` возвращает дерево к прод-линии 2.58.89
(`release/fix-2.58.89`/`d59fab94`, без рестарта) — downgrade на 2.58.88 в
этом пути исключён.
Прод-линия до релиза — `release/fix-2.58.89` (`d59fab94`, 2.58.89): остаётся
доступным более близким шагом, если проблема локализуется именно P0-дельтой
(решение за оркестратором). Ручные kill-switch-двери линий (P0) отсутствуют:
P0 — хотфиксы поведения, откат = возврат кода.

## 6. Риски/остатки (честно)

1. **`set_many` без пула** — при отсутствии PG-пула пишет только в память
   (silent); в web-путях гейтится `pg_available`, но это кандидат в
   следующий P0-пункт (вне мандата этого фикса; `persist-fix/report.md` §8).
2. **Провенанс до значения** — `prompt_factory._write_chat_speech_value`
   пишет провенанс ДО записи значения (аудит §8.6, низкая важность; не
   менялось).
3. **A/B-helper воркера** — формула сценария A/B продублирована в
   `web/api/memory_agi.py` (стоп-условие лейна, связка закреплена тестом);
   консолидация в общий helper — отдельная малая задача.
4. **Дрейф W6-fixture** — `plans/features/soul-1/evidence/w6/api-fixture.json`
   не содержит части новых метаданных (`examples.starter/telemetry/ab`);
   шаблон сделан устойчивым к отсутствующим полям, сам fixture — чужая зона
   (не правился).
5. **Видео (AMD.8.11)** — остаётся `not_configured`
   (`media_source_unconfigured`/`cobalt_absent`): сценарий без
   медиа-источника невоспроизводим (принятый остаток, не дефект релиза).
6. Прочее пре-существующее: W6-glass `lens_edge_*` FAIL,
   `test_t5150`-класс migration-окна, `test_asap7_direct_settings` ×2 —
   чужие зоны, воспроизведены на базе.

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\
  release-25890\deploy_25890.py` — T0-hardened (fail-fast, PID-анкер,
  один основной SSH-коннект, без ретраев, креды из `deploy_commands.txt`,
  вычищаются из вывода): A pre-state → B fetch origin/master (BUMP-ancestor
  gate) → C checkout + runtime-whitelist дельты → D sha256_12 (30 артефактов)
  + маркеры → F restart + T0 + healthz 2.58.90 + журнал → G served-bytes →
  J `rel90_final.sh` (read-only, с smoke маршрутов и регрессионными
  маркерами). Авто-откат ПОСЛЕ рестарта: `release/cfg1-2.58.88`;
abort до рестарта (whitelist/дельта/хеши) → `_tree_restore` к прод-линии
2.58.89 (`release/fix-2.58.89`/`d59fab94`, без рестарта).
- Ревью-биндинги (REV-REL-RECHECK, `review-release-25890.md`):
  `deploy_25890.py` sha256_12 `2d47290eeeb0`; `rel90_final.sh` sha256_12
  `c4e74d87e477`; abort-path симуляция 22/22 (`sim/logs/abort-path-table.txt`).
- Предусловие запуска: `master` запушен в origin с bump-коммитом 2.58.90
  (B3 fail-closed, иначе прод не трогается).
- `rel90_final.sh` — read-only пост-верификация (в том же каталоге).

## 8. Кандидат-фингерпринт

- HEAD (payload): `01e1cc8d6ad479edf907e103f9594f1e55285657` (P0A-UX).
- Bump-коммит: `f2cd3a71` (2.58.90) — дерево кандидата заморожено этим коммитом.
- sha256_12 runtime-артефактов — в `deploy_25890.py::EXPECT12` и в
  `evidence/release-25890/frozen-fingerprint.txt`.
