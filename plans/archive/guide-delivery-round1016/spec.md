# Спека F2 — `guide-delivery-round1016` (Доставка «Гайда по фичам»: версионирование канона + write-path)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer APPROVED, итерация 2). T-1634 закрыт.
> **Раунд:** 10.16. **Тип:** backend (config/info) + docs. **Приоритет:** P1 (прод-регресс ТЗ §7). **T-ID:** T-1634…T-1641.
> **ТЗ:** `plans/current_task.md` UPD2 (строка 151) + §7 (строки 50-56).
> **ADR:** [`adr-1016-3-guide-canon-versioning.md`](adr-1016-3-guide-canon-versioning.md).
> **Baseline:** HEAD `18a9aa1`; pytest 5774/0; каталог 435/90/406/411/88/19 (Δ=0).
> **Зависимости:** нет. **Вниз:** F3 (смоук guide), F5.

## 0. Цель

«Справка» = 2 блока: (1) legacy rich-HTML `content.info_how_it_works` — это «Гайд по фичам»; (2) Markdown `content.intelligence_guide`. Новый канон F7 (10.15) **не доехал в прод-PG**: миграция `_migrate_info_how_it_works_v1015` перезаписывает только при точном байт-равенстве `PREV_DEFAULT_INFO_TEXT`, а прод-значение оказалось дрейфовым → WARNING + пропуск.

Дополнительно `InfoService.save_text` (`/edit_info`, POST `/api/info`) пишет в **git-tracked** `info_text.md` → дрейф и блокировка fast-forward pull.

Результат: канон фактически доставляется; явная версионная политика; write-path не создаёт дрейф; ручные правки не затираются молча.

## 1. Точки изменения (`file:line` на HEAD `18a9aa1`)

| Файл | Строки | Что |
|---|---|---|
| `services/config_cache.py` | 26-29 | импорт `PREV_DEFAULT_INFO_TEXT` → реестр слепков + `INFO_CANON_VERSION` |
| `services/config_cache.py` | 211-233 | `_seed_info_key` — сид с `canon_version` |
| `services/config_cache.py` | 235-266 | `_migrate_info_how_it_works_v1015` — версионная идемпотентная миграция |
| `services/info_service.py` | 20-26 | `INFO_CANON_VERSION`, `KNOWN_INFO_SNAPSHOTS` |
| `services/info_service.py` | 78-… | `DEFAULT_INFO_TEXT` (канон, не менять байты) |
| `services/info_service.py` | 165-200 | `load`/`get_text` — не писать tracked-файл |
| `services/info_service.py` | 202-217 | `save_text` — **PG-only**, без записи файла |
| `services/info_service.py` | 219-221 | `_write_default` — не создавать tracked-файл в рантайме |
| `web/api/routes.py` | POST `/api/info`, `/api/info/guide` | + reset-canon; GET `/api/info` += `canon_version`/`canon_drift` |
| `handlers/*` (`/edit_info`) | — | поведение через `save_text` (PG-only) |
| `info_text.md` | весь | роль: **read-only сид + байт-канон** |
| `tests/test_info_service.py` | 28-45 | байт-тест сохранить; + тест «save_text не пишет файл» |

## 2. Модель данных канона

Значение `content.info_how_it_works` (JSONB, DML-only, DDL нет):
```json
{
  "html": "<...>",
  "canon_version": 2,
  "updated_at": "2026-09-14T…Z",
  "updated_by": 123456789,
  "prev_html": "<...>",          // только после force-reset (бэкап), опционально
  "prev_updated_at": "2026-09-13T…Z"
}
```
- `canon_version` — целое, текущий канон = `INFO_CANON_VERSION` (старт 2: 1 = до F7, 2 = канон F7).
- `updated_by` — **id** (R16), не имя.
- `content.intelligence_guide` — без изменений (Markdown, отдельный ключ).

### Нормализация и реестр слепков
```python
def normalize_canon(text: str) -> str:
    return "\n".join(line.rstrip() for line in
                     text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()

KNOWN_INFO_SNAPSHOTS: tuple[str, ...] = (PREV_DEFAULT_INFO_TEXT,)  # + фактические прод-слепки (см. §6)
```
Сравнение — по `normalize_canon(html)`, а не байт-в-байт: устраняет дрейф пробелов/переводов строк. Реестр — явные строки (для бэкапа/отката), сопоставление — нормализованное. Решение — ADR-1016-3 §3.

## 3. Алгоритм миграции (идемпотентный, версионный)

`ConfigCache.init` → `_migrate_info_how_it_works()` (переименование допустимо; старый вызов сохранить совместимым):
```python
current = self._settings.get(_INFO_KEY)
if not isinstance(current, dict):            # ключа нет → _seed_info_key (канон)
    return
html = current.get("html")
if not isinstance(html, str) or not html.strip():
    return
stored_ver = current.get("canon_version")
norm = normalize_canon(html)

if stored_ver == INFO_CANON_VERSION and norm == normalize_canon(DEFAULT_INFO_TEXT):
    return                                    # идемпотентный no-op
if norm == normalize_canon(DEFAULT_INFO_TEXT):
    write(canon, version=INFO_CANON_VERSION)  # дрейф версии, текст верный → добить версию
    return
if any(norm == normalize_canon(s) for s in KNOWN_INFO_SNAPSHOTS):
    write(canon, version=INFO_CANON_VERSION)  # наш прошлый канон → безопасно обновляем
    logger.info("[config_cache] info canon migrated | v=%s→%s", stored_ver, INFO_CANON_VERSION)
    return
# неизвестный текст = ручная правка владельца → НЕ затираем молча
logger.warning("[config_cache] info canon drift | stored_v=%s current_v=%s",
               stored_ver, INFO_CANON_VERSION)
# пометить drift: get_* отдаёт canon_drift=True (UI-подсказка force-reset)
```

### Force-reset (админ, RBAC `edit_info`)
```
POST /api/info/reset-canon   (requires_permission("edit_info"))
→ value = {
    html: DEFAULT_INFO_TEXT,
    canon_version: INFO_CANON_VERSION,
    updated_at: now(UTC), updated_by: <id>,
    prev_html: <текущий html>, prev_updated_at: <текущий updated_at>,
  }
→ 200 {canon_version, updated_at, updated_by}
```
- Бэкап — внутри значения (`prev_html`), откат = повторный reset/`save_text(prev_html)`.
- Аудит — `updated_by`/`updated_at` (R16/R17).
- UI: на экране «Справка» при `canon_drift=true` — баннер «канон изменён вручную» + кнопка «Сбросить к канону» (опционально; при отсутствии UI-работы reset доступен REST-ом). F2 ограничивается REST + документацией; визуальная кнопка — если @Builder успевает без риска.

### GET `/api/info` (аддитивно)
```
{ ...существующие поля...,
  "canon_version": 2,
  "canon_current_version": 2,
  "canon_drift": false }
```
Аддитивность: существующие клиенты не ломаются.

## 4. Write-path (PG-only, без дрейфа)

- `save_text(text)`:
  1. **не пишет** `info_text.md` (убрать `open(..., "w")`);
  2. `self._cache = text`;
  3. `ConfigCache.set(INFO_KEY, {html, updated_at, updated_by, canon_version=<сохранить текущую, если ручная правка — не менять? см. ниже>})`.
- **Решение по версии при ручной правке:** ручная правка — это НЕ новый канон. `canon_version` при `save_text` **не повышается**: значение сохраняется с `canon_version = <текущий INFO_CANON_VERSION>` и текстом владельца. Это осознанно: `canon_version` описывает код-канон, не пользовательский текст. `canon_drift` определяется по `norm != normalize_canon(DEFAULT_INFO_TEXT)`.
- PG недоступен → `save_text` **поднимает** `ConfigCacheUnavailableError` (как `save_guide`), роут/handler → 503/фраза; НЕ пишем локально-только (иначе прод-значение и локаль расходятся). In-memory кэш остаётся прежним.
- `load()`/`_write_default()`: файл отсутствует/пуст → `self._cache = DEFAULT_INFO_TEXT` **без создания файла**; `get_text` приоритет: ConfigCache → in-memory → код-канон.
- `info_text.md` остаётся tracked как **read-only сид и байт-канон** (нужен для `_seed_info_key` и байт-теста `DEFAULT_INFO_TEXT ↔ info_text.md`). Исключение из репо не делаем (потеряем сид/байт-эталон) — ADR-1016-3 §4.
- Тест-гарант: `save_text` не меняет содержимое/mtime `info_text.md`.

## 5. Доставка в прод (гарантия)

1. На старте отрабатывает версионная миграция (§3): для известного слепка (в т.ч. whitespace-дрейф прошлого канона) — авто-перезапись → прод-PG получает канон **без ручного вмешательства**.
2. Если прод-значение — **неизвестный** текст (реальная ручная правка), авто-перезапись запрещена; доставка — явным force-reset (§3), с бэкапом и аудитом.
3. Деплой-шаг (@DevOps): выгрузить текущий `content.info_how_it_works.html`; если это старый канон/его вариант — добавить текст в `KNOWN_INFO_SNAPSHOTS` (тогда авто-миграция закроет кейс) — инструкция в спеке и §6. Никаких секретов в выгрузке.
4. `/edit_info` больше не пишет tracked-файл → pull не блокируется.

## 6. Деплой-инструкция для @DevOps (вне репо)

```sql
-- только чтение, без секретов
SELECT value->>'canon_version' AS ver,
       md5(value->>'html')      AS html_md5,
       length(value->>'html')   AS len
FROM bot_settings WHERE key='content.info_how_it_works';
```
- Если `html_md5` совпадает с одним из известных слепков (сравнить с `md5` текстов `PREV_DEFAULT_INFO_TEXT`/канона) — авто-миграция сработает сама.
- Если нет — владелец решает: ручная правка сохраняется, доставка через `POST /api/info/reset-canon` (бэкап в `prev_html`).
- Пароль/секреты в выгрузку не попадают (R17).

## 7. Конфиг / флаги

- **Новых PG-ключей каталога нет** (каталог-Δ=0); `canon_version`/`prev_html` — поля внутри существующего JSONB, DML-only, DDL нет.
- Флаг не вводится. Rollback = `git revert` + (при необходимости) force-reset.
- Новый REST-роут `/api/info/reset-canon` — не параметр каталога; RBAC через существующее действие `edit_info`.

## 8. Тест-план (T-1638/T-1639)

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | байт-канон `DEFAULT_INFO_TEXT` ↔ `info_text.md` | равен (существующий тест сохранён) |
| 2 | PG-значение == `PREV_DEFAULT_INFO_TEXT` | миграция → канон, `canon_version=CURRENT` |
| 3 | PG-значение == канон, повторный init | no-op, без записи (идемпотентность ×2) |
| 4 | PG-значение == PREV + whitespace/CRLF-дрейф | нормализованный матч → авто-миграция |
| 5 | PG-значение == неизвестный текст | НЕ перезаписан; WARNING; `canon_drift=True` |
| 6 | `reset-canon` | канон записан; `prev_html` == прежний; `updated_by/at` |
| 7 | `save_text` | PG обновлён; `info_text.md` не изменён (content+mtime) |
| 8 | `save_text` при PG down | исключение/503; файл и кэш не разъезжаются |
| 9 | симуляция прод-PG со старым текстом → init | PG == `DEFAULT_INFO_TEXT` без ручного вмешательства |
| 10 | GET `/api/info` | аддитивные `canon_version`/`canon_drift`, старые поля целы |

## 9. Риски и меры

| Риск | Мера |
|---|---|
| Авто-перезапись удалит ручную правку владельца | авто-перезапись только при матче известного слепка; иначе force-reset + бэкап |
| Смена write-path ломает `/edit_info` в проде | `save_text` PG-only; при PG down — явная ошибка, не тихая локальная запись; регресс-тесты handler |
| `canon_version` не бампается вручную при правке канона | правило: любая правка `DEFAULT_INFO_TEXT` в коде **обязана** обновить `INFO_CANON_VERSION` и добавить прежний текст в `KNOWN_INFO_SNAPSHOTS` + байт-тест (документируется в docstring/тесте) |
| Новый ключ/поле ломает каталог-пины | новых ParamSpec нет; поле внутри JSONB — каталог не видит |
| UI «Справка» показывает не то | GET отдаёт drift-флаг; ручной текст остаётся видимым (не затирается) |

## 10. Критерии приёмки (DoD)

- [ ] Версионная идемпотентная миграция: известный слепок → канон; unknown → не затирается; `canon_version` пишется.
- [ ] Force-reset (`/api/info/reset-canon`, RBAC `edit_info`) с бэкапом `prev_html` и аудитом.
- [ ] `save_text`/`/edit_info` PG-only; `info_text.md` не пишется; pull не блокируется.
- [ ] GET `/api/info` аддитивно отдаёт `canon_version`/`canon_drift`.
- [ ] Тесты §8 зелёные (вкл. симуляцию прод-PG); полный `pytest` **0 failed**; каталог **Δ=0**.
- [ ] Инварианты: порядок роутеров `bot.py` не тронут; `media/`/`.env` не тронуты; байт-канон `DEFAULT_INFO_TEXT` не изменён без слепка.

## 11. Handoff

Реализация — @Builder: T-1635…T-1640; гейт — T-1641.
`@Orchestrator` — спецификация F2 готова.
