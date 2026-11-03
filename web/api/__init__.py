"""Epic 85 - REST API: deps (TMA-auth/RBAC) + routes.

Раунд 10.46 (MCA-12, ADR-1028-21 D2): роутер «Истории чата» — отдельный файл
зон (`web/api/stories.py`, прецедент memory_agi/oversight); re-export здесь,
регистрация — в web/app.py рядом с остальными роутерами. `web/api/routes.py`
не меняется (byte-freeze ROUTES_SHA256_F11 держится — hash не изменился,
re-pin сводится к осознанной верификации, L-F11S-1).

Раунд 10.47 (mca-17c, ADR-1028-23 D11): роутер витрины наблюдаемости —
отдельный файл `web/api/oversight_router.py` (ровно 3 санкционированных
маршрута /runs, /experience/funnel, /jobs/{id}/action); re-export здесь,
регистрация в web/app.py рядом с oversight_router; routes.py по-прежнему
не меняется.

Раунд P4 (meme-pipeline-refactor-01, `MEME-IIC-DIAG-UI`, 03.11.2026):
диагностика ДВУХ механизмов инициативы — отдельный файл-зона
`web/api/mechanism_diagnostics.py` (ровно 1 маршрут
GET /initiative/mechanism-diagnostics; RBAC — доступ к чату); re-export
здесь, регистрация — в web/app.py рядом с initiative_vitality. Новый
маршрут НЕ добавляется в routes.py: routes-инвентарь F8 и byte-freeze
`ROUTES_SHA256_F11` остаются осмысленными (Δ routes=0).
"""
from web.api.stories import stories_router  # noqa: F401
from web.api.oversight_router import oversight17c_router  # noqa: F401
from web.api.mechanism_diagnostics import (  # noqa: F401
    mechanism_diagnostics_router,
)
