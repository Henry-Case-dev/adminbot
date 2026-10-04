# ASAP 4.3 — canary-evidence (T-4859 Canary A, T-4860 Canary B)

Дата: 04.10.2026 (UTC). Статус: **Canary A — FAIL** (найдена конкретная причина,
фикс — кандидат, ждёт focused re-review; прод остаётся 2.58.50). **Canary B — не
выполнялся** (гейт «A зелёный» не пройден); внешний реальный prod-прогон
владельца опубликовал **base fallback**, не styled (детали ниже). Коммитов нет.

## Окружение и биндинг

- Прод: `https://admin-bot.duckdns.org` / 198.46.175.136, **APP_VERSION 2.58.50**
  (feat `1c47b5e`), PID 3594974, health 200. Рестартов/деплоя/DDL в ходе canary нет.
- Локально: HEAD `2329a9d` + 2 незакоммиченных файла (кандидат-фикс + регресс-тест).
- Auth: TMA initData для admin `5885953495` сгенерирован **на прод-хосте**
  (`/tmp/asap43_canary_recon.py`, HMAC «WebAppData» от `settings.API_TOKEN`;
  токен не печатался и хост не покидал), инжект `sessionStorage['adminbot.initData']`.
- Драйвер Canary A: локальный Playwright/Chromium (390×844, mobile), реальный
  prod UI/API. R17: секреты/initData/промпты не логировались, байты не сохранялись.

## Canary A (T-4859) — один реальный прогон: FAIL

Шаги: prod MiniApp → «Стили обложки» → редактор Medved Press → **один** клик
«Проверить стиль» (double-tap не делался) → poll `GET /api/cover/test-style/{job_id}`.

| Параметр | Факт |
|---|---|
| POST `/api/cover/test-style` | **200**, `{job_id: cov_77f2347eec7d85e6b3a15f93, status: queued, reused: false, preview_issue: "ВЫПУСК 00"}`, 0.3 с |
| Correlation (лог) | `cover_test_65e643fd17db` |
| Stage timeline (poll+лог) | queued → base_generating (0.6 с) → style_editing (55.8 с) → completed (124.3 с); heartbeats 30/60 с |
| Base | реально сгенерирована: 682 153 B, 54.2 с (`[image] generated`, mode=post) |
| Style edit | реально выполнен: 68.9 с, `COVER_STYLE_SUCCEEDED` |
| Provider/model | `nano-gpt.com` / `qwen-image-3-pro` (configured production image slot; style-slot пуст → inherit) |
| Reference | `reference_count=1`, `reference_bytes_total=475189` = medved_press.png; UI скачал reference asset 475 189 B, sha256[:16] `be0a700ba8d3af64` |
| Status итог | completed; `preview_revision=5 == revision`, `preview_job_id=cov_77f2…`, `preview_status=success`; prompt 392/0/105/98=597, limit unknown |
| UI | stage-тексты «Генерируем базовую обложку…» / «Применяем стиль…», «Стиль применён»; **after** — blob 1024×1024, загружен; **before — отсутствует**: `GET /api/cover/assets/cas_4f23007c…` → **404** (console error 404); сырого `Failed to fetch` нет |
| Пара атомарна | один UPDATE before+after+revision+job_id; id/revision/job согласованы (PG) |
| Issue counter | **не изменён** превью: assignments 11 (07:13) → мой preview ничего не создал; строка 12 появилась только от production-прогона владельца (12:02:34) |
| Публикация | **0**: для `cover_test_65e643fd17db` только `COVER_STYLE_*`, ни одного `PUBLISH_*`/`SUMMARY_*` |

**Итог: FAIL по критерию «UI получил обе картинки»** (before 404); остальные
критерии Canary A — green.

### Root cause (подтверждён кодом, БД и прод-историей)

`services/cover_style_preview.py::_store_base` писал base-байты в CAS, но **не
регистрировал asset в PG** (`registry.upsert_asset` вызывался только для after,
`:411`). Строки `cover_style_assets` для base нет → `GET /cover/assets/{before_id}`
→ 404 → UI не рендерит «До» (after отдаётся нормально).

Прод-подтверждение: `cas_4f23007c…` (мой прогон, 11:57) и `cas_59b765d4…`
(прогон владельца, 11:45) — **строк нет**; after `cas_2722410d…` — строка есть,
GET 200 (1 530 449 B). Регресс от `1c47b5e`: до деплоя (03:20, 04:21) base-строки
создавались, после деплоя (11:38/11:45/11:57 — владелец+canary) — нет.
`preview_pair_current` проверяет только непустые id/revision, поэтому пара
«формально валидна» при битом before. Затронуты и прогоны владельца.

### Кандидат-фикс (в рабочем дереве, НЕ задеплоен; ждёт focused re-review)

- `services/cover_style_preview.py` (+13/−3, sha256 `271DE93BC275…`):
  `_store_base(pg, path)` → `await registry.upsert_asset(pg, meta)`; ошибка
  регистрации = `_fail_job(base_generation_failed)` до записи пары (атомарный
  контракт §4, before без строки не попадает в пару). Оба call-site
  (fresh + resume) прокидывают `pg`.
- `tests/test_asap43_cover_style_surgical.py` (+57, sha256 `31632A31EF85…`):
  `test_preview_base_asset_registered_and_fetchable` — реальный registry
  (temp-SQLite shim, без моков upsert/set_preview): base в PG, оба asset
  GET = 200. **Негативный контроль: на pre-fix коде тест FAILED.**
- Focused reruns (изменённое окружение): asap43 **10 passed**;
  step3+jobs **52 passed**; step2c2+api **43 passed**. Полный suite не гонялся.

**Canary A repeat возможен только после re-review + deploy фикса** (прод —
2.58.50; молчаливый редеплой запрещён).

## Canary B (T-4860) — не выполнялся

- Гейт: Canary A не зелёный → второй paid production-прогон не запускался.
- Внешний реальный prod-прогон (**владелец**, `[/summary] manual=True`, 11:48:14,
  user 5885953495): run_id `64b40daad73043bebcd9b90673f31788`, выбран Medved
  (`COVER_STYLE_SELECTION selection_source=chat style_revision=5`):
  - text: L2 review rejected → legacy fallback (вне ASAP 4.3);
  - cover base: ok 73.4 с; **style-стадия**: prompt 915 chars → provider **400**
    «Your prompt is too long for Qwen Image 3 Pro. Please shorten» →
    `COVER_STYLE_FAILED reason=bad_request`; второй paid-вызов **не** отправлен
    (bounded retry сработал);
  - публикация: `PUBLISH_RICH_COMPLETE message_id=1132500`,
    `COVER_PIPELINE_DONE status=base fallback=style_failed` → **опубликован base
    fallback, не styled**; ladder `styled→base→Rich→plain` не сломан.
- Вывод: styled-публикация на проде **не подтверждена** (сейчас — base fallback).
  Причина в скоупе §7–§8, но не баг-регресс: лимит Qwen не сообщён числом (N нет →
  UNKNOWN, поведение по §7.1 «unknown не блокирует»); production-промпт Medved
  (brief 206 + instruction 392 + refs) превышает реальный лимит. Решение —
  за Orchestrator/владельцем (manual prompt-limit override / компактнее brief /
  отдельный bounded-фикс), не молчаливая правка в canary.

## Incidental

- Owner параллельно вёл live acceptance в MiniApp (auth-трейс 11:35–11:50) и
  триггерил `/summary`; его Test Style-прогоны затронуты тем же before-404.
- Console 404 у before — не отдельный дефект, тот же root cause.

## Остаточный риск

- Прод не изменён; фикс не подтверждён live-прогоном (нужен re-review → deploy →
  повтор только Canary A). Canary B и live acceptance — отдельным циклом.

## Prompt-limit resolution (05.10.2026, Orchestrator)

- Внешне подтверждённый route-cap: nanoodle-js live-probe `prompt-caps.mjs`
  (2026-07-26) — `qwen-image-3` = **800 chars**; NanoGPT отклоняет over-cap
  промпты ДО вызова провайдера (400 `prompt_too_long`, «shorten … to 800
  characters or less»); фронтенд NanoGPT (nanoaimaker, Qwen Image 3.0 Pro)
  показывает `0 / 800`. Наш вариант сообщения пришёл без числа → observed
  capability не пишется, лимит остаётся UNKNOWN по §7.1.
- Штатный рычаг по §7.2 — **manual prompt-limit override** (не код-константа):
  перед повтором Canary B выставить `800` (единица: символы) для маршрута
  Medved (provider `nano-gpt.com`, model `qwen-image-3-pro`, operation
  image_edit) через MiniApp; override виден как manual и меняется владельцем.
- Источники: github.com/nanoodlecom/nanoodle-js/blob/main/src/prompt-caps.mjs;
  nano-gpt.com/models/image/qwen-image-3-pro; nanoaimaker.com/image/qwen-3-pro.

---

# Canary A repeat (05.10.2026) — PASS

Прод **2.58.51** (feat `acbbe1f`), PID 3610541, NRestarts=0, health 200; локальный
Playwright 390×844, тот же server-generated initData. Один реальный прогон:
prod MiniApp → редактор Medved Press → один клик «Проверить стиль».

| Параметр | Факт (UTC прод-хоста) |
|---|---|
| POST `/api/cover/test-style` | **200**, `{job_id: cov_77f2347eec7d85e6b3a15f93, status: queued, reused: false}`, 12:26:51 |
| Correlation (лог) | `cover_test_efdc0925de59` |
| Stage timeline | base_generating +0.7 с → base_ready +54.7 с → style_editing +56.5 с → completed +130.4 с (12:29:01); heartbeats 30/60 с |
| Base | 887 912 B, 54.0 с (`[image] generated` 12:27:44) |
| Style edit | `COVER_STYLE_SUCCEEDED` 12:28:59, 74.5 с |
| Provider/model | `nano-gpt.com` / `qwen-image-3-pro` (`resolve_source=global_image_slot`) |
| Reference | `reference_count=1`, `reference_bytes_total=475189` (medved_press.png) |
| Pair (revision 5, atomic) | before `cas_d2ae85e74f5fa44ff9a06d79a111274b`, after `cas_272acc62b86cd9d166ff6c82ad7da1ba`; `preview_revision=5`, `preview_job_id=cov_77f2…`, `preview_status=success` |
| **UI: before GET** | **200**, 887 912 B, sha256[:16] `d2ae85e74f5fa44f`; blob 1024×1024, complete |
| **UI: after GET** | **200**, 1 706 155 B, sha256[:16] `272acc62b86cd9d1`; blob 1024×1024, complete |
| Fix proof (PG) | строка `cover_style_assets` для base **есть** (created 12:27:44.767) — до фикса отсутствовала |
| UI-тексты | «Генерируем базовую обложку…» / «Применяем стиль…», «Стиль применён»; `Failed to fetch` нет |
| Console | 2×404 — только старые pre-fix ассеты (12:26:49, `cas_4f23007c…`) при открытии редактора; новых ошибок нет |
| Issue counter | **не изменён**: assignments 12 (последняя — production-прогон владельца), preview-строка не создавалась |
| Публикация | **0**: для `cover_test_efdc0925de59` только `COVER_STYLE_*` |

**Вердикт: PASS** — все критерии Canary A выполнены, включая прежнюю точку
падения (before `GET` = 200, обе картинки в UI).

# Manual override 800 (§7.2) — BLOCKED, реальный UI-флоу падает на проде

Шаги (реальный MiniApp, 2.58.51): редактор Medved → `[data-cover-limit-mode]` =
«Задать вручную» → unit «символы» → значение `800` → «Сохранить лимит».
- `POST /api/cover/prompt-limit` (12:32:58, body `{profile_id: medved_press,
  operation: image_edit, mode: manual, unit: chars, value: 800}`) → **HTTP 422**
  `{"detail": "Не удалось определить модель/подключение."}` — override **не
  сохранён** (`manual_limit_map` пуст).
- До/после (UI): «Лимит текущей модели: **неизвестно**» → после клика UI
  **оптимистично** показывает «800 символов (задано вручную)», но breakdown
  остался `Последняя сборка: Style 392 · Context 0 · Refs/meta 105 · System 98 ·
  Итого 595 / неизвестно` — т.е. серверного состояния manual/800 нет, экран
  противоречив (отдельная UX-находка).
- `GET /api/cover/prompt-limit` / detail: `mode=auto, value=null, source=unknown`;
  средство §7.2 на проде для этого профиля **недоступно**.

## Root cause (read-only прод-проба)

§7.2-пути management-plane резолвят слот **без** лестницы наследования §35:
- `web/api/cover_styles.py:842` (`_resolve_limit_slot`), `:353`
  (`_prompt_limit_state`), `:311` (`_budget` → `pipeline.slot_capabilities`
  `cover_style_pipeline.py:281`) → `resolve_style_slot` (только
  `models.image_style_*`).
- Runtime-путь job'а: `services/cover_style_jobs.py:1224` →
  `resolve_style_slot_inherited` (leg 3c → `models.image_*`).

Прод-факт (тот же процесс/конфиг): `resolve_style_slot(medved)` →
`provider="", model="", configured=false`; `resolve_style_slot_inherited(medved,
pg)` → `nano-gpt.com` / `https://nano-gpt.com/api/v1` / `qwen-image-3-pro`
(`resolve_source=global_image_slot`) — ровно маршрут, который упражняет Canary A.
Итог: UI/API лимита не могут адресовать реальный edit-маршрут для seeded-профиля
в режиме «По умолчанию» при пустом глобальном style-слоте → 422.

Тест-щель: `tests/test_extra_cover_styles_api.py::TestPromptLimitOverride` всегда
передаёт `provider/base_url/model` явно (стр. 485–487) и не покрывает
profile-only резолв через наследование.

## Кандидат-фикс (НЕ применён; ждёт focused re-review)

- В §7.2 management-plane использовать `resolve_style_slot_inherited(profile=…,
  pg=…)` (async) вместо `resolve_style_slot`: `_resolve_limit_slot`,
  `_prompt_limit_state`, `_budget` (возможно `connection_status`) — чтобы лимит
  адресовался тому же маршруту, что и runtime.
- Регресс-тест: `POST /cover/prompt-limit` БЕЗ явных provider/model для
  default-mode профиля с пустым style-слотом → 200, persist, `GET` → manual/800;
  плюс UI-проверка, что «задано вручную» не показывается до серверного успеха.
- Альтернатива (если Orchestrator/владелец санкционирует, не выполнялась): тот же
  override через `POST /api/cover/prompt-limit` с явными
  provider/base_url/model реального маршрута (та же §7.2-persistence), но это не
  UI-флоу и маскирует дефект — по умолчанию не предлагается.

# Canary B (T-4860, 05.10.2026) — не выполнялся

- Гейт не пройден: шаг 2 (manual override через MiniApp) заблокирован 422, лимит
  800 не персистится; без него production-style-промпт (~915 chars с брифом)
  снова упрётся в route-cap 800 (как в прогоне владельца `64b40daa…`).
- Второй paid production-прогон не запускался; styled-публикация не проверялась.
- Невыполненные критерии шага: `GET /api/cover/prompt-limit` = manual/800;
  breakdown «Итого ≤ 800, source=manual».

# Логи (R17-safe, только вокруг job id)

```
12:27:44,720 image_generation: [image] generated | mode=post | model=qwen-image-3-pro | bytes=887912 | latency_ms=54020
12:27:45,467 cover_style_jobs: COVER_STYLE_RESOLVE | style_id=medved_press | connection_id=default | resolve_source=global_image_slot | status=start | chat_id=0
12:27:45,483 cover_style_jobs: COVER_STYLE_SUBMITTED | prompt_len=597 | reference_count=1 | reference_bytes_total=475189 | compiled_chars=597 | limit_unit=unknown:unknown | issue_present=True
12:28:15/45 cover_style_jobs: COVER_STYLE_RUNNING | duration_ms=30000|60007
12:28:59,296 cover_style_jobs: COVER_STYLE_SUCCEEDED | async_used=False | style_revision=5 | status=success | duration_ms=74511
12:32:58 web/api cover_styles: POST /api/cover/prompt-limit -> 422 (slot resolved empty; см. выше)
```

Гигиена: initData-файлы (prod `/tmp`, локальный temp) удалены; секреты/промпты
не печатались; байты изображений не сохранялись (только len+sha-префиксы).
