# REVIEW-WG — независимое ревью P0-хотфикса (Windows launch-fullscreen + Android-рефракция)

| Поле | Значение |
|---|---|
| Кандидат | рабочее дерево поверх `a8433e4f` (без коммита); отпечатки 8/8 совпали: `glass-refraction.js` `6a09d962d59d`, `glass-probe.js` `b2e6a1f987c6`, `app.js` `5a810c0f4443`, `app.css` `3c67a414da7b`, `index.html` `0971d49d5337`, `glass_refraction_test.js` `4fc4f9ca7848`, `glass_probe_test.js` `bed0d1dfca67`, `ui_win_glass_refraction_e2e.py` `612200f86b84`; `fullscreen-policy.js` не тронут (`96db06425079`) |
| Входы | `report.md`, `owner-steps.md`, `requirements-map.json` (+`slice-graph.json`), `source-hotfix-2026-10-18.md`, `evidence/**` |
| Вердикт | **Approved** (реализация и evidence); живые пункты — `PENDING_OWNER_E2E`; для strict-гейта — условия привязки карты (см. §5), не дефекты кода |

## 1. Windows-линия — VERIFIED (сверено исполнением + внешне)

- **API-факт:** в вендорном SDK нет ни одной функции геометрии окна; полный список postEvent-событий содержит только `web_app_request_fullscreen`/`web_app_exit_fullscreen` (плюс inset-запросы `request_viewport|safe_area|content_safe_area`, не геометрия окна). `window.moveTo/resizeTo` в `web/**` отсутствуют; e2e-проверка **D** их не находит (комментарии отфильтрованы).
- **Полоса управления:** `git diff HEAD -- web/static/fullscreen-policy.js` — пусто; авто-выход стартового fullscreen в политике отсутствует (единственный `exitFullscreen()` — пользовательский `exit()`).
- **Внешняя проверка (точечно, 18.10.2026):** `tdesktop#30963` — существует, **open**, label bug, создан 2026-07-12, обновлён 2026-08-20; суть совпадает: панель **resized but not moved**, панель задач видна, ввод смещён, смещение пропорционально позиции главного окна (левый верхний угол/второй монитор — верно), 6.9.3 x64, первопричина — frameless `showFullScreen()`. `#31041` и `#31114` — существуют, **закрыты как дубликаты** #30963. `desktop-app/lib_ui#342` — существует, **open** (не влит), +11/−0, отдельная ветка/коммит; мейнтейнер в комментарии 21.08.2026 сомневается в атрибуции Qt и указывает на возможную собственную причину клиента (нулевая геометрия `RpWidget`/`WA_Moved`) — в отчёте это отражено. **Документировано** (issues/PR/комментарии) vs **наблюдаемо у нас** (код SDK, e2e, симптом владельца) разделено корректно; наш «фикс» в веб-коде не заявляется.
- **owner-steps.md**: исполнимо и точно по существу (левый верхний угол; второй монитор; перезапуск через ⛶; проверка версии клиента; BotFather/`?mode=compact` как A/B с честной оговоркой «при ручном ⛶ баг вернётся» и предупреждением про мобильные). Заглушек вместо функциональности нет — есть рабочий обход + путь баг-репорта (чек-лист §B, наша админ-диагностика §8).
- Нит (не блокер): формулировка «подтверждённый апстримом обход» — наблюдение автора issue, не заявление команды Telegram; лучше «подтверждено в отчётах issue». Левый верхний угол как обход — по тексту issue.

## 2. Android-линия — VERIFIED локально; живой WebView = PENDING_OWNER_E2E

- **Код (прочитан целиком, 688 строк):** слой рисует ТОЛЬКО контролируемый фон — `drawImage` из `#polygon-background` (fallback `.aurora-flow-canvas`), живой DOM/текст не клонируется (клонируется только узел SVG-фильтра линзы); слой `pointer-events:none`, `aria-hidden`, `z-index:-1` под контентом, маска-рамка 20+46 px, подложка поверхности запекается (tint), бюджет слоёв по умолчанию 3, DPR-кап 1.5, тред 40 мс, `document.hidden` → пауза, `prefers-reduced-motion` → редкий режим, идемпотентные `sync/dispose`, честные reason-коды. `app.js`: carrier `backdrop|layer|null` по факту пробы (`svgRender && backdrop`) и SDK-платформе; `_syncLensFilters` не дублирует `url()` на layer-поверхностях; CSS `[data-refract-layer="on"]` снимает `url()` у backdrop-фильтра (без двойного blur).
- **Мой прогон e2e** (`tools/ui_win_glass_refraction_e2e.py`, evidence → scratch): **37/37 (A21/C4/B10/D2), WG-REFRACT-E2E-OK**; числа воспроизводятся: смещение линий −26/+32 device px (−13/+16 CSS px) corr 0.92/0.971, центр 0 (corr 1.0), шум OFF↔OFF 0/0; `moved_frac=0.149`, ring/center 4.46/0.0, яркость кромок −1.93 % (в отчёте −1.91 %, ±); слоёв 3 (≤3), `refractOn=16`, `filteredContent=0`, `url()` в backdrop у layer-поверхностей 0/16; `host_moved=0`, высота страницы 844→844; desktop: `layers=0`, FS-аудит «launch-fullscreen сохранён, кнопка=выход, второго request нет».
- **Мои доп. пробы (главные):** `?glassrefract=off` → 0 слоёв/reason disabled ✓; удаление источника фона + `invalidate()` → слои сняты, `reason=no-background-source` ✓ (честный отказ); `setEnabled(false)` → 0 canvas, 0 клонов фильтров, 0 инлайновых `overflow/isolation/position` на хостах, `data-lg-refract` снят; повторное включение — снова 3 слоя без дублей ✓; DPR-кап подтверждён по факту: bitmap = 1.5×CSS при devicePixelRatio 2; hidden-пауза: `reason=hidden`, приростов `paintCount` нет; hit-тест центра поверхности → контент (`hub-card-sub`), текст без `filter` ✓.
- **Единственные «сдвинувшиеся» rect'ы (2 шт. вне хостов) разобраны:** это `div.spinner.my-2` (анимированный `transform: rotate`), их axis-aligned rect меняется фазой вращения; к слою отношения не имеют (в контроле OFF↔OFF, снятом между кадрами анимации, они тоже «плавают»). Хосты (3) — строго без сдвигов.
- Живой Android WebView и iOS не проверялись (агентам недоступны) — `PENDING_OWNER_E2E` с точным сценарием (owner-steps §C) ✓; отчёт не заявляет успех на реальном устройстве.

## 3. Регрессии — VERIFIED

- `node tests/js/*` → **87/87** (вкл. новый `glass_refraction_test.js` — 50 assert; обновлённый `glass_probe_test.js` — 28).
- FS-полоса (`ui_asap8_w2_fullscreen_e2e.py`) — **12/12, 166 проверок** (launch-fullscreen и ⛶ сохранены; S6S7 + desktop FS-аудит).
- `tools/soul1_w4_frozen_check.py` (мой запуск с OUT→scratch, чужой файл не тронут) → **FROZEN-ASSETS-OK**; совпал с копией лейна (`evidence/frozen-assets.txt`): все 8 маркеров «same», index/app.js LF.
- `tools/ui_round1026_polygon.py`: 4 падения «getDiagnostics полей 19 != 11» — **предсуществующие**: в `HEAD:web/static/polygon-background.js` `getDiagnostics()` уже возвращает 19 полей, а инструмент ждёт 11; `polygon-background.js` лейном не изменён (frozen-OK).

## 4. Гигиена — OK, с одним инцидентом ревьюера (раскрываю)

- Чужие evidence-каталоги (`soul-1/evidence/fs-hotfix/**`, `soul-1/evidence/w4/frozen-assets.txt`) — дифф к HEAD пуст ✓; копии прогонов лейна в `evidence/fs-regression/` (12/12·166) и `evidence/frozen-assets.txt` ✓.
- `git status`: изменены/добавлены только файлы лейна (+ чужие предсуществующие untracked из старых лейнов, не тронуты).
- **Инцидент (мой, честно):** запустив `tools/ui_win_glass_refraction_e2e.py` с неверным env-именем, я перезаписал 6 файлов в `plans/features/win-glass-hotfix/evidence/e2e/**` (`_results.json` + 5 PNG) свежим прогоном того же инструмента на том же кандидате. Все детерминированные метрики воспроизвелись точно (смещения/corr/центр/шум/layers/16/3/host_moved=0), различаются только тайминги (paintMs 0.29/22.8 vs 0.22/21.7 мс, p95) и байты PNG. Оригинальные байты лейна не восстановимы; моя копия прогона — `OPENCODE_WORKFLOW_SCRATCH/<scratch>/review-wg/`. Смысловая целостность evidence не пострадала; при желании лейн может перегенерировать (детерминированно).

## 5. Карта: пригодность привязки для strict-гейта (учётному лейну)

Гейт (пуск мой): `--stage plan` → `stage=plan inventory=14 manual=16 scoped=0 errors=0` EXIT 0 ✓. Review-стадия ожидает по слайсам: WG-WIN `scoped=5` (01,04 — VERIFIED; 02,03,05 — RFL/VERIFIED), WG-ANDROID `scoped=6` (02 — RFL/VERIFIED; остальные VERIFIED), WG-VERIFY `scoped=13`.

- **WG-WIN/WG-ANDROID**: предложенные в отчёте artifact-пути покрывают все строки и **существуют** (`report.md`, `owner-steps.md`, `evidence/e2e/_results.json`, `evidence/e2e/pattern_on|off.png`, `evidence/fs-regression/_results.json`, `evidence/frozen-assets.txt`) — привязка пригодна.
- **WG-VERIFY (12 уникальных строк / 13 с учётом дубля) — привязки в отчёте НЕТ**: `WG-P0-01..07`, `WG-VER-01..05`. Нужны artifact_path (кандидаты уже есть: `report.md §3/§5`, `owner-steps.md §B/§C`, `evidence/README.md`, сам отчёт-вердикт, ledger AU-8/`owner_questions.md` для P0-01/03; для `WG-VER-04` — секция PENDING_OWNER_E2E; для `WG-P0-05` — этот ревью-вердикт + будущий релиз-evidence).
- **Дубль req_id:** `MAN-WG-04` и `MAN-WG-16` оба несут `req_id WG-P0-03` (гейт показывает WG-P0-03 в списке дважды) — до привязки либо пометить MAN-WG-16 `duplicate` со ссылкой на WG-P0-03, либо выдать отдельный id.
- **Кандидат:** `candidate_commit` пуст; strict-review требует реальный Git-коммит кандидата и совпадение с `--candidate` — коммит кандидата должен предшествовать привязке (последовательность: коммит → привязка evidence с `artifact_path` → `check --stage review --slice …`).
- **Live-строки:** после привязки переводить в `READY_FOR_LIVE` (не VERIFIED): `WG-WIN-02/03/05`, `WG-ANDROID-02`, `WG-VER-01/02` — гейт это допускает; сейчас все строки PENDING (overclaim отсутствует).

## 6. Итог и что дальше

`REVIEW-WG: Approved` — реализация и evidence P0-хотфикса подтверждены моими прогонами и внешней сверкой; заглушек нет, живые границы честные. Дальше: (1) учётный лейн — коммит кандидата + привязка по §5; (2) strict-review по трём слайсам; (3) релиз/деплой штатным каналом; (4) владельцу — `PENDING_OWNER_E2E`: Windows (обход §A.1 + снимок админ-диагностики), Android (видимое смещение у кромок, перф/скролл/поворот), опционально iOS.
