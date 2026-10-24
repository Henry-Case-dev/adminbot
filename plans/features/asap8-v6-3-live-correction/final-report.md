# ASAP 8 (v6.3 live correction) — остаток и классы

Время отчёта: 25.10.2026 08:44 UTC+12. Полоса `PM-RESIDUAL-CLOSE`, база `24ca634b` (docs-only).
Карта: candidate `d87284c1` (2.58.109), deployed в карте `fbf9013d`; прод на 25.10 — 2.58.129 @ `79ec3726`.
Ни одна строка в этой полосе не закрыта: новых замеров не было (прод/SSH/живые чаты запрещены).

## 1. Остаток (10 required строк)

| req_id | Статус | Класс | Что нужно |
|---|---|---|---|
| `U07-SYM-DESKTOP` | READY_FOR_LIVE | `OWNER_OPTIONAL` | Уже оформлено по `plans/owner_live_checks.md` (tier, policy_ref, причина, `engineering_req_ids` на `REQ-U07-HARD`/`U07.3a`/`U07-PLATFORMS`, `live_required=false`). Блокирующей роли не играет. |
| `REQ-U07-3` | READY_FOR_LIVE | `OWNER_OPTIONAL` | То же; инженерная часть (desktop-адаптив, Playwright, матрица платформ) доставлена. |
| `U07.3b` | READY_FOR_LIVE | `OWNER_OPTIONAL` | Клиентский журнал platform/version/drag/close ведётся на устройстве владельца; серверная часть и матрица есть. |
| `U07.3c` | READY_FOR_LIVE | `OWNER_OPTIONAL` | Нативные клиенты Windows/Android/iOS/macOS/Web; политика платформ и Android/Web-матрица закрыты. |
| `U07-OWNER-REALDEV` | PENDING | `OWNER_OPTIONAL` | Метаданные валидны, gate строку пропускает. Статус PENDING оставлен осознанно: это добровольное наблюдение, а не инженерная обязанность; VERIFIED без наблюдения был бы подделкой. |
| `REQ-B09-BODY` | READY_FOR_LIVE | `WAITING_EXTERNAL` | Нужно реальное событие Telegram `migrate_to_chat_id`; `chat_id_migrations` на проде пуста, механика (backup 1:1, resolve_canonical_chat_id) покрыта тестами. |
| `B10-R10` | READY_FOR_LIVE | `WAITING_EXTERNAL` | Тот же внешний триггер (перенос supergroup), закрывается вместе с `REQ-B09-BODY`. |
| `B10-R06` | READY_FOR_LIVE | `WAITING_EXTERNAL` | Восстановление квоты провайдера эмбеддингов + backfill/recovery; ротация ключей в бою подтверждена журналом (429→429→429). |
| `B10-R11` | READY_FOR_LIVE | `AGENT_CHECK_NOW` | Контракт Direct L1 (auth/budget/execution modes) доказан 43 тестами; в журнале окна не было отказов «запрет без ключа»/бюджет. Нужен контролируемый staging-прогон с принудительно отсутствующим ключом и лимитом. |
| `REQ-B11-E2E` | READY_FOR_LIVE | `AGENT_CHECK_NOW` | Для не-векторных механизмов нужен один контролируемый E2E на настоящих source/DB/worker (векторные честно `never_run` из-за квоты). |

## 2. Почему не закрыто больше

190 из 194 VERIFIED-строк имеют evidence, привязанное к `c2775a54` (2.58.79), а карта объявляет candidate
`d87284c1`. Поэтому release-gate даёт 289 ошибок, из которых 279 — этот структурный разрыв, а не отсутствие
доказательств. Массовая перепривязка candidate без повторной сверки каждого артефакта запрещена: это была бы
подделка. Лечение — отдельная задача «перепривязать карту ASAP8 к фактическому релизу и подтвердить артефакты».

## 3. Gate

`requirements_gate.py check --stage release --candidate d87284c1… --deployed-commit d87284c1…` → **EXIT 1**,
289 ошибок, разбор по видам:

- **190** — «no evidence bound to reviewed candidate»: строки с доказательствами, привязанными к `c2775a54` (2.58.79);
- **93** — «live requirement lacks evidence for stage release» у `live_required`-строк без live/production-доказательства, привязанного к candidate;
- **5** — статус `READY_FOR_LIVE` у обязательных live-строк (`REQ-B09-BODY`, `B10-R06`, `B10-R10`, `B10-R11`, `REQ-B11-E2E`);
- **1** — candidate `d87284c1` не совпадает с объявленным в карте deployed `fbf9013d`.

Owner-optional строки (4 RFL + 1 PENDING) гейтом пропускаются и в этот счёт не входят. Карта не «позеленена»;
новых обязательств для владельца не создано.
