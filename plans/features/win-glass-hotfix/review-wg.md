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

---

# R2 — BINDING verification (strict): **Approved**

| Поле | Значение |
|---|---|
| Кандидат | `0ca661fe8109fcecf752ad3e863355a4ec96e4ae` (23 файла, +3340/−27), база `8e326403` |
| Привязка | `f0d4b15f2cd4c7710a812564107bb799636d8ad7` (карта + `evidence/verify/candidate-commit.txt`) |
| Вердикт | **Approved** — состав кандидата, отпечатки, привязка (23 строки, артефакты+digest'ы), дубль и 4 гейта подтверждены моим исполнением |

## 1. Состав и байты кандидата

- `git show --stat 0ca661fe` — **ровно 23 файла** (+3340/−27), совпадает с `candidate-commit.txt` (name-status 23 пути, base `8e326403`).
- 8 кодовых файлов по committed-блобам: `glass-refraction.js` `6a09d962d59d`, `glass-probe.js` `b2e6a1f987c6`, `app.js` `5a810c0f4443`, `app.css` `3c67a414da7b`, `index.html` `0971d49d5337`, `glass_refraction_test.js` `4fc4f9ca7848`, `glass_probe_test.js` `bed0d1dfca67`, `ui_win_glass_refraction_e2e.py` `612200f86b84` — **все совпадают** с проверенными в REV-WG.
- Пост-коммитного дрейфа нет: `git diff 0ca661fe -- <пути кандидата>` даёт только добавленный привязкой `evidence/verify/candidate-commit.txt` (ожидаемо); сами файлы кандидата — идентичны. `fullscreen-policy.js` не тронут (`96db06425079`, в диффе 0).

## 2. Привязка карты (strict)

- `candidate_commit` карты = `0ca661fe…`; `strict_evidence: true`, `slice_graph_path` на месте; `deployed_commit` пуст (деплоя ещё не было).
- **23 required-строки** (WG-WIN 5 + WG-ANDROID 6 + WG-VERIFY 12), у каждой — **2 evidence-элемента** с `candidate_commit=0ca661fe…`, существующим `artifact_path` и **совпадающим `artifact_sha256`** (мой скрипт проверил все элементы; спот-чек `report.md` `369ac17e1ab08160`, `owner-steps.md` `6c844e6386c4938d`, `evidence/e2e/_results.json` `16f6e79305cce8fe`, `evidence/fs-regression/_results.json` `8c38a8214840c532`, `frozen-assets.txt` `e6cba2d12f881752`, `candidate-commit.txt` `5574b0acf2d7b78d` — OK).
- **Статусы:** VERIFIED 16 (preprod-строки), **READY_FOR_LIVE 7** — `WG-WIN-02/03/05`, `WG-ANDROID-02`, `WG-VER-01/02`, `WG-P0-05`; ни одна live-строка не VERIFIED.

## 3. Дубль

`MAN-WG-16` → `disposition: duplicate`, reason конкретный («строка 36 повторяет требование строки 4; отслеживается один раз под WG-P0-03 (MAN-WG-04)»); `source_line=36`/`source_text_sha256` сохранены и **совпадают с реальной строкой источника** (мой пересчёт), excerpt не пуст. Скоуп WG-VERIFY после этого = **12** (не 13).

## 4. Гейты (мой прогон, verbatim)

- `plan` → `stage=plan inventory=14 manual=16 scoped=0 errors=0` EXIT 0;
- `review WG-WIN --candidate 0ca661fe…` → `scoped=5 errors=0` EXIT 0;
- `review WG-ANDROID --candidate 0ca661fe…` → `scoped=6 errors=0` EXIT 0;
- `review WG-VERIFY --candidate 0ca661fe…` → `scoped=12 errors=0` EXIT 0.

## 5. Инцидент e2e (принят осознанно)

6 файлов `evidence/e2e/**`, перезаписанных моим ре-прогоном (см. §4 REV-WG), закоммичены как есть; сверено: committed-блобы == рабочее дерево (дрейфа нет), детерминированные метрики совпадают с отчётом, различаются только тайминги/байты PNG. Принято.

## 6. Что дальше (release-стадия)

1. Деплой кандидата `0ca661fe…` штатным каналом; после выката `deployed_commit := 0ca661fe…` (release-стейдж гейта требует `candidate == deployed`).
2. Живые наблюдения по 7 RFL-строкам: Windows (обход §A.1 + снимок админ-диагностики), Android (видимое смещение у кромок, перф/скролл/поворот; owner-steps §C), затем перевод строк в VERIFIED с postdeploy-evidence, привязанным к задеплоенному SHA.
3. `check --stage release --candidate 0ca661fe… --deployed-commit <deployed>` после наблюдений; до этого — «Approved for controlled deployment, parent not DONE».

---

# R3 — VERIFY-WG-LEDGER (re-anchor на задеплоенный `95526863`, 2.58.85)

| Поле | Значение |
|---|---|
| Кандидат / прод | ревью-линия `0ca661fe…`; задеплоено `9552686391dfe69dd7cb08ba7cd800a8a6c5106e` (release/win-glass-2.58.85, 2.58.85) |
| Коммиты | `28d5516c` (артефакты релиза) + `278605b2` (ре-анкор карты + `evidence/verify/release-line.txt`) |
| Вердикт | **Needs Fixes** — леджер/ре-анкор VERIFIED (пп.1–4 ниже), но на master остаётся **один красный guard, внесённый этим кандидатом** (находка R3-1) |

## 1. Скоуп и секреты — OK

- `git diff --name-only 915aa3c7..HEAD` = **31 путь**, все под `plans/features/win-glass-hotfix/**` (28× `evidence/release/**` + `release-2.58.85-report.md` + `requirements-map.json` + `evidence/verify/release-line.txt`); чужих файлов нет.
- Секрет-скан всех 31 новых файлов (17 паттернов: password/secret/token/api_key/PRIVATE KEY/ssh-rsa…): **креды/ключи/пароли не найдены**. Единственные срабатывания — имена тестов (`design_tokens`, `F9-SECRET-OK`) и `[stderr] [sudo] password for nik:` (это текстовый prompt sudo, не значение; `SUDO_NOPASS=0` — проба) + публичный `ssh nik@198.46.175.136` в rollback-блоке отчёта (логин/IP уже в repo-доках, значений нет).

## 2. Карта — привязка к прод-линии корректна

- top: `candidate_commit=0ca661fe…` (не менялся), `deployed_commit=95526863…` (единственное top-изменение), `strict_evidence: true`.
- Семантический дифф карты `f0d4b15f → 278605b2`: изменены **8 строк, у каждой +1 evidence** (WG-P0-05 +2: deploy-run + отчёт) = **9 release-записей в 8 строках**; строк не добавлено/удалено; **статусы не менялись: 16 VERIFIED / 7 READY_FOR_LIVE**.
- Все 9 записей: `artifact_path` существуют, `artifact_sha256` **совпали** (проверил все 9, спот-чек включает `isolation-classification.txt`, `deploy-run.txt`, `hashes.txt`, `e2e/_results.json`, `postdeploy_http.txt`, `postdeploy_probe.json`). `type:"production"` — на деплой-записях (`postdeploy_http`, `postdeploy_probe`, `deploy-run`).
- Все 7 live-строк несут явную пометку «Ждёт owner-наблюдений по owner-steps.md …»; ни одна не VERIFIED.

## 3. Прод-факты подтверждены независимо

- Коммит `95526863` существует, ветка `release/win-glass-2.58.85` = `origin/...` = `95526863` (запушена); цепочка `0b7a0aca → d637cfe9 → 95526863`.
- Блобы прод-линии: `glass-refraction.js` = `6a09d962d59d`, `fullscreen-policy.js` = `96db06425079` (SAME), `glass-probe.js` = `b2e6a1f987c6`, `glass_refraction_test.js` = `4fc4f9ca7848`, e2e-инструмент = `612200f86b84` — т.е. **5/8 файлов byte-equal**, 3 порт-файла (app.js/app.css/index.html) — как в `hashes.txt`/`release-line.txt`.
- `release-line.txt` (двухлинейная семантика, порт `d637cfe9`, 5/8 byte-equal) + секция «Леджер» в `release-2.58.85-report.md` (ре-анкор, конвенция soul-карт, release-стадия не запускалась) — на месте; **кавета про `candidate==deployed` на release-стадии зафиксирована** (release-line.txt §43-47). Изоляция: 39 = 8 порт + 31 bump, unclassified 0; prod healthz `2.58.85`, `/web/` 15×«2.58.85»/0×«2.58.84», 0 ERROR/CRITICAL.

## 4. Гейты (мой прогон, verbatim; release-стадию не запускал)

- `plan` → `stage=plan inventory=14 manual=16 scoped=0 errors=0` EXIT 0;
- `review WG-WIN` → `scoped=5 errors=0` EXIT 0;
- `review WG-ANDROID` → `scoped=6 errors=0` EXIT 0;
- `review WG-VERIFY` → `scoped=12 errors=0` EXIT 0.

## R3-1 — Блокер (внесён кандидатом; test-only): два bounds-guard'а красные на master

- **Требование:** repo-дисциплина новых `web/**`-файлов — каждый новый файл с тега `pre-round1026-a1` должен иметь NOTE-sanction в двух guard-тестах (прецеденты: da58e24b W3b, SOUL-1 W6).
- **Репро (мой прогон):** `pytest tests/test_tool_coordinator_round1026.py::TestBounds tests/test_unified_image_request_round1026.py::TestBoundsA3` → **2 failed, 10 passed**; offense: `web/static/glass-refraction.js` отсутствует в allowlist (проверено: `git diff --name-only pre-round1026-a1 -- web/` содержит этот файл). На родителе кандидата файла не было → guard'ы были зелёные; после коммита `0ca661fe` — красные. Продукт не затронут (тесты; рантайм-байты не меняются).
- **Готовое лечение (от лейна, не применено):** `evidence/release/bounds-guard-sanction-suggested.patch` (+NOTE +allowlist в обоих guard'ах). ВАЖНО (мой пересчёт): на **master этот патч НЕ применяется** — `git apply --check` = **rc 1** (контекст патча снят с релизной версии guard-файлов; в master после `web/api/__init__.py` идут дополнительные NOTE-записи SOUL-1 W6 и др.). Для master нужна своя тривиальная правка с master-контекстом; патч лейна пригоден для релизной линии (там он и проверялся).
- **Минимальная перепроверка:** Builder добавляет NOTE-sanction + allowlist-entry в оба guard-файла **на master** (2 тестовых файла, контекст master) → `.venv/Scripts/python.exe -m pytest -q tests/test_tool_coordinator_round1026.py::TestBounds tests/test_unified_image_request_round1026.py::TestBoundsA3` = ожидание **10 passed / 0 failed**; релизную линию не трогать сейчас (прод-байты не затронуты; sanction — при следующем касании релиза).

## Итог

Леджер и ре-анкор (пп.1–4) подтверждены полностью; единственное, что мешает закрытию, — красные guard'ы на master из-за нового файла слоя. После крошечного test-only патча + перепрогона двух guard'ов задачу можно закрывать; живые наблюдения остаются за владельцем (`PENDING_OWNER_E2E`, 7 RFL).
