# Ограничения и известные незакрытые проверки — `2.58.210` (M4A wave 1)

Деплоя и production-проверок в этом артефакте нет. Статус — **REVIEW**, не
`VERIFIED`; независимая приёмка релиза ещё впереди.

## 1. Живой Telegram Mini App / W3

- Playwright/Browser Use работают на локальном стенде с синтетическими
  состояниями осей и стаб-API; живой TMA (реальный Telegram-клиент, реальные
  chat_id/аватары, safe-area, жесты, клавиатура) **не проверялся**.
- M4A **wave 1** — только каталог, карточка, workspace и CHAT tri-state.
  W2/W3, `#/access/roles` (M4C) и «Статус» (M4B) не реализованы и не входят
  в этот релиз.
- Живой smoke после деплоя (каталог 21 модуля, tri-state, 409) остаётся
  post-deploy проверкой ответственного агента, но не блокирует подготовку
  релиза.

## 2. Desktop tri-state 32 px

- На 390/320 (coarse/mobile) workspace tri-state — 44 px и полные подписи.
- На 1440/1280 кнопки остаются 32 px по высоте: это прежний десктопный
  визуальный контракт, требование 44 px к десктопу не применялось.
- Это осознанное состояние, а не незамеченный дефект.

## 3. Topbar «0 — конфликт»

- Счётчик конфликтов в topbar показывает `0 — конфликт` и не связан с
  живыми 409-состояниями карточек; sync счётчика — backlog, в M4A wave 1 не
  реализовывался.

## 4. Известный test-debt

- Test-debt `tests/test_webapp_hotfix10_round1025.py` **закрыт** в этом
  bump-цикле отдельным test-only коммитом. Устаревшая проверка
  `.module-list max-width:1100px` заменена контрактом M4A (design-m3 §4.1,
  `evidence/m4a/wave1-brief.md`): у `.module-list`/`.module-catalog` нет
  потолка 1100, контентная колонка до 1440, сетка 4/3/2/1, карточка 132–164
  (верхняя граница — измерением, не `max-height`). Продуктовый код не
  менялся; RED на CSS 2.58.209 подтверждён.
- 4 pre-existing pytest-падения в `test_tool_coordinator_round1026.py` /
  `test_unified_image_request_round1026.py` (устаревшие epic-scope guards:
  tool canon 18 vs 17, forbidden-path allowlists) **остаются pre-existing**
  и к M4A не относятся; воспроизведены на базе 2.58.209.
- 4 pre-existing node-падения: `asap6_wave2_ux_tabs_test.js`,
  `evol_cog_scene_test.js`, `round1025_ia_routing_test.js`,
  `ur_ui_settings_test.js`; те же на базе, новых нет.

## 5. Манифест и identity

- Manifest dry-run выполнен на content tip `368e3001` с чистой tracked-базой;
  `deployed_sha` в dry-run — это SHA content tip, а не фактически выложенный
  SHA. При деплое штатный `tools/release_manifest.py` должен записать
  реальный checkout-коммит; иначе identity будет неверной.
- Evidence-файлы этого релиза и закрытие test-debt добавлены отдельными
  docs/test-only коммитами поверх content tip; продуктовый код они не меняют.
- Production в этой сборке не читался: health/effective-state/schema на
  сервере не проверялись.

## 6. Откат

- Цель отката — `37f6c76f` (2.58.209), schema 47, DDL 0, данных/настроек не
  меняется; M2.1 live-строки остаются. Подробности: `rollback.json`.
- Бэкапы — существующий deploy-пул keep=2 от 2.58.209; новых тяжёлых копий
  этот артефакт не создаёт.
