# QRNG P3 — селектор/fallback/нормализация (implementation)

**Дата:** 2026-11-17
**Стадия:** P3 из arch-decision `plans/features/vmq-onto-01/evidence/qrng-recovery/arch-decision-2026-11-17.md` (§3 D4/D5/D6, §6 P3).
**Требования:** `QAN-REC-REG-01` (расширение реестра), `QAN-REC-SEL-01`, `QAN-REC-SEL-02`, `QAN-REC-FALL-01`, `QAN-REC-FALL-02`; регрессия `QAN-REC-EXC-01…05`, `QAN-REC-PROV-02`, `QAN-REC-LFDR-01` (N1).
**База:** P2 approved tip `84abc2e5` (ветка `fix/qrng-p2`), не master/deployed.
**Ветка:** `fix/qrng-p3`; кандидат кода/тестов: **`d2ce1907`** (+ этот evidence-коммит).
**Статус:** REVIEW (не VERIFIED, не деплой, версия не bumped). P4/P5 не начаты.

## 1. Что сделано (ровно P3)

Один аддитивный слой в существующем `RandomSourceService` + три глобальных
параметра каталога. Второй RandomSource/store/очередь/планировщик/API ключей
не создаются, IBM job не включён (P5).

| Элемент | Назначение |
|---|---|
| `random.primary_provider` | select `ibm_quantum\|anu\|lfdr`, заводской `ibm_quantum`; категория memory, `global_only=True` |
| `random.fallback_order` | json-список, валидация: только действующие id реестра, без дублей, без primary, не длиннее реестра; порядок редактируемый |
| `random.fallback_enabled` | bool, заводской `true`; отдельная ось от PRNG |
| `keys.random_quantum_provider` | `hidden=True`: строка/значение в БД остаются, из UI/params-meta ключ исключён, ручная запись → существующий 422 |
| `ProviderResolution` + `resolve_selection()` | `selected_mode`, `primary_setting_raw/state`, `primary_provider`, `resolved_primary`, `effective_provider`, `fallback_enabled/order`, `effective_order`, `mode`, `blocker`; без расхода значений |
| `resolve_effective()` | совместимый фасад `(mode, blocker)` для существующих вызовов (новых потребителей нет) |
| `RandomStore.provider_ids` | аддитивный фильтр `reserve_draw`/`reserve_chunk`: значения берутся у выбранного провайдера, а не у «самой старой партии» любого |
| LfDR refill | `_do_lfdr_refill` через ОДИН сервисный `LfdrClient` (`set_lfdr_client`/`_get_lfdr_client`), N1 закрыт: breaker/min-interval общие между вызовами |
| `startup()`/`refill_if_needed()` | цель — первый запрашиваемый провайдер действующего порядка; ANU-путь прежний (квота/активация/fingerprint), LfDR — публичная партия с NULL-fingerprint; `mca_random_state` (ANU-scoped, G16) LfDR не пишет |
| `status_snapshot` | селектор + `prng_active`/`prng_setting`, per-provider `configured/state/consumable/quarantined/reserve`, `lfdr_state`, суммарный `reserve_remaining` |

## 2. Контракт резолва (D5/D6)

Порядок: **primary → fallback_order** (если `random.fallback_enabled`), PRNG
в порядок не входит.

- «Доступен» = сконфигурирован **и/или** имеет расходуемый запас действующей
  конфигурации (strict P1 fingerprint). `configured`: ANU — действующий ключ;
  LfDR — ключ не требуется (публичный документированный endpoint + адаптер
  P2); IBM — `false` (в P3 нет IAM/instance/CRN, P5), без фейкового зелёного.
  `state` (health) отдельно: LfDR `unverified` до первого успеха,
  `active`/`degraded` после; breaker виден в `providers[lfdr].breaker`.
- `resolved_primary` — первый доступный по порядку; `effective_provider` —
  первый, у кого есть расходуемый запас (именно он отдаст следующее значение).
- Если значения есть, но не у первого доступного — берётся следующий с
  запасом (`test_configured_primary_without_values_uses_next`).
- Ни одного с запасом: **quantum нет**. Если `memory.random_fallback_to_pseudorandom=true`
  (сохранённое значение владельца) — явный PRNG с причиной и подписью
  «псевдослучайный откат (не квантовый)»; если `false` — `deferred`
  (не quantum, не PRNG), 0 строк журнала. Скрытой подмены нет.
- K1/K2 OFF — прежняя семантика (`pseudorandom`/`disabled`, ANU-запросов нет).
- `memory.random_source=quantum|pseudorandom` сохраняет per-chat наследование;
  явный pseudorandom не расходует квантовый запас.

**Снятое значение (Lizaonair-класс, EXC-03).** Сохранённое `primary_provider`
вне реестра: `primary_setting_raw` отдаётся как есть, `primary_setting_state="requires_resolution"`,
значение **не действует** (голова порядка — канонический IBM), **не
подменяется молча** и **не перезаписывается**; действует канонический порядок
**IBM→ANU→LfDR**, сохранённый `fallback_order` под снятое значение не
применяется. Новые записи неизвестных id/алиасов → 422. История
`mca_random_batches/draws` не переписывается. Для `fallback_order` при
повреждённом сохранённом значении статус отдаёт `fallback_order_raw` +
`fallback_order_state=requires_resolution`; резолв применяет защитную
нормализацию, строка в БД не меняется.

**PRNG-дефолт.** Параметр `memory.random_fallback_to_pseudorandom` P3 **не
создаёт** (он существует с заводским `true`, у владельца сохранён `true`).
Условие D6 «заводской дефолт новых установок = false» относится к созданию
параметра; здесь оно не применимо, поэтому значение/дефолт не менялись (иначе
изменилось бы поведение установок без сохранённой строки). Сохранённое `true`
не перезаписывается — проверено тестом и `prng_setting`/`fallback_setting`.

## 3. Per-chat и RBAC

- Все три параметра `global_only=True` → `per_chat=False`; чатовая запись
  (`X-Chat-Id`) отбивается существующим 422 «ключ нельзя переносить на
  уровень чата»; чатовый админ их не видит (`GET /api/config` с чатом).
- Per-chat override провайдера **не поддерживается** (его нет в контракте).
- Запись селектора — обычное право параметра (`can_edit_param`), как у прочих
  глобальных настроек; новых ролей/матриц нет. Ключи провайдера остаются
  global-admin-only (P1 D8).

## 4. Изменённые файлы

- `services/mca_random_source.py` — селектор/резолв/фильтр провайдера/LfDR
  refill/DTO.
- `services/param_catalog.py` — 3 `ParamSpec` (memory_random, global_only),
  hidden `RANDOM_QUANTUM_PROVIDER`, правила валидации primary/order.
- `services/config_cache.py` — `_PG_ONLY_BOOL_DEFAULTS["random.fallback_enabled"]=True`
  (честная синтетика `get_all`; str/json остаются «не задано» по контракту D08).
- `services/status_service.py` — pass-through полей селектора/PRNG (R17: без
  ключей/отпечатков).
- `web/api/routes.py` — `_coerce_value` применяет правила каталога и к json;
  кросс-полевой guard `primary ∉ fallback_order` на итоговом состоянии пакета
  (осознанный 422, без тихой правки). Новых маршрутов нет.
- `plans/docs/param-registry-round1025.*`, `screen-map-round1025.md`,
  `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json` — F8-переиздание
  (`tools/_qrng_p3_reissue_f8.py`): REGISTRY 645→648, delta 244→247,
  `PARAM_CATALOG_SHA256_FOLLOWUP`/`ROUTES_SHA256_F11` переутверждены осознанно
  (L-F11S-1), hidden 16→17.
- UI (`web/app.js`, `web/index.html`, `web/static/*`) **не изменялся**.
- Тесты: новый `tests/test_qrng_p3_selector.py` (**37**); осознанные обновления
  пинов каталога (50+ файлов: счётчики 645→648 / 619→622, hidden-set, select-set,
  memory 59→62, routes-hash, namespace `random.`) и точных ожиданий
  резолва, изменившихся по контракту P3 (см. §6).

## 5. Тесты и доказательства

Артефакты в этом каталоге:

- `tests-p3.json` — полный прогон (P3 37, P1 29, P2 63, affected random/QND 296,
  mandatory 386, webapp 1455/33, JS 117/4, catalog-guards 45/1 pre-existing,
  broad-catalog 1892/26 pre-existing) + RED и мутации.
- `red-tests-84abc2e5.txt` — RED на базе: новый файл не собирается
  (`AttributeError: ... has no attribute 'SETTING_PRIMARY_PROVIDER'`).
- `red-probe-base-84abc2e5.json` / `green-probe-p3.json` — поведенческий
  пробник (исполняется и на базе): на базе нет селектора/полей статуса/каталога,
  provider-ключ не hidden, **выбор `primary=lfdr` игнорируется** (draw берёт
  старейшую ANU-партию, provider `anu`); на кандидате — provider `lfdr`,
  `resolved_primary/effective_provider=lfdr`, retired → `requires_resolution` +
  порядок IBM→ANU→LfDR без перезаписи raw.
- `mutations.json` — 9 мутаций, все убиты целевыми тестами; модули
  восстановлены (sha256 совпал): фильтр провайдера, silent-replace retired,
  per-chat accepted, скрытый PRNG, игнор fallback_order, снятая валидация id,
  one-shot LfDR-клиент (N1), fake-green IBM, подмена raw при чтении.
- `red_probe.py`, `mutation_probe.py` — воспроизводимые скрипты.

## 6. Осознанные обновления существующих ассертов

Селектор изменил точные причины отказа в мире одного провайдера — обновлены
только строки, описывавшие старый единственный ANU-контур (структурные
инварианты сохранены: deferred, 0 строк журнала, один notable-переход):

- `test_mca10a_random_source_block_a/b`, `test_qrng_p1_isolation`: при
  отсутствии ANU-ключа действующий порядок IBM→ANU→LfDR уже имеет
  сконфигурированный LfDR без значений → блокер `provider_unavailable`
  (было `provider_unconfigured`). `resolve_effective` при PRNG OFF возвращает
  `deferred` (не `pseudorandom`) — прямое требование P3.
- `test_mca10a_random_source_block_b`: LfDR-блокер **не пишет**
  `last_fallback_reason` в ANU-scoped `mca_random_state` (G16) — проверяется,
  что ANU-состояние не пачкается.
- `test_mca10a_random_source_block_c`: `keys.random_quantum_provider` скрыт →
  отсутствует в `/api/config`/params-meta (9→8), REGISTRY 648.
- `test_mca10a_random_source_block_d`: статус использует `resolve_selection`
  (детальный резолвер); monkeypatch обновлён.
- `test_cfg03_param_audit`: hidden-set +1; мёртвая ручка
  `keys.random_quantum_provider` удалена из DEAD_KNOBS (ключ стал consumed
  в P1 и теперь hidden).
- Пины каталога/маршрутов переутверждены осознанно (L-F11S-1), счётчики
  переизданы генератором.

## 7. Ограничения и передача

1. **P4:** новая страница/перенос `keys_random`/селекторные карточки не
   делались. Существующий generic-рендер параметров покажет три новые
   глобальные настройки в группе «Случайность» (Sleep-вкладка) — данные
   честные (`per_chat=false`, source default/global), но это не P4-UI;
   `web/*` не менялся. Скрытый provider-ключ в UI не появится.
2. **Live-запросы:** в P3 не выполнялись (адаптер LfDR не менялся с P2, где
   есть live-проба; ANU-клиент не менялся; ключ ANU доступен только в PG на
   проде, деплой запрещён). Живая проверка ANU действующим ключом остаётся
   последеплойной/контролируемой задачей (arch §10).
3. **Migrations/DDL:** нет; v48 не менялся.
4. **PRNG-дефолт:** см. §2 — параметр существует, дефолт не менялся.
5. **IBM:** `configured=false`, адаптера/job нет (P5); в статусе нет
   фейковых зелёных.
6. **`fallback_order` с повреждённым сохранённым значением:** защитная
   нормализация + видимый `requires_resolution`; значение не перезаписывается.
7. **Pre-existing failures** (воспроизведены на `84abc2e5`, не P3):
   `test_cfg03_param_audit::test_visible_dead_knobs...` (мёртвая ручка
   `flags.dig_pre_gate_enabled` — P1 сделал provider-ключ consumed);
   26 в broad-catalog, 33 в webapp-batch, 4 JS-файла — те же node id на базе.

## 8. Rollback

`git revert` коммита P3: параметры/резолв/фильтр исчезают, P1/P2-код остаётся
работоспособным; сохранённые строки `random.*` остаются неиспользуемыми
(старый код их не читает), данные и схема не затрагиваются. Немедленный
безопасный откат поведения без ревёрта: `random.primary_provider=anu` +
`random.fallback_enabled=false` → эквивалент 2.58.213 (ANU-запас; PRNG только
при сохранённом `memory.random_fallback_to_pseudorandom=true`).
