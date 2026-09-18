# spec.md — F2 `urgent-summary-aliases-ui-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: диагностика + frontend `web/**`
> **ADR:** `ADR-1022-2.md` (**Accepted — UPD3 §4: починить рендер JSON-объекта на фронте; restore запрещён**). **Задачи:** `tasks.md` (T-2028…T-2034).
> **ТЗ:** `plans/current_task.md`, «Проблема 2: Пропал словарь алиасов» (180–185) + UPD3 §4 (265–267).
> **UPD3-дельта (Д-4):** данные в БД **есть** → **обязателен фикс рендера JSON-объекта на фронте**;
> backend-распаковка строки-JSON — defense-in-depth (не обязательна); **restore из бэкапа запрещён**.
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Каталог `SUMMARY_ALIASES` (type `json`, widget `keyvalue`) | `services/param_catalog.py:1164-1166` |
| jsonb-кодек PG → объект | `services/pg_db.py:409-415` (`set_type_codec(json/jsonb, decoder=json.loads)`) |
| ConfigCache: `normalize_value` на загрузке | `services/config_cache.py:176` |
| `_cast_to_type` для `json` | `services/param_catalog.py:2146-2156` (str → `json.loads`; **двойное кодирование вернёт `str`**) |
| API `/api/config`: отдаёт `value` + `widget` | `web/api/routes.py:351-365` |
| Frontend: json со widget не строкифаймится | `web/app.js:3543-3552` |
| KV-редактор `sync()` принимает **только object** | `web/app.js:6334-6343` |
| KV-шаблон | `web/index.html:3018-3052`; вызовы `:528-533`, `:794-798` |
| Санитайзер справки (не связан с F2) | `web/app.js:4781-4793` (DOMPurify default) |

### 0.1. Root cause: не доказан статикой — гипотезы по убыванию

- **H1 (наиболее вероятна): `value` приходит строкой JSON** (двойное кодирование в PG или
  слой сериализации), а фронт при `widget='keyvalue'` строку **не парсит**, `sync()` её
  игнорирует → 0 пар → «Пар пока нет» (UI выглядит пустым, данные целы). Согласуется с
  диагнозом Step 0 «данные целы, рендер пуст».
- **H2: `spec=None`** для фактического ключа в PG (несовпадение имени/регистра) → `widget=''`
  → рендерится не тот виджет.
- **H3: stale JS-кэш** (браузер/TMA отдаёт старый `app.js`).
- **H4: real WebView** (headless ≠ TMA) — отложенное ограничение.

### 0.2. Расхождения с ТЗ

- ТЗ предлагает «восстановить из бэкапа, если затёрты миграцией» — **отменяется**: данные
  целы (38 записей), restore перезапишет свежий объект. Действие заменено на frontend-фикс.
- ТЗ упоминает «React/Vue компонент» — React в проекте нет; есть Vue-рендер (`index.html`)
  + `app.js`; формулировка трактуется как правка `web/app.js`/`web/index.html`.

---

## 1. Цель

Вернуть устойчивый рендер пар «Telegram ID → имя» для `limits.summary_aliases` в модалке
настроек, доказав сначала фактический shape ответа API, с защитой от повторной регрессии.

## 2. Архитектура фикса (симметричная защита)

1. **READ-ONLY фиксация shape (обязательно ДО правок, T-2028):** зафиксировать для
   `SUMMARY_ALIASES`: `type`, `widget`, `typeof value` (object/string), длину, число ключей —
   локально и/или на проде. Результат — в `tasks.md`/отчёте (без значений: R17).
2. **Backend-гарантия (если H1 подтверждена):** вход для `keyvalue`-виджета —
   всегда объект. На отдаче в `routes.py` (или в `normalize_value` для type=json) обеспечить
   распаковку строки-JSON **до** dict; при неудаче — отдать пустой объект + WARNING (не
   ломая остальные `json`-виджеты). `services/param_catalog.py` — **read-only** (причина не
   в каталоге; Δ каталога = 0).
3. **Frontend defense-in-depth:** `kv-editor.sync()` (`app.js:6334-6343`) дополнительно
   принимает `string`: если `typeof raw === 'string'` → `JSON.parse` в объект; иначе объект;
   иначе пусто. Не менять поведение для не-JSON строк.
4. **Cache-bust:** убедиться, что обновлённый `app.js` реально отдаётся (`Cache-Control:
   no-store` / версия запроса) — устранить H3.
5. **Регресс:** не сломать другие `json`- и `list`-виджеты (generic json остаётся
   textarea-строкой при `widget=''`).

### 2.1. Диаграмма потока

```
PG bot_settings(jsonb) → codec → object
      │
      ├─ object → API {value: {...}, widget: 'keyvalue'} → kv-editor.sync(object) → пары ✅
      └─ string (двойное кодирование) ──► API {value: "{...}", widget:'keyvalue'}
                 │
                 ├─ [Fix backend] распаковать → object → ✅
                 └─ [Fix frontend] sync(): JSON.parse(string) → object → ✅
```

## 3. Контракты

- `/api/config` для `SUMMARY_ALIASES`: `type='json'`, `widget='keyvalue'`, `value` — объект
  `{ "<tg_id>": "<имя>" }`.
- KV-редактор: вход объект **или** строка-JSON; выход при сохранении — объект (как сейчас,
  `app.js:6372-6378`).
- Прочие `json` без widget — текст, как раньше.

## 4. Feature Flags / Progressive Delivery

- Флагов нет. Δ каталога = **0**. Пересечение `web/**` — ступень **F2 → F7**.

## 5. Kill-switch / fallback / откат

- **Fallback:** если `JSON.parse` строки не удался — пустой список (текущее безопасное
  поведение), без исключения.
- **Откат:** `git revert` (web-only).

## 6. Стоимость / латентность

Не применимо (frontend-фикс, +1 `JSON.parse` на поле).

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | Critical | Выполнить restore из бэкапа и затереть свежие данные | Доказано «данные целы»; restore **запрещён** |
| R2 | High | Фикс ломает другие `json`/`list`-виджеты | Регресс JS-UNIT + ручной чек модалки |
| R3 | High | H1 не подтвердится (реальная причина — H2/H3/H4) | READ-ONLY фиксация shape первым шагом; фикс только под подтверждённую гипотезу |
| R4 | Medium | Headless ≠ TMA WebView | Headless-рендер выполнен (Playwright присутствует); остаток — живая приёмка в реальном TMA WebView |
| R5 | Medium | Stale JS-кэш маскирует причину | Проверка served-файла + cache-bust |
| R6 | R17/R18 | Секреты/имена в скриншотах/отчётах | Маскировать, не логировать значения |

## 8. Открытые вопросы

- Д-4 **закрыт** UPD3 §4: починить рендер JSON-объекта на фронте; данные есть; restore запрещён.
  См. `round1022-human-gate-map.md`. Открытых нет.

## 9. Задачи

См. `tasks.md` (T-2028…T-2034). Дополнение: зафиксировать `typeof value` в T-2028 до правок.
