# Фича F6 — `help-guide-integration-round1014` (Справка: редактор гайда с хранением в БД)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). Код написан; гейты T-1526/T-1533/T-1534 — за @Architect/@Reviewer/@PM.
> **Раунд:** 10.14. **Нумерация:** T-1526…T-1534 (продолжает T-1525).
> **Тип:** docs + backend + frontend. **Приоритет:** P2.
> **Зависимости:** **F2** (факт персоны), **F3** (вкладка «Личность»), **F1** (Anti-Echo).
> **ТЗ:** `plans/current_task.md` §5+§6 + **UPD п.5**. **Эпик:** Self-Awareness / Persona round1014. **Baseline:** HEAD `2edc65b`.

## 0. Цель

`plans/docs/intelligence_user_guide.md` дополняется разделами про самосознание и личность. Гайд интегрируется в
раздел «Справка» **вторым редактируемым блоком** и **редактируется админом из мини-аппа с сохранением в БД** (UPD п.5) —
никакого «мёртвого» файла как источника истины.

**Фундамент:** «Справка» = `activeTab 'info'` → `GET /api/info` (`services/info_service.py`) + редактор
(`web/index.html:3050-3083`); DOMPurify self-host (`web/static/vendor/dompurify-3.4.15.min.js`).

## 1. Требования (ТЗ §5/§6 + UPD п.5)

- [x] §5: дополнить `intelligence_user_guide.md` (Anti-Echo, личность), стиль сохранить.
- [x] §6: отдельный блок гайда сразу под «информацией об использовании функций»; красивое форматирование.
- [x] UPD п.5: **Markdown/Rich-text редактор** в мини-аппе с сохранением в БД; DOMPurify одобрен; сид идемпотентный,
      ручные правки не затираются.

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- `plans/docs/intelligence_user_guide.md` — дополнение (самосознание/Anti-Echo, личность, эволюция характера).
- `services/config_cache.py` — `_seed_intelligence_guide()` + `_GUIDE_KEY` (сид).
- `services/info_service.py` — `get_guide()`, `save_guide()` (одна точка записи), `DEFAULT_GUIDE_MARKDOWN` (фолбек).
- `services/param_catalog.py` — PG-only ключ `content.intelligence_guide` (образец `content.info_how_it_works` `:392`).
- `config/settings.py` — **без изменений** (путь сида — code-константа `_GUIDE_SEED_FILE` в `config_cache.py`).
- `web/api/routes.py` — `GET/POST /api/info/guide` (образец `/info` `:1012/:1032`).
- `web/index.html` — второй блок `:3050-3083`; `web/app.js` — state/computed/methods + `renderGuideMarkdown`.
- Тесты: `tests/test_help_guide_round1014.py`, `tests/test_param_catalog.py`.

## 3. Инварианты

- ✅ PG-DDL разрешён, но F6 Δ — только **+1 PG-only ключ** (без новых таблиц).
- ⛔ Канон `DEFAULT_INFO_TEXT` ↔ `info_text.md` (первый блок) не ломать.
- ⛔ Порядок роутеров `bot.py`, `media/`/`.env`, R17/R16.
- **Никаких новых `v-html` без `sanitizeHtml`; новых CDN нет** (DOMPurify self-host уже есть).
- **Стиль гайда:** простыми словами, ирония, без жаргона (grep = 0).
- Каталог-Δ: REGISTRY 435, Settings 406, categorized 411, GROUPS 90, mapped 88, TAB_RULES 19 (общий Δ раунда).
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, байт/маркер-тесты, R17-скан.

## 4. Зависимости

- **Вверх:** F1/F2/F3. **Вниз:** нет.
- **Конфликт файлов:** `web/index.html` делят F3/F4/F7/F6 — F6 вливать после F3/F4/F7.

## 5. Definition of Done

- [x] `intelligence_user_guide.md` дополнен; стиль сохранён.
- [x] Второй блок редактируется и сохраняется в БД; после рестарта на месте; сид не затирает правки.
- [x] Рендер Markdown + DOMPurify; XSS закрыт (тесты).
- [x] Δ каталога задокументирован.
- [x] Полный `pytest` 0 failed; `node --check` clean; `git diff --check` чист.

## 6. Чек-лист задач

- [ ] **T-1526 (@Architect, гейт):** spec редакции 2: хранение гайда в PG (`content.intelligence_guide`), формат
  Markdown, мини-конвертер + DOMPurify, идемпотентный сид, контракт API, Δ каталога.
- [x] **T-1527 (@Builder, docs):** дополнить `plans/docs/intelligence_user_guide.md` (Anti-Echo + личность),
  стиль сохранить; grep запрещённого жаргона = 0.
- [x] **T-1528 (@Builder, backend):** каталог-ключ + `_GUIDE_SEED_FILE` (code-константа); `_seed_intelligence_guide`
  в `ConfigCache.init`; `get_guide`/`save_guide` в `InfoService`; `GET/POST /api/info/guide` (`edit_info`, лимиты, 503).
- [x] **T-1529 (@Builder, frontend):** второй блок «Справки»: Markdown-редактор + предпросмотр + save;
  `renderGuideMarkdown` + `sanitizeHtml`; toggle редактирования.
- [x] **T-1530 (@Builder):** идемпотентный сид «ключ есть → не затирать»; тест на ручную правку.
- [x] **T-1531 (@Builder, tests):** сид, API (200/422/503), XSS, Markdown-юниты, маркеры UI, пин-тесты Δ каталога.
- [x] **T-1532 (@Builder):** `node --check web/app.js`, полный `pytest` (0 failed), `git diff --check`.
- [ ] **T-1533 (@PM/@Reviewer, гейт):** сверка DoD, стиль гайда, R17-скан, «глазами новичка».
- [ ] **T-1534 (@PM/@DevOps):** live-чеклист владельцу (редактирование/сохранение гайда на Android).

## 7. Открытые вопросы (закрыты владельцем)

- **F6-Q1:** PG-ключ (не файл-зеркало). **F6-Q2:** Markdown + DOMPurify (одобрен).
- **F6-Q3:** идемпотентный сид, ручные правки не затираются. **F6-Q4:** упоминание вкладки «Личность».

## 8. Feature flag / progressive delivery

- Не требуется (docs + аддитивный UI). Rollback = `git revert`.
