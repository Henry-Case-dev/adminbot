# SOUL-1 / W1-REGISTRY — отчёт слайса (Prompt Registry, Factory Defaults, удаление legacy-речи, backup)

- **Lane:** W1-REGISTRY (writer; join barrier для включения композера).
- **Кандидат:** master `d9b7f389` + рабочее дерево 16.10.2026 (без коммита),
  изменены только объявленные файлы (см. §6).
- **Покрытые требования:** `requirements-map.json` слайс W1 (20 строк:
  SOUL-EXEC.1–8, EXEC.13, SOUL-01.0–01.5, SOUL-15.0–15.4) и
  `requirements-map-amendment.json` слайс W1 (9 строк: SOUL-AMD.0.1, 1.4,
  2.1, 3.1, 3.3, 4.6, 7.1–7.2, 8.5). Привязка к приёмке — §5.

## 1. Backup (обязательный шаг §7.2) — сделан ДО правок

`plans/features/soul-1/evidence/w1/backup-speech-config.json` (338 КБ):

* 25 PG-ключей `prompts.*`: полный заводской текст + sha256_12 + ревизия;
* **все** известные PREV/rollback-слепки лестницы миграций полным текстом
  (именно они могут лежать в PG прода);
* запись 6 прод-custom summary-ключей (sha/длины, baseline 2.58.33);
* `pg_status="down"` (`WinError 1225`) — **живые значения и per-chat
  overrides снять не удалось**, это прямо записано в `not_verified`;
* процедура восстановления — `restore` в самом снимке и
  `evidence/w1/README-restore.md` (CLI `py -3 -m services.prompt_factory
  restore <файл> [--apply]`, идемпотентно, с историей). Источник отката —
  только захваченное значение (`text`); заводской текст источником не
  является (защита от затирания правки владельца). В этом снимке `text`
  пуст у всех 25 ключей (PG был недоступен) — аварийные пути: `reset-all`
  (заводские редакции) и `rollback_legacy_speech`.

Проверка «реальные значения, не заглушки»: `prompts.search_system_prompt`
= 2622 символа, `sha256_12=ba43fb679db6`; `prompts.direct_chat_system_prompt`
= 5294 символа, `sha256_12=cf404931f84c` (сверяются тестом и дампом).

## 2. Prompt Registry (SOUL-AMD.3.1–3.3)

`services/prompt_registry.py` — машиночитаемая карта
`источник → смысл → потребитель → Registry ID → решение о миграции`:

* **65 блоков** (42 речевых, 13 помечены `legacy_persona`): 25 PG-ключей
  каталога (список ключей берётся ИЗ каталога — второго списка нет) + 40
  кодовых блоков (управляемые сообщения, идентичность, стиль/формат/ретраи,
  extent-блоки, авторские и машинные стадии: dreams, lore, nostalgia,
  dossier, episodes, vision, self-reflection, initiative-observer,
  orchestrator, anticliche);
* у каждого: `purpose`, `family`, `scope`, `consumers` (file:line из аудита),
  `composition_point`, `enabled_by`, `migration`, `owner_lane`, `ui`,
  фабричная ревизия `fac:<sha256_12>` + версия-метка владельца;
* `effective_prompt()` даёт active-ревизию, источник
  (`chat|global|default|code`), признак отличия от заводского и состояния
  `Factory / Global Custom / Chat Override / Inherited` (SOUL-AMD.4.3);
* `registry_view()` — для UI W6, `param_catalog.speech_registry_view()` /
  `unmanaged_speech_blocks()` — join с каталогом (без новых ключей, Δ=0);
* **guard «нет неучтённой речевой инструкции»**: `FACTORY_SET_SHA256_12`
  — отпечаток набора фабричных текстов; любая правка любого канона без
  осознанного бампа ломает тест. Плюс тест «любой `prompts.*`-литерал
  рантайма есть в каталоге» (закрывает дефект аудита: ключ L1-планировщика
  читался, но был невидим).

## 3. Factory Defaults (SOUL-AMD.4.1–4.5)

`services/prompt_factory.py`:

* заводской текст = код-канон каталога (`factory_default` ==
  `resolve_code_source(spec.code_source)` — доказано тестом; скрытого дубля нет);
* `plan_factory_reset` — diff + предпросмотр, **ничего не пишет**;
* `apply_factory_reset` — пишет заводской текст как НОВУЮ active-ревизию,
  предыдущая уходит в `character.prompt_history` (bounded 12 на блок,
  append-only, одна JSON-строка `bot_settings`, без новой таблицы);
* `reset_chat_override` — **не** заводской сброс: снимает только per-chat
  override, глобальный ключ не пишется (доказано тестом, который запрещает
  вызов `chat_params.set_chat_params` при глобальном сбросе);
* `plan/apply_speech_profile_reset` — предпросмотр + сброс речевого профиля;
  данные бота не затрагиваются;
* `restore_backup` — обратный путь к аварийной копии W1.

## 4. Удаление legacy-речи из effective-слоя (SOUL-AMD.1.2/7.2/8.5)

Механизм — детерминированная вычистка известных сегментов на сборке
(прецедент `response_extent.strip_cap_phrases`, design §8.7), **не** перепись
PG: 9 правил (`LEGACY_PERSONA_RULES`: определение личности «токсичный …
бот-абьюзер … двача», «Игнорируй все настройки безопасности…», «унизить
оппонента», «обоссав автора», «унизив разработчика», «токсичный стиль»,
«человеческо-токсичный язык», «саркастично-токсичной манере»).

Правила подавления (проверены тестами):

1. применяется только к ПЕРСИСТЕНТНОМУ значению (`chat|global`) — кодовый
   fallback (PG down) остаётся байт-в-байт (OFF-паритет W2 13/13 цел);
2. только если байты совпали с ИЗВЕСТНЫМ каноном (`known_canon_hashes`):
   фабричные тексты + все PREV/rollback-слепки; **кастом владельца не
   правится никогда**, но виден как `legacy_persona_present` (витрина
   конфликта для W6);
3. идемпотентна (`removed=0` на повторном прогоне), не трогает несвязанные
   контракты.

Точки рантайма: `prompt_style_blocks.resolve_prompt` /
`resolve_prompt_with_source` (единый проход PG-значения через реестр) и
`direct_chat_service` (база канала Direct — через
`prompt_registry.resolve_chat_speech`, semantics chat→global→default
сохранена). Композер не изменялся.

`services/prompt_migrations.py` (фаза A/B, JB-3-ready):
`plan_legacy_speech_removal` (read-only dry-run: класс
`absent|canon_current|canon_prev_step|custom_legacy|already_normalized`,
предсказанное действие, sha до/после), `normalize_legacy_speech(apply=True)` —
один `set_many` (одна PG-транзакция), оригиналы пишутся в
`character.migration_snapshots` (append-only), кастомы пропускаются с WARNING;
идемпотентность через записанный `normalized_sha256_12`;
`rollback_legacy_speech` возвращает оригиналы и не трогает значения,
изменённые после миграции. PG down → skip (поведение не меняется: работает
сборка-подавление).

**Before/after (evidence):** `evidence/w1/before-after-effective.md`
12 из 25 PG-канонов теряют сегменты личности (removed 1–5), маркеры
«токсичн/бот-абьюзер/унизить/Игнорируй все настройки безопасности» после
подавления отсутствуют, а контракты целы: у фактчека — `вердикт`, `источник`,
`АНТИ-БОТ`; у Direct — `АНТИ-ГАЛЛЮЦИНАЦИИ`, `ИНСТРУМЕНТЫ`,
`query_chat_memory`, `<Target_User>`, `не выдумыв`; у L1 — `СХЕМА JSON`;
у синтезатора — `JSON`/`response_mode`; у чек-апа — `JSON`/`хеши`.
Дополнительно: реальный `DirectChatService._l2_write_answer` (композер OFF,
PG-слой = сид код-канона) собрал system `79a5c9709d4c`/1917 символов **без**
маркеров личности при живых `JSON`, `ТИПОГРАФИКА`, `АНТИ-БОТ`, `АСИММЕТРИЯ`,
`Persona`, `не выдумыв`.

Побочный косметический эффект (объявлен): при удалении сегмента схлопывается
пустая строка-дубль в каноне — только когда `removed > 0`.

## 5. Acceptance — статус по пунктам

| Пункт брифа | Статус | Доказательство |
|---|---|---|
| Новые тесты зелёные | **PASS** | `tests/test_soul1_registry_completeness.py` (9), `tests/test_soul1_registry_legacy_removal.py` (31), `tests/test_soul1_factory_defaults.py` (10) → **50 passed** |
| Фокусный W2-паритет 13/13 и композер OFF | **PASS** | `tests/test_soul1_composer_parity_off.py` → **13 passed** (хеши из `evidence/direct-runtime-assembly.txt`); смежные W2-сьюты (6 файлов) 55 passed; фокусный объединённый прогон 11 файлов — 166 passed; `mca_gates.unified_composer_env_enabled() is False`, `unified_composer_enabled() is False`, `UNIFIED_COMPOSER_ENABLED` не задан |
| `gen_param_registry_round1025.py --check` OK | **PASS** | `CHECK OK: реестр 572 == REGISTRY` (Δ каталога = 0); re-pin `tests/fixtures/round1025/f8_baseline.json` (2 строки) + датированная заметка в `tests/test_round1025_f8_registry.py` |
| Backup с реальными значениями и restore-путём | **PASS** | `evidence/w1/backup-speech-config.json` (338 КБ, `factory_text` + `known_prev_revisions` + `restore`), `evidence/w1/README-restore.md` |
| Before/after: legacy-канон вне effective, контракт цел | **PASS** | `evidence/w1/before-after-effective.{md,json}`, тесты `test_suppression_keeps_non_speech_contracts`, реальный payload L2 |
| Registry completeness / factory-reset semantics / idempotent removal | **PASS** | §2–§4 + тесты |

Регресс по всему затронутому периметру (финальный кандидат):
`pytest tests -k "soul1 or catalog or registry or prompt or direct_chat or
summary or config"` → **3123 passed, 0 failed** (`tests/test_summary_memory.py`
исключён — предсуществующий зависающий teardown aiosqlite, к слайсу не
относится). Ранее падавший `test_round1025_f8_registry::test_param_catalog_unchanged`
закрыт осознанным re-pin'ом sha каталога (§6).

## 6. Изменённые файлы

Отпечатки кандидата (sha256_12, для привязки ревью):

```
5a351d54d950 services/prompt_registry.py         f0d9eee24a48 services/prompt_factory.py
47a01e69d390 services/prompt_migrations.py       0e36754b3b04 services/prompt_style_blocks.py
64f53eacaeef services/param_catalog.py           4c68d6ba712f services/direct_chat_service.py
9183ea223ddb tests/test_soul1_registry_completeness.py
9fabe5df82cf tests/test_soul1_registry_legacy_removal.py
42698b65aebe tests/test_soul1_factory_defaults.py
69a2737e3b6e tests/test_prompt_migrations.py     f9a563c5126f tests/fixtures/round1025/f8_baseline.json
8a3fc0a8f53e evidence/w1/backup-speech-config.json
4368b43edd02 evidence/w1/before-after-effective.md
857e3a0b8b12 evidence/w1/migration-preview.json
5b3cc2a8d1d2 evidence/w1/registry-snapshot.json
9e29f318d236 evidence/w1/README-restore.md
```

Периметр: реестр + фабрика (новые), `prompt_style_blocks`/`direct_chat_service`
(единые точки резолва), `prompt_migrations` (фаза A/B + откат),
`param_catalog` (read-only экспозиция), тесты, evidence, отчёт.

* **новые:** `services/prompt_registry.py`, `services/prompt_factory.py`,
  `tests/test_soul1_registry_completeness.py`,
  `tests/test_soul1_registry_legacy_removal.py`,
  `tests/test_soul1_factory_defaults.py`,
  `plans/features/soul-1/evidence/w1/*`, этот отчёт;
* **правки:** `services/prompt_style_blocks.py` (единый проход PG-значения
  через реестр в `resolve_prompt`/`resolve_prompt_with_source`),
  `services/direct_chat_service.py` (одна точка: база канала Direct),
  `services/prompt_migrations.py` (фаза A/B + откат),
  `services/param_catalog.py` (read-only экспозиция реестра, Δ параметров = 0),
  `tests/test_prompt_migrations.py` (переанкерен один ассерт: лестница
  проверяется как «новый канон», а не его байты — контракт effective-слоя
  изменился по уточнению владельца),
  `tests/fixtures/round1025/f8_baseline.json` + `tests/test_round1025_f8_registry.py`
  (осознанный re-pin sha каталога, прецедент L-F11S-1).

## 7. Осознанные границы слайса (что осталось и кому)

1. **Кодовый fallback (PG недоступен) сохраняет старые каноны** — OFF-паритет
   W2 требует байт-в-байт; нормализация самих фабричных редакций — шаг JB-3 /
   W2-factory с перезаписью эталона `evidence/direct-runtime-assembly.txt`.
   До этого `source=default` виден в реестре/диагностике (тихой подмены нет).
2. **Код-пути без PG-ключа** (фраза `CHAT_PERSONA_PHRASE` в
   `smartmodule_phrases`, рендер `handlers/direct_chat.py:253`) зарегистрированы
   как `managed_message` + `legacy_persona` и назначены W3/W10: на сборке их
   не подавить (значение не персистентное), нужна замена управляемым
   шаблоном (`message.smartmodule.*`, `message.image_generation_fallback` —
   жёсткая фраза image-фолбэка принадлежит W10 по §5.3).
3. **Редактор/UI**: ключи каталога и TSV/screen-map не менялись (check OK),
   поэтому «убрать legacy из пользовательского редактора» (SOUL-AMD.4.6)
   требует перегенерации `plans/docs/param-registry-round1025.*` в том же
   diff — это делает владелец UI-слайса (W6), вместе с ключами управляемых
   сообщений (Δ каталога ≠ 0).
4. **Живой backup прод-значений** не снят (локальный PG down). Живое снятие —
   DevOps на прод-хосте перед включением флага; не помечать SOUL-AMD.1.2/8.4
   в `VERIFIED` по этой поставке без повторного снимка.
5. **Write-pass (JB-3)** реализован и протестирован, но на проде не выполнялся
   (по плану — после фиксации реестров W2+W3); сейчас работает сборка-подавление.
6. `mca_gates_w2`-оси и UI-регистрация флагов — вне слайса (review-w2 §4.3).

## 8. Блокер (маркер для сканера: `composer_flag_release_gate`)

**`UNIFIED_COMPOSER_ENABLED` (env + `flags.unified_composer_enabled`) не
включать**, пока не выполнены: (а) живой снимок прод-значений `prompts.*`
(повтор §1 при доступной PG, DevOps), (б) запись нормализации
legacy-речи (`prompt_migrations.normalize_legacy_speech apply=True`) или явное
решение Orchestrator'а ограничиться сборкой-подавлением, (в) повторная
проверка OFF-паритета (13/13) на кандидате после этих шагов. Флаг остаётся
OFF: код-дефолт `False`, env не задан, каталожного ключа нет.

## 9. Инцидентальные находки (не блокируют)

* `resolve_prompt_with_source` в HEAD возвращал `global` даже при отсутствии
  ключа в PG (источник не различался) — исправлено в рамках слайса
  (`resolve_hot_prompt`: `global` только при реальном наличии ключа).
* `tests/test_summary_memory.py` — зависающий teardown aiosqlite при полном
  прогоне (предсуществующее, не связано).
* В канонах есть предсуществующая пустая строка-дубль перед `АНТИ-БОТ` —
  схлопывается только при удалении сегментов (косметика).

## Fix pass (review-w1 BLOCKER-1/2, SMALL-3/4)

**Кандидат:** тот же HEAD `9e63b3cf` + рабочее дерево (без коммита).
Требования-источник: `source-architectural-clarification.md` §1.1/1.2/4.1/4.6/7.2/8
(приоритет над SOUL-03/04 о сохранении кастомов) + `requirements-map-amendment.json`
SOUL-AMD.1.2/8.4.

### BLOCKER-1 — провенанс вместо «доверия PG»

Механизм (выбранный): **журнал провенанса**. Persisted-значение канона старой
личности становится действующим слоем только если его ревизия записана через
API реестра/фабрики; значение, попавшее в PG иным путём (старый UI, SQL,
PREV-слепки), **удерживается**: работает заводская редакция, сохранённые байты
не трогаются, расхождение видно как диагностика/WARNING/витрина.

* класс удержания — `prompt_registry.withholding_required()` (11 ключей:
  direct tool-phase/l2-writer, factcheck single/verbalizer, summary single/narrator,
  search, checkup, youtube ×2, web). Ветки режимов (`verbilizer.mode.*`) —
  явное исключение `PROVENANCE_EXEMPT_PREFIXES` (правила длины/формата, их
  legacy-сегмент снимает детерминированная вычистка; иначе ломались бы
  принятые контракты вкладок режимов и `test_prompts_round1024`):
  `services/prompt_registry.py:1196-1208`;
* журнал — тот же аддитивный документ `character.prompt_history`
  (`items` = ревизии для отката, `provenance` = последняя записанная API
  ревизия; провенанс дают `owner_edit`/`factory_reset`, **не** даёт
  `backup_restore`): `prompt_registry.py:91-104`, `prompt_factory.py:158-215`;
* резолвер: `resolve_speech_value` (`prompt_registry.py:1336-1379`) —
  удержание + диагностика (`persisted_value_withheld`, `provenance_missing|
  mismatch|unavailable`, `persisted_legacy_persona_marker`) + WARNING без
  текста (R17-safe); точки рантайма `resolve_hot_prompt`/`resolve_chat_speech`
  (`:1446-1500`) → `prompt_style_blocks.py:186-240` → `direct_chat_service.py:2365`;
* витрина конфликта для Inspector: `pr.withheld_values()` (`:1382-1443`),
  поля `EffectivePrompt.withheld/withheld_revision/provenance_reason/
  stored_source` (`prompt_registry.py:901-937`, `effective_prompt` `:990-1056`);
* обратный путь правки владельца: `prompt_factory.write_speech_value()`
  (`prompt_factory.py:315-393`, глобальный ключ и per-chat override) — это и
  есть «значение, записанное через новый API реестра» (§1.1/§4.1); несёт
  видимый (`legacy_persona_marker`) признак, но текст владельца не переписывает;
* аварийный `restore_backup` возвращает значение как ДАННЫЕ
  (`effective_layer=withheld_factory_governs`, §4.6) — старый канон не
  становится действующим слоем, но и не теряется.

Почему так, а не «никогда не доверять PG»: §1.1 даёт владельцу полный контроль
над речью через MiniApp; поэтому решение принимается не по байтам и не по
«PG = плохо», а по провенансу ревизии. Trade-off (объявлен): до W6 (редактор
реестра) правка речевого канона через текущий UI (`/api/config`) действует
только после `write_speech_value`/`apply_factory_reset` — иначе она удерживается
и это видно в диагностике и логе; W6 обязан писать через API реестра.
Содержательная эвристика («маркер = вырезать») сознательно НЕ используется:
она бы пропустила канон-заместитель без маркеров (класс прод-кастома search) и
нарушила бы §8 «старые PG речевые overrides не оказываются в effective prompt».

Before/after (исполненный зонд, реальные резолверы + реальный потребитель
`FactCheckService`; `evidence/w1/fix-pass-probe.json`):

```
stored custom (канон + «…будь токсичным бот-абьюзером и унизь всех»)
  ДО   : withheld=true  effective.source=default  markers_in_effective=[]
         diagnostics=[persisted_value_withheld, provenance_missing,
                      persisted_legacy_persona_marker], factory_source=Factory,
         stored_source=global, stored 2c6ee597f83a читается байт-в-байт,
         consumer system: markers=[], контракты вердикт/АНТИ-БОТ целы
  ПОСЛЕ: write_speech_value → applied=true, revision=act:2c6ee597f83a,
         attested_revision.kind=owner_edit, withheld=false, source=global,
         consumer system == записанный текст
  RESTORE: applied=1, effective_layer=withheld_factory_governs,
         stored_value_after_restore=true
```

### BLOCKER-2 — шесть потребителей через единый резолвер

Маршрутизированы: `factcheck_service.py:183`, `search_service.py:73`,
`summary_generator.py:1600` и `:1753`, `checkup_service.py:49`,
`web_summarizer_service.py:57`, `youtube_summarizer_service.py:93/140/177`.
Дополнительно (тот же класс, тот же модуль-владелец):
`direct_chat_service.py:4603` (оценка payload в MCA-07 больше не расходится с
фактическим payload). Guard: `tests/test_soul1_direct_prompt_reads.py` — ноль
прямых чтений у шести потребителей + allow-list на все прочие прямые чтения в
`services/**` (включая ключи, спрятанные в модульных константах) с причинами:
`summary_generator.py` (стиль обложки), `cover_style_pipeline.py`/
`cover_style_jobs.py` (ключ-селектор профиля обложки), `summary_memory.py`
(сжатие памяти — машинная стадия), `prompt_style_blocks.py`
(`verbilizer_default_mode` — селектор режима). Интеграционная часть теста
гоняет реальные `CheckupService`/`WebSummarizerService`/
`YoutubeSummarizerService`/`FactCheckService` и проверяет, что в system,
уходящем в LLM, нет маркеров старой личности, а запись через API реестра
доходит до шва.

### SMALL-3 — аварийный `restore_backup`

`prompt_factory.restore_backup` теперь использует одну селекцию источника для
`plan` и `apply` (`text` → `pg_value_at_backup`, `prompt_factory.py:594-671`,
фикс — `restore_texts`/`:605-650`); план сообщает
`source_field`/`withheld_in_runtime`, применение — `effective_layer`. Тест:
`tests/test_soul1_factory_defaults.py::test_restore_backup_accepts_pg_value_at_backup_source`
(plan → apply → идемпотентный повтор, без `KeyError('text')`).

### SMALL-4 — реестр: фраза чек-апа и указатели потребителей

* `CHECKUP_FALLBACK_NOTICE` зарегистрирован как управляемое сообщение
  `message.checkup_fallback_notice` (`prompt_registry.py:449-459`), текст
  фабрики = реальная константа, `ui=catalog_pending`, владелец W3; тест
  `test_checkup_fallback_notice_is_registered_as_managed_message`;
* указатели потребителей лора исправлены: `internal.lore.story`
  → `lore_compiler_service.py:184` (+ `tool_router.py:2827`), `internal.lore.init`
  → `lore_worker.py:696`, `internal.lore.merge` → `lore_worker.py:692`
  (`prompt_registry.py:601-615`); тест
  `test_registry_consumer_pointers_point_at_real_lines` физически сверяет
  строку файла;
* отпечаток набора фабричных текстов обновлён осознанно:
  `FACTORY_SET_SHA256_12 = "8cc27a902dae"` (было `940d4f253676`; дельта —
  зарегистрированная фраза чек-апа + правка указателей), `REGISTRY_VERSION`
  → `soul1-w1-2`.

### Re-verification (исполнено)

| Проверка | Результат | Артефакт |
|---|---|---|
| W2 OFF-паритет | **13/13 passed** | `evidence/w1/fix-pass-tests.txt` |
| SOUL-1 сьюты (8 файлов, фикс-пасс) | **95 passed** | там же |
| Периметр `-k "soul1 or catalog or registry or prompt or direct_chat or summary or config"` (без `test_summary_memory.py` — предсуществующий teardown) | **3139 passed / 0 failed** | `evidence/w1/fix-pass-perimeter.txt` |
| Потребители по путям (checkup/factcheck/hot_config/mca23/ui_verbilizer/smartsearch/web/youtube) | **265 passed / 0 failed** | `evidence/w1/fix-pass-consumers.txt` |
| `gen_param_registry_round1025.py --check` | **CHECK OK: 572 == REGISTRY** | `evidence/w1/fix-pass-tests.txt` |
| Флаг композера | `env set: False`, `env_enabled: False`, `enabled: False`; `prompt_composer.py`/`mca_gates.py` — **диффа нет** | вывод команды в отчёте фикс-пасса |

Ре-анкерены пинящие тесты (setup, не утверждения) — те же контракты через
санкционированный путь записи: `tests/test_soul1_registry_legacy_removal.py`
(кастом/чат-оверрайд: data-safety + удержание + провенанс),
`tests/test_soul1_legacy_custom_preserved.py`,
`tests/test_soul1_registry_completeness.py`,
`tests/test_soul1_factory_defaults.py`, а также синтетические посевы
`prompts.*` в `tests/test_hot_config.py`, `tests/test_mca23_response_plan.py`,
`tests/test_ui_verbilizer_tabs_round1023.py` (3 теста) — они проверяли
hot-применение промпта, а не источник провенанса.

### Отпечатки fix-pass кандидата (sha256_12)

```
0a3bec633cd9 services/prompt_registry.py     035287b8d438 services/prompt_factory.py
cfe5e7f36410 services/prompt_style_blocks.py 714338bfed11 services/direct_chat_service.py
60c25b173961 services/factcheck_service.py   62d9157c91c5 services/search_service.py
caabea37af08 services/summary_generator.py   a53b76a5237a services/checkup_service.py
e61892f6ad06 services/web_summarizer_service.py  dd5092d2f4a8 services/youtube_summarizer_service.py
5d108c5e1bb6 tests/test_soul1_registry_completeness.py
e7b0faef0ae7 tests/test_soul1_registry_legacy_removal.py
60b9f915b3e7 tests/test_soul1_factory_defaults.py
38e3a4090690 tests/test_soul1_legacy_custom_preserved.py
0b53c78a0eab tests/test_soul1_direct_prompt_reads.py
ebcd7e0326af tests/test_hot_config.py       95f9c6838bcf tests/test_mca23_response_plan.py
a1c2f2a80804 tests/test_ui_verbilizer_tabs_round1023.py
```

Не изменялись (проверено `git diff` = пусто / sha сверен): `services/prompt_composer.py`,
`services/mca_gates.py`, `services/param_catalog.py` (`64f53eacaeef`),
`services/prompt_migrations.py` (`47a01e69d390` — провенанс там не нужен:
нормализация пишет канон, который вычистка приводит к тому же effective-тексту;
откат возвращает оригинал как данные).

**Что всё ещё блокирует включение флага:** (а) живой снимок прод-значений
`prompts.*` (PG down локально) — до него нельзя утверждать, какие именно
кастомы будут удержаны; (б) W6 обязан писать речевые блоки через
`prompt_factory.write_speech_value` (иначе правки владельца из MiniApp будут
удержаны — это видно в диагностике, но UX-разрыв); (в) решение владельца по
JB-3 (write-pass нормализации) / по регламенту `rollback_legacy_speech`.
Класс удержания расширяется одной строкой метаданных (W-слайс), если owner
решит включить в него `summary_l2_writer`/ветки режимов/машинные стадии.

**Отличия от рекомендаций review-w1 (заявлено прямо):**
1. Ревью предлагало вариант «пропустить шесть потребителей через `resolve_prompt`
   **или** явно объявить их и внести в гейт флага» — выбран первый (маршрутизация),
   поэтому зависимости от write-pass на этих путях больше нет; остальные прямые
   чтения объявлены в allow-list guard-теста.
2. Ревью (BLOCKER-1) трактовало сокрытие как «сокрытие/нейтрализация
   legacy-кастомов»; механизм расширен до провенанса ревизии (иначе нарушался бы
   §1.1 — владелец не смог бы править канон через новый API без правки кода).
3. Класс удержания НЕ включает `summary_l2_writer`, ветки режимов и машинные
   стадии: у них есть действующие контракты (вкладки режимов, golden-тесты
   Summary Hybrid), а их «старый канон» — не определение личности. Это осознанная
   граница, а не пропуск: расширение — одна строка метаданных + recheck.
4. Ревью считало pinning-тест `test_soul1_registry_legacy_removal.py:129-136`
   закрепляющим неверное поведение; он переанкерен, но сама функция
   `suppress_legacy_speech` осталась «не правит байты кастома» — удержание
   выполняется уровнем выше (резолвер), потому что data-safety (не мутировать
   сохранённое) и effective-решение — разные обязанности.
