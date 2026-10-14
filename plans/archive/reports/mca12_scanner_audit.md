# Scanner-аудит безопасности/R17 — `mca-12-miniapp-stories` (T-5173, 07.10.2026)

## Вердикт: **к деплою ДА** (Critical 0 / High 0)

**Сводка: Critical 0 / High 0 / Medium 0 / Low 0 / Info 4** (N-1/N-2 ревью подтверждены с дисполицией, новых блокирующих нет).

- **Биндинг перепроверен пересчётом:** HEAD `e12a94d1dcaa…` (= origin/master, прод-линия 2.58.64); манифест `plans/reports/mca12_wth_manifest_review.txt` — **25/25 файлов хеш-в-хеш совпадают с working tree** (binary sha256; 0 расхождений), агрегат **MANIFEST_SHA256 `a0bdb9cf…0952` воспроизведён точно** (рецепт: строки манифеста в исходном path-порядке, join `\n` + хвостовой `\n`; повторная сортировка полных строк даёт другой дайджест — сортировка у генератора по пути, не по «hash  path»). Кандидат = ровно то, что ревьюено (Approved, итер.1). Вне манифеста — задокументированные исключения его заголовка (workflow_state/backlog/MEMORY, mca-17c/mca-21-пакеты, сам манифест/review.md, скриншоты-E2E-артефакты). Дрейфа нет.
- **Мои прогоны на этом дереве:** focused mca-12 — **22 passed**; F8-пины + смежный mca-05 + JS-unit — **130 passed**. Секретный скан 25 кандидат-файлов по 8 сигнатурам — **0 совпадений**.
- **Санкции импортом факта:** KS=**85** (grep; ровно 2 новых `MCA_STORIES_VITRINA_/MANAGE_ENABLED`, env-only ClassVar вне dataclass-полей, default ON, оси независимы — `settings.py:1627–1630`, `mca_gates.py:1940–1957`); Δ DDL=0 (database.py/pg_db.py вне дельты); каталог/F8 NOT_APPLICABLE (тест `test_round1025_f8_registry` в моём прогоне 130); routes.py не тронут (нет в numstat, пин-тест в 22 passed), регистрация — `web/app.py:230–231` (`include_router(stories_router, prefix="/api")`, единственная вставка). Диффы аддитивные: app.js +583/0, index.html +504/0, app.css +25/0, mca_gates +48/2 (−2 = EOL-нормализация хвоста `temporal_max_evidence_per_run` при append — тело функции идентично, `mca_gates.py:1927–1931`), web/api/__init__ −1 = замена docstring. routes.py бит-в-бит.

## Независимые проверки (мой код-аудит + репро)

1. **Курсор/дедуп ленты (A54/TH-8):** сервер — строго `id > cursor` ASC после первой страницы (`web_stories.py:102–115`), первая страница DESC limit+1 с честным `has_more`; дедуп по id + монотонный курсор max(id) (`:126–135`); клиент — merge по id, seq-guard устаревших ответов при смене чата (`app.js:6031,6037`).
2. **Split без межчатовой инъекции эпизодов (TH-1):** hostile-сценарий «split чужими episode_id» закрыт на фасаде: `move_set ⊆ source_eps` иначе no-op (`mca_episodes.py:1161–1163`), source_eps — только эпизоды самого source-story; новая история наследует chat_id source'а; плюс router'ный chat-match до вызова (`web_stories.py:491–494`). Межчатовый merge запрещён (`web_stories.py:537–540`).
3. **Telegram-ссылки только из чисел (TH-3/D14):** `_parse_tg_key` принимает ровно `<chat_id>:tg:<id>` с chat_id==карточки, всё прочее → archive_only (`web_stories.py:281–294`); `_tg_link` строит URL только из int-частей, ЛС → честный archive_only (`:297–307`); клиент не строит URL, а выбирает серверный `links[0].url` (`app.js:6231–6234`).
4. **CAS/redirect (TH-6/A13):** `story_action` резолвит redirect ДО чтения (`web_stories.py:491`); stale → 409 с `current_version`; UI на stale показывает актуальную версию, перечитывает карточку и НЕ повторяет слепую отправку (`app.js:6264–6273`).
5. **XSS (TH-3, структурное доказательство):** весь дифф фронтенда — 0×`v-html|innerHTML|insertAdjacentHTML|outerHTML|dangerously|document.write|eval(|new Function|{{{|onclick=|<script` (мой греп, включая дополнения app.js/index.html/app.css); рендер — только mustache-интерполяции (`index.html:5740–5741,5769` — title/text/participants), `toast()` кладёт текст в state, не в HTML (`app.js:586+`); JS-suite дополнительно ассертит отсутствие вставок в новых зонах (js-test:246–262). Sinks отсутствуют классом — runtime-репро не требуется; CSP zero-build не тронут (routes pin).
6. **R17-логи:** новые warning-точки — только сообщения об ошибке чтения без контента (`web_stories.py:117,186,205`); в stories.py logger объявлен и не используется; `_tma_trace` пишет `init_data_len`/path без query/initData (прецедент, deps.py:146+). Событие мануальной правки — summary="manual edit", участники-ID, без текста (`web_stories.py:515–524`) — в границах существующего контракта mca-05.
7. **TH-7:** LIKE-метасимволы экранируются (`like_pattern`+`ESCAPE '\'`, `mca_episodes.py:560–567,592–602`), всё параметризовано, ORDER BY/LIMIT фиксированы (`:640–645`), Query-whitelist 422 (тест TH-7 в 22 passed), длины Body ограничены (`stories.py:239–247`).
8. **OFF-паритет (K1/K2 независимы):** K1 OFF → все read честный `disabled` (не 404; тест k1_off), блок скрыт `v-if="storiesEnabled"` (`index.html:5667`); K2 OFF → POST 409 `disabled` ДО проверок прав (`stories.py:273–276`), кнопки скрыты бейджем «только просмотр»; оси не пересекаются (`_summary_disabled` лишь транслирует manage_enabled для UI). Легаси бит-в-бит (см. биндинг).

## Проверка по чек-листу брифа

1. **XSS (TH-1/TH-3):** закрыт — см. репро 3/5 (0 sinks в диффе + mustache + CSP).
2. **RBAC/chat-scope (TH-2/TH-1):** все 5 routes под `get_tma_user` (401 без initData); чат только из `X-Chat-Id` (мусор 422, `stories.py:43–51`); `access_for`+`can_access_chat` → 403 (`stories.py:54–65`); мутации: K2 → whitelist действия → `user_is_global_admin` (`deps.py:198–213`, прецедент memory_agi) → chat-scope → CAS 409 (`stories.py:273–291`); карточка/действие чужого чата → 404 без раскрытия (`web_stories.py:437–439,492–494`); feed/summary шарят ровно те же ворота, что карточка → права идентичны. Порядок маршрутов: статические `/stories/summary`, `/stories/feed` объявлены до `/stories/{story_id}` (`stories.py:92,122,151,208`) — перехвата пути нет.
3. **Публичная витрина (TH-4, N-1):** `text` ленты = `entity.summary[:200]` (`web_stories.py:81`) — LLM-сжатие эпизодных summary (`mca_episodes.py:2277–2279` → `:2367/2381/2394`), НЕ raw-сообщения; участники — ID (та же экспозиция, что у карточки); message_keys/refs в feed не отдаются. N-1 подтверждён как осознанный профиль: то же содержимое доступно карточке при тех же правах (read-feed == read-card), требование `:798` («разрешённые краткие данные, не сырые логи») выполнено. Disposition: accepted, не ужать.
4. **N-2 exclude/restore:** подтверждено (`web_stories.py:560–565` → `set_story_excluded`, `mca_episodes.py:1024–1039`: только UPDATE флага+updated_at, без версии/события/created_by). Риск ограничен: действие недеструктивное (retrieval-флаг), global-admin-only, результат виден в таблице (`excluded_from_retrieval`); версии/события остальных действий полны. Аудит-след двух действий неполный — вне санкции mca-12 (write-семантика фасада, CA-12-1). Disposition: ADR-хвост/реестр отклонений, не ретро-фикс; деплою не мешает.
5. **M-MCA05-2:** детектор расширен корректно (`mca_episodes.py:2309–2337`): claims → `claims_identity` (sorted (text, sorted refs), `:381–387`), участники → `participants_identity` (sorted multiset, `:390–392`), даты → int-коэрция start/end; override-поля в сравнении не участвуют (A13); no-op rebuild → `continue` без версии/события (`:2336–2337`). Источник фактов — 3 теста MMCA05-2 в моих 22 passed.
6. **R17:** см. репро 6 + секрет-скан 0/8-сигнатур; `current_task.md` не изменялся (вне дельты); событий/логов с raw-текстом сверх существующего контракта mca-05 не добавлено.
7. **KS OFF-паритет:** см. репро 8.
8. **TH-5…TH-8:** TH-5 ✓ (initData не логируется ни одной новой точкой; секреты не в localStorage/console — греп диффа 0); TH-6 ✓ (репро 4); TH-7 ✓ (репро 7); TH-8 ✓ (честные no_chat/restricted/unavailable/empty/disabled — отдельные ветки и в API `stories.py:76–113`, и в UI `index.html:5693–5701`; «история ограничена» — `index.html:5784–5786`; нулей без расчёта нет).

## Находки

Блокирующих нет. Info (не блокируют, диспозированы):

| # | Severity | Координаты | Суть | Blocking |
|---|---|---|---|---|
| I-1 | Info | `web_stories.py:60–65` | `access_for` в `_require_chat_access` при инфраструктурной ошибке → 403: транзиентный сбой БД выглядит для UI как «restricted» (нет доступа), а не «unavailable». Fail-closed (утечки нет), но TH-8-оттенок честности. Backlog: различать 403 от отказа матрицы и 503 от инфраструктуры. | нет |
| I-2 | Info | `mca_episodes.py:680–691` + `web_stories.py:124` | `stories_titles` обогащает ленту по IN(story_id) без chat_id-фильтра: title чужого чата утёк бы только при уже повреждённых данных (story_id из события чужого чата) — события пишутся фасадом с chat_id своего story. Теоретический, defense-in-depth. | нет |
| I-3 | Info | `web_stories.py:80,136` | Лента не резолвит redirect: для объединённого source показывает старый story_id/пустой title (строки source скрыты из list, но заголовок по id ещё берётся). Косметика; карточка по клику резолвится корректно (репро 4). | нет |
| I-4 | Info | `web/api/deps.py:86–87` | initData принимается из query-параметра (прецедент, не mca-12): попадает в access-логи веб-сервера как часть URL. Новым кодом не усугубляется (новые routes ничего не логируют); отметить владельцу как унаследованный профиль TMA-auth. | нет |

Incidental (unrelated/pre-existing): EOL-хвост `mca_gates.py` — нормализация при append, тело идентично (проверено чтением диффа); −1 docstring в `web/api/__init__.py` — перезапись шапки при re-export, содержимого не меняет.

## Disposition

- Блокирующих находок нет; N-1/N-2 итер.1 ревью подтверждены с диспозицией (accepted-профиль / ADR-хвост), N-3…N-6 не воспроизводятся в новую проблему.
- Обязательное post-deploy условие прежнее: T-5175 live-приёмка (PENDING OWNER).
- Rollback: soft — 2 switch OFF (`MCA_STORIES_VITRINA_ENABLED`/`MCA_STORIES_MANAGE_ENABLED`; OFF = честный disabled/скрытие, легаси бит-в-бит — диффы строго аддитивные), cold revert тривиален (Δ DDL=0, Δ каталога=0, routes.py не тронут — пере-pin не нужен).
- Числа для DevOps (bump 2.58.65, T-5174): кандидат 25 файлов, манифест `a0bdb9cf…0952` (пересчитан мной, сходится), HEAD `e12a94d1`; APP_VERSION в дереве 2.58.64 → bump на деплое; секвенция после mca-20 (2.58.64); SSH-гейт владельца (fail2ban) — по регламенту AGENTS.md, статус прода проверять по HTTP `/healthz`.

R17: в отчёте секретов и сырого контента нет.

**Вердикт: к деплою ДА** (Critical 0 / High 0; join-barrier T-5174 @DevOps снят).