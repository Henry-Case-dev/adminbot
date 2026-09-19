# Задачи: summary-cover-rich-article-round1023

> **Раунд 10.23** · Приоритет **P1** · Шаг 1 @PM (+ Step 2 @Architect: `spec.md` + **ADR-1023-6**) · Тип: backend/LLM + канон + egress + UI-настройка
> **ТЗ:** `plans/current_task.md`, «Генерация изображений и Rich Text Саммари → 2. Расширение Саммари (Генерация обложек и Лонгриды)». Untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** F5 (провайдер изображений), F3 (Канон-контур / Stage-2), F1 (канон-контур).

## Цель
Слой 1 (Редактор саммари) после текста выжимки генерирует короткий **визуальный промпт на английском** (≤300 символов). Настройка «Стиль обложки» (авторская) конкатенируется с visual prompt и отправляется в image-API. Готовое саммари доставляется как нативный **Rich Text / Article** через `sendRichMessage` (Telegram Bot API 10.1+) с прикреплённой обложкой. При падении генерации обложки — **тихий откат** на обычное текстовое саммари без сообщений об ошибке.

## Контекст / что уже есть
- Редактор саммари Stage-1: `services/summary_generator.py:298` `_generate_two_call`, `services/summary_prompts.py` (SUMMARY_EDITOR) + `services/system2_handoff.py::validate_summary_digest` (`:128`).
- Rich-образец: `handlers/info.py:103-104,157-158` — `bot.send_rich_message` + `InputRichMessage(html=...)`, fallback `TelegramBadRequest` (D231).
- Egress-реестр: `services/telegram_send.py:26` `SEND_POINTS` / `:35` `SEND_ALLOWLIST` (любая новая точка отправки обязана попасть в реестр).
- Стриминг/чанки саммари: `services/summary_generator.py:380-475` (при Article — отдельный путь доставки, стриминг не ломать).
- Группа промптов `prompts_summary` (`services/param_catalog.py`), группа моделей/ключей изображений — F5.

## КРИТИЧЕСКОЕ ПРАВИЛО ТЗ
Перед интеграцией `sendRichMessage` — **обязательно** изучить актуальную документацию Telegram Bot API через веб-поиск; проверить поддержку `Article` в установленной версии aiogram.

## Задачи
- [x] **T-2147** [@Architect] ADR-1023-6: контракт visual prompt (EN, ≤300, валидатор), поле «Стиль обложки» (каталог `prompts_summary`), контракт Article/`sendRichMessage` (Bot API 10.1+), регистрация новой точки отправки в `telegram_send`, путь доставки vs стриминг, тихий фолбэк, откат. Создать `spec.md` + `ADR-1023-6.md`.
- [x] **T-2148** [@Builder] **Веб-ресёрч (обязательно):** актуальная документация `sendRichMessage`/`InputRichMessage` и поддержки Article в используемой версии aiogram; сверить с рабочим образцом `handlers/info.py:103-104`; зафиксировать выводы в spec/ADR (без секретов).
- [x] **T-2149** [@Builder] Stage-1 Редактор саммари возвращает visual prompt (EN, ≤300) в JSON; валидатор в `services/system2_handoff.py` (нормализация/обрезка/отсутствие → пусто).
- [x] **T-2150** [@Builder] Настройка «Стиль обложки» в `services/param_catalog.py` (`prompts_summary`); конкатенация «авторский стиль + visual prompt» перед вызовом image-API (F5).
- [x] **T-2151** [@Builder] Доставка Article: сформировать Rich Text с обложкой через `sendRichMessage`; новая точка отправки зарегистрирована в `services/telegram_send.py` (SEND_POINTS/ALLOWLIST с обоснованием).
- [x] **T-2152** [@Builder] **Тихий фолбэк:** любая ошибка генерации обложки/Article → обычное текстовое саммари, пользователю без сообщений об ошибке (fail-open); стриминг/чанки не сломаны.
- [x] **T-2153** [@Builder] Канон-миграция ADR-1013-3 (слепки `PREV_*_R1023`, `services/prompt_migrations.py`, `plans/docs/canon/**`) — одним коммитом с изменениями Stage-1 промпта.
- [x] **T-2154** [@Builder] Тесты: разбор/лимит visual prompt, конкатенация стиля, путь Article, тихий фолбэк при ошибке image/Article, реестр egress покрывает новую точку.
- [x] **T-2155** [@Builder] Регресс: обычный путь саммари (стриминг/чанки) без обложки не сломан; полный pytest 0 failed.
- [ ] **T-2156** [@DevOps] Деплой + живая приёмка: саммари приходит Article с обложкой; при сбое — тихий текстовый фолбэк; отчёт (R17/R18).

## Критерии приёмки
- Редактор выдаёт visual prompt (EN ≤300); «Стиль обложки» конкатенируется и уходит в image-API.
- Саммари доставляется Article с обложкой; любая ошибка → тихий текстовый фолбэк.
- Новая точка отправки присутствует в реестре egress; канон-миграция атомарна.
- Полный pytest — 0 failed.

## Риски
- **R1 (High):** `sendRichMessage`/Article не поддержан версией aiogram → веб-ресёрч + фолбэк на текст (T-2148/T-2152).
- **R2 (High):** ломается стриминг/HTML-доставка саммари → отдельный путь Article, регресс обычного пути (T-2151/T-2155).
- **R3 (Medium):** незарегистрированная точка отправки обходит egress-guard → реестр + тест покрытия (T-2151/T-2154).
- **R4 (Medium):** обложка роняет саммари → silent fallback (T-2152/T-2154).
- **R5 (Medium):** канон-атомарность → один коммит (T-2153).
- **R6 (R17/R18):** секреты/сырьё в логах.

## Зависимости / ступени вливания
- **Зависит от F5** (провайдер/исполнитель изображений) и канон-контура (F1/F3) → после F5 и после F4.
- Эксклюзив: `services/summary_generator.py`, `services/summary_prompts.py`, `services/telegram_send.py`, `handlers/info.py` (образец — только чтение).
- Канон-контур: ступень … → F4 → **F6**.
- Требует `spec.md` + `ADR-1023-6` (Step 2 @Architect).

## Feature flag / раскатка
- `SUMMARY_COVER_ARTICLE_ENABLED` — env-only `ClassVar` (**default ON**, Δ каталога = 0): OFF → обычное текстовое саммари. Раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert` + обратная канон-миграция.
