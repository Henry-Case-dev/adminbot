# Отчёт ревью — F9 `disk-space-audit-retention-round1024`

**Итоговый статус: Approved** (итерация 2, коммит `07644db`).
Итерация 1 (коммит `c437270`) — **Changes Requested**, все findings закрыты; см. раздел
«Итерация 2» ниже. Раздел «Итерация 1» оставлен как исторический контекст.

> Примечание: исправления F9 (`07644db`) лежат поверх F17 (`ca40e0f`). Всё, что относится к
> `smart_cache`/`SMART_CACHE_LOCK_RESILIENCE_ENABLED`, — это F17 и к F9 не приписано.

---

# Итерация 2 — повторный аудит (коммит `07644db`)

## Проверка закрытия findings итерации 1

| # | Находка (iter1) | Статус | Доказательство |
|---|---|---|---|
| High-1 | sniff fail-open на `OSError` | **Закрыта** | `disk_retention.py::_looks_like_history` — `except OSError: return True`; тест `test_unreadable_jsonl_is_history` (нейтральное имя + monkeypatch `open` → `OSError` → `immutable`, не в плане). |
| High-2 | `apply_cleanup` доверял входному плану | **Закрыта** | `apply_cleanup` — `path.exists()` → `classify(path)` перед `unlink`; `immutable`/любое исключение → `blocked`, WARNING, файл не удаляется. Тест `test_apply_blocks_immutable_item_in_plan` (ручной «злой» план с `imported_history_*.jsonl` → `blocked=1, deleted=0`, файл цел). |
| Medium-3 | CLI-дефолт ≠ рантайм (hot-config) | **Закрыта** | Общий `resolve_backup_dir()` (hot→settings); `default_dirs()` делегирует. Тесты `TestDefaultDirs` (hot-резолв + fallback). Формула идентична `memory_backup`/`memory_rebuild`. |
| Medium-4 | лживый `MEMORY_BACKUP_KEEP` | **Закрыта** | Описание в `param_catalog.py` переписано: «НЕ действует … хранится ровно 1 … значение игнорируется»; комментарий в `settings.py`. Ротация по-прежнему жёстко 1. |
| Medium-5 | `_history_immutable()` — мёртв, тест тавтологичен | **Закрыта** | `classify()` вызывает `_history_immutable()`; однократный WARNING через `_log_retention_warned`; тест проверяет и игнор флага, и наличие WARNING (`caplog`). |
| Medium-6 | `LOG_RETENTION_DAYS` без потребителя | **Закрыта** | `audit()` → `log_retention_days`; `log_retention_days()`, `journald_config_snippet()`; runbook `docs/runbook-disk-retention.md`; CLI печатает `log_retention_days=7`. Тесты `TestLogRetention`. |
| Low | мёртвый код/тавтологии/число тестов | **Закрыта** | Удалены `import os`, `RetentionDisabled`, `JSONL_ROTATE_PATTERNS`; `_db_keep()` → явный `return 1`; `forecast_monthly` дополнен `method`/`files`/`immutable_bytes` + документированная методика; сквозной тест `test_sniff_history_excluded_end_to_end`. |

## Инвариант «история неприкосновенна» — теперь абсолютный (fail-closed)

Проверено отсутствие любого пути удаления истории:
- `plan_cleanup` — immutable исключён (`classify`).
- `apply_cleanup` — **барьер re-classify**: `immutable` блокируется, любое исключение классификации
  трактуется как `immutable` (fail-closed). Примитив удаления не доверяет плану.
- `_looks_like_history` — `OSError` → `True` («возможно история»).
- `prune_db_backups` (`*.db`) и `prune_facts_exports` (`facts_*.txt`) физически не матчат `*.jsonl`.
- Deny-list по имени (`imported_history`, `raw_history`, `chat_history`, …) + content-sniff
  (`messages` / `text`+мессенджер-ключ).

Вывод: для известного формата (и любых нечитаемых/неизвестных по содержимому файлов) удаление
неприкосновенной истории невозможно. Остаточный риск — только sniff-эвристика для *ненайденного*
синтаксиса произвольных дампов без deny-имени (см. «Остаточные замечания»).

## Контракт

- High-1/High-2 — закрыты по существу, покрыты тестами. ✔
- Medium-3/4/5/6, Low — закрыты. ✔
- Тесты не тавтологичны: `test_hard_even_if_flag_false` теперь проверяет WARNING и игнор флага;
  `test_apply_blocks_immutable_item_in_plan` и `test_unreadable_jsonl_is_history` бьют в сам механизм.
- `imported-history-immutable`: **абсолютный, fail-closed**. ✔
- «1 бэкап БД обоих префиксов»: ✔ (`prune_db_backups(keep=1)` из обоих call-site).
- non-history JSONL 180д / facts 1 / логи 7д: ✔ (логи — параметр + сниппет + runbook).
- `audit`/`plan_cleanup` read-only: ✔; `apply_cleanup` fail-closed verify: ✔.
- R16/17/18: в выводе/логах только имена/размеры/счётчики; egress-тест (g) зелёный; runbook без секретов
  (только серверный путь/команды). ✔
- Δ DDL = 0: миграции не трогались. ✔
- Δ каталога = 0: новые флаги — `ClassVar`; `param_catalog` — правka только текста описания
  (структура не менялась). ✔
- `parse_mode=None`, `physical-two-call`: не затронуты.
- F1/F2/F7/F8/F12/F17/F20/F21/F22: регрессий нет — полный pytest зелёный.

## Тесты / полный прогон

- Целевой: `tests/test_disk_retention_round1024.py` — **31 passed**; вместе с `test_memory_backup.py` — 38 passed.
- Полный: **`7657 passed, 0 failed`** (1 warning — Starlette deprecation, не связано).
- Наблюдение: один промежуточный прогон завершился с дампом `pytest-timeout` (зависание, вероятно
  flaky, к F9 не относится); последующий полный прогон — 7657 passed, 0 failed, воспроизвести не удалось.

## Остаточные замечания (Low, не блокируют)

1. CLI `disk cleanup --apply` печатает `deleted/bytes_freed/skipped/errors`, но не `blocked`.
   В штатном потоке `blocked==0` (plan_cleanup immutable не выдаёт), но для наблюдаемости стоит печатать.
2. `resolve_backup_dir()` вынесен в `disk_retention`, однако `memory_backup`/`memory_rebuild` сохранили
   собственные (идентичные по формуле) резолверы — дублирование; «общий» резолвер фактически не переиспользован.
3. При изменении `LOG_RETENTION_DAYS` сниппет `journald_config_snippet()` подстроится, а runbook
   жёстко содержит `7d`/`500M` — возможен дрейф документации.
4. Sniff-эвристика покрывает известный формат (`text` + мессенджер-ключ, `messages`). Произвольный
   дамп переписки в ином синтаксисе и без deny-имени теоретически может не опознаться — но это
   свойство выбранного spec-подхода (deny-list+sniff), а не дефект реализации.

**Статус: Approved.**

---

# Итерация 1 — исходный аудит (коммит `c437270`)

**Статус итерации 1: Changes Requested**

## Резюме (без смягчения)

Функциональное ядро F9 сделано правильно и решает корневую причину +6 ГБ: `prune_db_backups`
действительно покрывает **оба** префикса (`local_database_*` + `memory_rebuild_*`), держит ровно
1 новейший и вызывается из обоих мест (`memory_backup._rotate`, `memory_rebuild.create_safety_backup`).
Инвариант «история неприкосновенна» для **известного** формата (`imported_history_*.jsonl`) соблюдён
и на имени, и на содержимом. Однако модуль, который стоит последней линией защиты перед
**необратимым удалением неприкосновенных переписок**, содержит fail-open ветку и доверяет входному
плану «на слово». Этого достаточно для отклонения: политика владельца сформулирована как
«удалять КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО», а значит любая ошибка чтения обязана трактоваться как «не трогать»,
а не как «не история — удалить». Плюс есть функциональный баг с дефолтным каталогом CLI и «мёртвые»/
лживые параметры, вводящие оператора в заблуждение.

---

## Findings

### [Severity: High]
File: `services/disk_retention.py`
Location: `_looks_like_history` (:121–150, ключевое — :148–149)
Problem: при `OSError` (нет прав, transient I/O, повреждённый inode) функция возвращает `False` —
то есть «это не история». Дальше `classify` отдаёт `jsonl_retention`, и файл старше 180 дней попадает
в `plan_cleanup` → `apply_cleanup` делает `unlink`. Если дамп/архив сырой переписки имеет имя вне
deny-list (`HISTORY_DENY_NAME_MARKERS`) и в момент сканирования не читается, он **будет удалён**.
Why it matters: это ровно тот сценарий, от которого владелец защищался словами «если есть файловые
архивы сырых переписок — они неприкосновенны» и «удалять КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО». Потеря архива
переписки необратима (spec §10: восстановление только из внешних бэкапов). Модуль удаления обязан
быть fail-closed (spec §8 R1), а здесь он fail-open на самой чувствительной ветке.
Required fix: в `_looks_like_history` при `OSError` возвращать `True` (трактовать как потенциальную
историю), либо ввести тристейт `unknown` и в `plan_cleanup` исключать `unknown` из кандидатов.
Добавить тест: нечитаемый (`chmod 000`/monkeypatch `open` → `OSError`) `.jsonl` с нейтральным именем
НЕ удаляется.

### [Severity: High]
File: `services/disk_retention.py`
Location: `apply_cleanup` (:394–404)
Problem: единственная защита неприкосновенности реализована в `plan_cleanup` (:344–348), а сам
деструктивный примитив `apply_cleanup(plan)` не перепроверяет категорию. Любой вызывающий, подавший
план с `imported_history_*.jsonl` (или иным immutable-файлом), удалит его без возражений.
Why it matters: инвариант «история никогда не удаляется» должен быть свойством **кода удаления**, а не
соглашением о том, кто формирует список. Сейчас достаточно одной ошибки/расширения в будущем
call-site — и переписка теряется. Для политики «КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО» это слабая гарантия.
Required fix: в цикле удаления перед `unlink` повторно вызывать `classify(path)`; если категория
`immutable` — не удалять, инкрементить `blocked` (новое поле отчёта) и логировать WARNING с именем.
Тест: план, вручную содержащий immutable-файл, → он остаётся на диске, `deleted` его не считает.

### [Severity: Medium]
File: `services/disk_retention.py` (:75–77) — в связке с `services/memory_backup.py:94` и
`services/memory_rebuild.py:144–146`
Problem: боевые сервисы берут каталог бэкапов через `hot.get("reactions.memory_backup_dir",
settings.MEMORY_BACKUP_DIR)`, а `default_dirs()` CLI читает **только** `settings.MEMORY_BACKUP_DIR`.
Если на сервере каталог переопределён хот-конфигом, `python manage.py disk audit|cleanup` без `--dir`
просканирует не тот каталог.
Why it matters: владелец по UPD2 п.7.3 требует честный отчёт «что именно вызвало рост +6 ГБ и что
удалено». Аудит/очистка по неправильному пути дадут ложную картину и не уберут реальные safety-бэкапы —
фича формально есть, но не решает задачу на проде.
Required fix: `default_dirs()` должен использовать `hot.get("reactions.memory_backup_dir",
settings.MEMORY_BACKUP_DIR)` (тот же резолвер, что и сервисы; лучше вынести общий `resolve_backup_dir`).

### [Severity: Medium]
File: `services/param_catalog.py:1136–1137`, `config/settings.py:917`
Location: `MEMORY_BACKUP_KEEP`
Problem: F9 убрал чтение хот-ключа (`_backup_keep_default` удалён), ротация жёстко `keep=1`, но параметр
остался в UI-каталоге с описанием «Сколько последних бэкапов хранить. **Больше — надёжнее**, но тяжелее
на диске». `settings.MEMORY_BACKUP_KEEP` по-прежнему парсит и отдаёт `10` (покрыто
`tests/test_settings_helpers.py:561–569`).
Why it matters: оператор выставит 3 (или 10), поверит описанию и будет думать, что у него 3 бэкапа, —
а фактически 1. Это противоречит «хранить 3 ЗАПРЕЩЕНО» и создаёт ложное чувство защищённости
(а бэкап — последняя линия восстановления). Лживый параметр хуже отсутствующего.
Required fix: удалить `MEMORY_BACKUP_KEEP` из `param_catalog.py` и `settings.py` (и поправить тесты),
либо переопределить описание как «принудительно 1 по политике владельца (UPD3 №5)» и сделать параметр
read-only/игнорируемым с явным предупреждением при попытке переопределить.

### [Severity: Medium]
File: `services/disk_retention.py:104–109`; `tests/test_disk_retention_round1024.py:126–134`
Location: `_history_immutable` / `test_hard_even_if_flag_false`
Problem: `_history_immutable()` **никогда не вызывается** (`grep` — только определение). Ветка
«`HISTORY_JSONL_IMMUTABLE=false` → WARNING» — мёртвый код; фактическая непреложность достигается тем,
что `classify` вообще не смотрит на флаг. Тест `test_hard_even_if_flag_false` не проверяет ни факт
игнорирования флага функцией, ни наличие предупреждения — он тавтологичен относительно заявленной цели.
Why it matters: контракт spec §6/T-2261 («`HISTORY_JSONL_IMMUTABLE=false` игнорируется, с
предупреждением») не выполнен как заявлен, а тест создаёт видимость покрытия. Если кто-то позже
«починит» `classify`, подключив флаг, защиты не останется, а тест это не поймает.
Required fix: вызвать `_history_immutable()` из `classify` (как единую точку hard-инварианта) и в тесте
проверить `caplog` на WARNING; либо удалить функцию и честно описать, что флаг не используется, убрав
из теста иллюзию проверки.

### [Severity: Medium]
File: `config/settings.py:942`; `tasks.md` T-2260
Location: `LOG_RETENTION_DAYS`
Problem: `LOG_RETENTION_DAYS` не читается ни одним потребителем (ни CLI, ни `audit`, ни отчёт); единственная
ссылка — тест на дефолт `7`. Journald-сниппета (`SystemMaxUse`/`MaxRetentionSec`) и runbook-артефакта в
коммите нет. При этом T-2260 отмечена `[x]`.
Why it matters: цель «логи — 7 дней» по факту не обеспечена кодом и не зафиксирована как артефакт; отчёт
владельцу не может подтвердить, что политика логов применяется. Галочка в tasks.md вводит в заблуждение.
Required fix: вывести `LOG_RETENTION_DAYS` в `disk audit` (например `log_retention_days=7`) и приложить
journald-сниппет/runbook; либо перевести T-2260 в `[ ]` до поставки @DevOps-артефакта.

### [Severity: Low]
File: `services/disk_retention.py:84–93`
Location: `_db_keep`
Problem: `return 1 if raw >= 1 else 1` — тавтология, всегда `1`. `raw` вычисляется ради ничего;
`DB_BACKUP_KEEP` не влияет ни на `prune_db_backups` (там `keep=1` захардкожен в call-site), ни реально
на план.
Why it matters: мёртвая логика маскирует намерение и путает следующего читателя (кажется, что флаг
«почти» учитывается).
Required fix: свести к явному `return 1` с комментарием «фиксированный guard по UPD3 №5», либо
реализовать честный hard-cap (например `min(max(1, raw), 1)` осмысленным именем) — но без видимости
настраиваемости.

### [Severity: Low]
File: `services/disk_retention.py`
Location: :35 (`import os`), :69–70 (`RetentionDisabled`), :48 (`JSONL_ROTATE_PATTERNS`)
Problem: мёртвый код — неиспользуемый импорт, неиспользуемое исключение, неиспользуемая константа
`JSONL_ROTATE_PATTERNS` (классификация и так режет все не-history `.jsonl`).
Required fix: удалить перечисленное.

### [Severity: Low]
File: `tests/test_disk_retention_round1024.py`
Location: весь файл
Problem: заявлено «30 новых тестов»; фактически в новом файле **23** тест-функции, остальное —
правки существующих `test_memory_backup.py`. Также нет теста, что sniff-распознанный history-файл
(нейтральное имя) исключается именно из `plan_cleanup`/`apply_cleanup` — проверяется лишь `classify`.
Required fix: скорректировать отчётность и добавить сквозной тест «sniff → не в плане → не удалён».

### [Severity: Low]
File: `services/disk_retention.py:418–446`
Location: `forecast_monthly`
Problem: в прирост включаются immutable-файлы (растущая история), а при `oldest ≈ now` `span_days`
клэмпится к `1.0`, что завышает `bytes_per_day`/`projected_30d`.
Why it matters: прогноз — часть обязательного отчёта владельцу; завышение без пояснения снижает доверие.
Required fix: зафиксировать методику в docstring/отчёте (что именно суммируется) и предусмотреть
минимальный интервал наблюдения/перечислить состав, чтобы цифра была объяснима.

---

## Контракт

**Задачи (`tasks.md`)**
- [x] T-2254 ADR — **да** (ADR-1024-2 присутствует, Accepted).
- [x] T-2258 retention БД = 1 — **да** (оба префикса, оба call-site; тест покрыт).
- [x] T-2259 JSONL-ротация + hard-исключение — **частично** (для известного формата — да;
  fail-open на `OSError` и неполный sniff — см. High-находки).
- [x] T-2260 логи 7 дней — **не подтверждено** (нет потребителя `LOG_RETENTION_DAYS`, нет
  journald-сниппета/runbook; см. Medium).
- [x] T-2261 тесты — **частично** (23 новых; guard-тест есть; сквозного plan/apply-теста history нет;
  `test_hard_even_if_flag_false` тавтологичен).
- [ ] T-2255/2256/2257/2262/2263 — вне объёма кода (DevOps/Reviewer), не блокируют ревью.

**Инварианты**
- `imported-history-immutable`: имя deny-list + content-sniff — **работает**, но есть fail-open ветка
  (`OSError`) и удаление доверяет входному плану → не абсолютная гарантия. **Не принять.**
- «1 бэкап БД для ОБОИХ префиксов»: **выполнено** (`prune_db_backups(keep=1)`, вызывается из
  `_rotate` и `create_safety_backup`; новейший сохраняется). ✔
- non-history JSONL 180д / facts 1 / логи 7д: JSONL и facts — **да**; логи — **нет** (Medium).
- `audit`/`plan_cleanup` read-only: **да** (побочных эффектов нет).
- `apply_cleanup` fail-closed с verify: **да** для «нет свежего валидного бэкапа» (тесты d);
  но нет защиты immutable внутри apply (High).
- R16/17/18: логи/вывод — только имена/размеры/счётчики; egress-тест (g) зелёный. ✔
- Δ DDL = 0: миграции не трогались. ✔
- Δ каталога = 0: новые флаги — `ClassVar`, в `param_catalog` отсутствуют. ✔ (но `MEMORY_BACKUP_KEEP`
  остался лживым — Medium.)
- `parse_mode=None`, `physical-two-call`: не затронуты.
- F1/F2/F7/F8/F12/F20/F21/F22: регрессий не выявлено (полный pytest зелёный, см. ниже).

**CLI `manage.py disk audit|cleanup`**
- Парсер `disk` без коллизий, `disk_sub.required=True`, `--apply` (default dry-run), `--dir`
  (`append`, множественный) — корректно. Секретов в выводе нет. ✔
- Дефолтный каталог расходится с рантаймом хот-конфига (Medium). ✘

**Тесты**
- 30 (23 новых + 7 в `test_memory_backup.py`, из них 3 переписаны) — проходят (`30 passed`).
- Не тавтологичны по большинству кейсов, но `test_hard_even_if_flag_false` — тавтологичен; guard
  истории покрыт только на уровне `classify`.
- Полный pytest: 1-й прогон — `2 failed, 7647 passed, 3 errors`
  (`tests/test_smart_cache.py::TestLockResilience`, flaky test-pollution, изолированно `31 passed`);
  2-й прогон — `7649 passed, 0 failed`. Заявленный «7641» не совпадает с фактом (7649/7647), F9
  регрессий не вносит.

---

## Точный список к исправлению (минимум)

1. `_looks_like_history`: `OSError` → fail-closed (не кандидат на удаление); + тест.
2. `apply_cleanup`: повторная проверка `classify` для каждого элемента, `immutable` → блокировать; + тест.
3. `default_dirs()`: резолвить каталог через `hot.get("reactions.memory_backup_dir", ...)`.
4. `MEMORY_BACKUP_KEEP`: убрать лживый параметр из каталога/настроек (или сделать read-only с явным
   предупреждением) и поправить тесты.
5. `_history_immutable`: либо подключить в `classify` и проверять WARNING в тесте, либо удалить вместе
   с иллюзией в тесте.
6. `LOG_RETENTION_DAYS`: вывести в `audit` и приложить journald-сниппет/runbook; иначе снять `[x]` с T-2260.
7. Вычистить мёртвый код (`os`, `RetentionDisabled`, `JSONL_ROTATE_PATTERNS`, тавтологию `_db_keep`).
8. Скорректировать отчётность по числу тестов; добавить сквозной тест history-в-plan/apply.
9. `forecast_monthly`: зафиксировать методику (состав, минимальный span) — иначе цифра необъяснима.

Верни исправленную версию. Текущий код отклонён.

*(Исторический вердикт итерации 1. Итоговый статус после итерации 2 — **Approved**, см. начало отчёта.)*
