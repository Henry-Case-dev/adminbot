# MOD-ACL-UX-01 — план, очередь и порядок зависимостей

**Источник:** `plans/owner_inputs/2026-11-09-mod-acl-ux-01.md` (FINAL v1.0, 09.11.2026, 732 строки,
sha256 `BA6CF3D6…6FF92A7`). **Baseline:** `plans/features/mod-acl-ux-01/m0-baseline.md`
(sha256 `42C0103F…B5E03706`, read-only probe, ветка `integ/unify-release`, 09.11.2026).
**Леджер:** `requirements-map.json` (274 обязательные строки, 93 context), **машина зависимостей:**
`slice-graph.json`.

Правило владельца неизменно: это **новый** эпик, а не продолжение прежних редизайнов; место в очереди
определено ниже по фактическим зависимостям, а не по номерам M0–M6 из ТЗ.

---

## 1. Место в очереди

`MOD-ACL-UX-01` — **последний новый эпик действующей очереди: после `SELF-DIAG-01` и `VMQ-ONTO-01`**
(в `plans/progress_scope.json` задача уже зарегистрирована как `mod-acl-ux-01`, PENDING;
вход `OI-2026-11-09-MOD-ACL-UX-01` ждёт `reconciled: true` от оркестратора).

Полный Builder стартует **только** после того, как освободятся шесть файлов, занятых in-flight
работой MEMORY-08 S3. До этого разрешены только две независимые критические правки (см. §2).

### 1.1. Что пересекается с соседними эпиками

| Эпик / работа | Пересечение | Правило |
|---|---|---|
| **MEMORY-08 S3** | `web/api/memory_agi.py`, `services/mca_gates.py`, `services/config_cache.py`, `services/param_catalog.py`, `web/app.js`, `web/api/cognitive_map.py` — M-статус | Не писать параллельно; ждать merge/close в `integ/unify-release` либо явной PM-координации одного патча |
| **SELF-DIAG-01 (ACL)** | доступы, диагностика, resource-based матрица промптов | Одна политика доступа: MOD-ACL не вводит вторую; строки `MAC-S4-173`, `MAC-S10-13` учитывают будущий ACL SELF-DIAG |
| **VMQ-ONTO-01 (QRNG panel)** | «Случайность» в «Статусе», провайдер QRNG | Детали провайдера остаются во вкладке «Случайность» (`MAC-S6-REST-01`); панель VMQ не ломается и не дублируется |
| **prompt registry** | вкладка «Промпты», версии и права | Используется существующая система версионирования; принудительных ревизий при релизе нет (`MAC-S0-06`, `MAC-S5-TAB-03`) |
| **frontend-работа других эпиков** | `web/app.js`, `web/index.html`, `web/static/app.css` | Один владелец UI-полосы на integration slice; M4A → M4B → M4C последовательно |

---

## 2. Две независимые критические правки, допустимые раньше эпика

1. **M1 — ложный 403 у `global_admin`** (`web/api/memory_agi.py`): локальная копия
   `_is_global_admin` не вызывает `role_type_of()`; 15+ memory-endpoints недоступны владельцу.
   Правка — замена на общий `requires_global_admin` из `web/api/deps.py`.
   **Ограничение:** `memory_agi.py` занят MEMORY-08 S3 → старт только после освобождения файла
   либо по явной PM-координации патча. Разблокирует AC-06 и весь аудит §4.
2. **M5A — EXP-FIX-01..07, 09, 10** (`services/mca_experience_jobs.py`, `mca_experience.py`,
   `memory_maintenance.py`): ни один из этих файлов не входит в шесть сериализованных, поэтому
   corrective может идти **сейчас**, не дожидаясь MEMORY-08 и дизайна.
   EXP-FIX-08 (`M5B`) требует семантики M2 и раньше неё не начинается.

Обе правки дают самостоятельный, отдельно проверяемый результат и не являются «первой волной редизайна».

---

## 3. Порядок вех и владельцы

| Веха | Содержание | Владелец | Зависит от | Риск |
|---|---|---|---|---|
| **M0** | Read-only baseline closure: deployed SHA, бэкап конфигурации, матрица stored/effective по 2–3 чатам | DevOps probe + Architect review, леджер ведёт PM | — | R1 |
| **M1** | ACL corrective: единый predicate, 401/403/404/503, негативная матрица, Embeddings и аналитика | Builder (backend) | — (см. §2) | R1 |
| **M2** | Canonical `GLOBAL default → CHAT override`, пять осей, adapters, совместимость и impact report | Builder (backend) по контракту Architect | M1 | R2 |
| **M3** | Design freeze: IA-карта, wireframes, тексты, responsive, token mapping | Architect (Opus 5.5) | M0, M2 | R1 |
| **M4A** | Каталог модулей и workspace-страницы с реальными вкладками | Builder (UI) | M3 | R2 |
| **M4B** | «Статус»: пять живых лент, воронка, последний вызов, лента опыта | Builder (UI) | M4A | R2 |
| **M4C** | «Роли и права» страницей: поиск, наследование, 409, проверка доступа | Builder (UI + ACL read) | M4B | R2 |
| **M5A** | EXP-FIX-01..07, 09, 10 + короткий regression set | Builder (контур опыта) | M0 | R2 |
| **M5B** | EXP-FIX-08: shared review при GLOBAL OFF + CHAT ON | Builder (опыт + gates) | M2, M5A | R2 |
| **M5C** | Ограниченный production-proof (60–90 мин) + нативный `question` | DevOps read-only + Architect + **оркестратор** | M5A, M5B | R1 |
| **M6** | Live acceptance в TMA, пять viewport, deploy и rollback | Reviewer + DevOps | M4C, M5C | R1 |

Почему один M4 и один M5 разбиты: «M4» содержит три независимо проверяемых пользовательских
результата (каталог/вкладки, «Статус», права), а «M5» — исправления без семантики наследования,
одно межсистемное исправление (EXP-FIX-08) и отдельный human gate. Иначе приёмка становится
неделимой и ревью не может вернуть точечный дефект.

### 3.1. Волны исполнения

- **Волна 0 (сейчас):** M5A — как только Builder свободен; M1 — при доступности `memory_agi.py`.
- **Волна 1:** M0 closure + M2 (после M1) — строго последовательно по backend-контракту.
- **Волна 2:** M3 design freeze; параллельно может завершаться M5B после M2.
- **Волна 3:** M4A → M4B → M4C (одна UI-полоса).
- **Волна 4:** M5C (proof + gate) — не блокирует UI-волну, кроме расширения семантики уроков.
- **Волна 5:** M6 live acceptance и deploy.

Параллельно допустимо: read-only проверки, редактура, дизайн, тесты backend. Недопустимо: два
писателя в `web/app.js`, `web/index.html`, `web/static/app.css`, `services/chat_params.py`,
`services/mca_experience_jobs.py`, `web/api/memory_agi.py` одновременно.

### 3.2. M0 refresh — 2026-11-16 (deployed 2.58.205)

Датированное примечание к §M0. Таблица вех и baseline 09.11 выше сохранены как история и не
переписаны.

- **Артефакты:** `evidence/m0/mac-m0-01.md` (sha256 `41a4f95f…cb62`), raw DOM-проба
  `evidence/m0/catalog-dom-probe-2026-11-16.json` (sha256 `caa49780…315c`); `m0-baseline.md`
  дополнен разделом 8, `baseline_sha256` карты = `EAD79303…2351`.
- **Deployed / HEAD:** 2.58.205 @ `bca18c1e` (identity `verified_deployed`), схема 47, DDL 0;
  served `app.js` sha256 `3cf2c916…f594` = checkout; плановая линия `master` — старт
  `ad06a034`, сдача `6f91b888` (плановая линия не runtime, аудит кода — по deployed checkout).
- **Каталог:** 21 видимая карточка = 16 static `mod_*` + 5 registry-only (`stories, character,
  experience, random, embeddings`); реестр — 11 ModuleSpec / 10 видимых, hidden
  `factcheck_temporal`; DOM-проба 21/21. «11 модулей» из baseline — это Python-реестр, не UI;
  ни один из трёх списков по отдельности не равен 21, совпадение даёт только union.
- **ACL:** 249 route-decorators, единственный endpoint без auth — `GET /api/health`; 181
  `get_tma_user`, 33 `requires_permission`, 40 `requires_global_admin`; M1 false-403 исправлен
  (`memory_agi._require_global_admin` → `deps.user_is_global_admin`), 17/17 M1 + 2/2
  truth-table тестов на deployed checkout. Остаётся локальная пере-реализация
  `routes.py:4139–4160` — по коду эквивалентна.
- **Расхождения с baseline 09.11:** 11 registry ≠ 21 UI; `app.js` уже merge реестра, не
  fallback; effective-state сведён M2-резолвером; схема 46 → 47; строки Roles & Permissions
  сдвинуты. Состав 21 не совпадает с перечнем `m3-design-freeze.md` §2 (число то же) — это
  вопрос M3/M4, а не M0.
- **Live-срез (догрузка 2026-11-16 16:06Z, `24b12016`):** `evidence/m0/effective-state-2.58.205.md`
  (sha256 `983f43ad…9bfd`) и `.json` (`ac01a5cb…2cf`): read-only на проде `bca18c1e`, 16 capability ×
  3 профиля = 48 пар, GLOBAL-строки мастеров 9/10 (memory.random_enabled — дефолт), гейты G8/DM5
  поштучно, ровно одна пара GLOBAL OFF + CHAT ON (`gate:permsoc` у G32), `changed_pairs=0`, digest
  `bot_settings`/`chat_profiles` совпадает с pre/post 2.58.205. Конфигурация сохранена серверным
  gzip-JSON снапшотом обеих таблиц (read-back equal).
- **Gaps:** (1) `pg_dump`/`pg_restore` на хосте нет — custom-format архив не создан; снапшот двух
  конфиг-таблиц является заменой, но не pg_dump (задокументировано); (2) независимого
  Reviewer-одобрения M0-доказательств нет; (3) живой Mini App с owner-сессией не открывался — это
  проверка M4, не M0.
- **Гейты (факт, до rebind):** plan `errors=0`; scoped review M0 на `bca18c1e` — `errors=2` (candidate
  mismatch из-за намеренно не перенесённого map-level кандидата `34213999` + отсутствие
  независимого Reviewer-одобрения), на `34213999` — `errors=1` (evidence не привязан к старому
  кандидату). Цифры этого пункта неполные: полный прогон до rebind давал `errors=3` (третья ошибка —
  «live requirement lacks evidence» из-за устаревших `artifact_sha256`); актуальные значения — ниже.
- **Статус (историческое состояние до одобрения):** `MAC-M0-01` = **REVIEW** на кандидате `bca18c1e`, не `VERIFIED`: live-матрица и
  конфигурационный снапшот есть, но независимого Reviewer-одобрения нет; pg_dump-ограничение
  зафиксировано. M0 не закрывает эпик; следующий dependency-ready срез — **M3 design freeze**
  (M4A depends_on M3).
- **Поправка D1–D4 (2026-11-16, Builder `a4e1f12c` + `f300ecca`; rebind карты — коммит этого
  примечания):** актуальные sha256 доказательств — `mac-m0-01.md` `D3D00E38…AE50`,
  `effective-state-2.58.205.md` `BCC1EBBE…92DE`, `.json` `9A0CBA41…AD31`, DOM-проба `CAA49780…315C`,
  `m0-baseline.md` `EAD79303…2351` (не менялся). D1: inner sha256 снимка — `1c5312fe…ea78` (прежний
  `309f1947…9914` — хеш от `str(bytes)`; gz не менялся, sidecar на проде исправлен). D2:
  `registry_for_frontend()` отдаёт 10 записей, 11 — это весь реестр. D3: байт-в-байт верно только для
  `app.js`, `index.html` отличается подстановкой `__APP_VERSION__`. D4: два остаточных неверных хеша —
  gz-суффикс в §6 и старый sha `.json` в §8 `effective-state-2.58.205.md`, gz-суффикс в §1.4
  `mac-m0-01.md` — исправлены `f300ecca`. Значения sha256 в пунктах выше — исторические (до поправки),
  их заменяет эта запись.
- **Map-level candidate согласован (2026-11-16):** `candidate_commit` = `deployed_commit` = `bca18c1e`
  (2.58.205); история `34213999` (2.58.175) сохранена в `deployment_evidence`, evidence-записях строк
  и git log, строки не переоценивались. Живая сверка того же дня: публичный `/healthz` → 2.58.205,
  `/web/app.js` 2 311 044 B, sha256 `3cf2c916…f594`.
- **Гейты после rebind (до одобрения):** plan `errors=0`; scoped review M0 `--candidate bca18c1e` → `errors=1` —
  только отсутствие независимого Reviewer-одобрения (после одобрения — `errors=0`, см. ниже). До rebind тот же прогон давал `errors=3`
  (candidate mismatch и «live requirement lacks evidence»: устаревшие `artifact_sha256` отбрасывались
  при `strict_evidence`), поэтому прежнее утверждение «sha256 валидны» снято как неверное.
- **Закрытие M0 (2026-11-16):** независимый Reviewer выдал **Approved** по кандидату `bca18c1e`;
  запись `type=review` (`reviewer_role: Reviewer`, `verdict: Approved`) привязана в
  `MAC-M0-01.evidence` к артефакту `evidence/m0/mac-m0-01.md` (sha256 `D3D00E38…AE50`), строка
  переведена **REVIEW → VERIFIED**. Scoped review M0 → **`errors=0`**. Принятые ограничения остаются
  в силе и не скрыты: pg_dump/pg_restore на хосте нет (снапшот двух конфиг-таблиц — не pg_dump),
  живой Mini App с owner-сессией — проверка M4, матрица 48 пар — срез 2026-11-16 04:03Z.
  Карта: **69 VERIFIED / 0 REVIEW / 219 PENDING** из 288 обязательных; эпик не закрыт.

---

### 3.3. M3 design — Approved (2026-11-16); M4A после M2.1

Датированная запись к §3 (M3). История §3.2 сохранена; прежний §3.3 (M2.1) перенумерован в §3.4
без изменения содержания.

- **Вердикт:** независимый Reviewer — **Approved design** (кандидат docs
  `ae937d9e6fae2870e4062b4389458c0e403d8e6d`, продукт-база
  `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1`). Ревью вернуло E1 и D1–D12; после исправлений
  rev2.1 все D1–D12 PASS, E1 PASS, повторная проверка D1 — PASS.
- **Артефакты (sha256):** `design-m3-2026-11-16.md` — `91d60e5b…181692`;
  `copy-inventory.md` — `892f749c…b6519752`; `m3-design-freeze.md` — `cbc2cb96…c06ca9`;
  `evidence/m3/mac-m3-01.md` — `8fbebdf0…82fc65`. Git blobs: `0cea464b…` / `eaada4f3…` /
  `0563d9a0…` / `9d2e1adb…`.
- **Строки M3 (20):** 18 REVIEW, 2 PENDING. Разбиение Reviewer — 15 covered / 5 partial; PM
  закрыл три partial по acceptance: `MAC-S0-07` (содержательное ревью и редактура выполнены;
  модельная оговорка Opus 5.5 условна и неприменима), `MAC-S9-ARCH-01` и `MAC-S13-ARCH-01`
  (per-card вкладки закрыты D1 §2.4; все обязательные разделы design присутствуют). Остались
  PENDING: `MAC-S5-281` — copy inventory готов (D5 закрыл шапку), но Reviewer не читал русский
  текст в живом интерфейсе; `MAC-AC-09` — design утверждён, но реальные действия на живом
  продукте не проверялись. Обе gap'ы закрываются live-preflight M4A/M6, не M3.
- **Почему REVIEW, а не VERIFIED:** design принимает контракт, а не runtime/UI. Продуктовое
  поведение, реальные переключатели, 409 и live-ACL проверяются M4A/M4B/M4C/M6; `VERIFIED` без
  этих доказательств был бы инфляцией.
- **Зависимость:** `M4A depends_on [M3, M2.1]`; **M2.1 остаётся обязательным предшественником**.
  Design Approved не отменяет M2.1 и не разблокирует M4A: до закрытия M2.1 M4A не рисует
  CHAT-контролы 12 модулей (§12.2/§12.5). M2.1 идёт отдельным лейном: его ревью вернуло
  Needs Fixes (F1–F4; F5–F10), corrective уже запущен.
- **Долг docs-accuracy (low, не блокер):** F1 — счётчики §2.4 включают hidden
  (`limits_summary` 3/7, `limits_factcheck` 2/4, `limits_qnd` 24/27, `direct/limits` 6/7/2);
  F2 — evidence §3 без self-sha; F3 — устаревший checkout-указатель. Записаны в карту
  (`m3_design_2026_11_16.findings`); артефакты не переписаны, их хеши зафиксированы approval.
- **Не приёмка:** продукт, тесты, конфиг и деплой не менялись; эпик не закрыт. Гейты: plan
  errors=0; scoped review M3 `--candidate bca18c1e` scoped=20 errors=2 (две PENDING-строки,
  фактические сообщения — в карте); workflow_progress exit 0, queue 41/41.

---

### 3.4. M2.1 — per-chat adapters для 12 модулей (2026-11-16, prerequisite M4A)

Датированное дополнение к §3.2 и к design §12.2/§12.3. Новых требований не вводит: пять существующих
PENDING-строк M2 перенесены по полю `slice`, текст acceptance и статусы не менялись.

- **Почему отдельный срез.** На выкате 2.58.205 chat override без product master-AND читают только
  7 модулей (`summary, sleep, nostalgia, budgets, images, vision, experience`); 11 читают глобальный
  `hot.get`, хотя каталог объявляет `per_chat=True`, а `initiative_observer` сохраняет master-AND с
  `flags.initiative_enabled`. Итого 12 модулей. Проверено по checkout `bca18c1e`:
  `handlers/search.py:140`, `handlers/checkup.py:434`, `handlers/voice_transcription.py:414`,
  `handlers/youtube.py:1682`, `handlers/direct_chat.py:236`, `handlers/web.py:142`,
  `handlers/factcheck.py:1154`, `services/media_download.py:198`,
  `services/mca_gates.py:2673/1974/1720`, `services/initiative_observer.py:438,493` — все читают
  глобальный слой. Рисовать CHAT tri-state в M4A до этого — инертный контрол (owner §9.3), поэтому
  M2.1 идёт первым.
- **12 модулей:** `initiative, direct, factcheck, search, web, transcribe, video_summary,
  media_download, checkup, stories, character, random`.
- **Владение M2.1:** 5 существующих строк — `MAC-S2-TT-5`, `MAC-AC-04`, `MAC-S10-01`,
  `MAC-S15-12`, `MAC-S2-SHARED-01` (перенос из M2 по полю slice, статусы PENDING сохранены).
  Consumer-level доказательства добавляются к `MAC-S0-01`, `MAC-S2-TT-4`, `MAC-S2-91`,
  `MAC-S2-116`, `MAC-AC-02`, которые остаются у M2 со своими статусами: две VERIFIED-строки не
  понижаются, но их универсальная формулировка на 2.58.205 подтверждена только для резолвера и
  адаптированных потребителей — это записано в карте, а не скрыто.
- **M4A остаётся:** `MAC-S5-197` (tri-state/effective/readiness), `MAC-AC-08`, `MAC-M4-01`,
  `MAC-S5-TAB-01..07`, `MAC-S5-CAT-01/02`, `MAC-S5-SAVE-01`, `MAC-S5-NAV-01`, `MAC-S9-BLD-01`.
  **M3 остаётся:** `MAC-AC-01`, `MAC-S3-CAT-01`, `MAC-S3-SHARED-01`.
- **Write scope (17 позиций):** 12 consumer-файлов (`services/initiative_observer.py`,
  `handlers/direct_chat.py`, `factcheck.py`, `search.py`, `web.py`, `voice_transcription.py`,
  `youtube.py`, `checkup.py`, `video_download.py`, `services/direct_chat_service.py`,
  `services/media_download.py`, `services/mca_gates.py`), `services/tool_router.py`,
  `services/feature_gates.py`, `tests/test_mod_acl_ux_01_m21_adapters.py`,
  `tests/test_mod_acl_ux_01_m21_gates.py`, `evidence/m21/**`.
- **Acceptance:** каждый из 12 модулей решает потребление через существующий
  `resolve_capability(chat_id, …)` без второго resolver/ACL/registry; GLOBAL OFF + CHAT ON исполняет
  только в этом чате; GLOBAL ON + CHAT OFF не исполняет в чате, не останавливая shared worker, индекс
  и operative-историю; INHERIT = глобальное значение; initiative без product master-AND (emergency —
  env); nostalgia precedence = `memory.nostalgia_enabled`; stored values не переписаны.
- **Тесты:** `tests/test_mod_acl_ux_01_m21_adapters.py` (по модулю: GLOBAL OFF + CHAT ON, GLOBAL ON +
  CHAT OFF, INHERIT, shared service alive при CHAT OFF), `tests/test_mod_acl_ux_01_m21_gates.py`
  (nostalgia precedence, initiative emergency, отсутствие второго resolver).
- **Зависимости:** M2.1 зависит от **M2** (резолвер и write-path; общие `mca_gates.py` и
  `feature_gates.py`), но не от M3 как среза: замороженный design §12.2/§12.3 — контракт, а строки
  M3 — UI/copy/wireframe. M4A `depends_on [M3, M2.1]`; M5B `depends_on [M2.1, M5A]` (общий
  `services/mca_gates.py`).
- **Evidence:** `evidence/m21/**` — прогон тестов на точном кандидате плюс read-only пара на проде
  (GLOBAL OFF + CHAT ON и GLOBAL ON + CHAT OFF) с counters/ledger по `chat_id`.
- **Не приёмка:** статусы не повышались, реализации нет; строки M2.1 остаются PENDING до кандидата и
  независимого ревью.

---

## 4. Соблюдение требования «не только тесты»

Правило из ТЗ §0.7/§9 и `AC-09`, `AC-19` записано как обязательный барьер приёмки, а не пожелание:

- **Architect** обязан выдать единый design specification (IA-карта на все карточки, реальные вкладки
  и owner-ключи, wireframes каталога и трёх классов модулей, «Статуса» и страницы прав, responsive,
  token mapping, окончательные русские тексты, таблица навигации, данные первого viewport) и
  **критически отредактировать** макеты как продуктовый редактор — до любых CSS-работ.
  Пустой второй экран, повтор заголовка, зарытое действие, технический жаргон и низкая плотность
  считаются дефектом контракта, а не вкусовщиной (`MAC-S9-ARCH-01/02`, `MAC-S5-276…281`).
- **Reviewer** обязан сам открыть **реально работающую** сборку в браузере/Playwright, увидеть
  desktop/tablet/mobile и оценить: решает ли экран задачу пользователя, читается ли русский текст,
  совпадают ли контролы с реальным backend. Скриншот шаблона, unit-snapshot, отчёт Builder или
  «тесты зелёные» приёмкой не являются (`MAC-S9-REV-01`, `MAC-S9-BL-01…11`, `AC-10`, `AC-19`).
- Блокирующие замечания Reviewer (первый viewport пустой, два перехода до формы, ложное «сохранено»,
  кнопка без runtime-эффекта, пустой KPI как «успех», утечка секрета, срез мобильных контролов)
  возвращают срез Builder независимо от состояния тестов.
- Русский текст проверяется **в интерфейсе**, а не по CSV: Architect делает copy inventory до/после,
  Reviewer читает его на живом экране (`MAC-S5-281`).

---

## 5. Human gate: механика, а не отчёт

1. **Предусловие.** EXP-FIX-01..10 исправлены и проверены (M5A/M5B), затем выполнен **ограниченный
   read-only production-proof 60–90 минут** по §7.3 (deployed_sha, курсоры, backlog, причины нулей).
   Бюджет — цель планирования, а не право оборвать тест; недоступность VPS фиксируется как `unverified`
   с причиной, без выдуманных production-доказательств.
2. **Кто вызывает.** **Оркестратор** из основной интерактивной сессии вызывает **нативный инструмент
   OpenCode `question`** (в этой primary-сессии он доступен) с заголовком «Стратегия уроков» и тремя
   вариантами: проверяемые смысловые уроки (рекомендуется), оставить узкий каталог, расширить каталог
   по образцам. Предварительно проверяются версия OpenCode и effective permissions основной сессии
   (для v2 — правила `permissions` с `action: "question"`, а не старый `permission.question`).
3. **Что не заменяет gate.** Текстовый отчёт, markdown-список вариантов, «нужно выбрать» в ленте,
   промежуточный исследовательский отчёт — **не gate**. Gate существует только при реально вызванном
   `question` и полученном или ожидаемом ответе (`MAC-AMD-01C`).
4. **Пока ответа нет.** Никакого варианта по умолчанию: расширенная семантика уроков **не
   реализуется**; совместимые работы эпика (UI, права, наследование, документы, тесты, deploy
   остального) продолжаются (`MAC-AMD-01B`, `MAC-S7-456`).
5. **После ответа.** Выбранная ветка фиксируется в леджере/ADR и исполняется; повторный gate для
   обычных code fixes и UI-деталей не требуется. Если инструмент недоступен по технической причине —
   фиксируется конкретный blocker (нет tool, deny permission, клиент без формы) и запрашивается
   минимальная правка настроек, а не обход владельца (`MAC-S17-729`).

---

## 6. Покрытие источника

- 279 инвентаризованных строк источника классифицированы: 186 обязательных + 93 context
  (заголовки, наблюдения §1, адреса файлов §14, ссылки, §16-дубли) — неразобранных строк нет.
- 88 `additional_requirements` покрывают норматив, который gate не извлекает: шесть случаев truth
  table (`MAC-S2-TT-1..6`), пять осей (`MAC-S2-AX-01..05`), EXP-FIX-01..10 (`MAC-EXP-*`),
  поправочные обязательства (`MAC-AMD-01`, `MAC-AMD-01B`, `MAC-AMD-01C`, `MAC-AMD-02`), правила
  вкладок, «Статуса», матрицы прав, ролей Architect/Reviewer и вехи M0–M6.
- Все 19 критериев `AC-01…AC-19` присутствуют отдельными строками; все 10 дефектов опыта — тоже.
- Итого 274 обязательные строки, все `PENDING`; ни одна не помечена `VERIFIED` до фактических
  доказательств. `live_required` выставлен там, где приёмка требует живого интерфейса, runtime или
  production (146 строк, из них 1 postdeploy — deploy-подтверждение `MAC-S17-730`).

### 6.1. Состояние после выката 2.58.172 (обновление 09.11.2026)

Строки выше — снимок планирования. Фактическое состояние леджера на 10.11.2026 (после выката
2.58.175):

- всего обязательных строк **285** (279 из инвентаря + 99 manual, из которых 88 исходных и 11 поправки
  уроков), из них `live_required` — 152;
- `VERIFIED` — **64**: `MAC-EXP-01…07, 09, 10` (M5A, кандидат `4e07817e`, live-строка `MAC-EXP-06`
  на `42f068df`), `MAC-LSN-01…06` (M5L, кандидат `c51933d0`, выкат `bee14188`), **39 строк M2**
  (кандидат `dd52cbf9`, выкат `34213999`; доказательства `evidence/m2/m2-evidence-dd52cbf9.md`,
  `evidence/m2/m2-evidence-3b1ba3b2.md`, `reports/m2-impact-3b1ba3b2.md`,
  `reports/m2-consumers-dd52cbf9.md`, `reports/m2-deploy-surface-dd52cbf9.md`,
  `evidence/m2/m2-deploy-2.58.175.md`), **6 строк M1** (доступ и предикат:
  `evidence/m1/m1-owner-live-confirmation-2.58.175.md`) и **4 строки M4A** (вкладки/параметры
  «Векторной памяти»: `evidence/m4a/m4-module-settings-2.58.175.md`);
- `PENDING` — **221**, включая `MAC-LSN-07…11` (M5L-OBS), 15 строк M2 (живая матрица флагов и строки,
  требующие реального события чата или живого UI), 15 строк M1 (аудит/инвентарь/секреты/аналитика) и
  31 строку M4A.

Срез **M2** на 10.11.2026: 54 строки, из них 39 `VERIFIED` и 15 `PENDING` (точные условия — §8.1 и
`evidence/m2/m2-deploy-2.58.175.md` §6). Задеплоенный `34213999` содержит M2-код и M2-тесты
байт-идентичными кандидату `dd52cbf9`, поэтому строки привязаны к выкату; полного `VERIFIED` у среза
нет только из-за живых пар truth table и строк, ждущих реального события.

Срез **M4A** после 2.58.175: 35 строк, из них 4 `VERIFIED` и 31 `PENDING`. Выкат доказывает один
рабочий экран одного модуля («Векторная память»: вкладки, 25 реальных параметров каталога, поиск,
четыре честные причины пустоты), а не каталог и не остальные вкладки.


Поправка уроков 09.11.2026 заведена двумя срезами: **M5L** (реализация и выкат контракта —
`MAC-LSN-01…06`, доказано) и **M5L-OBS** (живые наблюдения — `MAC-LSN-07…11`, PENDING с точными
условиями). Контракт заморожен в `lesson-strategy-contract.md`, доказательство выката —
`evidence/m5l/lessons-deploy-2.58.172.md`.

### 6.2. Что именно доказывает приёмку (кратко)

| Требование | Наблюдаемое доказательство |
|---|---|
| Truth table, включая GLOBAL OFF + CHAT ON | runtime-прогон шести пар на двух чатах + impact report |
| stored values не переписаны, UNSET = INHERIT | migration diff, дампы до/после, отсутствие override при просмотре |
| владелец не получает ложный 403 | API-трасса Embeddings/analytics с role_type=global_admin + негативные тесты |
| 401/403/404/503 | разные сообщения и разные backend-причины на одном экране |
| роли страницей | живой экран с поиском, наследованием, 409 и preview пути разрешения |
| «Статус» | пять лент с досье наверху, воронка без псевдоконверсий, пустой «Последний вызов» компактен, лента опыта под индикаторами |
| EXP-FIX-01..10 | regression set §7.2 на реальных SQL-строках + `unverified` там, где production недоступен |
| секреты | отсутствие сырых ключей в ответах, DOM, логах и ошибках |
| ON по умолчанию | effective-state после деплоя при сохранённых пользовательских OFF |

---

## 7. Следующее действие

- **Немедленно исполнимого кода по опыту нет:** M5A и M5L выкачены и доказаны, новых правок продукта
  эти срезы не требуют.
- **M5L-OBS — наблюдение, а не работа Builder.** Условия (`MAC-LSN-07…11`): архивный курсор и
  покрытие после дренажа свежего бэклога ≈2 суток (15 628 строк при чистом дренаже ≈+7.4 тыс./сутки),
  первое противоречие (`temporal_rank ×0.5`, строка сохраняется), первое независимое повторное
  подтверждение (`+0.1`, `confirmation_count` только по новому `source_ref_id`), первое применение
  урока в живом ответе, оставшиеся 5 событий аналитики. Артефакт наблюдений:
  `evidence/m5l/lessons-observations-2.58.172.md`.
- **Следующий инженерный шаг эпика** — M4A: остальные вкладки/экраны каталога (`MAC-S5-TAB-03…07`,
  `MAC-S5-SAVE-01`, `MAC-S5-LAY-01`, каталог) на уже принятой базе «Векторной памяти»; `M5B`
  (`MAC-EXP-08`) ждёт M2.
- **M2 (backend)** — доказан на кандидате `dd52cbf9`, выкачен в 2.58.175 (`34213999`) и привязан в
  леджере: 39 строк `VERIFIED`. Осталось 15, все — живая матрица флагов (TT-2/3/5/6, AX-05,
  SHARED-01, S10-01, S2-81, AC-02), живой UI-прогон (S10-04, S15-1-01) и реальное событие чата
  (AC-04, S10-20, S15-12) плюс сводная `MAC-M2-01`. Детали — §8.1 и
  `evidence/m2/m2-deploy-2.58.175.md` §6.
- **M1** — доступ владельца и предикат закрыты (`MAC-S0-05`, `MAC-S2-50`, `MAC-S4-158/159/160`,
  `MAC-S15-1-06`), но 15 строк M1 остаются `PENDING` без привязанных артефактов (аудит ACL, отчёт
  аудита, секреты, паритет путей, аналитика, 503/UI). Это блокирует выпуск M2 как самостоятельного
  среза: гейт `--stage release --slice M2` даёт 30 ошибок = 15 строк M2 + 15 строк зависимости M1
  (`evidence/m1/m1-owner-live-confirmation-2.58.175.md` §5).
- **Владелец — одна живая проверка, которая закрывает 4 строки M4A:** открыть в Mini App на 2.58.175
  «Модули → Векторная память → Основные настройки» и убедиться, что видны 25 параметров и поиск
  (`MAC-S5-TAB-02`, `MAC-S5-EMPTY-01`, `MAC-S10-16`, `MAC-S15-14`).


---

## 8. Правило размещения карты требований (постоянное, 09.11.2026)

**Решение: вариант (a) — review/release gate всегда запускается из основного checkout против SHA
кандидата. Карта требований на релизную ветку не переносится.**

Причина в одну строку: `requirements-map.json` — единственный живой леджер, и его вторая копия на
релизной ветке немедленно разошлась бы с master, а перенос потребовал бы merge-шума в каждом
релизе.

Точная форма запуска (единственная поддерживаемая):

```
<OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/mod-acl-ux-01/requirements-map.json \
  --stage review --slice <срез> \
  --candidate <полный SHA кандидата> --repo <корень основного checkout>
```

Отсутствие `plans/features/<epic>/` в изолированном checkout кандидата — **не дефект среза и не
повод возвращать `Needs Fixes`**: gate читает карту из основного checkout, а Git-объект кандидата
проверяет по `--repo`. За два цикла это стоило двух блокировок M2; правило выше закрывает вопрос.

Альтернатива (b) — переносить `plans/features/<epic>/` (`requirements-map.json`, `slice-graph.json`,
`plan.md`, `evidence/`, owner input) в релизную ветку тем же коммитом, что и релизный bump — остаётся
допустимой только для случая, когда ревью обязано быть воспроизводимым из одного checkout. Тогда у
карты должен быть явно назван владелец ветки, иначе две копии леджера разойдутся.

### 8.1. Релизный чек-лист (часть про требования)

1. **Gate — только из основного checkout** (`--repo .` / путь корня), `--candidate` = полный SHA
   проверяемого кандидата. Не запускать gate из изолированного checkout релизной ветки.
2. `--stage plan` должен быть `errors=0` **до** любых работ Builder.
3. `--stage review --slice <срез> --candidate <SHA>` — перед вердиктом Reviewer; остаток ошибок
   разбирается по категориям (недоказанные строки vs ошибки привязки), а не «gate красный».
4. `--stage release --candidate <SHA> --deployed-commit <SHA>` — только при фактическом выкате;
   `deployed_commit` в карте должен совпасть с реальным.
5. Перед вердиктом проверить, что карта привязана к **тому же** SHA: `candidate_commit` карты =
   `--candidate`, строки среза имеют `evidence[].candidate_commit` этого же кандидата.
6. Строки, доказанные на предыдущем кандидате (как impact report `reports/m2-impact-production-17c3a05e.md`
   на `97cfdef1`), **не переносятся**: либо повторный прогон на финальном кандидате, либо строка
   остаётся `PENDING` с условием. Перенос допустим только с проверенным основанием — файлы тестов не
   изменились (тот же блоб), ядро `resolve_capability` и приоритет не правились, изменения нового
   кандидата аддитивны; основание записывается в `observation`, а не подразумевается.
7. У impact report (`reports/m2-impact-3b1ba3b2.md`) колонка OLD — **реконструкция** домигрированной
   семантики: задеплоенный прод `2.58.174` (`ac943f40`) не содержит `chat_params.resolve_capability`
   и несёт собственный `services/capability_registry.py`. Это сравнение семантик на реальных
   сохранённых строках, **не** живое сравнение рантаймов; поэтому отчёт не подменяет live-строки и не
   даёт «M2 выкачен».

Итог gate по M2 на `dd52cbf9` (main checkout): `stage=plan … errors=0`;
`stage=review … scoped=54 errors=18`, все 18 — `mandatory not ['VERIFIED'] (got PENDING)` (15 живых,
сводная `MAC-M2-01`, `MAC-S10-04`, `MAC-S10-20`); ошибок привязки артефактов, `candidate mismatch` и
ошибок slice-graph нет. Хронология среза: 67 ошибок до первой привязки (1 `candidate mismatch` + 42
недоказанные строки + 24 ошибки привязки на 12 строках), 34 после привязки кода `3b1ba3b2`, 31 после
impact report, 18 после поведенческих строк `dd52cbf9`.


