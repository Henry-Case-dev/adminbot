# Release 2.58.219 — VMQ-TIME-09 (per-run years/exclusions coverage UI)

**Дата сборки:** 19.11.2026
**База / развёрнутый checkout:** `e6239230656dd807ba1ba63a9913a86c09ccefef`
(2.58.218, content `50b1dd6b`, схема 48, PG DDL 0).
**Ветка:** `release/vmq-time09-2.58.219` (push без force).
**Merge-коммит:** `7db82f57dbc7ee56813d382ee720a83d244ffc46`
(parents `e6239230` + `f4d67b33`).
**Content tip:** `f80cba08ff6c444395753e77885ea2e37e2f308f` (merge + bump; evidence —
docs-only коммит после него).
**Статус:** REVIEW сборки. Продукт независимо одобрен в
`plans/features/vmq-onto-01/evidence/time09/review-r2.md` (master, коммит
`33766776`, verdict **APPROVED FOR RELEASE PREPARATION**); этот артефакт
описывает только сборку поезда и не заявляет VERIFIED. Деплой не выполнялся,
production/SSH/БД не затрагивались.

## 1. Состав поезда

| # | Что | Коммит |
|---|---|---|
| 1 | Merge `--no-ff` одобренного tip `fix/vmq-time09` (`f4d67b33`) поверх 2.58.218 | `7db82f57d` |
| 2 | Bump `2.58.218 → 2.58.219` + стандартная волна пинов | `f80cba08` |
| 3 | Release evidence (docs-only, этот каталог) | evidence-коммит ветки |

Одобренный источник: tip `f4d67b332705b54892b86faca52f5a7545c12bf2`;
продуктовые коммиты `738bd3a2` + `ee94ddf9` + `4c23f4b4`; предыдущий
review-tip `eefd555c2`; RED/мутации — в `time09/` этого же поезда.

Merge выполнен `git merge --no-ff f4d67b33`. Конфликтов нет. Один файл
(`tests/test_round1025_f8_registry.py`) авто-слит `ort`: разные ханки
(комментарий/hash VMQ-TIME-09 и APP_VERSION-пин 2.58.218); после merge
пин обновлён bump-коммитом до 2.58.219. Продуктовые файлы не разрешались
вручную.

## 2. Точное равенство одобренному продукту

Для всех продуктовых и тестовых файлов TIME-09 blob в `HEAD` совпадает с
`f4d67b33`; единственное отличие — `tests/test_round1025_f8_registry.py`
(только строка `APP_VERSION == "2.58.219"` вместо `2.58.217`; hash
`4faa0a53…` не менялся).

| Файл | blob (HEAD = f4d67b33) | sha256 |
|---|---|---|
| `services/mca_retrieval_context.py` | `1bf39528ba99f699e52818c90dc69803fb2b5df8` | `65be9ff0bc50d834d3f635b13facc0731bd5288875a0c062186b7a0e5781bcdd` |
| `services/direct_chat_service.py` | `8bb4aad039dc9a74d62f62aaaa499531538badc0` | `ae4c659bcb2ac5303b84f546ef29bf11282d702d8b01b1df262737b653b91472` |
| `web/api/routes.py` | `a7b51bd3ce3c82aaa3b4e2af0edd3e1827f71aaa` | `4faa0a5379a9943d7b0f11403a051777eb779a033c3bc069a1b3300cb7392ee7` |
| `web/app.js` | `9ce4e337982fcd6257c1a74549ffbc52d85abbd9` | `ac08167bf5c79524e72915c8c3a4989c3aa7f2f686414124d15dfc7efe0f8191` |
| `web/index.html` | `8cae227a9e14ec83744410c9bc909e054326c33b` | `d9193e9b0970afbb591d270d2dcf2a23b9b7e70a5580e1b6f24acfba197d64b8` |
| `web/static/status-analytics.js` (новый) | `5ae81a330569f6067569940bb8b54add64533514` | `39b00422bcf2c4b43494ff962cb52ea57a361ee14fa679417585a23af17ed7c2` |
| `tests/js/vmq_time09_year_coverage_ui_test.js` | `55faf50ec319b7b9d5cde3a301bec2e29cd1df21` | `e16fc0682d4535f511c5e8f60cc2e045d8fa3bfaa66a4b8967a8a53b03f08da4` |
| `tests/test_vmq_time09_turn_coverage.py` | `687ddccd8186ca5082fee068c538c800b1d9e91e` | `c302cdcceb9cbae0d8a0f87e0c605d75184c675905b154c5db21e7167218b432` |
| `tests/ui_vmq_status_analytics_e2e.py` | `373557d0635de76e76a4df3be7be4d4af8ff4f7a` | `d9fdacf2249891b327a4ef451db9d8f5698bf2eaf541c580df5c21855419ca78` |
| `tests/js/evol_glass_seam_test.js` | `c20b2d1a4f354ce2bf598249ad61f2626efb1ccb` | `41b45fa8f63497dd28bfcfd9dd0066f1a701af755b8e249dd998ccc29158473d` |
| `tests/test_ur_f_inspector_step2.py` | `4e7cfc9f042032556a45a0c4875bdfeed1c95a6b` | `970ff4bfb1ef14849bef02c0a893c24205f09a8cb356f68b4c3d17e1b252f9f6` |
| `tests/test_mca23_planned_vs_actual.py` | `79fcd88ec8573d706ec72bb0fffebc4d5fde5396` | `780ffd2d6b62e398cab146b22a0e3ba5c450191f7ba27fd32c9890fa883b10b4` |

`git diff f4d67b33 HEAD -- <эти 13 файлов>` = только APP_VERSION-пин в
`test_round1025_f8_registry.py` (1 строка). Продуктовый diff
`f68e7631d..f4d67b33` остаётся исходным (+1000/−22 в шести product-файлах;
initial `738bd3a2` + corrective `ee94ddf9`/`4c23f4b4`), новых правок в
релизной сборке нет.

## 3. Полный diff поезда

`git diff --shortstat e6239230..f80cba08`: **53 files changed, +3893 / −58**.

| Группа | Файлов | Что |
|---|---|---|
| Product TIME-09 | 6 | `mca_retrieval_context`, `direct_chat_service`, `web/api/routes`, `web/app.js`, `web/index.html`, новый `status-analytics.js` |
| Tests TIME-09 | 7 | node 327, pytest 635, e2e 563, `evol_glass_seam` allowlist, `ur_f_inspector` stages, `mca23`/`f8` route pins |
| Evidence TIME-09 | 11 | brief, implementation, limitations, mutations, RED, tests, playwright, review-r1 |
| Bump | 30 | `settings.py` (APP_VERSION+changelog), meta, 24 py-пина / 4 JS-пина |

Пересечение групп — `tests/test_round1025_f8_registry.py` (TIME-09 + bump),
поэтому 24 + 30 − 1 = 53. Product-файлов, не относящихся к TIME-09, в поезде
нет. `deploy_v2.9.2.py`, `services/mca_random_source.py`,
`services/database.py`, `services/pg_db.py`, `web/static/app.css`,
`web/app.py`, `handlers/web.py`, `web/api/memory_overview.py`,
`services/memory_diagnostics.py` байт-идентичны `e6239230`.

## 4. Схема, DDL, каталог

- `services/database.py` и `services/pg_db.py` байт-идентичны базе: схема
  остаётся **v48**, PG **DDL 0**, новых миграций/колонок/таблиц нет.
- TIME-09 читает существующую durable-трассу и существующий
  `GET /api/direct/turn-diagnostics`; store/endpoint/DDL не добавляются.
- Temp-DB smoke: `user_version=48`, `config_fingerprint`/`external_ref`
  присутствуют, `schema_migrations` 48→48, повторный `initialize()` — no-op.
- `APP_VERSION = "2.58.219"` (changelog: TIME-09 + `Prior 2.58.218`);
  каталог `REGISTRY 648 / GROUPS 121 / _TAB_BY_GROUP 119 / TAB_RULES 23`,
  `Settings` 472 поля; `gen_param_registry_round1025.py --check` — OK.
- Стандартная волна: 30 файлов / 31 замена (settings 1, meta 1, 24 py —
  25 вхождений, 4 JS в escaped-виде), BOM `EF BB BF` и CRLF `settings.py`
  сохранены (3645 CRLF / 3646 LF до и после).

## 5. Инварианты в собранном дереве

1. **F-01 сохранён байт-в-байт:** `services/mca_random_source.py`
   blob `4192f0338fa4c6766dc721c68c4989ab73538589` / sha256
   `0827075acf8f63004d16f31b8fa33e08c2c353f23d7717b141c2bf98f8d58111`,
   тест `17d754ab…` / `fb7f6951…`; `git diff 00d9ce3f HEAD` по обоим пусто.
2. **QRNG 2.58.217/218 не тронут:** единственные изменения поверх
   `e6239230` — файлы TIME-09 и пины версии; F-01 focused 4/0,
   random/P1/P2/P3 314/0.
3. **Новых маршрутов нет:** `@api_router` — 76 декораторов / 63 уникальных
   пути (как на базе); осознанно переутверждён `ROUTES_SHA256_F11`
   (`4faa0a53…`, L-F11S-1) в `test_round1025_f8_registry.py` и
   `test_mca23_planned_vs_actual.py`, `f8_baseline` не переиздавался.
4. **UI/визуальный контракт:** `app.css` байт-идентичен; 44 px — inline
   `min-width/min-height`; 320/390/1280 без overflow; aggregate
   `/api/memory/retrieval-coverage` не вызывается (0 в Playwright).
5. **R17:** `retrieval[]`/`stages.retrieval` несут только коды/числа/хост;
   секретов/пользовательских текстов в новых полях нет.
6. **Честность:** `years_present`/`excluded_present` отличают измеренный
   ноль от отсутствия данных; при смене хода старые числа скрываются до
   ответа (`aria-busy`); «последний ход» — только для хода 1.

## 6. Проверки

Точные команды/результаты — `tests-2.58.219.json`. Кратко, на content tip
`f80cba08`: node TIME-09 OK; pytest **13/0**; inspector **19/0**; affected
**482/0**; mandatory **386/0**; schema/apps **197/0**; F-01 **4/0**;
random/P1/P2/P3 **314/0**; JS candidate **119/4** vs base **118/4** (те же
4 файла); Playwright **66/66**, console 0, overflow 0, aggregate 0;
`node --check` rc=0; `git diff --check` рабочего дерева rc=0;
`gen_param_registry --check` rc=0.

`git diff --check e6239230..HEAD` даёт единственное предупреждение —
trailing whitespace в `time09/red-base-time09.txt:39` (raw-транскрипт RED,
известный N2, не product). Артефакт не переписывался.

## 7. Намеренно не сделано

- Деплой, production-доступ, SSH, реальные ключи/флаги/БД, миграция.
- Живой ход после выката (`mca07_retrieval.trace_id` + сверка SQL/UI) —
  агентская post-deploy проверка, см. runbook; до неё VERIFIED не заявлен.
- Browser Use: `BU_CDP_URL=http://127.0.0.1:9222` недоступен
  (`WinError 10061`), проверка честно помечена blocked; визуальный контракт
  подтверждён Playwright и реальным браузером в `review-r2.md`.
