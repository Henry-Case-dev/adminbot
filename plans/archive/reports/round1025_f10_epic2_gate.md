# F10 — §79 СТОП-ГЕЙТ: существующий пайплайн Саммари / generate_image / sendRichMessage / fallback (T-3116/T-3117/T-3118)

> **Тип:** smoke/интеграция **существующего** пайплайна БЕЗ изменения алгоритмов
> (§79: «Только после этого приступать к изменению алгоритмов Саммари»).
> Новый пайплайн Эпика 2 в прод **не включался**.

## Инвариант «не переписано»

`git diff --stat` по рантайму — пусто (изменены только `tools/**`, `plans/**`,
`tests/**`). Алгоритмы Саммари / `generate_image` / `sendRichMessage` / текстовый
fallback **не изменялись**.

## T-3116 — существующий пайплайн Саммари

Smoke/интеграция (без изменения алгоритмов): `pytest -q` подмножества
`test_summary_generator`, `test_summary_handlers`, `test_summary_prompts`,
`test_summary_two_call_round1022`, `test_hotfix3_summary_fallback_round1025`,
`test_hotfix5_summary_cover_window_round1025` → **зелёно**. Общий прогон
`pytest -q` → **8463 passed**.

## T-3117 — `generate_image`

`test_image_generation_round1023`, `test_summary_cover_round1023`,
`test_summary_cover_model_compat_round1024`, `test_summary_cover_round1023` →
**зелёно**; `services/**` не менялся (подтверждение отсутствия правок).

## T-3118 — `sendRichMessage` + текстовый fallback

- `sendRichMessage` присутствует в `services/telegram_send.py` (2) и
  `services/summary_generator.py` (1) — не изменялся.
- Fallback-покрытие: `tests/test_hotfix3_summary_fallback_round1025.py` (отсутствие
  обложки не теряет текст), `tests/test_hotfix5_summary_cover_window_round1025.py`
  — **зелёно**.
- §116-блок «ЭПИК 2 НЕ ЗАВЕРШЁН, ЕСЛИ…» к текущему (старому) пайплайну **не
  применяется** — Эпик 2 не начат; проверялись только инварианты «не переписано»
  и «работает».

## Сводный прогон подмножества §79

```
pytest -q tests/test_summary_generator.py tests/test_summary_handlers.py \
  tests/test_summary_prompts.py tests/test_summary_two_call_round1022.py \
  tests/test_hotfix3_summary_fallback_round1025.py \
  tests/test_hotfix5_summary_cover_window_round1025.py \
  tests/test_image_generation_round1023.py tests/test_summary_cover_round1023.py \
  tests/test_summary_cover_model_compat_round1024.py
→ 300 passed
```

## Вердикт стоп-гейта

Существующий пайплайн Саммари / `generate_image` / `sendRichMessage` / текстовый
fallback **работает и не изменён** (`git diff` по рантайму пуст). Условие §79 для
старта Эпика 2 **выполнено** (см. `round1025_f10_acceptance.md`, D4).
