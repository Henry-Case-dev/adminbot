# AC-23 golden set - независимое ревью

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `b3e9fe6e5ee7a696cc5e385532cea10317a5d437`, docs `e617bc8e49b2fb5b96c9ad8d8e4d801803527751`.
База: `16fa04e7`; production code не менялся; golden - только tests.

**Вердикт: Approved для SD1-AC-23.** 36 anonymized cases + 2 meta
используют существующие DiagnosticCollector/probes/inspect_runtime/
prompt_readback/CheckupService; измерения accuracy/evidence/hallucination/
scope/style покрыты. Это deterministic contract set, не production false-rate.

## 1. Состав и assertions

- 36 cases: known_cause 15, irrelevant_commit 3, insufficient_data 5,
  wrong_role 4, secret 3, negative 3, style 3; 2 meta (shape/coverage,
  anonymization).
- Assertions реальные: status/reason/facts paths, not_checked, absent/
  present/output_present, redaction, sent count, stable prompt hash, plain
  text; `_check` fails on concrete mismatches.
- Cases проходят через существующий collector/probes, реальный
  `inspect_runtime` dispatch, `readback.prepare`, `CheckupService`; нового
  harness/движка/агента/LLM/стора нет.
- Anonymous: нет owner id, repo origin, прод-VPS, bot-token формы;
  synthetic IDs/secret.

## 2. Независимые проверки

- `tests/test_self_diag_golden.py` -> **38 passed**.
- selected golden cases `G16/G17/G19/G24` -> **4 passed**.
- 355 focused set -> **355 passed**; D5 prompt set 62; prompt baseline 56+1.
- Мутации набора из evidence (STT cause, empty journal, incident fingerprint,
  foreign voice queue, prompt secret) дают ожидаемый RED; independent
  mutation D5 role-whitelist также red/restore green.

## 3. Границы

- Набор не измеряет production false diagnosis rate и доли observed/
  hypothesis; `golden_eval.available=false` остаётся. Это contract checks,
  не live-статистика.
- Backlog D3/D4: `_probe_deploy_identity` не отдаёт requested commits в facts;
  `conflict` не меняет status. Golden фиксирует фактическое поведение, не
  обходит его. Не AC-23-блокеры.
- Live Telegram/PG и реальные инциденты не проверялись.

## 4. Строка AC-23

`SD1-AC-23`: **REVIEW**-кандидат; golden set >=25 и покрытие измерений
подтверждены. D7/AC-23/self-diag DONE не объявляется; карта/progress_scope
не менялись.

## 5. Три опоры

- **Implementation:** прочитаны CASES, `_run_*`, `_check`, meta tests;
  проверено использование существующих путей.
- **Test validity:** 38/355/56+1 запусканы; assertions 36 cases и meta
  прочитаны; selected golden cases и mutations дают RED.
- **Independent challenge:** G16/G17/G19/G24 и D5 role-spoof mutation;
  конкретные status/reason/facts/absent проверки, не тавтологии.

## 6. Итог

**Approved** для AC-23 на `b3e9fe6e` / `e617bc8e`. Production code/
settings/prod не менялись; деплоя не было; probe/mutation временные
артефакты закрыты.

