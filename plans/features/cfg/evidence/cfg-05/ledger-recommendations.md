# CFG-05-Verify — рекомендации по 8 строкам карты (карта НЕ менялась)

**Важно:** `requirements-map.json` в этом лейне **не изменялся** (правило брифа). Ниже — что предлагается записать PM/Orchestrator при привязке, с точными артефактами. Все артефакты лежат в `plans/features/cfg/evidence/cfg-05/`.

**Привязка кандидата:** `candidate_commit` = SHA этого evidence-коммита (продуктового диффа нет), `deployed_commit` = `99f5672c5e1d27e957100395a13178fef929b035` (2.58.97). Верхнеуровневые `candidate_commit`/`deployed_commit` карты сейчас указывают на `113f3a62` (2.58.95) — их нужно обновить, иначе strict-гейт проверит не тот кандидат.
`artifact_sha256` PM вычисляет при привязке: `sha256` файла на момент коммита (файлы после коммита не меняются).

| req_id | Рекомендуемый статус | Пометка в observation | Артефакты (`artifact_path`) |
|---|---|---|---|
| **ADD-1.C6** | `VERIFIED` | «полигональный фон не изменён: blob `c2ad97d446f5…` = deployed; пины палитры/топологии/рендерера зелёные; 178/178 без новых замечаний; 0 пиксельных отличий фона (фон заморожен)» | `deployed-sha.json`, `pins.json`, `matrix-178-cand.json`, `ui/status-390x844-cand97.png` |
| **CFG-05.1** | `VERIFIED` | `REUSED_EXISTING / OWNER_VISUAL_CONFIRMED`: deployed SHA 2.58.97 (`/healthz`) сверен с отревьюенной линзой (6298 б, `5367ec45…`, `scale=32`); U08/SOUL-17 переиспользованы; наблюдение владельца 18.10 (L183) зафиксировано; нового кода/деплоя нет | `deployed-sha.json`, `reuse-map.md`, `owner-observation.md` |
| **CFG-05.2** | `VERIFIED` | «новых рендеров/стенда/оптического рендерера/A-B/tier/CSS не запускалось: дифф продукта = 0, скан glass-ключей = 1 строка использования существующего токена» | `diff-guard.txt`, `README.md` (§8) |
| **CFG-05.3** | `VERIFIED` | «стекло/фон/компоновка прежние после CFG-04: 2050 ячеек — 0 отличий материала/линзы/токенов; карточка „Бот“ 0 пикселей @390/@1440; 106 rect-дельт только конфиг-экраны (CFG-04), „Статус“ без дельт» | `glass-invariant.json`, `matrix-178-cand.json`, `ui/status-hero-390x844-cand97.png`, `ui/status-hero-1440x900-cand97.png` |
| **CFG-05.4** | `VERIFIED` | «правило триажа зафиксировано; новых конкретных воспроизводимых регрессий нет; гипотетические дефекты очередь не держат» | `failures.md` |
| **ADD-1.T5** | `VERIFIED` | `OBSERVED_FIXED / REUSE_EXISTING`: второй реализации стекла нет (дифф `web/**` = 0, glass-тестов не добавлено); владельцы — SOUL-17 и U08/WG | `diff-guard.txt`, `reuse-map.md` |
| **CFG-05.D** | `VERIFIED` | `OBSERVED_FIXED / NO_NEW_IMPLEMENTATION`: отдельного деплоя стекла нет; однократная сверка deployed SHA + U08/SOUL-17 + наблюдения выполнена; закрытие как `REUSED_EXISTING/OWNER_VISUAL_CONFIRMED` | `deployed-sha.json`, `owner-observation.md` |
| **CFG-05.B** | `VERIFIED` (composite) | критерий собран из `.1` + `.3`: наблюдаемое поведение соответствует запросу владельца (L183), рефракция/фон сохранены после CFG-04, новых обязательств нет | `README.md` (§2,§6), `glass-invariant.json`, `owner-observation.md` |

## Что НЕ рекомендуется

- **`ADD-2.5`** — оставить `PENDING` до CFG-FINAL (это строка другого слайса; CFG-05 лишь поставляет evidence).
- **`CFG-04.D.4`** — `PENDING_OWNER_E2E` (owner-optional по PET), не блокер.
- **SOUL-17.4 / U08-остатки / WG-живые пункты** — строки чужих карт; CFG-05 их не переписывает (см. `reuse-map.md`).
- Не ставить `VERIFIED` без привязки `deployed_commit=99f5672c`: именно эта привязка отличает «уже исправлено» от фиктивного PASS.

## Гейт (после привязки)

```
py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check --stage review \
  --slice CFG-05-Verify --candidate <evidence-commit> --repo . \
  --map plans/features/cfg/requirements-map.json
py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check --stage release \
  --slice CFG-05-Verify --candidate <evidence-commit> \
  --deployed-commit 99f5672c5e1d27e957100395a13178fef929b035 --repo . \
  --map plans/features/cfg/requirements-map.json
```

Ожидание: `review` — зелёный по слайсу (8 строк, evidence существует и привязано); `release` — зелёный по слайсу при обновлённых `candidate_commit`/`deployed_commit`. Остальные слайсы CFG остаются `PENDING` — это нормально (гейт release проверяет весь проект, но CFG-05 не обязан закрывать чужие строки).
