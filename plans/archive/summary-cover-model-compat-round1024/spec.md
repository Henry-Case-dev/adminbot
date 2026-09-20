# spec.md — F12 `summary-cover-model-compat-round1024` (универсальный payload + тест-подключение)

> Раунд 10.24, Часть 1 (backend-core) · Приоритет **P1** · ADR: **ADR-1024-4** (AMEND ADR-1023-5/6)
> ТЗ: `plans/current_task.md` UPD2 п.10 (стр. 222–226) + п.10.1 (стр. 228–229), UPD3 п.8 (стр. 263–267). Секреты не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; pytest 7424/0.

## 1. Цель

Сделать генерацию обложки независимой от модели: `payload` — строго по OpenAI-стандарту, без hardcode-карты и без полей, ломающих совместимость (`size`, `response_format`). Гарантировать подмешивание `prompts.summary_cover_style` в финальный промпт. Добавить кнопку **«Проверить подключение»** (тестовый промпт → тост с успехом или сырым безопасным текстом ошибки). Ошибки провайдера — видны в логах (F2).

## 2. Что уже есть (координаты)

- Запрос к провайдеру: `services/image_generation.py` — документация `:8-9`; жёсткие `_IMAGE_SIZE="1024x1024"` `:62`, `_IMAGE_WIDTH/_HEIGHT` `:63-64`; POST-тело `:258-264` (`size`/`response_format:"url"`); `_generate_post` `:246-288`; `_generate_get` `:306-331`; `download` `:291-303`; `generate` `:357-398`; `generate_image` `:401-418`.
- Скрытие причины: `_reason_from_status` `:176-186`; `generate` WARNING без тела `:379-390`.
- Обложка: `services/summary_generator.py:653-688` (`_deliver_rich`: `style = hot.get("prompts.summary_cover_style", SUMMARY_COVER_STYLE_DEFAULT)` `:664`, `compose_cover_image_prompt` `:666`); `:101-105` (`compose_cover_image_prompt`, кап `COVER_IMAGE_PROMPT_MAX=300` `:85`); `SUMMARY_COVER_STYLE_DEFAULT` — `services/summary_prompts.py:153`; каталог `services/param_catalog.py:403`.
- Лог-хуки: F2 `services/external_log.py` (ADR-1024-1).
- Флаг 10.23: `SUMMARY_COVER_ARTICLE_ENABLED` (ON); тул `generate_image` и пре-гейт работают.

## 3. Требуемое поведение

1. POST-тело = `{prompt, model, n:1}`; `size`, `quality`, `response_format` **не отправляются**.
2. Ответ принимается как `data[0].url` (скачивание) или `data[0].b64_json` (декод) — обе формы.
3. `compose_cover_image_prompt`: стиль сохраняется (до своего капа 500), visual усекается до общего капа `SUMMARY_COVER_PROMPT_MAX_CHARS` (1000); при нехватке — режется visual.
4. Финал промпта логируется: `style_present`/`style_len`/`visual_len`/`final_len` (без полного текста).
5. `POST /api/images/test` (глобальный админ) → probe-результат; фронт показывает тост успех/сырой безопасный текст ошибки.
6. При «тихом откате» саммари в логе — реальная причина (статус/тело/модель), не только «unavailable».
7. `IMAGE_MODEL_COMPAT_ENABLED=False` → прежнее тело/поведение (kill-switch).

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/image_generation.py` | Тело POST `{prompt, model, n:1}`; `probe()` + `ProbeResult`; логирование статуса/тела через F2; сохранение обеих форм ответа |
| `services/summary_generator.py` | `compose_cover_image_prompt` — стиль-приоритет + новый кап; лог `style_present`/длин; причина отката |
| `config/settings.py` | env-only `ClassVar`: `IMAGE_MODEL_COMPAT_ENABLED` (ON), `SUMMARY_COVER_PROMPT_MAX_CHARS` (1000), `SUMMARY_COVER_STYLE_MAX_CHARS` (500) |
| `web/api/routes.py` (или `web/api/images.py`) | `POST /api/images/test` (RBAC global admin, rate-limit) |
| `web/index.html` / `web/app.js` | (Часть 2) кнопка «Проверить подключение» + тост |

## 5. Контракты

### 5.1. Универсальное POST-тело

```python
body = {"prompt": prompt, "model": model, "n": 1}
# НЕ отправлять: size, quality, response_format
# Ответ: item.get("url") → download | item.get("b64_json") → b64decode
```

### 5.2. Probe

```python
@dataclass
class ProbeResult:
    ok: bool
    status_code: int | None
    reason: str          # R17-safe код
    body_excerpt: str    # safe_text(resp.text), усечён, без ключей
    latency_ms: int
    model: str
    mode: str            # "post" | "get"

async def probe(*, chat_id: int | None = None) -> ProbeResult
```

`POST /api/images/test` → JSON `ProbeResult`; 200 даже при неуспехе провайдера (`ok=false`, `body_excerpt`); 5xx только при внутренней ошибке.

### 5.3. Композиция промпта

```python
def compose_cover_image_prompt(style, cover_prompt) -> str:
    s = (style or "").strip()[:SUMMARY_COVER_STYLE_MAX_CHARS]
    remaining = SUMMARY_COVER_PROMPT_MAX_CHARS - len(s) - 1
    v = (cover_prompt or "").strip()[:max(0, remaining)]
    return " ".join(p for p in (s, v) if p)
```

## 6. Тесты

- (a) при `gptimage` тело запроса не содержит `size`/`quality`/`response_format`.
- (b) при `flux` поведение сохранено (генерация/скачивание).
- (c) ответ `b64_json` корректно декодируется; ответ `url` корректно скачивается.
- (d) стиль присутствует в финальном промпте; при переполнении режется visual, а не стиль; лог `style_present=True`.
- (e) `probe()` возвращает `ok=false` + безопасный `body_excerpt` при 400; без ключей (R17).
- (f) при отказе провайдера причина логируется (F2), а не только «image unavailable».
- (g) `IMAGE_MODEL_COMPAT_ENABLED=False` → прежнее тело.

## 7. Флаги / Δ

- `IMAGE_MODEL_COMPAT_ENABLED` (env-only `ClassVar`, default **ON**).
- `SUMMARY_COVER_PROMPT_MAX_CHARS` (1000), `SUMMARY_COVER_STYLE_MAX_CHARS` (500).
- Δ каталога = 0; Δ DDL = 0.

## 8. Риски

- **R1 (High):** отсутствие `size` меняет дефолтный размер → для обложки приемлемо; тесты на обе модели.
- **R2 (High):** probe/лог промпта может раскрыть пользовательские данные → только обезличенно/усечённо (R17).
- **R3 (Medium):** усечение visual уберёт смысл → стиль приоритетнее, visual — до капа.
- **R4 (Medium):** «тихий откат» для юзера остаётся → логи полные (принцип п.11).

## 9. Критерии приёмки

- Обложка саммари генерируется с `gptimage` и с `flux`; откат на текст — только при реальной невозможности, с причиной в логах.
- Параметры запроса универсальны (нет жёстко зашитых неподдерживаемых полей).
- Подтверждено, доходит ли `prompts.summary_cover_style` до модели (лог + probe), вывод зафиксирован.
- Кнопка «Проверить подключение» отдаёт успех/сырой безопасный текст ошибки.
- pytest зелёный; прямой чат не сломан.

## 10. Откат

- `IMAGE_MODEL_COMPAT_ENABLED=False` / `git revert`. Δ DDL = 0, Δ каталога = 0.

## 11. Артефакты-ссылки

- ADR: `ADR-1024-4.md`; AMEND `plans/archive/image-generation-tool-round1023/ADR-1023-5.md`, `plans/archive/summary-cover-rich-article-round1023/ADR-1023-6.md`;
- карта/ресёрч: `round1024-architecture.md` §3.3, §9.
