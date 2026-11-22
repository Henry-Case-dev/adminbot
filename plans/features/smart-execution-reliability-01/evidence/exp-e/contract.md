# EXP-E-TRUNC / EXP-E-LAG — контракт исполнения (2026-11-22)

- Owner input: `plans/owner_inputs/2026-11-22-p0-embed-503-failover.md`, §B,
  sha256 `d23bf6f96c69e8ddd1537a07f8f203fbf434b0022f693e5368a64c8731828f09`.
- Amendment map: `plans/features/smart-execution-reliability-01/requirements-map-exp-amendment.json`
  (`strict_evidence: true`, `amended: true`, `S9-EVENT-PIPELINE`).
- Plan: `plans/features/smart-execution-reliability-01/plan.md` §12.
- Deployed/base: `56e2450d2c02e3d8ac595b9a412a121127f57b57` (2.58.234).
- Branch: `fix/exp-e-trunc-lag`; implementation commit:
  `819361a71d8c5ce122dc4919107d464e085e2f92`.
- Не новый эпик/экстрактор/очередь. `progress_scope.json` и
  `workflow_state.md` не изменялись; deploy/SSH/LLM/prod не выполнялись.

## Обязательные строки

| ID | Наблюдаемая приёмка | Где доказано |
|---|---|---|
| `EXP-E-TRUNC-01` | `truncated_reasoning, finish_reason=length` воспроизводится; универсальный 1500 не применяется; бюджет учитывает модель и размер окна; контролируемый retry/уменьшение окна; принимается только валидный контент; typed parse/SourceRef/idempotency сохранены; отказавшееся окно не крутится вечно | `tests/test_exp_e_trunc_lag_amendment.py` (1–3, 7); `red-green.md` A |
| `EXP-E-LAG-01` | установлена и исправлена причина несходимости; новые события обрабатываются при отстающем хвосте; lag — измеренный COUNT; история не удалена; курсор не двигается фиктивно; lag не подменён нулём | тесты 4–6, 8–9; `red-green.md` B/C; `implementation.md` §2 |
| `EXP-E-DOD-B-01` | reasoning-only → восстановление; durable-курсор/restart; измеренные throughput/lag до/после; непроверенный production-спад = REVIEW/RFL | тесты 3, 8; §«Статус» ниже |
| `EXP-E-AMEND-STAMP-01` | `amended=true` + дата + owner ref/sha + связи `EXP-FIX-02/03`, `SXR-I2-01`, `EP-E-EXTRACT/ACCEPT`; без нового эпика/очереди | map + plan §12; этот контракт |

Связанные существующие обязательства: `EXP-FIX-02` (темп дренажа отдельно от
каденции), `EXP-FIX-03` (прочитанные/pending/checkpoint), `SXR-I2-01`
(несколько батчей за проход, честный lag/throughput), `EP-E-EXTRACT` /
`EP-E-ACCEPT`.

## Границы

В scope только существующий Experience-контур:

- `services/mca_experience_jobs.py` — семантический экстрактор, его durable
  checkpoint, планировочные пределы и замер lag;
- `tests/test_exp_e_trunc_lag_amendment.py` — новые RED→GREEN тесты;
- `tests/test_mca16_experience_block_d_round1039.py` — обновлён source-pin:
  вместо удалённого `SEMANTIC_BATCH_MAX_TOKENS` пин требует модельный бюджет.

Вне scope (не изменялось): `mod-acl-ux-01`, C3/ACL/UI, embedding/503,
схема БД/DDL, `record_feedback`, `progress_scope.json`,
`workflow_state.md`, второй планировщик/воркер/очередь.

## Инварианты

1. Курсор двигается только после durable обработки валидного ответа
   (или deliberate skip структурно непригодных строк).
2. Reasoning не становится `content`: обрезанный ответ не парсится и не
   двигает позицию.
3. `pending` уменьшается на прочитанные строки и не уходит ниже нуля.
4. История не удаляется; `lag_rows` — измеренный `COUNT` после курсоров
   (включая обе полосы), а не `max_id - cursor` и не `pending`.
5. Один job, один экстрактор, один LLM-путь; fresh-полоса — durable-курсор
   внутри того же прохода.
6. Повторный проход идемпотентен по существующему `dedup_key` /
   `record_feedback`.
7. Отказавшееся окно получает durable причину, уменьшенное окно и
   ограниченный backoff; вечного tight-loop нет.

## Статус

Реализация и локальные проверки: `REVIEW`. Реальный спад production-lag не
измерялся (деплой запрещён рамками задачи) → **RFL** для
`EXP-E-LAG-01/EXP-E-DOD-B-01`; `VERIFIED` без production-замера не
заявляется.
