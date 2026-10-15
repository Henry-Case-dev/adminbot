# W4 live-пробы V01–V07 — asap8-v6-3-live-correction

Дата: 2026-10-16. Прод: 2.58.79 @ `c2775a54` (server-verified, см. live-canary.md).
Все факты сняты С СЕРВЕРА (локальный DNS хоста admin-bot.duckdns.org не резолвится —
внешняя проверка домена остаётся за владельцем).

## 1. Живые факты (agent-side, mechanical)

| Проверка | Факт |
|---|---|
| `/healthz` (127.0.0.1:8000) | `{"status":"ok","version":"2.58.79"}` |
| `/web/` | 200, 727 145 байт |
| `/web/static/fullscreen-policy.js`, `glass-probe.js`, `polygon-background.js` | 200/200/200 (фон отдаётся без изменений — CORR-1) |
| CSP (через caddy) | `img-src 'self' data: blob:` → **data:-URI линзы разрешён**; внешних CDN нет (`script-src 'self' 'unsafe-eval'`) — CSP-пин жив |
| journal (2 ч) | 97 строк с `initiative`, 0 ERROR/Traceback |
| Инициатива (B01) живая | тик каждые 5 мин; `initiative_observer_scan` success; job `initiative.observe` **completed 25×/24h**; вход 3516 сообщений свежих; последний тик `observed=0 opportunities=0` |
| B11 на проде с PG DSN | RC=0, 8 ok / 2 never_run (`graph_memory`, `embeddings` — векторный контур, см. backlog), gate-слой теперь покрывает и PG-каталог |

## 2. Статусы V-сценариев

| V | Сценарий | Статус | Обоснование |
|---|---|---|---|
| V01 | Инициатива: живой SEND при opportunity | **BLOCKED_REAL_HUMAN_GATE** | Механизм жив (25 успешных job/24h, вход есть), но `opportunities=0` — нужен естественный повод + окно canary 24–48 ч (владелец) |
| V02 | Опыт: семантическое извлечение в бою | **BLOCKED_REAL_HUMAN_GATE** | B11: experience ok, но последняя попытка `failure` 2026-10-10; честная загрузка/измерение cursor lag — только на естественном потоке |
| V03 | Память: исторический поиск по expired-фактам | **READY_FOR_LIVE** | Прод-данные есть, эндпоинты живые; проверка требует админ-сессии (owner). Векторный контур деградирован (квота эмбеддингов parked) → семантика не проверяется, только FTS |
| V04 | Доставка styled-обложки в чат | **BLOCKED_REAL_HUMAN_GATE** | B04.5 зависит от `InputRichMessageMedia` в прод-aiogram (2 предсуществующих фейла) — нужен реальный чат |
| V05 | UI на 320/360/390/430/768/1440 + landscape | **READY_FOR_LIVE** | Скриншоты всего viewport есть в evidence волн 2–3; прод-визуал — owner |
| V06 | Fullscreen на реальных клиентах (Windows/Android/tdesktop) | **BLOCKED_REAL_HUMAN_GATE** | 8 пунктов карты (U07.*) требуют реальных клиентов; mock-матрица и Playwright не заменяют |
| V07 | Оптическое стекло + CSP на проде | **READY_FOR_LIVE** | CSP live-проверен (data: разрешён), Tier-сканлайн-корреляция в evidence; физический FPS/визуал — owner |

## 3. Векторный контур (связано с V03) — не регрессия v6.3

Прод-факты: `embedding_quota_state` = `primary/fallback_1/fallback_2 → exhausted`,
`next_allowed_at=1792109100` (2026-10-16 00:05 UTC), note `parked kind=spend est=utc_day_end`;
журнал `embed rate limit | parked=1 | cooldown_s≈86391`; `EMBEDDING_GENERATION_PAUSED |
index=graph_facts_vec | reason=paused_rate_limit | checkpoint preserved`.
Код v6.3 не трогал этот контур (`embedding_control_plane.py`/`graphrag_rebuild.py` — 0 diff).
Поправка: «no such module: vec0» из первого B11-прогона — артефакт скрипта (не грузит
расширение sqlite-vec), на проде `sqlite-vec available`, таблицы vec существуют.

## 4. Ключи эмбеддингов — проверка по запросу владельца

* Код: каждый alias (`primary`/`fallback_1`/`fallback_2`/`extra_N`) = **своя** quota-группа
  (auto-group = alias либо `EMBEDDING_QUOTA_GROUP_LABELS` вида `alias:group`);
  `_pick_credential` пропускает cooling-группы и берёт следующий ключ → ротация есть.
* Прод-журнал подтверждает работу ротации: 00:05:08 `primary` 429 → 00:05:19 `fallback_1`
  429 → 00:05:28 `fallback_2` 429 — три независимых ответа провайдера, ключи разные,
  группы разные (слипания в нашем слое нет).
* Все три ключа идут на **один** provider-host `apinet.cloud` (model `gemini-embedding-001`).
  Одновременное исчерпание при разных аккаунтах ⇒ лимит/кап на стороне прокси
  (общий на IP/апстрим), а не в нашей ротации.
* Находка конфигурации: `EMBEDDING_API_KEY` в `.env` **отсутствует**; primary-ключ приходит
  из hot-конфига (`keys.embedding_api_key`). `pool_rotation_diagnosis` при пустом primary-слоте
  молчит (`degenerate: False` при 2 ключах) → потеря primary не диагностируется (backlog).