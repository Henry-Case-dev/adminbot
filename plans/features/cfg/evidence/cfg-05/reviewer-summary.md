# Reviewer-summary — что проверить независимо

Пакет: `plans/features/cfg/evidence/cfg-05/**`. Продуктового диффа нет; кандидат — docs/evidence-коммит. Проверка идёт на **уже выкаченном** 2.58.97 @ `99f5672c`.

## 1. Перепроверить самому (не по выводам лейна)

```powershell
# deployed и версия
# GET https://admin-bot.duckdns.org/healthz  -> {"status":"ok","version":"2.58.97"}

# блоб-равенство защищённых объектов
git rev-parse 99f5672c:web/static/polygon-background.js     # c2ad97d446f5e7c7b72fb46d9bb560ae3777d6c3
git rev-parse 99f5672c:web/static/glass-refraction.js       # 0c57cc25265e0a58cb195a28937ff752834ff375
git rev-parse 99f5672c:web/static/glass-probe.js            # 4eab69ac4aa0fcd2f4a3afee073b7114436e2e3a
# блок #lg-lens из git show 99f5672c:web/index.html -> 6298 б, sha256 5367ec45…d3db, scale="32"

# diff-guard
git diff --stat 95d11472 99f5672c -- web/     # 3 файла CFG-04
git diff --stat 99f5672c HEAD -- web/ tests/ tools/   # пусто
git show --stat <evidence-commit>             # только plans/features/cfg/evidence/cfg-05/**
```

Проверить в скане диффа: единственная glass-строка CFG-04 — `.tech-key__copy:hover { border-color: var(--glass-border-color) }`; в `app.js`/`index.html` — 0.

## 2. Пины

`pins.txt`/`pins.json`: 131 passed + 4/4 node OK **на worktree `99f5672c`**, не в основном дереве (в основном есть чужие незакоммиченные `web/api/speech.py`, `tests/test_soul1_w6_speech_ui.py`, `tests/test_add_exp_expression.py` — к CFG-05 не относятся; лейн их не трогал).

## 3. Честность reuse-map

- `SOUL-17.4` — `READY_FOR_LIVE` (не VERIFIED).
- U08-карта — `REQU-U08/U08.3e/U08.5.4/REQ-U08-DOD/B10-R19` = `READY_FOR_LIVE`, `U08.4d/U08.5.1/REQ-U08-4` = `PENDING` (bookkeeping на `0b7a0aca`), не переписаны.
- WG — живые пункты `PENDING_OWNER_E2E`.
- Ничего из этого не выдано за `VERIFIED`.

## 4. Кадры

- `ui/status-390x844-{base96,cand97}.png` — **побайтово идентичны** (проверяемо `Get-FileHash`): фон заморожен, анимации остановлены, canvas/aurora скрыты для детерминизма.
- `ui/status-hero-*.png` — карточка «Бот» (0 отличающихся пикселей base↔cand).
- Прод-кадр **не** заявлен: живой `/web/` без Telegram-сессии не авторизуется; подделки нет, честно указано в README §7.
- 69 пикселей на 1440-кадре — живая метка времени, не стекло.

## 5. Формулировка owner-наблюдения

`owner-observation.md`: цитата L183, платформа не названа, скриншот владельца в repo отсутствует, «все браузеры/перф» не подтверждены. `REUSED_EXISTING / OWNER_VISUAL_CONFIRMED` — про материал, а не про все устройства.

## 6. Известные ограничения (ожидаемые, не дефекты)

1. Headless Chromium → Tier B; оптический сдвиг здесь не измеряется (это SOUL-17/U08/WG).
2. `/static/app.js` → 404 — штатно (index грузит `/web/app.js`).
3. Дельта index.html 120 б / app.css 22 б — серверная подстановка версии.

## 7. Гейт

`requirements_gate.py check --stage review --slice CFG-05-Verify --candidate <evidence-commit>` — после привязки 8 строк по `ledger-recommendations.md`; затем `--stage release ... --deployed-commit 99f5672c…`.
