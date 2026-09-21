# F2 `design-tokens-liquidglass-v2-round1025` — отчёт @Builder (итерация 1)

- **Фича:** F2 (Эпик 1, Волна 1). **База:** `f2328fb`. **Коммит F2:** `e895726`.
- **ADR:** `adr-1025-9-design-tokens-liquidglass-v2.md` (D1–D6; AMEND итерации @Reviewer).
- **Точка отката:** тег `pre-round1025-f2`, бэкап `var/backups/f2-round1025-20260921-185357/`, `.env.bak.round1025-f2`.
- **Инварианты:** Δ DDL = 0, Δ каталога = 0; CSP/zero-build (только inline SVG, без библиотек/WebGL).

---

## 1. Контраст (D4, WCAG AA 4.5:1 для `.75rem` = 12 px — нормальный текст)

### 1.1 Текст/статусы на плотных поверхностях §8

| fg \ bg | surface-0 `#090D17` | surface-1 `#151B2A` | surface-2 `#1C2537` | surface-3 `#232E45` | Итог |
|---|---|---|---|---|---|
| text-1 `#F4F7FB` | 18.07 | 15.99 | 14.27 | 12.62 | PASS |
| text-2 `#AAB6C8` | 9.46 | 8.37 | 7.47 | 6.61 | PASS |
| text-3 `#A2B0C6` | 8.84 | 7.82 | 6.98 | 6.18 | PASS |
| ok `#3DD68C` | 10.35 | 9.16 | 8.18 | 7.23 | PASS |
| warn `#F6C56F` | 12.14 | 10.75 | 9.59 | 8.48 | PASS |
| err `#F07178` | 6.78 | 6.00 | 5.36 | 4.74 | PASS |

### 1.2 Эффективный фон стекла (AMEND @Reviewer)

Текст в стеклянной карточке читается на композите:
`wash §10 (alpha .42) → surface-0` затем `--glass-bg (alpha .5)`. Худший случай —
**самая светлая фаза** wash (teal `#42D6C4`): эффективный фон `rgb(27,62,69)`.

| fg | на `--glass-bg` (B, худшая фаза) | Итог | на `--glass-bg-strong` (C) | Итог |
|---|---|---|---|---|
| text-1 `#F4F7FB` | 10.73 | PASS | — | PASS |
| text-2 `#AAB6C8` | 5.62 | PASS | — | PASS |
| text-3 `#A2B0C6` | 5.25 | PASS | 6.02 | PASS |
| warn `#F6C56F` | 7.21 | PASS | 9.66 | PASS |
| ok `#3DD68C` | 6.15 | PASS | 8.23 | PASS |
| err `#F07178` | 4.03 | **FAIL (не применяется на B)** | 5.40 | PASS |

**Обоснование коррекции `--text-3`:** на худшем стеклянном фоне `#94A3B8` давал ровно
**4.50** (на грани, провал при любом сдвиге) → скорректирован на **`#A2B0C6`**: 5.25 на
стекле-B, 8.84 на surface-0, по-прежнему приглушённее `--text-2` (`#AAB6C8`) — «характер»
палитры сохранён (ТЗ §8 разрешает уточнять «ради контраста»).

**Статус-цвета не менялись** (ТЗ §8 пинит `#F6C56F`/`#F07178`): `err` на голом стекле-B = 4.03,
но статусный текст фактически лежит на `*-bg`-тинтах (err на `--err-bg` = **4.93**) или на
уровне C `.keys-avail`/`.sticky-save` (`--glass-bg-strong`, err = **5.40**) — оба PASS.

---

## 2. Liquid Glass A/B/C (§9) — итерация @Reviewer

### 2.1 min-сторона ≥240 — обратимо и транзитивно
- `web/app.js::reconcileLiquidGlass` **не переписывает** opt-in `data-glass`; ставит/снимает
  `data-glass-downgraded` (A↔B обратимо). CSS: `[data-glass="a"][data-glass-downgraded="1"]` → B.
- Пересчёт: `mounted` + `resize` + `$nextTick` после смены `activeTab` (watch) +
  `MutationObserver` на `document.body` (`childList/subtree/attributeFilter:['data-glass']`,
  debounce rAF) — узлы, достроенные позже (v-if/маршруты/данные), ловятся автоматически.
- Второй `visibilitychange`-обработчик **не введён** (пауза фона — внутри `onVisibilityChange`).

### 2.2 Приближение карты преломления (edge-weighted)
- Карта уровня A — **сглаженный низкочастотный `feTurbulence`** (`baseFrequency 0.009/0.013`,
  `feGaussianBlur 3.2`, `scale 14`). Это **документированное приближение** «оптического»
  преломления, **не** радиально-взвешенная edge-map (карта пространственно однородна).
- «Усиление у краёв» даёт **CSS-кромка** (`inset box-shadow --glass-highlight[-soft]`), а не
  смещение. Истинное радиальное маскирование (`feImage`/`mask`-градиент) **отложено** —
  CSP/zero-build + нестабильная поддержка `feImage`-ссылок в движках (ADR-1025-9 D2).
- Комментарии в `web/index.html` и `web/static/app.css` приведены в соответствие (uniform-шум
  больше не выдаётся за оптику).

### 2.3 WebKit / UA-gate
- `CSS.supports('backdrop-filter','url(#…)')` в WKWebView **недостоверен** → уровень A
  гейтится **UA-gate**: отвергаем `AppleWebKit` без `Chrome|Chromium|Edg|OPR`, плюс feature-check.
- WebKit/иные движки получают уровень **B**. Движок WebKit в среде **недоступен**
  (`webkit-2336` не установлен) → ограничение пробы зафиксировано (прецедент ADR-1021-6).

---

## 3. Inventory-тест (D5) — симметричный
- **Presence + симметрия:** `tests/test_webapp_design_tokens_round1025.py`
  (`test_inventory_symmetric_difference`) и `tests/js/round1025_design_tokens_test.js` (блок 1b)
  сравнивают множество токенов семейств `--surface-/--text-/--grad-/--glass-/--teal-/--purple-/
  --indigo-/--magenta-/--lilac-` и `--ok/--warn/--err[-bg]` с эталоном → ловят **и пропажи,
  и ЛИШНИЕ** маркеры.
- **Absence:** авто-скан first-party `web/**` (vendor исключён) на 25 OD4-литералов.
- **Пины:** `?v=`/`APP_VERSION == 2.58.5` входят в набор.

---

## 4. Метрики (итерация 1)
- `python -m pytest -q`: **8096 passed / 0** (база 8071).
- `node tests/js/*`: **24/24** (`node --check web/app.js` OK).
- `python tools/ui_round1025_matrix.py`: **0** нарушений (10 вьюпортов × 13 маршрутов;
  F2-пробы: палитра §8, диапазоны 60–90/90–120 c из computed `animationDuration`,
  glass allow `url(#lg-displace)` c **min-стороной ≥240**, deny `none`, hidden-пауза,
  reduced-motion `animation-name: none`).
- Red→green на старом `app.css`: matrix **130 failures**, новый pytest — 14 failed, JS — fail.
- `git diff --check` — exit 0.

---

## 5. Ограничения и остаток
- WebKit-проба уровня A — недоступна в среде (осознанное ограничение; A = progressive enhancement Blink).
- Истинное радиальное edge-маскирование преломления — отложено (см. §2.2).
- Далее: **@Reviewer итерация 2** → **@DevOps** T-2560 (деплой) / T-2561 (LIVE-гейт владельца).
