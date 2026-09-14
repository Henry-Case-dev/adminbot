# Фича F2 — `guide-delivery-round1016` (Доставка «Гайда по фичам» + политика канона)

> **Статус: ✅ COMPLETED** (14.09.2026; @Reviewer APPROVED, итерация 2). Реализовано T-1635…T-1640; гейт T-1641 открыт (@DevOps: доставка canon_version==2 / canon_drift==false).
> **Spec:** [`spec.md`](spec.md) · **ADR:** [`adr-1016-3-guide-canon-versioning.md`](adr-1016-3-guide-canon-versioning.md).
> **Раунд:** 10.16. **Нумерация:** T-1634…T-1641.
> **Тип:** backend (config/info) + docs. **Приоритет:** **P1 (прод-регресс ТЗ §7)**.
> **Зависимости:** нет (конфликт файлов с F3/Audit — тесты; и с F1 — нет).
> **Конфликт файлов:** `services/config_cache.py`, `services/info_service.py`, `handlers/*` (`/edit_info`), `web/api/routes.py` (POST `/api/info`, `/api/info/guide`), `info_text.md`; тесты `tests/test_info_service.py`, `tests/test_config_cache*`.
> **Эпик:** `Epic: Багфиксы + полный аудит round1016`.
> **ТЗ:** `plans/current_task.md`, **UPD2** (строка 151: «Задача 7 не выполнена…») + §7 (строки 50-56).
> **Baseline:** HEAD `18a9aa1`; pytest **5774 passed / 0 failed**; каталог **435/90/406/411/88/19** (Δ=0); SQLite **v9**; APP_VERSION 2.57.0.

## 0. Цель

«Справка» содержит 2 блока:
1. **Legacy rich-HTML** `content.info_how_it_works` (GET `/api/info`, `services/info_service.py` `DEFAULT_INFO_TEXT`/`PREV_DEFAULT_INFO_TEXT`, сид `info_text.md`) — это и есть **«Гайд по фичам»**;
2. **Markdown** `content.intelligence_guide`.

Миграция `_migrate_info_how_it_works_v1015` (`services/config_cache.py:235-266`) перезаписывает **только** если PG-значение == `PREV_DEFAULT_INFO_TEXT`; иначе (ручная правка/дрейф) → WARNING и пропуск. Прод-PG был засеян старой/дрейфовой версией → миграция пропущена → **гайд в проде остался как был**.

Дополнительно: `InfoService.save_text` (`services/info_service.py:202-217`) пишет в **git-tracked** `info_text.md` → дрейф и блокировка fast-forward pull.

Цель: политика версионирования канона (известные PREV-слепки / force-reset), фактическая доставка нового гайда в прод, устранение блокирующего write-path в tracked-файл, байт/смоук-тесты.

## 1. Доказательства (`file:line` на HEAD `18a9aa1`)

- `services/config_cache.py:235-266` — `_migrate_info_how_it_works_v1015`: `if html.strip() != _PREV_DEFAULT_INFO_TEXT.strip(): WARNING + return` (пропуск при дрейфе).
- `services/info_service.py:20-76` — `PREV_DEFAULT_INFO_TEXT` (слепок до F7); `:78-…` — `DEFAULT_INFO_TEXT` (новый канон F7).
- `services/info_service.py:202-217` — `save_text`: `open(self._file_path, "w")` — запись в **tracked** `info_text.md` + кэш + ConfigCache.
- `services/config_cache.py` `_seed_info_key` — сидит только при **отсутствии** ключа (обновление файлом не работает).
- `web/index.html` — блок «Справка» (2 блока: гайд по фичам + `content.intelligence_guide`).
- Тест байт-в-байт: `tests/test_info_service.py:28-45` (`DEFAULT_INFO_TEXT` ↔ `info_text.md`).

## 2. Требования (UPD2 §1 / §7)

- [x] Новый канон **фактически** доставляется в прод-PG (не пропускается из-за дрейфа).
- [x] Политика версионирования канона: известные PREV-слепки (список/хэши) + force-reset для админа (с бэкапом/аудитом).
- [x] Убрать блокирующий write-path в git-tracked `info_text.md`: PG-only либо неблокирующая синхронизация (не ломать fast-forward pull).
- [x] Байт-тесты канона + смоук-тесты миграции (идемпотентность, дрейф, force-reset).
- [x] Ручные правки владельца не затираются молча (либо явный force-reset с подтверждением).

## 3. Constraints (инварианты раунда)

- **SQL/DDL не требуется** (только DML по `content.*`); каталог-инварианты **435/90/406/411/88/19** — **Δ=0**.
- **R17:** секреты не логировать; `updated_by` — id, не имя (R16).
- **R16:** id — ключ.
- Байт-канон `DEFAULT_INFO_TEXT` не ломать без слепка; при правке канона — обновить `PREV_DEFAULT_INFO_TEXT` и/или реестр слепков + байт-тесты.
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **Новых CDN/`v-html` без санитайза нет** (гайд — rich-HTML legacy + Markdown/DOMPurify self-host).
- **Git-гигиена:** не коммитить `plans/current_task.md`; `info_text.md` не должен становиться источником дрейфа, блокирующего pull.
- **Ревью-гейты:** полный `pytest` 0 регрессий, байт-тест канона, R17-скан, `git diff --check`; русские commits.

## 4. Зависимости / порядок

- **Вверх:** нет. **Вниз:** F3 (смоук-тест guide), F5 (финализация).
- **Порядок:** вторая фича раунда.

## 5. Definition of Done

- [ ] Прод-PG после релиза содержит **новый** канон (миграция больше не пропускается при известном дрейфе). *(авто-доставка при старте: известный слепок → миграция; иначе одноразовая форс-доставка канона с маркером `canon_delivered_version`, ревью-итер.1; проверка — гейт T-1641 после деплоя: `canon_version==2`, `canon_drift==false`)*
- [x] Есть force-reset/версионирование канона с аудитом; ручные правки не теряются молча.
- [x] `save_text`/`/edit_info` не блокируют pull (PG-only).
- [x] Байт/смоук-тесты (идемпотентность ×2, дрейф, force-reset) зелёные.
- [x] Полный `pytest` **0 failed** (5931 passed); каталог **Δ=0**.

## 6. Чек-лист задач

- [ ] **T-1634 (@Architect, гейт):** полировка политики: реестр версий канона (PREV-слепки/хэши), семантика force-reset, write-path (PG-only vs sync), учёт 2 блоков Справки.
- [x] **T-1635 (@Builder):** `services/config_cache.py` — версионирование канона: список известных PREV-слепков + идемпотентная миграция до актуального `DEFAULT_INFO_TEXT` (в т.ч. для дрейфованного прод-PG).
- [x] **T-1636 (@Builder):** force-reset гайда (админ-действие, RBAC `edit_info`): бэкап текущего + запись нового канона + аудит `updated_by`/`updated_at`.
- [x] **T-1637 (@Builder):** `services/info_service.py` — устранить блокирующий write-path в tracked `info_text.md` (PG-only); сид-файл — только источник кода-канона.
- [x] **T-1638 (@Builder):** `tests/test_info_service.py` + config-cache тесты: байт-канон, миграция ×2, дрейф→доставка, force-reset, устойчивость при PG down.
- [x] **T-1639 (@Builder):** смоук доставки: симулировать прод-PG со старым текстом → после init PG == `DEFAULT_INFO_TEXT` (без ручного вмешательства).
- [x] **T-1640 (@Builder):** гейты: полный `pytest` 0 failed, каталог Δ=0, R17-скан, `git diff --check`.
- [ ] **T-1641 (@PM/@Reviewer, гейт):** сверка DoD, проверка прод-доставки гайда и политики канона.

## 7. Открытые вопросы (@Architect → владелец)

- Формат реестра слепков: явный список строк vs хэш-нормализация (пробелы/переводы строк)?
- Force-reset: автоматический при «известном дрейфе» или только по явной команде админа?
- `info_text.md` — оставить как read-only сид (убрать из write-path) или исключить из репозитория в пользу PG-канона?

## 8. Feature flag / progressive delivery

- **Flag не требуется.** Rollback = `git revert` + force-reset гайда админом.
- **Progressive delivery:** доставка гайда — идемпотентная DML-миграция (атомарно на старте); мониторинг — `[config_cache]`-логи.
