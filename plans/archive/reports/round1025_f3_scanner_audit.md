# Scanner-аудит F3 `global-scope-selector-round1025` (коммит `76a6c40`)

Дата: 21.09.2026 · Область: `web/app.js`, `web/index.html`, `web/static/app.css`,
`web/api/routes.py`, `config/settings.py`, новые тесты, `tools/ui_round1025_matrix.py`.
Метод: diff `5dcc6bd..76a6c40` + критические файлы; дерево чистое.

## Вердикт: к деплою — **ДА**
Critical **0** / High **0** / Medium **1** / Low **4** / Info **3**. Блокеров нет.

## Чисто (проверено, не находка)
- **RBAC/DELETE** `web/api/routes.py:852-904`: `access_for(user.id, chat_id)` скоупит
  грант по чату (`services/roles.py:180-198`), поэтому local-admin чата A не сбросит
  override чата B (403); DM — только владелец своего ЛС (`is_dm_owner`). Снятие
  override НЕ делает factory-reset: `overrides.pop(key)` + merge `meta`, 404 если
  override нет. Переопределение не рушится при смене глобального (get_config
  накладывает override поверх глобала).
- **Секреты/R17/инъекции**: лог `routes.py:902-903` пишет только `chat=,key=,by=`
  (без значений); `resetChatOverride` шлёт `encodeURIComponent(item.key)`, SSRF/URL-
  fetch отсутствует; ответ `{reset, chat_id}` — только своему пользователю. Полный
  `chat_id` в UI спрятан в `<details class="scope-tech">` (§5).
- **Гонки/stale**: `scopeEpoch++` (`app.js:2509`) + `_scopeGuard` (`app.js:3379`)
  действительно отбрасывают запоздавший `loadConfig` (loading чужого scope не
  снимается); черновики (`blockDrafts/keyDrafts/personaDraft/configChatUpdatedAt`)
  и `configItems` очищаются при смене scope — переноса нет. JS-тест это проверяет
  поведенчески (`tests/js/round1025_scope_selector_test.js`).
- **CSP/zero-build, адаптив**: `.scope-wrap{order:5;flex-basis:100%}` работает —
  header имеет `flex-wrap` (`index.html:89`); mobile-тач-цель 44px; токены
  `var(--glass-bg-strong/--radius-md/--card-border/--shadow-xl/--text-3)` определены.
  Тег-баланс index.html: +8/+8 (паритет сохранён; pre-existing расхождение 1 не выросло).
- **Инварианты**: Δ DDL=0, Δ каталога=0 (`REGISTRY=459`), `stash@{0}` цел,
  zip в git нет (все `*.zip` под `.gitignore:107`), `git diff --check`=0.

## Medium
- **[M-F3-1] `web/app.js:2472-2482` — guard несохранённых правок не видит черновики
  блоков llm_providers.** `hasUnsavedEdits()` смотрит `stickyDirtyCount/dirtyItems/
  dirtyKeyItems/saving`, но НЕ `blockDrafts` (вкладка «LLM-провайдеры»:
  `blockFieldValue` читает `blockDrafts[f.key]`, `app.js:4015-4028`; значение в
  `configItems` при этом не меняется). Сценарий: пользователь правит base_url/model
  в блоке → не жмёт «Сохранить блок» → меняет область → `setActiveChat` молча
  затирает `this.blockDrafts={}` (`app.js:2538`) без подтверждения. Правка теряется.

## Low
- **[L-F3-1] `web/app.js:3282-3292` — шумная/двусмысленная пометка §43.** В chat-scope
  для ВСЕХ non-per_chat параметров (≈101 из 459 каталога) выводится амбер-строка
  «Глобальный параметр — локальное значение не применяется» на каждой карточке.
  При этом сохранение такой правки из chat-scope уходит глобально
  (`persistItems` делит по `per_chat===false` → `globalItems` `app.js:5656-5690`),
  т.е. формулировка может прочитаться как «правка не применится».
- **[L-F3-2] `tests/test_scope_selector_round1025.py:1-147` — маркерные grep-проверки.**
  Поведение реально покрывает только JS-тест; python-класс пройдёт и при инверсии
  логики (проверяет вхождения строк, не результат). Для регрессий логики — слабо.
- **[L-F3-3] `tools/ui_round1025_matrix.py` — «matrix 0» не воспроизведён.**
  В текущем окружении `playwright` отсутствует; независимо прогнать 10 вьюпортов не
  удалось (заявленные цифры коммита — на доверии).
- **[L-F3-4] F0-слой `web/app.js:5667-5692` (не F3, но касается «быстрого переключения»).**
  В `persistItems` epoch снимается ПОСЛЕ `await loadConfig()` (RC-6-ветка, `!=null`):
  если в этом окне сменить чат, POST уйдёт с токеном нового чата и элементами старого.
  Guard F3 снижает вероятность (dirty → confirm), но окно остаётся. Follow-up F0.

## Info
- **I-F3-1** На этой машине `py -m pytest -q` = **8142 passed / 5 failed / 1 skipped**;
  все 5 падений — окружение `aiogram` без `InputRichMessageMedia`
  (`services/telegram_send.py:174`; `test_outgoing_guard_round1022.py`,
  `test_summary_cover_round1023.py`), F3 не трогал эти файлы → не регрессия.
  Заявленный коммит `8148/0` локально не воспроизводится.
- **I-F3-2** local-admin не видит кнопку «Вернуть глобальное» (`index.html:689`:
  `isGlobalAdmin||isDmCtx()`), хотя backend для групп её разрешает (`routes.py:874`) —
  pre-existing F-14, а не F3.
- **I-F3-3** «Аудит состояния»: `nodes` `full_audit_results.md`/`global_map.md`
  синхронизированы этой записью.

## Цифры
`node --check web/app.js` — OK; `node tests/js/round1025_scope_selector_test.js` —
`SCOPE-SELECTOR-OK`; новый python-тест + JS-обёртка — 31 passed. APP_VERSION=2.58.6.
`RESULT: ✅ Аудит завершен. @Orchestrator, передаю эстафету для шага 7.`
