# Отчёт @Reviewer — раунд 10.23, F9 `help-ui-v5-round1023`

- **Коммит:** `f69551f` — «feat(services,docs,tests): раунд 10.23 F9 — Справка v5 и Гайд по возможностям v2 (3 режима, System 2, анти-клише, изображения)»
- **Ревью:** Step 5, строгий аудит @Reviewer
- **Spec / ADR / задачи:** `plans/features/help-ui-v5-round1023/spec.md`, `ADR-1023-9.md`, `tasks.md` (T-2176…T-2182)
- **Сквозной слой:** `plans/features/round1023-architecture.md` §3.4, §5, §4 (инварианты)
- **Гейты (проверено лично):**
  - Целевые pytest (`test_help_ui_round1023`, `1022`, `1020`, `test_info_service`, `test_info_handlers`, `test_help_guide_round1014`) — **138 passed**.
  - Полный pytest — **7398 passed / 0 failed** (заявленные 7398/0 подтверждены).
  - Байт-зеркало `DEFAULT_INFO_TEXT == info_text.md` — True; `PREV_R1023_INTELLIGENCE_GUIDE == git show f69551f^:plans/docs/intelligence_user_guide.md` — **байт-в-байт True**.
  - Счётчики: `<h1>=1`, `<h2>=11`, `<blockquote>=24`, `<p>=44`; размер гайда 17 367 < `_GUIDE_LIMIT` 65 536.
  - Обратный греп коммита на `sk_`/`api_key`/`token`/`https://gen`/`pollinations` — совпадений в контенте нет (R18 чист).

## Статус: **Changes Requested**

Контентная и миграционная часть выполнены сильно: v5 строго равен v4 + новая секция, оба слепка (info v4 и guide v1) байт-точные, все четыре правила §4.2 идемпотентности реализованы и покрыты тестами, счётчики вёрстки и tone-of-voice не сломаны, инварианты раунда не затронуты, полный pytest зелёный. Однако **весь блок «Откат» из spec §9/ADR-1023-9 (Decision 6) фактически не реализован для гайда**, а явно запрошенные в ревью-чеклисте **тесты обратимости миграции отсутствуют**. Это не «почти готово» — контракт сопровождения заявлен, но не обеспечен.

---

## Findings

### [Medium] Откат гайда не реализован — spec §9/ADR Decision 6 обещают возврат, механизма нет
**Файл:** `services/config_cache.py:368-446`, `services/info_service.py:390-610,736-752`, `web/api/routes.py:1200-1239`
**Проблема.** Для info откат действительно работает: после `git revert f69551f` `_migrate_info_how_it_works_v1015` на старте видит `canon_delivered_version=5 != 4` и делает одноразовую форс-доставку v4 (ветка `config_cache.py:301-312`). Для гайда такого пути нет:
- единственный «возвратный» механизм — сама функция `_migrate_intelligence_guide_r1023` (`config_cache.py:368`), а `git revert` удаляет её целиком → PG остаётся на v2, тогда как репозиторий/файл `plans/docs/intelligence_user_guide.md` возвращаются к v1. `get_guide()` (`info_service.py:736`) продолжит отдавать v2 из PG — **молчаливый рассинхрон кода и БД**;
- аналога `reset_canon` (`info_service.py:700`) для гайда нет: `POST /api/info/guide` (`routes.py:1213`) умеет только записать присланный текст, но канон v1/v2 через API не отдаётся, а `GET /api/info/guide` (`routes.py:1200`) возвращает лишь `markdown`/`updated_at`/`updated_by`;
- `KNOWN_GUIDE_SNAPSHOTS` (`info_service.py:610`) в текущем коде работает только «вперёд» (v1→v2) и **не участвует ни в каком пути возврата** — то есть заявленное в spec §9 «слепок v1 … позволяет распознать и **вернуть**» не обеспечено.
**Почему это важно.** Если F9-контент гайда потребуется откатить, прод будет показывать пользователям v2, а репозиторий — v1: ровно тот класс рассинхрона «код один, БД другой», от которого раунд 10.16 защищал Справку. Принять это как «и так сойдёт» нельзя.
**Обязательное исправление.** Закрыть контракт одним из вариантов:
1. добавить `InfoService.reset_guide(cache=...)` + `POST /api/info/guide/reset` (RBAC `edit_info`, аддитивно — R16), который пишет код-канон из `_GUIDE_SEED_FILE` и бэкапит `prev_markdown`/`prev_updated_at` (по образцу `reset_canon`); либо
2. минимум — вернуть `prev_markdown`/`prev_updated_at` в `GET /api/info/guide` и зафиксировать в spec §9 реальную процедуру отката (SQL UPDATE / `save_guide(prev_markdown)`), убрав неверное утверждение про «вернуть» через `KNOWN_GUIDE_SNAPSHOTS`.
В обоих случаях — добавить тест отката.

---

### [Medium] Нет теста обратимости info-миграции (v5 → v4) — прямое требование ревью-чеклиста
**Файл:** `tests/test_help_ui_round1023.py` (класс `TestInfoMigrationV4ToV5`, ~:225-255)
**Проблема.** Проверены: слепок v4→v5, идемпотентность (повтор → no-op), ручной дрейф → не затирается. Путь **отката** (код снова `INFO_CANON_VERSION=4`, а в PG лежит v5) не покрыт ни одним тестом. Механизм рабочий (я проследил его вручную), но недоказан.
**Почему это важно.** Это ровно тот сценарий, который в ревью-чеклисте заявлен обязательным («миграция … обратима (rollback → v4)»). Без теста любой будущий рефактор ветки `if not delivered_done` (`config_cache.py:301`) тихо сломает откат, и узнают об этом только на проде.
**Обязательное исправление.** Добавить тест: monkeypatch `services.config_cache._INFO_CANON_VERSION=4`, `_DEFAULT_INFO_TEXT = PREV_R1023_DEFAULT_INFO_TEXT`, `_KNOWN_INFO_SNAPSHOTS = (v1, v2, v3)`; seed PG = v5-text с `canon_version=5`, `canon_delivered_version=5`; после `init` — html == v4, `canon_version==4`, `prev_html` записан, ровно 1 INSERT.

---

### [Low] Не покрыта ветка «текст == канон, но `*_version`/маркер устарели»
**Файл:** `services/config_cache.py:289-295` (info) и `:401-407` (guide) — обе вызывают `_write_*_canon` «добить маркеры»
**Проблема.** Ветки `info canon version fixed` / `guide canon version fixed` не проверяются ни одним тестом. Это реальный прод-кейс (значение уже каноничное, но маркеров нет — например, после ручного SQL или частичной доставки).
**Почему это важно.** Без покрытия легко потерять идемпотентность «добивки маркеров», и значение будет перезаписываться на каждом старте.
**Обязательное исправление.** Тест: `markdown == канон`, маркеры отсутствуют → ровно 1 запись, после повторного `init` — 0 записей.

---

### [Low] `prev_markdown`/`prev_updated_at` — write-only мёртвые данные
**Файл:** `services/config_cache.py:439-445` (запись) → `services/info_service.py:736-752` (чтение)
**Проблема.** Бэкап создаётся только в пути форс-доставки, но никакой read-path его не отдаёт: `get_guide` фильтрует поля, `GET /api/info/guide` возвращает лишь `markdown`/`updated_at`/`updated_by`. Владелец, чья правка была перезаписана одноразовой форс-доставкой до F9, восстановить её без сырого SQL не может.
**Почему это важно.** ADR-1023-9 Decision 3 обосновывает бэкап гарантией восстановления. Сейчас гарантия недоступна через продукт.
**Обязательное исправление.** Либо отдавать `prev_markdown`/`prev_updated_at` через `GET /api/info/guide`, либо включить в `reset_guide`/документацию (см. Medium #1).

---

### [Low] Тест форс-доставки проверяет бэкап только in-memory, а не персистентность
**Файл:** `tests/test_help_ui_round1023.py:339-350` (`test_unknown_before_delivery_force_delivered_with_backup`)
**Проблема.** `assert value["prev_markdown"] == manual` читает in-memory копию `cache.get(GUIDE_KEY)`; фактический INSERT-payload не инспектируется (в info-эквиваленте payload проверяется через `_inserts`). Если `prev_markdown` потеряется при `normalize_value`/`json.dumps`, тест этого не заметит.
**Обязательное исправление.** Дополнительно декодировать `json.loads(q[1][1])` из `_inserts(conn, GUIDE_KEY)[0]` и проверить `prev_markdown` в персистированном значении.

---

### [Low] Дублирование helper'а `_between_adjacent_blockquotes`
**Файл:** `tests/test_help_ui_round1022.py` и `tests/test_help_ui_round1023.py` (одна и та же реализация)
**Проблема.** Копипаст регламентного гейта вёрстки в двух модулях — при правке правил разъедутся.
**Обязательное исправление.** Вынести в общий test-util (например, `tests/helpers/info_layout.py`) и импортировать.

---

### [Low] Нет байт-эталона гайда: тест v2 проверяет только ключевые подстроки
**Файл:** `tests/test_help_ui_round1023.py:271-278` (`test_v2_content_has_new_blocks`)
**Проблема.** Для info есть жёсткий байт-тест «константа ↔ `info_text.md`», а для гайда проверяются лишь 7 подстрок. Усечение/порча середины файла (или исчезновение старой секции) тест не поймает.
**Обязательное исправление.** Добавить инвариант целостности гайда-канона (например, наличие заголовков `## 1.`…`## 12.` в фиксированном порядке и/или эталонный счётчик символов/секций).

---

## Контракт: чекбоксы

| Пункт | Статус | Комментарий |
|---|---|---|
| Spec §2.1: v5 = v4 + `<h2>11. Генерация изображений</h2>`, команды в `blockquote` | ✅ | `DEFAULT_INFO_TEXT.startswith(PREV_R1023_DEFAULT_INFO_TEXT)`; 3 команды в `<blockquote>` |
| Spec §2.2: `INFO_CANON_VERSION` 4→5, v4 в слепках | ✅ | `INFO_CANON_VERSION=5`; `len(KNOWN_INFO_SNAPSHOTS)=4` |
| Spec §2.3: `info_text.md` байт-в-байт | ✅ | `DEFAULT_INFO_TEXT == info_text.md` — True |
| Spec §2.4: идемпотентная PG-миграция v4→v5 + ручной дрейф не затирается | ✅ | тесты v4→v5 / повтор / drift |
| Spec §2.4-бис: **обратимость (rollback → v4)** | ⚠️ | механизм есть, **теста нет** (Medium #2) |
| Spec §2.5: гайд v2 — манеры/System 2/анти-клише, без жаргона | ✅ | «Быстрый трёп / Обычный разговор / Глубокий разбор», «фильтр против штампов», словарик пополнен |
| Spec §2.6: доставка гайда v1→v2 идемпотентна, ручные правки не затираются | ✅ | 4 правила §4.2 покрыты |
| Spec §2.6-бис: **откат гайда** | ❌ | нет пути возврата (Medium #1) |
| Spec §2.7: Δ каталога = 0, DDL = 0, web = 0 | ✅ | коммит не трогает `param_catalog.py`/`pg_db.py`/`web/**` |
| Spec §3.1: только `<h1>`/`<h2>`, без точек/запятых/«или» между `<blockquote>` | ✅ | h1=1, h2=11, h3-h6=0; `_between_adjacent_blockquotes` gaps пусты |
| Spec §3.1: команды соответствуют реальным триггерам F5 | ✅ | `IMAGE_KEYWORD_RE` (`services/image_generation.py:81-89`) матчит все 3 примера канона |
| Spec §3.2: запрет внутреннего жаргона в гайде | ✅ | `validator/scrubber/regex/вербализатор/синтезатор/аналитик/loop/промпт/llm` отсутствуют; «режим» в новой части не используется (только в легаси-§10 про безлимит) |
| Spec §4.2: 4 правила миграции гайда | ✅ | все ветки реализованы; тесты на 3 из 4 |
| Spec §6: байт-тесты, цепочка слепков, идемпотентность | ✅ | `test_help_ui_round1023.py` |
| Spec §6: **rollback-тесты** | ❌ | отсутствуют (Medium #2) |
| Spec §8: критерии приёмки (контент, стиль, версии, 0 failed) | ✅ | полный pytest 7398/0 |
| Spec §9: откат | ❌ | для гайда не обеспечен (Medium #1) |
| `physical-two-call-pipeline` | ✅ | F9 не касается LLM-вызовов |
| egress (`send_rich_message` не дублирован) | ✅ | `telegram_send.py`/`outgoing_guard.py` не тронуты |
| R16 / R17 / R18 | ✅ | API не менялся; в логах миграций только версии-числа; ключ изображений не цитируется, в диффе нет секретов |
| `parse_mode=None` | ✅ | разметку доставки не меняли |
| Δ каталога = 0 / Δ DDL = 0 | ✅ | `content.info_how_it_works`/`content.intelligence_guide` — уже зарегистрированы как `json`; `normalize_value` маркеры сохраняет |
| F1–F8 не сломаны | ✅ | полный pytest 7398/0 |
| порядок роутеров `bot.py` | ✅ | `bot.py` в коммите отсутствует |
| `[x]` T-2176…T-2181 действительно реализованы | ✅ | T-2182 (деплой/живая приёмка) — `[ ]`, вне код-ревью |

## Версии канонов (фактически)

| Артефакт | Значение |
|---|---|
| `INFO_CANON_VERSION` | **5** |
| `KNOWN_INFO_SNAPSHOTS` | len = **4** (v1…v4), v4 = `PREV_R1023_DEFAULT_INFO_TEXT` |
| `GUIDE_CANON_VERSION` | **2** |
| `KNOWN_GUIDE_SNAPSHOTS` | len = **1** (`PREV_R1023_INTELLIGENCE_GUIDE` = байт-точный v1) |
| `DEFAULT_INFO_TEXT` вёрстка | h1=1, h2=11, blockquote=24, p=44 |
| `info_text.md` | 6 915 симв., без trailing `\n` (совпадает с константой) |
| гайд v2 | 17 367 симв. < `_GUIDE_LIMIT` 65 536 |

## Список для @Builder (обязателен к исправлению)

1. **Medium:** `services/config_cache.py:368-446` + `web/api/routes.py:1200-1239` — обеспечить откат гайда: `InfoService.reset_guide()` + `POST /api/info/guide/reset` (RBAC `edit_info`, аддитивно), либо отдавать `prev_markdown`/`prev_updated_at` в `GET /api/info/guide` и зафиксировать реальную процедуру отката в spec §9 (убрать неверное «вернуть» через слепки). Тест отката обязателен.
2. **Medium:** `tests/test_help_ui_round1023.py` — добавить тест обратимости info v5→v4 (reverted-код: `INFO_CANON_VERSION=4`, `_DEFAULT_INFO_TEXT=v4`, `_KNOWN_INFO_SNAPSHOTS=(v1,v2,v3)`, PG=v5+delivered=5 → v4 + `prev_html`, 1 INSERT).
3. **Low:** добавить тесты ветки «текст == канон, маркеры устарели» для info и guide (ровно 1 запись, повтор → 0).
4. **Low:** раскрыть `prev_markdown`/`prev_updated_at` (связано с п.1).
5. **Low:** `tests/test_help_ui_round1023.py:339-350` — проверять `prev_markdown` в персистированном INSERT-payload, а не только in-memory.
6. **Low:** вынести `_between_adjacent_blockquotes` в общий test-util (сейчас дублируется).
7. **Low:** добавить инвариант целостности гайда-канона (заголовки §1…§12 по порядку) вместо проверки только подстрок.

После правок — повторный полный pytest (ожидаемо 7398+ новых / 0) и обновление этого отчёта (итерация 2).

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — повторный аудит

- **Коммит:** `1b148fe` — «fix(services,web,tests): раунд 10.23 F9 — откат гайда, тесты обратимости, целостность канона (review iter1)». Поверх — фикс F8 `27c7b2a` (к F9 не относится, не приписываю).
- **Проверено лично:**
  - Целевые pytest (те же 6 модулей) — **147 passed** (+9 к итерации 1).
  - Полный pytest — **7413 passed / 0 failed** (заявленные 7413/0 подтверждены).
  - `git show 1b148fe --stat`: только `services/info_service.py`, `web/api/routes.py`, тесты, `spec.md`, `ADR-1023-9.md`. `param_catalog.py` / `pg_db.py` / `bot.py` / `telegram_send.py` / `outgoing_guard.py` / `web/index.html` / `web/app.js` — **не тронуты** (проверено грепом stat).
  - Обратный греп диффа на `sk_`/`api_key`/`password`/`https://gen`/`pollinations` — секретов нет (R18).
  - `tests.helpers.info_layout.between_adjacent_blockquotes` импортируется и работает (проверено запуском).

## Статус итерации 2: **Changes Requested**

## Итог по 7 пунктам итерации 1

| № | Пункт | Статус | Комментарий |
|---|---|---|---|
| 1 | Medium: откат гайда (`reset_guide` + роут + RBAC/503 + spec) | ✅ по коду / ⚠️ runbook | `InfoService.reset_guide` (`info_service.py:790-828`), `POST /api/info/guide/reset` (`routes.py:1245`), unit (`test_reset_guide_*`), API (admin 200 / non-admin 403 / PG down 503) — корректны. НО описанная в spec §9/ADR процедура отката неисполнима (см. Medium ниже). |
| 2 | Medium: тест обратимости info v5→v4 | ✅ | `test_rollback_v5_to_v4` (`test_help_ui_round1023.py:262-280`): monkeypatch v4-кода, PG=v5+delivered=5 → v4 + `prev_html`, 1 INSERT. Не тавтологичен — реально проходит ветку `config_cache.py:301`. |
| 3 | Low: тесты «текст == канон, маркеры устарели» | ✅ | `test_canon_text_with_stale_markers_rewritten_once` для info и guide (1 запись, повтор → 0). Логика проверена. |
| 4 | Low: `get_guide` отдаёт бэкап | ✅ (с оговоркой) | `prev_markdown`/`prev_updated_at` в `get_guide` (`info_service.py:751-761`) и в fallback (`None`). Но отдаётся в `GET /api/info/guide` любой роли (см. Low ниже). |
| 5 | Low: бэкап в INSERT-payload | ✅ | хелпер `_persisted` + `json.loads(rows[-1][1][1])`; проверяется и в force-delivery, и в `reset_guide`. |
| 6 | Low: общий test-util | ✅ | `tests/helpers/info_layout.py` + `__init__.py`; `round1022` делегирует через тонкую обёртку. Дублирования кода больше нет. |
| 7 | Low: целостность канона гайда | ✅ | `test_canon_integrity_headings_in_order`: `## 1.`…`## 12.` строго по порядку. |

## Findings (итерация 2)

### [Medium] Runbook отката гайда неисполним и противоречив (spec §9, ADR Decision 6, docstring)
**Файл:** `plans/features/help-ui-v5-round1023/spec.md:141`, `ADR-1023-9.md:27`, `services/info_service.py:790-806` (docstring `:797-798`)
**Проблема.** Описанная процедура «`git revert` (файл снова v1) + вызов `POST /api/info/guide/reset`» не работает в обоих прочтениях:
1. `reset_guide` пишет **текущее** содержимое `_GUIDE_SEED_FILE` (`info_service.py:804`), а не исторический v1. Сразу после F9 это v2 — то есть вызов роута **не откатывает** гайд к v1, а повторно записывает v2. Чтобы получить v1, нужно сначала заменить сам сид-файл — в spec/ADR/docstring этого нет.
2. Если выполнить `git revert f69551f` «как написано» (это удаляет `GUIDE_CANON_VERSION = 2` из `services/info_service.py` и `_migrate_intelligence_guide_r1023`), то оставшийся код из `1b148fe` (не реверченный) содержит `from services.info_service import GUIDE_CANON_VERSION as _GUIDE_CANON_VERSION` (`services/config_cache.py:27`) и `reset_guide` со ссылкой на `GUIDE_CANON_VERSION` (`info_service.py:810-811`) → **ImportError/NameError на старте бота** (проверено: `git show f69551f^:services/config_cache.py` не содержит этого импорта, а `1b148fe` — содержит). Если ревертнуть **оба** коммита — исчезает сам роут, которым предписано откатывать.
Дополнительно: при подмене сид-файла на v1 `reset_guide` всё равно проставит `guide_version=2` (`info_service.py:810`) — метка разойдётся с содержимым.
**Почему это важно.** @DevOps, следуя runbook буквально, либо получит не-откат (повторную запись v2), либо уронит бот на импорте. Это ровно тот операционный тупик, ради устранения которого пункт и заводился.
**Обязательное исправление.** Переписать процедуру отката на исполнимую: **не** ревертить код F9; восстановить целевую версию сид-файла (`git checkout <pre-F9> -- plans/docs/intelligence_user_guide.md` либо правкой файла), затем вызвать `POST /api/info/guide/reset`; прежний текст при этом сохранится в `prev_markdown`. Добавить явное предупреждение «`git revert` кода F9 удаляет роут и константу канона — откат через роут тогда недоступен». Поправить docstring `info_service.py:797-798`. По желанию — тест, что `reset_guide` доставляет произвольный (старый) канон из файла и кладёт прежний в `prev_markdown` (текущий `test_reset_guide_returns_to_canon_with_backup` это уже почти покрывает на `V2_CANON` — достаточно расширить под реальный сценарий подмены файла).

### [Low] `prev_markdown`/`prev_updated_at` отдаются в `GET /api/info/guide` любой TMA-роли
**Файл:** `web/api/routes.py:1200-1210` (`get_tma_user`), `services/info_service.py:743-761`
**Проблема.** Роут `/api/info/guide` доступен **любой** аутентифицированной TMA-роли (у него нет `requires_permission`), а ответ теперь включает `prev_markdown` — предыдущую ревизию гайда (в т.ч. возможно непубликованный черновик, сохранённый владельцем до сброса). Фронтенд (`web/app.js:5352`) забирает этот ответ для показа гайда; поле в UI не используется, но уезжает всем.
**Почему это важно.** Бэкап — админский артефакт; его раскрытие всем ролям — регрессия по умолчанию безопасности (принцип наименьших привилегий).
**Обязательное исправление.** Отдавать `prev_markdown`/`prev_updated_at` только при наличии `edit_info` (например, отдельное поле/эндпоинт под `requires_permission("edit_info")`), либо возвращать их исключительно в ответе `POST /api/info/guide/reset`. Или явно зафиксировать принятие риска в spec/ADR.

## Контракт (итерация 2)

| Пункт | Статус |
|---|---|
| `reset_guide` возвращает код-канон, бэкапит `prev_markdown`/`prev_updated_at`, ставит маркеры | ✅ (код/тесты) |
| `POST /api/info/guide/reset`: RBAC `edit_info`, 200/403/503 | ✅ (3 API-теста) |
| spec §9/ADR: убрано неверное «вернуть через `KNOWN_GUIDE_SNAPSHOTS`» | ✅ |
| spec §9/ADR: описана **исполнимая** процедура отката | ❌ (Medium выше) |
| Интеграционный тест отката info v5→v4 | ✅ |
| Ветка «канон + устаревшие маркеры» (info/guide) | ✅ |
| Персистентность бэкапа в INSERT-payload | ✅ |
| Общий test-util вёрстки | ✅ |
| Целостность гайда §1…§12 | ✅ |
| Δ каталога = 0 / Δ DDL = 0 / frontend = 0 | ✅ |
| `physical-two-call-pipeline` / egress | ✅ (не тронуты) |
| R16 (роут аддитивен) / R17 (логи — только id/версия/bool) / R18 | ✅ |
| `parse_mode=None` | ✅ |
| F1–F8 не сломаны | ✅ (7413/0) |
| `bot.py` порядок роутеров | ✅ (не тронут) |

## Список для @Builder (итерация 3, обязателен к исправлению)

1. **Medium:** переписать runbook отката гайда в `spec.md:141`, `ADR-1023-9.md:27` и docstring `services/info_service.py:797-798` на исполнимый (заменить сид-файл → вызвать роут; предупредить про потерю роута при `git revert` кода F9); убрать «`git revert` + вызов роута» как совместный рецепт.
2. **Low:** ограничить отдачу `prev_markdown`/`prev_updated_at` ролью `edit_info` (или отдавать только в ответе reset), либо зафиксировать принятие риска.

После правок — повторный прогон целевых и полного pytest; обновить отчёт (итерация 3).

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 3 — финальный аудит

- **Коммит:** `2e056e7` — «fix(services,web,tests,docs): раунд 10.23 F9 — исполнимый runbook отката и RBAC бэкапа гайда (review iter2)».
- **Проверено лично:**
  - `git show 2e056e7 --stat`: `services/config_cache.py`, `services/info_service.py`, `web/api/routes.py`, тесты, `spec.md`, `ADR-1023-9.md`. `param_catalog.py`/`pg_db.py`/`bot.py`/`telegram_send.py`/`outgoing_guard.py`/`web/index.html`/`web/app.js` — **не тронуты**.
  - Целевые 6 модулей — **152 passed** (+5). Полный pytest — **7418 passed / 0 failed** (заявленные 7418/0 подтверждены).
  - Секретов в диффе нет (R18); фронтенд ссылок на `prev_markdown`/`guide/backup` не имеет — не сломан.
  - Независимая симуляция решений миграции (не через тесты Builder'а): пост-откатный рестарт (файл v1, PG v1) → **NOOP** (нет ре-апгрейда на v2); апгрейд v1→v2 → MIGRATE→canon; откат через файл+рестарт → FORCE-DELIVER; повторный апгрейд → MIGRATE. `guide_version_for`: v1→1, v2→2, пусто/None→2 (константа).

## Статус итерации 3: **Approved**

## Закрытие замечаний итерации 2

| № | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1 | Medium: исполнимый runbook отката | ✅ | `spec.md §9/§5`, `ADR-1023-9.md` Decision 6 и docstring `reset_guide` (`info_service.py:826-837`) теперь: «код F9 НЕ ревертить (ImportError/потеря роута) → восстановить сид-файл → `POST /api/info/guide/reset`». `config_cache.py` больше не импортирует `GUIDE_CANON_VERSION`, а считает версию по содержимому через `guide_version_for` (`info_service.py:613-633`; используется в `_seed_intelligence_guide:357`, `_migrate_intelligence_guide_r1023:400`, `_write_guide_canon:437`, `reset_guide:848`). Тест подмены сид-файла на v1 — `test_reset_guide_after_seed_file_downgrade_to_v1` (маркер = 1, прежний текст в `prev_markdown`, персист). Симуляция веток — верна. |
| 2 | Low: RBAC бэкапа | ✅ | Публичный `get_guide` отдаёт только `{markdown, updated_at, updated_by}` (`test_set`-assert); бэкап — `get_guide_backup()` + `GET /api/info/guide/backup` под `requires_permission("edit_info")` (401 без initData / 403 moderator / 200 admin — `test_help_guide_round1014.py`); `POST .../reset` возвращает бэкап вызывающему с `edit_info`. |

## Findings (итерация 3)

Блокирующих нет. Незначительные наблюдения (не требуют правок для приёмки):

### [Low] Косметика: warning в runbook называет не тот импортируемый символ
**Файл:** `services/info_service.py:833`, `spec.md:141`, `ADR-1023-9.md:27`
После итерации 3 `config_cache` импортирует `guide_version_for` (а не `GUIDE_CANON_VERSION`), но предупреждение перечисляет `GUIDE_CANON_VERSION`/миграцию. Суть верна (реверт кода F9 ломает импорт и убирает роут), но точнее назвать `guide_version_for`/`KNOWN_GUIDE_SNAPSHOTS`. Косметика.

### [Low] `save_guide` оставлен на хардкоде `GUIDE_CANON_VERSION`
**Файл:** `services/info_service.py:808-809`
Ручная правка через UI помечается текущей версией — это осознанно (защита от повторной форс-миграции). Наблюдаемого отличия от `guide_version_for(markdown)` нет: для кастомного текста обе дают константу, а для текста-снапшота ветку перекрывает `KNOWN_GUIDE_SNAPSHOTS` (миграция вперёд). Не дефект.

### [Low] Тест `test_reset_guide_after_seed_file_downgrade_to_v1` не перезапускает `init` после reset
**Файл:** `tests/test_help_ui_round1023.py:458-478`
Тест проверяет сам reset, но не идемпотентность «после отката рестарт не вернёт v2». Я проверил это независимой симуляцией — NOOP; для полноты можно добавить повторный `cache.init()` в тест.

## Финальный контракт

| Пункт | Статус |
|---|---|
| Spec §8 — критерии приёмки (контент v5, гайд v2, стиль, версии, 0 failed) | ✅ |
| Spec §9 — исполнимый runbook отката (info авто, guide через роут) | ✅ |
| `INFO_CANON_VERSION=5` / v4 в `KNOWN_INFO_SNAPSHOTS` / `info_text.md` байт-в-байт | ✅ |
| `GUIDE_CANON_VERSION=2` / v1-слепок байт-точный / миграция идемпотентна / откат через файл+роут | ✅ |
| `physical-two-call-pipeline` | ✅ (не тронут) |
| egress (`send_rich_message` не дублирован) | ✅ (не тронут) |
| R16 (роуты аддитивны) / R17 (логи — id/версия/bool) / R18 (секретов нет) | ✅ |
| `parse_mode=None` | ✅ (не тронут) |
| Δ каталога = 0 / Δ DDL = 0 / Δ frontend = 0 | ✅ |
| F1–F8 не сломаны | ✅ (7418/0) |
| порядок роутеров `bot.py` | ✅ (не тронут) |
| Целевые pytest | ✅ 152 passed |
| Полный pytest | ✅ 7418 passed / 0 failed |

**Approved** @Orchestrator. F9 `help-ui-v5-round1023` принят: все находки итераций 1–2 закрыты, инварианты сохранены, полный pytest зелёный. Можно переходить к T-2182 (деплой + живая приёмка).
