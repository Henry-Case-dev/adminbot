# F7 — Stories humanize: отчёт (ASAP 8, §14/§28.17)

Статус: implementation complete, не коммичено (ожидает Reviewer).
Базис: master `02b38cb` (2.58.76). Lane: F7 (только Stories; Random/Experience решены в F5).

## Дифф-фингерпринт кандидата

- diff SHA256 (git diff по 3 файлам): `91112ba635ed2337f1af391e6bf476235e96f3e7`
- файлы (sha256[:16]): `web/api/stories.py` 57adbbd10fa32104, `web/app.js` 0827a544effd8ed4, `web/index.html` bb098c56f7d443c8
- новый файл: `tests/test_asap8_f7_stories.py`
- объём: 271 insertions / 33 deletions по 3 файлам

## 1. Контракт display_names (web/api/stories.py, API-слой)

Серверный резолв — существующие механизмы, дублей нет:

- источник имён: `DatabaseService.get_active_participants(chat_id, now-30д, 200)`
  — тот же вызов/окно/cap, что `web/api/chat_lore.py::_participant_names` и
  `web/api/oversight.py::_feed_user_index_one`;
- поверх — `summary_aliases.build_alias_resolver(chat_id)` (AliasResolver,
  `limits.summary_aliases`, per-chat override → наследование);
- резолв: alias → author_name → честный fallback; `'@'` срезается самим
  AliasResolver; неразрешённый числовой участник → **«Участник N»** (не
  выдуманное имя); не-числовой участник (историческое канон-имя из LLM-пути
  mca-05) — наружу как есть, без чистки;
- форма: `display_names: [{id, name, ambiguous}]`, порядок = `participants`,
  `id` — служебное поле (фильтр/merge/split/Developer details), наружу в
  главном UI — только `name`;
- **неоднозначность**: два разных участника с одинаковым display name НЕ
  склеиваются — обе записи остаются, обе помечены `ambiguous: true`
  (casefold-сравнение), различие по `id` доступно под Developer details;
- fail-open: чтение имён/резолвер упало → `{}`/None → честный «Участник N»,
  ответ не роняется (прецедент oversight);
- обогащаются только `state == "ok"`-ответы: feed events (каждое событие) и
  card (`story.display_names` + каждый `episodes[].display_names`);
  disabled/unavailable/no_chat возвращаются как есть (честные состояния не
  маскируются);
- raw `participants` из ответов НЕ удалены (обратная совместимость + серверный
  фильтр `participant=` + Developer details); R17: message-контент и сырые
  логи по-прежнему не отдаются (TH-4 не тронут).

Таблица `/api/stories` (D6) display_names не получает — в WRITE_SCOPE
feed/card; таблица участников не показывает (проверено).

## 2. UI-структура (web/index.html + web/app.js)

Витрина «Статус» (`data-stories`):

- заголовок → «Истории памяти»; бейджи §14: **«Всего: N»**, **«Новых за
  24ч: N»** (+ muted «дополнено за 24ч», «ожидают проверки» — guard
  `counters` сохранён байт-в-байт, пин p0_stories_no_chat_render_test);
- новый блок `data-stories-explain` — человеческое объяснение §14 дословно
  («…объединённые в эпизоды…») + «Это не Telegram Stories и не Summary»;
- прогресс → человеческие метки: **«Последняя сборка:»**
  (`storiesBuildLabel`: не запускалась / успешно / с ошибкой / идёт · время),
  **«Backfill:»** (`storiesBackfillLabel`: не запускался / в очереди / идёт /
  на паузе / завершён / с ошибкой / отменён / прерван · «выполняется»);
- лента: «участники:» → `storiesParticipantsLabel(ev.display_names,
  ev.participants)` — имена; ambiguous → суффикс «(?)»; fallback на сырые
  participants только для старых ответов без display_names;
- карточка в ленте (`data-stories-card`): дата (период + обнаружена), суть,
  «Участники:», «Исходных сообщений: N|200+» (`storiesSourceCount` — счётчик
  оригинала, ≥200 честно «200+»), «бот: используется в поиске памяти /
  исключена из поиска — не используется» (`storiesUsageLabel` — retrieval-
  статус; фактов recall в модели нет (related_beliefs: direct_links_absent),
  поэтому «использовалась ли потом» показывается как доступность в поиске,
  без выдуманных счётчиков), проверка/состояние бейджами;
- **Developer details** (`<details data-stories-dev>`, collapsed) в обеих
  карточках: story_id, версия, участники (ID), эпизоды (ID)
  (`storiesEpisodeIds`), ключи исходных сообщений, источники утверждений
  (`storiesClaimRefs`), related_beliefs reason, redirect_target.

Управление «Память» (`data-story-card`):

- «Участники (ID):» → «Участники:» display names; raw-строка «Участники
  (ID)» осталась ровно в одном месте — внутри Developer details;
- добавлены «Исходных сообщений / бот» (те же хелперы);
- хронология эпизодов: + «участники:» display names на каждый эпизод;
- утверждения: raw-ключи refs `(источники: …)` убраны из главного вида →
  Developer details;
- split-чекбоксы: подпись `{{ title }} · {{ дата }}` вместо
  `episode_id.slice(0,8)…` (raw id остался только в `value` чекбокса —
  функциональное значение);
- версии `<details>` — без изменений (уже collapsed).

app.js: 7 новых чистых методов (storiesParticipantsLabel, storiesSourceCount,
storiesUsageLabel, storiesBuildLabel, storiesBackfillLabel, storiesEpisodeIds,
storiesClaimRefs) — без html-вставок (TH-3), внутри MCA-12 блока (структурный
JS-пин round1046 не нарушен).

## 3. Тесты

Новый `tests/test_asap8_f7_stories.py` — **9 passed** (TEST-LIFECYCLE:
CONTRACT owner=asap8/F7):

1. feed display_names: резолв из author_name, порядок=participants,
   {id,name,ambiguous}-форма, raw participants сохранены;
2. fallback «Участник N» (неизвестный ID) + неоднозначность (два ID, одно
   имя «Аня» → обе ambiguous, не склеены) — два чата;
3. alias-резолв (`build_alias_resolver` подмена) — алиас побеждает без
   author_name;
4. карточка: display_names на story и каждом эпизоде; не-числовой
   «Лёва» — passthrough;
5. fail-open чтения имён → «Участник N»;
6. HTTP: feed/card несут display_names (router-обвязка);
7. no_chat/disabled — без обогащения;
8. UI-пин: объяснение §14, витрина Всего/Новых за 24ч/Последняя
   сборка/Backfill, наличие всех 7 хелперов;
9. UI-пин §28.17: «участники: {{ ev.participants.join» удалён из ленты,
   «Участники (ID)» ровно 1 раз и внутри data-stories-dev, split без
   `episode_id.slice`, refs-ключи не в главном виде, ровно 2
   `data-stories-dev`, оба — `<details>` (collapsed).

Комбинированные прогоны (актуальные имена):

- `pytest tests/test_asap8_f7_stories.py tests/test_mca12_stories_round1046.py
  tests/test_mca05_episodes_stories_round1027.py tests/test_routes_helpers.py -q`
  → **104 passed**;
- смежные html/js-пины: `test_104_backend_additions + test_aliases_render +
  test_extra_cover_styles_ui + test_font_subset +
  test_frontend_tab_mapping` → **80 passed**;
- `node --check web/app.js` → OK;
- JS: `round1046_mca12_stories_ui_test.js` → MCA12-STORIES-UI-OK,
  `p0_stories_no_chat_render_test.js` → P0-STORIES-NO-CHAT-RENDER-OK;
  полный tests/js прогон: 3 падения (round1020_ui_test,
  round1020_ui_rework_test, round1024_budget_toggle_test — пины «состав
  меню») — **воспроизводятся на чистом HEAD `02b38cb` без моих изменений**
  (git stash-проверка): pre-existing от закоммиченных F5/F8, вне WRITE_SCOPE.

## 4. UI-верификация (два обязательных канала)

Харнесс: scratch-серверы (OpenCodeScratch/f7_ui_server*.py) + route-моки
/api/* с честными формами ответов (включая ambiguous и fallback-участника).
TMA-гейт — через sessionStorage initData (механизм getInitData app.js).

Playwright (детерминированный поток):

- desktop 1280×800: витрина (Всего: 3 / Новых за 24ч: 2 / Последняя сборка:
  успешно · 22.09, 02:13 / Backfill: на паузе), лента «участники: Аня,
  Борис», ambiguous «Аня (?), Аня (?)», fallback «Участник 333333», в
  витрине нет ни одного raw ID; карточка: Участники/Исходных сообщений:
  200+/бот-статус; Developer details collapsed by default, после раскрытия —
  story_id/участники (ID)/эпизоды (ID); manage-карточка: главный вид без raw
  IDs (idLabelCount=0 до раскрытия), split-лейблы «Эпизод А · 14.04.2025»
  без episode_id; скриншоты f7_vitrina_card_desktop.png,
  f7_manage_card_desktop.png (.playwright-mcp/);
- mobile 390×844: все те же проверки true, docOverflow=false; скриншот
  f7_vitrina_mobile_390.png;
- console errors: **0** во всех прогонах.

Browser Use (реальный рендер, локальный Chrome через scratch-сервер 8801 с
/api-моками): витрина/объяснение/лента/карточка отрисованы, Developer
details → collapsed ▶, раскрытие показывает story_id · участники (ID) ·
эпизоды (ID) только внутри details; скриншоты в сессии Browser Use.

## 5. Инцидентальные находки

- `related/pre-existing` (head): 3 JS меню-пина падают на HEAD (см. §3) —
  релевантно F5/F8 владельцам, не блокирует F7;
- `related-nonblocking`: счётчик «Исходных сообщений» ограничен серверным
  потолком 200 ключей оригинала (services/web_stories.build_original) — UI
  показывает «200+» честно; для точного «всего» нужен owner-контракт на
  несрезанный счётчик (вне WRITE_SCOPE — services/*);
- `related-nonblocking`: «использовалась ли история потом» в ТЗ — при
  отсутствии в модели фактов recall показан retrieval-статус (доступна/исключена);
  если владелец хочет реальные recall-события — нужен новый эмиттер mca-05
  (вне F7);
- `unrelated`: «@undefined» в шапке харнесса — артефакт мока /api/me (нет
  username), не дефект.

## 6. Ограничения/риски

- LIVE_UNVERIFIED на живом прод-чате с реальными именами участников —
  post-deploy evidence волны (резолв использует тот же get_active_participants,
  что chat_lore/oversight в проде — риск низкий);
- второй коллекции Stories нет; сервисы (services/*) не тронуты — DO_NOT_TOUCH
  соблюдён; plans/current_task.md не менялся.
