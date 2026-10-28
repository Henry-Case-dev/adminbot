# QUOTES-URL-FIX — кавычки внутри URL больше не считаются обычным текстом

Кандидат: `f0092e8a` — «fix(style): keep guillemets inside URLs protected
(QUOTES-URL-FIX)» (`services/style_policy.py`, `tests/test_quotes_modes.py`).
Этот файл привязан к нему отдельным docs-коммитом (HEAD полосы).

## Причина

`_URL_RE` (`services/style_policy.py:1240-1244`) исключал `«»` из набора
символов URL: `[^\s<>()"\'«»\[\]]+`. Для текста
`https://example.org/s?q=«x»` совпадение обрывалось на `«`, весь URL в защиту
не попадал, и режимы кавычек правили саму ссылку.

## Исправление

- В charset URL добавлены `«»` (IRI/поисковые запросы): ссылка защищается
  целиком, включая кавычки внутри.
- Новый `_url_span_end` срезает хвостовую пунктуацию и только **непарные**
  закрывающие `»`: `«https://x/a»` остаётся «кавычки вокруг ссылки», а не
  «URL, поглотивший закрывающую кавычку».
- Кавычки вне ссылки обрабатываются как раньше; A/B/OFF, код, JSON,
  литералы и дюймы не затронуты.

## До / после (реальные прогоны `StylePolicyValidator.run`)

```
BEFORE normalize  Смотри https://example.org/s?q=«x» и всё -> ...?q="x" и всё    repaired
BEFORE normalize  https://x/«y»                            -> https://x/"y"       repaired
BEFORE strip      Смотри https://example.org/s?q=«x» и всё -> ...?q=x и всё      repaired
BEFORE strip      https://x/«y»                            -> https://x/y         repaired

AFTER  normalize  Смотри https://example.org/s?q=«x» и всё -> байт-в-байт        exempted/protected_verbatim
AFTER  normalize  https://x/«y»                            -> байт-в-байт        exempted/protected_verbatim
AFTER  strip      Смотри https://example.org/s?q=«x» и всё -> байт-в-байт        exempted/protected_verbatim
AFTER  strip      https://x/«y»                            -> байт-в-байт        exempted/protected_verbatim
AFTER  normalize  «https://x/a»                            -> "https://x/a"       repaired (обе кавычки — текст)
AFTER  strip      «https://x/a»                            -> https://x/a         repaired
AFTER  OFF        Смотри https://example.org/s?q=«x» и всё -> байт-в-байт        исходов нет
```

## Тесты

RED (старый `_URL_RE`, `git stash` только `services/style_policy.py`):

```
py -3 -m pytest tests/test_quotes_modes.py -k "guillemets or outside_url or trailing_closer"
6 failed, 4 passed, 30 deselected
```

PASS на кандидате:

```
py -3 -m pytest tests/test_quotes_modes.py            -> 40 passed
py -3 -m pytest tests/test_quota_removal_composer.py  ->  8 passed
py -3 -m pytest tests/test_soul1_style_policy.py      -> 59 passed
py -3 -m pytest tests -k quotes                       -> 67 passed
```

Новые тесты (`TEST-LIFECYCLE: REGRESSION owner=QUOTES-URL-FIX`):
`test_url_with_guillemets_stays_byte_identical` (3 текста × 2 режима),
`test_quotes_outside_url_are_still_processed`,
`test_trailing_closer_after_url_is_not_swallowed`.

## Границы

Прод/SSH не трогались; каноны, композер, `mca_expression`, карты и
`plans/current_task.md` не менялись. Поведение A/B/OFF не изменено:
меняется только распознавание защищённого URL-сегмента.
