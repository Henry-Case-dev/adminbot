# D6 B2/B3 residuals - независимое re-review

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `d5e97727fd5808df0de137421c713678a699aa86`, docs `ca9e9cb37a295434b8a751e6731e350804059fc3`.
База: `722ccfc5`; предыдущий кандидат `cbb52d66` (Needs Fixes по B2/B3 residuals).
Diff `cbb52d66..HEAD`: только `handlers/checkup.py`, `web/api/routes.py`,
`tests/test_checkup_contract.py`, F8 re-pin и docs. B1/B4-файлы, UI, промпты,
настройки, D3/D5/D4 не менялись.

**Вердикт: Approved для B2/B3-исправления.** B2/B3 residuals закрыты;
B1/B4 остаются подтверждёнными. D6/self-diag DONE не объявляются; полная
строка `SD1-D6-18` остаётся partial из-за ранее известных неинструментированных
retry/cache/stale, а D7/live/UI остаются за пределами этого среза.

## 1. B2 - skipped вне calls/latency

`web/api/routes.py:3704-3758`: `measured` исключает `skipped`; `triggered`
считает все события; `calls`, `durations`, `by_stage` и p50/p95 строятся только
по measured.

Независимый прогон `_self_diag_stats`:

```text
checkup_triggered: triggered=3 calls=1 partial=0 complete=1 skipped=2
                   partial_share=0.0 p50_ms=900 p95_ms=900 measured=true
by_stage: [{"stage":"final","calls":1,"failed":0,p50:900,p95:900}]
inspect_runtime_called: calls=1 partial=1 complete=0 p50=200
only_skipped: triggered=1 calls=0 partial_share=null measured=false
```

Один `report_sent` 900 ms + `cooldown` 0 ms даёт `calls=1`, `p50=900`;
cooldown не искажает latency. `inspect_runtime/degraded` остаётся partial.
B2 residual снят.

## 2. B3 - allowed-only validation

`handlers/checkup.py:225-245` теперь проверяет `publication.allowed`, берёт
`publication.status` (а не несуществующий `.report`) и вызывается только после
ветки blocked. `web/api/routes.py:3790-3805` считает только
`checkup_output_validated` со статусами `clean`/`partially_redacted`.

Независимые результаты:

```text
success checkup + blocked checkup + blocked validation:
{"measured": false, "value": null, "reason": "validation_not_correlated",
 "deliveries":{"checkup":1,...}, "validated":{"checkup":0,...},
 "gaps":{"checkup":1}}

paired allowed:
{"measured": true, "value": 0, "reason": "enforcement_measured", "gaps":{}}

publication events:
[("checkup_output_validated","clean"),
 ("checkup_output_validated","partially_redacted")]
blocked publication -> события нет
```

Blocked-валидация больше не закрывает gap; ложный измеренный 0 не
воспроизводится. B3 residual снят.

## 3. B1/B4 и D3/D5/D4

- B1-файлы (`services/checkup_service.py`) и B4-код (`checkup_probe_deps`)
  в диффе отсутствуют; ранее подтверждённые per-run hash/source и
  `configured=0/24 false` сохраняются.
- 39 checkup contract включают B1/B2/B3/B4; B1/B4 assertions зелёные.
- 932 focused D6+D3/D4/D5 и 661 D4-B+prompt contracts проходят; approved
  D3/D5/D4 behavior не сломан. Merge-коммиты чистые.

## 4. Тесты и mutation

- `pytest tests/test_checkup_contract.py -q` -> **39 passed**.
- Broad focused D6+D3/D4/D5 (22 файла) -> **932 passed**, 1 warning.
- D4-B+prompt contracts -> **661 passed, 1 failed**; только pre-existing
  `mca10b` pin 643 vs 644 (D4-B, не D6); BACKLOG.
- **Independent mutation:** в отдельном worktree @ `d5e97727`
  `measured = list(states)` (skip exclusion удалён);
  `test_cooldown_is_not_a_call_or_latency_sample` -> **1 failed**
  (`calls == 2`, expected 1); restore -> **39 passed**.
- RED на старом `cbb52d66` по binding: 3 failed/2 passed; на `d5e97727`
  все 39 green.

## 5. Строки D6

- **REVIEW-eligible:** `SD1-D6-05` (B1), `SD1-D6-17` (B3), B2-часть
  `SD1-D6-18`, `SD1-D6-12/16` (B4; UI render D7).
- **Partial, не полный REVIEW:** `SD1-D6-18` - retry/cache-hits/stale reads
  по-прежнему не инструментированы и честно `null/measured=false`; это
  ранее известное ограничение, не B2/B3-регрессия. `SD1-D6-19` (golden eval/
  hypothesis), `SD1-D6-20` (history growth) - partial/D7.
- **D7/live/UI:** реальный Telegram/VPS, UI-рендер, golden eval, hypothesis
  shares, история роста, code-vs-wrong-SHA, фактическая доставка prompt
  readback.
- D3/D5/D4 approved behavior сохранён. `SD1-D6-07` дважды в карте и
  `mca10b` pin - PM/backlog. 200-vs-403 - не блокер без явного контракта.


## 6. Три опоры

- **Implementation:** прочитаны diff B2/B3, `_self_diag_stats`,
  `_self_diag_validation_coverage`, `emit_checkup_validation_event`; проверено,
  что skipped исключены из calls/latency, blocked не эмитит validation, а
  status берётся из `Publication.status`.
- **Test validity:** 39/932/661 запусканы; assertions B2/B3 прочитаны;
  mutation skip-exclusion red/restore green. `SD1-D6-18` partial-часть
  (retry/cache/stale) тестами не притворяется измеренной.
- **Independent challenge:** один success + cooldown -> calls=1/p50=900;
  degraded inspect -> partial; success+blocked validation -> measured=false/
  gaps=checkup:1; paired allowed -> measured=true/value=0; blocked publication
  не эмитит validation.

## 7. Итог

**Approved** для B2/B3-исправления на `d5e97727` / `ca9e9cb3`. B1/B4 и
D3/D5/D4 behavior сохранены. D6/self-diag DONE не объявляются: полная
`SD1-D6-18` остаётся partial из-за неинструментированных retry/cache/stale,
D7/live/UI остаются открытыми. Карта/progress_scope не менялись; продуктовый
код/настройки/прод не менялись; деплоя не было; mutation worktree и probe-run
закрыты.

