# Addendum к binding C2/C3 — исправление review-блокера (whitespace only)

- Предыдущий кандидат: `fa37e48522ce3522943442a6e378cc2dc36eb139`
- Новый кандидат для повторного ревью: `946bfc260ed6772469eb79fa311dee0b92f476c0`
- Ветка: `smart/c-source`; база `36dd6b23` (C1) не менялась.
- Вердикт Reviewer: `Needs Fixes` с единственным блокером — trailing whitespace в
  `git diff --check 36dd6b23 fa37e485`.

## Что исправлено (только whitespace)

| Файл | Действие |
|---|---|
| `services/direct_context_composer.py` | CRLF → LF по всему файлу; trailing spaces/tabs удалены. Логика, лимиты, docstring-содержание и тесты не менялись. |
| `plans/features/.../evidence/c2c3/*.txt`, `*.diff` | удалены trailing spaces (pytest-логи/мутационный diff), содержимое читаемо |
| `plans/features/.../evidence/review-c2c3-fa37e485.md` | line endings + лишняя пустая строка в EOF; текст ревью не менялся (включая финальное обновление `dd96aafd review-c2c3-update`) |

Доказательство отсутствия поведенческих изменений:
```
git diff -w --stat fa37e485 HEAD -- services tests
# пусто; IGNORE_WS_LINES=0
```

## Проверка

```
git diff --check 36dd6b23 HEAD
# пусто, exit 0 (было 694 строки)

python -m pytest tests/test_smart_exec_evidence.py \
  tests/test_smart_c1_source_reader_limits.py -q
50 passed in 3.81s
# evidence/c2c3/pytest-whitespace-fix-0f6f7039.txt
```

Финальная нормализация также покрыла review-артефакт, обновлённый параллельным
`dd96aafd review-c2c3-update`; содержание не менялось. Итоговый `HEAD`
`946bfc26` — кандидат для повторного ревью.

Focused 24 + C1 26 = 50 passed; поведение и все проверки предыдущего кандидата
сохранены. Мутационное доказательство `fa37e485` остаётся действительным: файлы
изменены только по whitespace.

## Residual concern

Нет нового. Прежние cross-slice остатки C2-01/C3-02 из binding §7 не изменились
и по-прежнему требуют join с S2/S4/S8/S11/S13–S16; этот addendum их не закрывает.

`WHITESPACE_FIX_READY_FOR_RE_REVIEW`
