# ASAP3 Corrective — план исполнения (PM-ASAP3)

Источник: `source-2026-10-23.md` (557 строк, sha256 `B6AFDB21…B498642`, read-only).
Карта: `requirements-map.json` — 234 required-строки → 171 уникальное требование, 47 context, 0 неклассифицированных; `strict_evidence`, `slice-graph.json`.
Приоритет **P0**: скрытые лимиты, кеши алиасов и имена из памяти молча отменяют явные настройки владельца.

## Волны

```
W0  AUDIT  ‖ GOV
W1  STYLE-LIMITS ‖ DASH ‖ HIDDEN-LIMITS ‖ IDENTITY
W2  UI               (единственный писатель web/app.js)
W3  MIGRATION        (factory/active/default/global/chat)
W4  ACCEPT           (S1–S10, A1–A16, ACC-01..ACC-10, отчёт)
```

Зависимости и write scopes зафиксированы в `slice-graph.json`; одновременные писатели не пересекаются.
Сознательные последовательные соединения: `MIGRATION → UI` (имена параметров), `STYLE-LIMITS → MIGRATION`
(контракт лимитов), `IDENTITY` использует `prompt_composer.py` только после `STYLE-LIMITS`.

## Архитектурная классификация

- `ARCH_REUSE_CONFIRMED` — STYLE-LIMITS, DASH, HIDDEN-LIMITS, MIGRATION: работают в существующих
  `prompt_style_blocks.py`, `style_policy.py`, `prompt_composer.py`, `param_catalog.py`, `hot_config`,
  `chat_params`; контракты SOUL-16 (`effective_style_policy`) и SOUL-10.P3 (единый Inspector) не меняются.
- `ARCHITECT_REQUIRED` — IDENTITY: единый порядок имён для всех речевых маршрутов, слияние global/chat
  по каждому `user_id` и путь инвалидации кешей/обратных карт — общий контракт между Direct, Summary,
  инициативой, инструментами и досье. До фиксации решения Builder не трогает `summary_aliases.py`,
  `message_identity.py`, `bot.py`; допустим read-only аудит §5.
- Проверено фактически: `STYLE_POLICY_HINT_MAX_CHARS=400` / `MAX_ITEMS=5` есть в
  `services/prompt_style_blocks.py:431-432` и урезают блок; `AliasResolver` не инвалидирует `_by_name`,
  `build_alias_resolver` подставляет чатовый словарь целиком — оба дефекта источника подтверждены.

## Что можно запускать сразу

1. `AUDIT` — read-only снимок кода, активной конфигурации PostgreSQL и factory-defaults.
2. `GOV` — нормативные запреты §0/§5/§6 проверяются на каждом диффе.
3. После AUDIT без ожидания архитектора: `STYLE-LIMITS`, `DASH`, `HIDDEN-LIMITS` (инвентаризация).
4. `IDENTITY`, `MIGRATION`, `UI`, `ACCEPT` — после решения ARCH-ASAP3 по контракту имён.

## Пересечения — reuse, не дублировать

SOUL-1 W6 «Речь и характер» / SOUL-16.5.1 «Стиль письма»; SOUL-10.P3 единый Prompt Inspector;
CFG-каталог `param_catalog`/`chat_params`; ASAP-2 Direct — те же маршруты и резолвер.
Второй резолвер, реестр имён, страница настроек и универсальная система лимитов запрещены (§0, §2).
## Живые проверки

`A16` и `ACC-09` — `live_required: postdeploy` (READY_FOR_LIVE до деплоя, затем реальные доказательства).
Наблюдения владельца в живом Telegram-чате — необязательные, отдельно; `BLOCKED_REAL_HUMAN_GATE`
по ним не создаётся (§10, строка 553). Живые сообщения в рабочие чаты не отправлять (строка 491).
