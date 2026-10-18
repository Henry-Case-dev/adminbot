# P0 hotfix: инициатива + сохранение SOUL-1 + UX «Речь и характер»

Карты требований (legacy-режим, без `strict_evidence`):

- `requirements-map.json` — источник `source-p0-hotfix-2026-10-18.md`; слайсы `P0A-INIT`, `P0A-PERSIST`, `P0A-UX`, `P0A-ACCEPT`.
- `requirements-map-followup.json` — источник `source-p0-followup-2026-10-18.md`; слайсы `P0B-INIT-ARCH`, `P0B-NOST`, `P0B-ACCEPT`.

Live-семантика: строки с `live_required=true` и `live_when=postdeploy` допускают `READY_FOR_LIVE` на ревью и подтверждаются production-наблюдением после деплоя; строки с `live_when=preprod` требуют UI-evidence (Browser Use/Playwright) на ревью. Ни одна строка не помечается VERIFIED без привязанного доказательства.

ADD-1: строки с `alias_of` ссылаются на существующие требования (SOUL-1/CFG) — правки идут в их компоненты и статусы; повторных реализаций и вторых контуров не создавать.
