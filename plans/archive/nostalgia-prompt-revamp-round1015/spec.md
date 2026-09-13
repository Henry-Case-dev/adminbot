# Спека F4 — `nostalgia-prompt-revamp-round1015` (Окно ±10, инжект Лора/мемов, живой стиль)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). Реализовано; pytest 5654 passed / 0 failed.
> **Раунд:** 10.15. **Тип:** backend + prompt engineering. **Приоритет:** P1. **T-ID:** T-1575…T-1583.
> **ТЗ:** `plans/current_task.md` §3. **ADR-политика:** ADR-1013-3 (`adr-1013-3-prompt-canon-policy.md`).
> **Зависимости:** нет. **Конфликт файлов:** `services/nostalgia_worker.py`, `services/nostalgia_prompts.py`, `config/settings.py`, `services/param_catalog.py` (только текст описания).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19.

## 1. Цель

Расширить окно «год назад» с `±2` до `±10` дней (дефолт), инжектировать в user-блок ностальгии **Лор чата** + **локальные мемы**, переписать канон промпта под «давнего участника, которого пробило на воспоминания» (ирония/сленг из лора, анти-«робот-архивариус»).

## 2. Scope

**In scope**
- Дефолт `NOSTALGIA_YEAR_BACK_DAYS_WINDOW` 2→10 (+ описание каталога «(10)»), устранение хардкода `or 2`.
- `build_nostalgia_user` — аддитивные секции «Лор чата» / «Локальные мемы» (пустые опускаются).
- Сбор лора (`self.store.get_profile`) и мемов (`db.list_chat_memes`) в `_llm_once` + капы, fail-open.
- Перепись `NOSTALGIA_PROMPT` по ADR-1013-3 (PREV-слепок + байт/маркер-тесты).
- Тесты инжекта и окна.

**Out of scope**
- Изменение `clean_llm_text`/`is_unchanged_response`-семантики, `{max_words}`-механики, детекта UNCHANGED.
- `PROMPT_MIGRATIONS` (канон ностальгии туда не входит — подтверждено; F4-Q1 RESOLVED).
- Новые каталог-ключи (Δ=0).

## 3. Окно «год назад» (точный)

- `config/settings.py:1173-1174`: дефолт `2 → 10`.
- `services/param_catalog.py:1535-1539`: текст описания завершить «(10)».
- `services/nostalgia_worker.py:546-548`: убрать хардкод — вместо `... or 0) or 2`:
  ```python
  window_days = int(self._limit(
      "year_back_days_window",
      settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW) or 0) or \
      settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW
  ```
  (ключ остаётся per-chat-переопределяемым; F4-Q5 RESOLVED: **только дефолт**, существующие per-chat значения не мигрируют.)

## 4. Инжект Лора и мемов (точный)

F4-Q3 RESOLVED: **лор активного чата** (перчат-профиль через `self.store.get_profile(chat_id)`; `manual_lore` приоритетно, иначе `auto_lore`).
F4-Q4 RESOLVED: **все мемы чата** (`db.list_chat_memes(chat_id, target_user=None, limit=…)`) — как в direct-chat; сортировка «свежие первыми» уже в запросе.

**Капы (F4-Q2 RESOLVED, код-константы в `services/nostalgia_prompts.py`):**
```python
_LORE_MAX_CHARS = 600        # лор — обрезается по границе слова
_MEMES_LIMIT = 10            # число мемов
_MEME_MAX_CHARS = 120        # обрезка текста одного мема
```

**Сигнатура (обратно совместима):**
```python
def build_nostalgia_user(year_lines, golden_lines, lore="", memes=None) -> str
```

**Порядок секций (фиксированный):**
```
В чате давно тихо. Вот память:
События примерно год назад в этот день:
<year_lines>

Старые факты по последней теме разговора:
- <golden>

Лор чата (как тут принято общаться):
<lore>

Локальные мемы (местные ярлыки и шутки):
- <fact>
- [<target_user>] <fact>
```
- Пустые секции опускаются; если всё пусто → `""` (поведение как раньше; fail-open).
- Мемы рендерятся как `- {fact}`; при непустом `target_user` → `- [{target_user}] {fact}` (R16: `target_user` — это имя-лейбл, не id).
- Лор/мемы санитизируются: `" ".join(str(x).split())`, обрезка по капам.

**Сбор в `nostalgia_worker._llm_once` (сигнатура `_llm_once(self, candidate, chat_id)`):**
```python
lore_text = ""
if self.store is not None:
    try:
        prof = await self.store.get_profile(chat_id)
        if prof is not None:
            lore_text = (prof.manual_lore or prof.auto_lore or "")
    except Exception:
        logger.warning("[nostalgia] lore fetch failed — без лора | chat_id=%s",
                       chat_id, exc_info=True)
        lore_text = ""
memes = []
try:
    memes = await self.db.list_chat_memes(chat_id, None, limit=_MEMES_LIMIT)
except Exception:
    logger.warning("[nostalgia] memes fetch failed — без мемов | chat_id=%s",
                   chat_id, exc_info=True)
    memes = []
user_text = build_nostalgia_user(
    candidate.get("year_lines") or [],
    candidate.get("golden_lines") or [],
    lore=lore_text,
    memes=memes)
```
Обновить вызов `:432` → `await self._llm_once(candidate, chat_id)`.

## 5. Канон `NOSTALGIA_PROMPT` (точный текст, ADR-1013-3)

- Создать `PREV_NOSTALGIA_PROMPT` = текущий текст (`services/nostalgia_prompts.py:21-25`, байт-в-байт) — слепок для отката/диффа.
- Новый `NOSTALGIA_PROMPT` (единственный `{max_words}`, `UNCHANGED` сохранён, **без длинных тире**):

```python
NOSTALGIA_PROMPT = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день, старые факты по последней теме, а также лор чата и список местных мемов. Вбрось этот старый факт так, как будто ты давний участник беседы, которого внезапно пробило на воспоминания: с иронией и сленгом из лора, по-свойски, будто вспомнил вслух. Не пиши как робот-архивариус. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""
```

**Политика ADR-1013-3 (F4-Q1 RESOLVED):**
- `NOSTALGIA_PROMPT` — модульная канон-константа (НЕ PG-сид, НЕ REGISTRY-ключ).
- Правка = `PREV_NOSTALGIA_PROMPT`-слепок + новый текст + обновление байт/маркер-тестов `tests/test_nostalgia_prompts.py:29-46`.
- `PROMPT_MIGRATIONS` **не трогать** (ностальгия в миграции не входит — подтверждено: `services/prompt_migrations.py:63` содержит только `prompts.*`-каноны).
- Эталон `docs/canon/` — **опционально** (канон не PG; политика 10.13 не требовала файла для ностальгии). Достаточно слепка + байт-тестов.

## 6. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `config/settings.py:1173-1174` | Дефолт `NOSTALGIA_YEAR_BACK_DAYS_WINDOW` 2→10. |
| 2 | `services/param_catalog.py:1535-1539` | Описание окна «(2)»→«(10)» (текст, Δ каталога 0). |
| 3 | `services/nostalgia_worker.py:546-548` | Убрать хардкод `or 2` (см. §3). |
| 4 | `services/nostalgia_prompts.py:21-25` | `PREV_NOSTALGIA_PROMPT` + новый `NOSTALGIA_PROMPT`. |
| 5 | `services/nostalgia_prompts.py:103-116` | `build_nostalgia_user` += `lore`/`memes`; капы-константы. |
| 6 | `services/nostalgia_worker.py:595-616` | `_llm_once(self, candidate, chat_id)`: сбор лора/мемов, fail-open, новый вызов. |
| 7 | `services/nostalgia_worker.py:432` | Вызов `_llm_once(candidate, chat_id)`. |
| 8 | `tests/test_nostalgia_prompts.py:29-46` | Обновить байт/маркер-тесты канона (стиль «давний участник», анти-«робот-архивариус»). |

**Не трогать:** `clean_llm_text`, `is_unchanged_response`, `format_nostalgia_hint`, `format_year_back_line`, `format_golden_line`, `PROMPT_MIGRATIONS`.

## 7. Feature-флаг / progressive delivery

Не требуется (промпт-канон + дефолт настройки). Rollback = `git revert`; окно — рантайм-настройкой `memory.nostalgia_year_back_days_window`. Каталог-Δ=0.

## 8. Тест-план

- `tests/test_nostalgia_prompts.py`: канон содержит «давний участник»/анти-«робот-архивариус», ровно один `{max_words}`, `UNCHANGED`, нет `—`; `build_nostalgia_user`: секции «Лор чата»/«Локальные мемы» появляются при непустых входах и опускаются при пустых; порядок секций; капы (длинный лор обрезан ≤600; мемов ≤10, каждый ≤120).
- Новый `tests/test_nostalgia_revamp_round1015.py`: `_llm_once` передаёт лор/мемы в user-блок (моки `store.get_profile`, `db.list_chat_memes`); fail-open при исключении (блок как раньше); окно ±10 (границы `center±10*86400`); обратная совместимость вызова `build_nostalgia_user(y, g)`.
- Регресс: `tests/test_nostalgia_worker.py` зелёный.
- **Гейты:** полный `pytest` 0 failed; каталог-Δ=0; R17-скан; `git diff --check`; русский commit.

## 9. Открытые вопросы → решения

- **F4-Q1** PREV-слепок обязателен; `PROMPT_MIGRATIONS` не трогаем (ностальгия вне миграций).
- **F4-Q2** капы: лор ≤600 симв., мемы ≤10 шт. ×≤120 симв.; при конфликте токенов лор важнее мемов (лор идёт выше, мемы усекаются первыми).
- **F4-Q3** лор активного чата (manual → auto).
- **F4-Q4** все мемы чата (как direct-chat).
- **F4-Q5** только дефолт 10 (per-chat переопределение сохранено).

## 10. Риски

| Риск | Митигация |
|---|---|
| Удорожание вызова (больше промпт) | Жёсткие капы (600/10×120 ≈ +1.2k симв.); ревью стоимости T-1583. |
| Лор/мемы «заглушают» старый факт | Секции идут ПОСЛЕ фактов; стиль-инструкция велит вбросить именно факт. |
| PG down (store) | fail-open: секция опускается, блок как раньше. |
| Слом байт-тестов канона | Слепок + синхронное обновление тестов в T-1580. |

## 11. Критерии приёмки (DoD)

- [x] Дефолт окна «год назад» = 10 (настройка/каталог синхронны; per-chat переопределяемо).
- [x] User-блок содержит «Лор чата» и «Локальные мемы», когда они есть; пустые секции опускаются.
- [x] Промпт: «давний участник, которого пробило на воспоминания», ирония/сленг из лора, анти-«робот-архивариус»; `{max_words}`/`UNCHANGED` сохранены; `PREV_NOSTALGIA_PROMPT` есть.
- [x] Тесты канона обновлены; тесты инжекта/окна зелёные; полный `pytest` 0 failed; каталог Δ=0.

## 12. Инварианты

ADR-1013-3 (канон-константа, PREV+байт-тесты, `PROMPT_MIGRATIONS` не трогать), `{max_words}` ровно один, UNCHANGED-семантика, no-markdown/ёлочки/длинные-тире в ОТВЕТЕ, R17, `media/`/`.env`/порядок роутеров `bot.py` не трогать, каталог 435/406/411/90/88/19.
