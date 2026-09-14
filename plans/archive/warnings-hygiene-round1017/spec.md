# Спека F5 — `warnings-hygiene-round1017` (WARNING в `avatars.py` + «brotli»/Caddy)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer **APPROVED**, итерация 2). brotli — WONTFIX; Caddy `zstd+gzip` — подтверждение @DevOps (Step 9).
> **Раунд:** 10.17. **Тип:** backend (гигиена логов) + docs/infra. **Приоритет:** P2/P3.
> **T-ID:** T-1696…T-1702. **ADR:** не требуется (решение по brotli — WONTFIX с обоснованием; фиксируется здесь и в docs).
> **Baseline:** HEAD `772f192`; pytest 5936/0; каталог 435/406/411/90/88/19 (Δ=0); SQLite v9.
> **ТЗ:** `plans/current_task.md` UPD3 (стр. 160): «3 перехваченных WARNING в аватарах (старый код); «brotli» требует плагина Caddy — обработать».

## 0. Цель

1. **WARNING в `web/api/avatars.py`:** генеральные `except Exception: logger.warning(..., exc_info=True)` шумят **ожидаемыми** сбоями Bot API (нет фото/нет прав/чат не найден) полным трейсом. Классифицировать: ожидаемое → `debug` без `exc_info`; неожидаемое → `warning` с `exc_info` (R17-safe). Негатив-кэш и транзиентные ветки сохранить.
2. **«brotli»:** в репо brotli — **только build-time** (субсет шрифта, `scripts/requirements-font.txt`); в runtime `requirements.txt` его нет. В Caddy brotli требует плагина (`xcaddy`/`http.encoders.brotli`), но `zstd+gzip` уже включены @DevOps (10.16). **Решение — WONTFIX (оставить zstd+gzip)**; зафиксировать в docs, снять неопределённость.

## 1. Scope

**In scope:**
- Политика уровня логов + правка `web/api/avatars.py` (все генеральные `except Exception`-сайты).
- Тесты `caplog` на 3 ключевых сайта (ожидаемый путь — не WARNING с трейсом; неожидаемый — WARNING без секретов).
- Docs: brotli build-time-only; Caddy сжатие `zstd+gzip` (zstd ~ brotli по эффективности, без сборки Caddy).
- Верификация @DevOps: `Content-Encoding` в проде.

**Out of scope:**
- Установка `xcaddy`/сборка Caddy (вне репо; WONTFIX).
- Изменение поведения аватаров (кэш/негатив/транзиент/same-origin прокси).
- CSP/self-host (10.16, ADR-1016-2) — не трогать.
- `services/media_send.py`, `tools/video_downloader.py`.

## 2. Точки изменения (`file:line` на `772f192`)

| Файл | Строки | Что |
|---|---|---|
| `web/api/avatars.py` | 146-148 | `fetch_avatar_bytes`: +`except TelegramBadRequest` (expected) → debug; generic → warning |
| `web/api/avatars.py` | 180-182 | `chat_display_info`: +expected-ветка |
| `web/api/avatars.py` | 208-211 | `user_display_info` (get_chat_member): +expected-ветка |
| `web/api/avatars.py` | 220-223 | `user_display_info` (profile photos): +expected-ветка |
| `web/api/avatars.py` | 267-269, 288-290 | `global_user_display_info`: +expected-ветка (транзиент уже есть) |
| `web/api/avatars.py` | 28, 154-157 | импорт `TelegramBadRequest`; `safe_exc_text` без изменений |
| `tests/test_webapp_avatars_ui.py` / `tests/test_avatars_round1017.py` | новый/расширение | caplog-тесты |
| `README.md` / `plans/ARCHITECTURE.md` | brotli-упоминания | зафиксировать build-time-only + `zstd+gzip` |
| `scripts/requirements-font.txt` | — | **не менять** (источник истины) |

**Текущая картина (6 генеральных сайтов, не 3):** UPD3 назвал 3 из прод-логов (`fetch_avatar_bytes`, `chat_display_info`, `user_display_info`); применяем единую политику ко **всем** 6 (иначе шум вернётся), тесты — минимум на 3 названных + 1 неожидаемый.

## 3. Политика исключений и логирования

| Класс ошибки | Пример | Уровень | `exc_info` | Кэш |
|---|---|---|---|---|
| `TelegramBadRequest` (**ожидаемо**) | «chat not found», «not enough rights», «user not found», «photo not found» | `debug` | Нет | Негатив кэшируется (как сейчас) |
| `TelegramRetryAfter` / `TelegramNetworkError` (**транзиент**) | rate-limit/сеть | `warning` | Нет (`safe_exc_text`) | **НЕ** кэшируется (BUG-4) — как сейчас |
| Прочее (**неожидаемо**) | баг/парсинг/неведомый класс | `warning` | Да | Негатив кэшируется |

Хелпер (модульный, без изменения каталога):
```python
def _log_bot_api_failure(site: str, *, kind: str, tid: int, exc: Exception,
                         expected: bool) -> None:
    if expected:
        logger.debug("[avatar] %s expected failure | kind=%s tid=%s err=%s",
                     site, kind, tid, safe_exc_text(exc))
    else:
        logger.warning("[avatar] %s failed | kind=%s tid=%s",
                       site, kind, tid, exc_info=True)
```
R17: в логи — только `site/kind/tid`/`safe_exc_text` (без токенов/URL/`initData`); `exc_info=True` для неожидаемых — стек без секретов (Bot API-исключения секретов не несут, `safe_exc_text` уже маскирует).

Псевдокод сайта:
```python
try:
    ...
except (TelegramRetryAfter, TelegramNetworkError) as exc:
    logger.warning("[avatar] transient Bot API error — NOT cached | ... err=%s",
                   safe_exc_text(exc))            # без изменений
    return None / not cached
except TelegramBadRequest as exc:                # NEW: ожидаемо
    _log_bot_api_failure("fetch", kind=kind, tid=tid, exc=exc, expected=True)
    data = None                                  # негатив кэшируется
except Exception:                                # неожидаемо
    _log_bot_api_failure("fetch", kind=kind, tid=tid, exc=None, expected=False)
    data = None
```
(Порядок `except` обязателен: `TelegramBadRequest` — до generic `Exception`.)

## 4. Решение по «brotli» — WONTFIX (обоснование)

| Вариант | Вердикт |
|---|---|
| Включить brotli через `xcaddy` + `http.encoders.brotli` | **Отклонён (WONTFIX):** требует сборки/замены Caddy на сервере (вне репо), риск регресса прод-веб-сервера; выигрыш против `zstd` минимален |
| Оставить `zstd+gzip` (уже включено @DevOps 10.16) | **Принят:** zstd даёт сжатие уровня brotli при широкой поддержке; gzip — фоллбэк для старых клиентов; zero-maintenance |
| Добавить brotli как runtime-зависимость Python | **Отклонён:** brotli в репо — **build-time** (шрифт), в runtime не нужен и не влияет на Caddy |
| Ничего не решать/молчать | **Отклонён:** UPD3 требует явного решения |

Действие @DevOps (T-1699): подтвердить в проде `Content-Encoding: zstd` (или `gzip` для старых UA) на `/web/`, `/static/*`; отчёт (без секретов). Сборка Caddy **не выполняется**.

## 5. Тест-план

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | `fetch_avatar_bytes`, `bot.get_chat` кидает `TelegramBadRequest` | запись уровня `DEBUG` без `exc_info`; результат `None`; негатив в кэше |
| 2 | `chat_display_info`, `TelegramBadRequest` | `DEBUG`, без трейса; поля `None`; негатив в кэше |
| 3 | `user_display_info`, `TelegramBadRequest` (member/photo) | `DEBUG`, без трейса; `None`-поля |
| 4 | `fetch_avatar_bytes`, неведомый `RuntimeError` | `WARNING` с `exc_info`; результат `None` |
| 5 | `TelegramRetryAfter`/`TelegramNetworkError` | `WARNING` без трейса, **не** кэшируется (регресс BUG-4) |
| 6 | caplog-скан | нет токенов/`initData`/URL/`bot`-секретов |
| 7 | brotli-док | `requirements.txt` не содержит brotli; `scripts/requirements-font.txt` содержит; docs говорят build-time-only |
| 8 | поведение API аватара | `GET /api/avatar/...` 200/404 без регресса; `Cache-Control` сохранён |

## 6. Риски

| Риск | Мера |
|---|---|
| Приглушили реальную ошибку под видом `TelegramBadRequest` | `TelegramBadRequest` — узкий Bot API-класс; прочее остаётся WARNING с трейсом (тест 4) |
| Потеря диагностики негативов | негатив-кэш сохранён; при необходимости — `debug` виден при `LOG_LEVEL=DEBUG` |
| WONTFIX brotli воспримут как недоделку | явное обоснование + verификация `zstd` @DevOps |
| Регресс BUG-4 (кэширование транзиента) | ветки `TelegramRetryAfter/NetworkError` не трогаются; тест 5 |

## 7. Критерии приёмки (DoD)

- [ ] Ожидаемые `TelegramBadRequest` не пишут WARNING с трейсом; неожидаемые — пишут WARNING без секретов.
- [ ] Негатив/транзиент/прокси-поведение аватаров не изменено (тесты 1-5, 8 зелёные).
- [ ] По brotli зафиксировано WONTFIX (zstd+gzip); docs согласованы; отчёт @DevOps о `Content-Encoding`.
- [ ] Полный pytest 0 failed; каталог Δ=0; R17-скан чист; `git diff --check`.

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (гигиена логов + инфра-решение). Rollback = `git revert` (код); Caddy не меняется.
- **Progressive delivery:** неприменим; проверка — `pytest` (caplog) + прод-логи `[avatar]` после деплоя.

## 9. Handoff

`@Orchestrator` — спецификация F5 готова. Реализация — T-1697/T-1698/T-1700/T-1701 (@Builder), T-1699 (@DevOps), гейт T-1702 (@Reviewer/@PM).
