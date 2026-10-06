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
"""
from web.api.stories import stories_router  # noqa: F401
from web.api.oversight_router import oversight17c_router  # noqa: F401
