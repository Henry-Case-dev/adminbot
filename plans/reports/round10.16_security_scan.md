# Раунд 10.16 — F5 `security-rotation-finalize-round1016`: скан секретов и git-гигиена

> **Исполнитель:** @Builder (Step 4, T-1662/T-1663). **Дата:** 14.09.2026.
> **Baseline:** HEAD `18a9aa1` + незакоммиченное рабочее дерево (F1–F4).
> **Тип:** security-верификация + docs. **Прод-код не менялся** (каталог-Δ=0).
> **Правило:** значения секретов в этом отчёте **не приводятся** (R17) — только факты и счётчики.

## 0. Итог (кратко)

| # | Проверка | Результат |
|---|---|---|
| 1 | `plans/current_task.md` в рабочем дереве git | **не отслеживается** ✅ |
| 2 | `plans/current_task.md` в истории git | **нет** ✅ |
| 3 | Пароль/секрет в истории (скан по безопасному маркеру) | **0 совпадений** ✅ |
| 4 | Приватные ключи (`BEGIN ... PRIVATE KEY`) в tracked + истории | **0** ✅ |
| 5 | `.env` когда-либо в git | **нет** ✅ |
| 6 | Прочие закоммиченные креды в tracked-файлах | **не найдено** ✅ |
| 7 | `git diff --check` | чисто (только штатные LF→CRLF) ✅ |

**Вывод:** утечки пароля/SSH-доступа в git-историю и tracked-файлы **нет**;
`git filter-repo` не требуется. Пароль присутствует только в **untracked** рабочем
файле владельца — его ротация/отзыв за @DevOps (см. `ssh-rotation-checklist.md`).

## 1. `plans/current_task.md` — не в git

```bash
$ git ls-files --error-unmatch plans/current_task.md
error: pathspec 'plans/current_task.md' did not match any file(s) known to git

$ git log --all -- plans/current_task.md
# (пусто — файл никогда не коммитился)

$ git check-ignore -v plans/current_task.md
.gitignore:70:plans/current_task.md	plans/current_task.md

$ git ls-files --error-unmatch .env
error: pathspec '.env' did not match any file(s) known to git

$ git log --all --diff-filter=A -- .env | wc -l
0
```

- `.gitignore:67-70` — явное правило «личный вход владельца: ТЗ текущего раунда (не для git)».
- Файл существует в рабочей копии и содержит плейнтекст-пароль (`:61-76`) — это
  **рабочее состояние владельца**, не репозитория. Правка рабочей копии — по
  согласованию с владельцем (Builder её не трогает).

## 2. Скан истории на секрет (без печати значения)

Использован **безопасный маркер** — подстрока пароля из рабочей копии
(само значение намеренно не приводится и в отчёт не сохраняется).

```bash
$ git log --all -S'<маркер>' --oneline | wc -l
0

$ git grep -I -n '<маркер>' $(git rev-list --all) 2>/dev/null | wc -l
0
```

Дополнительно — история по маркерам «санитизации» и ключевым заголовкам:

```bash
$ git log --all -S'PASSWORD = "'            --oneline | wc -l   # 0
$ git log --all -S'BEGIN RSA PRIVATE KEY'   --oneline | wc -l   # 0
$ git log --all -S'BEGIN OPENSSH PRIVATE KEY' --oneline | wc -l # 0
$ git log --all -S'BEGIN PRIVATE KEY'       --oneline | wc -l   # 0
```

Единственные совпадения по `SUDO_PASSWORD`/`GIT_PASSWORD`/`DEPLOY_SSH_PASSWORD`
(по 1 коммиту) — это **комментарии санитизации** в `check_remote_bot.py` /
`deploy_v2.9.2.py` («хардкод-секреты убраны; пароль — env `DEPLOY_SSH_PASSWORD`
или `getpass`»), а не значения секретов.

## 3. Скан tracked-файлов и истории на прочие секреты

```bash
$ git grep -I -E "BEGIN .*PRIVATE KEY" -- . | wc -l                 # 0
$ git grep -I -E "ssh [a-z]+@[0-9.]+" -- . | wc -l                  # 6 (docs: «ssh user@host»)
$ git grep -I -E "[0-9]{8,10}:[A-Za-z0-9_-]{35}" -- . | wc -l       # 1 (опубликованный вектор)
```

- **Приватные ключи** — не найдены ни в tracked, ни в истории.
- **`ssh user@host`** (6 вхождений) — только в `plans/archive/*/tasks.md` и
  `plans/reports/round10.15_reviewer.md` как **деплой-инструкция** (без пароля).
  Хост/пользователь секретом не являются (адрес есть и в README/ARCHITECTURE).
- **Похожие на токен строки** — 1 вхождение: `tests/test_webapp_deps.py:583`
  `VECTOR_TOKEN` — **опубликованный вектор из официальной документации Telegram**
  (проверка HMAC `initData`), не боевой секрет (см. docstring теста).
- **Синтетические креды в тестах** (`sk-test-key`, `123456:TEST_TOKEN…`,
  `user:secret@127.0.0.1`) — заглушки, не реальные значения.
- **`deploy_*` / `check_remote_bot.py`** — несмотря на `.gitignore:6-7`, оба файла
  **отслеживаются** и уже **санитизированы**: секреты вынесены в env
  (`DEPLOY_SSH_PASSWORD`) / `getpass`; хардкода нет. Замечание (Info): трекаемые
  файлы «деплой-утилит» в `.gitignore` не влияют — правило применяется только к
  новым файлам; отдельного действия не требуется (файлы безопасны), но при
  следующей правке деплой-скриптов стоит решить: оставить (sanitized) или убрать
  из индекса `git rm --cached`.
- **`.env.example`** — только плейсхолдеры (`your_telegram_bot_token_here`,
  `your_postgres_password_here`), реальных значений нет.

## 4. Что НЕ делалось (осознанно)

- **`git filter-repo` / перезапись истории** — не требуется: секрет в истории не
  найден (§2). Force-push без явного запроса владельца запрещён.
- **Правка `plans/current_task.md`** — файл принадлежит владельцу (untracked);
  Builder его не редактирует. Удаление пароля из рабочей копии — по согласованию
  с владельцем (см. открытые вопросы в `tasks.md` §7).
- **Хардening-хук** — `.gitignore` уже покрывает личный файл; pre-commit не
  добавлялся (нет зависимости в проекте, польза при untracked-файле нулевая).

## 5. Ротация (вне репо, @DevOps)

Процедура и чек-лист — [`ssh-rotation-checklist.md`](../features/security-rotation-finalize-round1016/ssh-rotation-checklist.md).
Отчёт @DevOps — строго без секретов (R17): только «ключ установлен / пароль
отозван / доступ подтверждён».

## 6. Инварианты

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты вне репо/логов/коммитов) | ✅ | скан §1–§3; новых логов нет |
| R16 | ✅ | не применимо (кода нет) |
| Каталог-Δ=0 | ✅ | прод-код не менялся; pytest зелёный |
| Порядок роутеров `bot.py` | ✅ | не тронут |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| SQL/DDL | ✅ | не требуется; SQLite v9 |

## 7. Валидатор

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5910 passed**, 1 warning (StarletteDeprecationWarning — не наш код) | 0 |
| `node --check web/app.js` | (см. `round10.16_audit.md`; F5 JS не трогает) | — |
| `git diff --check` | чисто (LF→CRLF-предупреждения штатные) | 0 |

*Round 10.16 F5 security scan generated by @Builder on 2026-09-14.*
