# W4 (UI §8) — привязка карты к релизному коммиту 2.58.113

Дата: 23.10.2026. Лейн: `PM-BIND-258113` (writer: только карты/документы).
Кандидат: `e4ee54f3` (поезд 2.58.113, база `678c0616`).
Карта: `plans/features/asap-speech-arch/requirements-map.json` (`candidate_commit` = `e4ee54f3`).

Код W4: `5e7d986e` (UI §8) + `dd4e0522` (rework: U-02 detail под шапкой, U-07 один CTA
без retry в конфликте), в поезде — черри-пики `0358b593` / `141333ed`.

## 1. Строки W4

| Строка | Раздел ТЗ | Статус | Привязанное доказательство |
|---|---|---|---|
| `UI-U01` | U-01 Desktop: карта ИИ | **VERIFIED** | `ui-report.json`, `review-r2.md`, `report.md`, `shots/` |
| `UI-U02` | U-02 Desktop: «Речь и характер» | **VERIFIED** | то же (+ `ui-acceptance.md` §1) |
| `UI-U03` | U-03 Desktop: каталог/редактор промптов | **VERIFIED** | `ui-report.json`, `review-r2.md` |
| `UI-U04` | U-04 Mobile: кодовые поля и Inspector | **VERIFIED** (инженерная часть) | viewports 320/360/390/430 + landscape |
| `UI-U05` | U-05 Mobile: редактирование Core | **VERIFIED** (инженерная часть) | `core_expand_320/390/430/landscape.png` |
| `UI-U06` | U-06 Header / breadcrumb / scope | **VERIFIED** | `header_1024.png` и др. |
| `UI-U07` | U-07 Sticky Save (pristine/dirty/saving/saved/error/conflict) | **VERIFIED** | e2e 409-ветка в реальном Chrome, `review-r2.md` |
| `UI-P2` | U-08 Glass/material + доступность | **VERIFIED** | `ui-acceptance.md` §1–§5, `contrast_390.png`, `glass_*.png` |
| `UI-U09` | U-09 Смежные экраны и взаимодействия | **VERIFIED** | e2e маршрутов GLOBAL/CHAT, `review-r2.md` |

Итог по карте (required, 115 строк): VERIFIED — **80**, PENDING — **35**; из них
строки W4/§8 закрыты полностью (9/9).

## 2. Артефакты и SHA-256

| Артефакт | SHA-256 |
|---|---|
| `plans/features/asap-speech-arch/evidence/w4/ui-report.json` | `1e77955cf13ef451348d0a5f3c97a9d3916122d9aeba2b59d49ff26168480445` |
| `plans/features/asap-speech-arch/evidence/w4/report.md` | `9b071b3d799c1ef6ce015bc8083c702b4b36efffd5d9ea41fe9087aa85edfc89` |
| `plans/features/asap-speech-arch/evidence/w4/ui-acceptance.md` | `0134c139099ee6ca72001ab3b8316ebe7ae917cb19dde2af83001ef10fa1e552` |
| `plans/features/asap-speech-arch/evidence/w4/review-r2.md` | `5277478cb2dc9092…` (файл ещё не закоммичен лейном ревью) |

Прогон: 9 viewport (320/360/390/430/768/1024/1280/1440/landscape), **failures = 0**,
27 скриншотов в `evidence/w4/shots/` (before/after), 8 постов API.

## 3. Гейт

`requirements_gate.py check --map plans/features/asap-speech-arch/requirements-map.json
--stage review --slice <UI-…> --candidate e4ee54f3 --repo .`
(запуск в временном worktree на `e4ee54f3`).

| Слайс | Scope | Ошибки | EXIT |
|---|---|---|---|
| `UI-U01` | 1 | 0 | **0** |
| `UI-U02` | 1 | 0 | **0** |
| `UI-U03` | 1 | 0 | **0** |
| `UI-U04` | 1 | 0 | **0** |
| `UI-U05` | 1 | 0 | **0** |
| `UI-U06` | 1 | 0 | **0** |
| `UI-U07` | 1 | 0 | **0** |
| `UI-P2` | 1 | 0 | **0** |
| `UI-U09` | 1 | 0 | **0** |

## 4. Что НЕ заявляется

- Реальный Telegram WebView и физический Android **не** проверялись: стенд — Chromium
  (Playwright 1.62). FPS/клавиатура Android, поведение внутри Telegram — только
  **необязательное наблюдение владельца** (`plans/owner_live_checks.md`), не гейт.
  Это зафиксировано в `ui-acceptance.md` §6 и в `review-r2.md`.
- Post-deploy проверки W4 (реальный WebView, живой API) остаются штатными после деплоя
  `e4ee54f3`; до них строки W4 остаются закрытыми по инженерной приёмке, но не по
  устройству.
- Открытые строки карты (35 PENDING) относятся к другим слайсам (W1/W2/W3/W5, I-серия,
  отчётность) и не закрываются этим поездом.
