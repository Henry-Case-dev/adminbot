# Spec F6 — `help-guide-integration-round1014` (Справка: редактор гайда с хранением в БД)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, **итерация 2**, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1526…T-1534. **ТЗ:** `plans/current_task.md` §5+§6 + **UPD п.5**.
> **Зависимости:** **F2** (факт персоны), **F3** (вкладка «Личность»), **F1** (Anti-Echo). **Baseline:** HEAD `2edc65b`.
> **Конфликт файлов:** `web/index.html` — вливать F6 после F3/F4/F7.
> **Ревизия:** отменяет редакцию 1 (файл-зеркало `info_bot_guide.md` + rich-HTML): гайд живёт **в БД**, редактируется в мини-аппе.

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **F6-Q1** хранение | **PG-ключ `content.intelligence_guide`** (json, группа `content_info`, tab=None): `{markdown, updated_at, updated_by}`. **Никакого файла-зеркала как источника истины.** `plans/docs/intelligence_user_guide.md` — только **источник идемпотентного сида**. |
| **F6-Q2** формат | **Markdown** (редактор — textarea, предпросмотр). Рендер на фронте: мини-конвертер Markdown→HTML + **DOMPurify self-host** (`web/static/vendor/dompurify-3.4.15.min.js`) — UPD п.5 одобряет DOMPurify. |
| **F6-Q3** сид/правки | Идемпотентный сид при `ConfigCache.init`: ключа нет → читаем `intelligence_user_guide.md` → `set`. Ключ есть → **не трогаем** (ручные правки неприкосновенны). |
| **F6-Q4** связь с F3 | В тексте гайда — упоминание вкладки «Личность» (`#/ai/persona`). |
| §5 docs | `plans/docs/intelligence_user_guide.md` дополняется разделами про Anti-Echo и личность (стиль сохранить, жаргон-гейт = 0). |
| Каталог-Δ | +1 запись (REGISTRY 435), Settings +0 (PG-only). |

---

## §1. Цель и scope

`intelligence_user_guide.md` дополняется разделами про самосознание и личность. Гайд интегрируется в раздел «Справка»
**вторым редактируемым блоком** сразу под «информацией об использовании функций» и **редактируется админом прямо из
мини-аппа с сохранением в БД** (UPD п.5).

**In scope:** docs-дополнение; PG-ключ гайда + идемпотентный сид; API чтения/записи; второй блок UI с Markdown-редактором
и предпросмотром; санитайз; сохранение ручных правок.

**Out of scope:** изменение первого блока `content.info_how_it_works`; новый CDN; rich-text WYSIWYG; F2/F3-логика.

---

## §2. Схема данных и API

### 2.1. Каталог-ключ (санкционированный Δ)
```python
# services/param_catalog.py — _CONTENT (json PG-only, рядом с content.info_how_it_works :392)
("content.intelligence_guide",
 "Гайд по возможностям бота (Markdown)",
 "content_info",
 "Человекочитаемый FAQ-гайд, редактируется в админке. Markdown: заголовки, "
 "списки, ссылки, код. Рендер на фронте + санитайз DOMPurify."),
```
- группировка `content_info` (tab=None); per_chat=True по категории content, но значение по смыслу глобальное.

### 2.2. Сид (`services/config_cache.py`)
```python
_GUIDE_KEY = "content.intelligence_guide"
_GUIDE_SEED_FILE = "plans/docs/intelligence_user_guide.md"   # code-константа (не Settings: путь сид-артефакта, не редактируется)

async def _seed_intelligence_guide(self) -> None:
    """Ключа нет → markdown из _GUIDE_SEED_FILE → PG.
    Ключ есть → НЕ трогаем (ручные правки неприкосновенны)."""
    if _GUIDE_KEY in self._settings:
        return
    try:
        with open(_GUIDE_SEED_FILE, encoding="utf-8") as fh:
            markdown = fh.read()
    except OSError:
        logger.warning("[config_cache] guide seed skipped: файл не читается")
        return
    if not markdown.strip():
        return
    value = {"markdown": markdown,
             "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "updated_by": settings.ADMIN_USER_ID}
    await self.set(_GUIDE_KEY, value, "content")
```
- Вызов в `ConfigCache.init()` после `_seed_info_key()`.

### 2.3. API (`web/api/routes.py`, рядом с `/info`)
- `GET /api/info/guide` → `{key, markdown, updated_at, updated_by}` (TMA-auth, любая роль). PG down/нет ключа → markdown из код-канона/пусто (fail-open), 200.
- `POST /api/info/guide` → `requires_permission("edit_info")` (переиспользуем действие, UPD не требует нового); body `{markdown}`; пусто → 422; ≤ `_GUIDE_LIMIT` 65536 → иначе 422; PG down → 503. Пишет через `InfoService.save_guide` (одна точка записи).

### 2.4. Frontend (`web/index.html` `:3050-3083`; `web/app.js`)
- Второй `<div class="card p-5">` в `activeTab==='info'` сразу под первым:
  - заголовок «Гайд по возможностям» + `updated_at`;
  - просмотр: `v-html="sanitizedGuideHtml"` (**только санитайзенный**);
  - редактор: `textarea` (`v-model="guideDraft"`, maxlength 65536) + toggle «Редактировать/Просмотр» + «Предпросмотр» (`renderGuideMarkdown`) + «Сохранить» (`saveGuide()`); `canEditInfo` (`:1184`) переиспользуется.
- Новые методы: `loadGuide()`, `saveGuide()`, `toggleGuideEditor()`, `renderGuideMarkdown(text)`; computed `sanitizedGuideHtml` = `sanitizeHtml(renderGuideMarkdown(guideHtml))`.
- `setTab('info')` грузит оба блока.

### 2.5. Мини-конвертер Markdown (frontend, без новых зависимостей)
- `renderGuideMarkdown(md)`: сначала **escape HTML** (`&<>"`), затем последовательно:
  `#..######` → `<h1..h6>`; `**bold**` → `<b>`; `*italic*` → `<i>`; `` `code` `` → `<code>`; `- ` список → `<ul><li>`;
  `[text](http(s)://…)` → `<a href target="_blank" rel="noopener">text</a>` (**только http/https**, остальные ссылки — текстом);
  пустая строка → закрыть абзац; остальное — `<p>`. Уровни вложенности инлайн-разметки фиксированы (тесты).
- Результат ВСЕГДА проходит через `sanitizeHtml` (DOMPurify self-host) перед `v-html` — защита от XSS.
- Никаких `v-html` без санитайза.

### 2.6. Docs (`plans/docs/intelligence_user_guide.md`)
- +разделы: «Бот помнит свои слова, но не верит им» (Anti-Echo) и «Личность бота» (имя/био/характер/осознание ИИ; эволюция характера; настройка во вкладке «Личность»).
- Стиль: простыми словами, лёгкая ирония; grep запрещённого жаргона (RAG/LLM/токены/эндпоинты/JSON/SQLite/PG) = 0.

## §3. Конфиг-ключи/дефолты

| Ключ | Тип | Дефолт |
|---|---|---|
| `content.intelligence_guide` | json | сид из `intelligence_user_guide.md` (PG-only) |
| `_GUIDE_SEED_FILE` (code) | str | `plans/docs/intelligence_user_guide.md` |

Settings-полей F6 **не добавляет** (`Settings` остаётся 406 в сводном Δ).

## §4. Feature flag / progressive delivery

Не требуется (docs + аддитивный UI). Rollback = `git revert`; первый блок не трогается.

## §5. Тест-план

1. Сид идемпотентен: ключа нет → запись из файла; ключ есть (в т.ч. правленый) → не перезатирается.
2. `GET/POST /api/info/guide`: 200/200; пусто → 422; >65536 → 422; PG down → 503; право `edit_info`; запись → reload → на месте.
3. XSS: `<script>`/`onerror`/`javascript:` вырезаются `sanitizeHtml`; `renderGuideMarkdown` экранирует HTML.
4. Markdown-юниты: заголовки/жирный/курсив/код/список/ссылка http(s) (и отказ на `javascript:`)/параграфы.
5. Маркеры UI (`tests/test_help_guide_round1014.py`): второй блок под первым, редактор, кнопка save, предпросмотр, sanitize.
6. Пин-тесты Δ каталога: REGISTRY +1 (435), Settings без роста; GROUPS/mapped/TAB_RULES без роста.
7. `node --check`, полный pytest 0 failed, `git diff --check`.

## §6. Критерии приёмки (DoD)

- [ ] `intelligence_user_guide.md` дополнен разделами про Anti-Echo и личность; стиль сохранён.
- [ ] В «Справке» — ВТОРОЙ редактируемый блок, красиво отформатирован, текст санитайзится (без XSS).
- [ ] Админ редактирует/сохраняет прямо из мини-аппа; после рестарта текст на месте; сид не затирает правки.
- [ ] Гайд хранится в БД (`content.intelligence_guide`), файл — только сид-источник.
- [ ] Полный `pytest` 0 failed; `node --check` clean; Δ каталога задокументирован.
