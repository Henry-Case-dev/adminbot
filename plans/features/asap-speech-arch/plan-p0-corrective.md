# P0 CORRECTIVE — план работ (продолжение asap-speech-arch)

Источник: `source-owner-p0-corrective-2026-10-25.md` (дословный снимок, 214 строк).
Карта: `requirements-map-p0-corrective.json` (95 required / 28 context / 5 duplicate, 87 req_id).
Граф: `slice-graph-p0-corrective.json`. Plan-гейт: EXIT 0.

Новый эпик не создаётся. Ветка карты: `task/speech-hotfix-map`. Код правится в рабочей P0-ветке, кандидат появится позже.

## Волны и зависимости

| Волна | Слайс | Зависит от | Кто | Что доказывает |
|---|---|---|---|---|
| W0 | `PROD` | — | DevOps | 13 файлов production описаны по происхождению, reset/удаления нет, развёртывание воспроизводимо |
| W0 | `L1` | — | Builder | оба исходных запроса уходят в research/deep по реальному резолверу, глубина ≠ длина, без хардкода |
| W1 | `HARNESS` | L1 | Builder | harness из того же commit, счётчики сходятся, payload несёт RAG/Memory/Core/Expression |
| W2 | `PROBES` | L1, HARNESS, PROD | Builder | офлайн-пробы на верных режимах: 2 исходных запроса + короткие сообщения, без живых чатов |
| W3 | `ALIASES` | PROBES | Builder | Telegram ID, приоритет имён, 11 изолированных проверок, 12 runtime-путей, имя в фактическом payload, «Гипербореец» |
| W3 | `MEMORY` | PROBES | Builder | аудит старых `lore_stories`, provenance блокирует выдумки, точечная правка, история сохранена |
| W4 | `CORE` | ALIASES | Builder | полный Core без обрезки, FREQUENT в реальном режиме, нет мета-вступлений и навязанной структуры |
| W5 | `REVIEW` | PROBES, ALIASES, MEMORY, CORE | Reviewer | 9 условий §4 на артефактах кандидата; при провале — конкретный дефект и повтор |
| W6 | `DEPLOY` | REVIEW | DevOps | штатный деплой: версия, `/healthz`, чистый старт |
| W7 | `REPORT` | DEPLOY | PM | 8 вопросов §5 фактами, включая остаточные проблемы |

## Параллельность

- W0: только два независимых писателя — `PROD` (evidence production) и `L1` (`services/direct_l1.py`), области не пересекаются.
- W3: `ALIASES` и `MEMORY` не параллельны в этой карте: `MEMORY` зависит от `PROBES`, `CORE` — от `ALIASES`. Причина — общий payload и общая схема записей; два писателя дали бы конкурирующие источники имени/факта.
- Максимум одновременных писателей — 2. Дальше цепочка сериализована сознательно.

## Ограничения владельца, зашитые в карту

- `PROBES-NO-LIVE-SENDS`: никаких тестовых отправок в рабочие Telegram-чаты.
- `PROD-NO-BLIND-RESET`: без `git reset --hard`, удаления файлов и перезаписи production-конфигурации.
- `MEMORY-NO-MASS-WIPE`: без массовой очистки истории и без новых квот инструкций.
- `ALIAS-EXISTING-MECHANISMS`: без новой независимой системы имён.
- `MAN-OWNER-LIVE-NOT-GATE`: `owner_live_checks` не является условием DONE/деплоя; все строки — `verification_tier=engineering`.

## Барьеры

- `L1` → `HARNESS`: без исправленного маршрута замеры стенда бессмысленны.
- `PROBES` → `ALIASES`/`MEMORY`: правки поведения проверяются на уже исправном стенде и на реальных данных.
- `REVIEW` — единственный владелец вердикта; `DEPLOY` не начинается без APPROVED, `REPORT` — без фактической версии на production.
- Кандидат привязывается к карте при первом review-гейте; до этого `candidate_commit` пуст, VERIFIED не выставляется.
