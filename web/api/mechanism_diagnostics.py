"""MEME-PIPELINE-REFACTOR-01 P4 (`MEME-IIC-DIAG-UI`) — диагностика ДВУХ
механизмов инициативы для карточки мемов.

Один аддитивный маршрут на собственном роутере-зоне (прецедент
stories/oversight_router/speech): `web/api/routes.py` НЕ меняется, byte-freeze
`ROUTES_SHA256_F11` остаётся в силе, а новый маршрут не попадает в
routes-инвентарь F8 (`tests/fixtures/round1025/f8_baseline.json`).

* ``GET /api/initiative/mechanism-diagnostics`` — ровно то, что собрал
  ``services.initiative_diagnostics.collect_mechanism_diagnostics``: два
  НЕЗАВИСИМЫХ блока (``text_initiative`` и ``meme``) плюс список
  ``degraded``. Ни склейки блоков, ни пересчёта полей, ни нового хранилища —
  одна точка чтения на карточку (контракт P9 уже принят отдельно).

Права — те же, что у чтения настроек мемов: доступ к КОНКРЕТНОМУ чату
(``_require_chat_access``), а не глобальный админ: диагностика всегда про
чат. Без ``X-Chat-Id`` → 422 (у диагностики нет глобального слоя); чужой
чат → 403 без раскрытия существования. Сборщик read-only, никогда не
бросает и ничего не пишет — маршрут не добавляет своего guard'а поверх.
"""
from __future__ import annotations

from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from web.api.deps import get_tma_user
from web.api.routes import _chat_id_or_none, _require_chat_access

mechanism_diagnostics_router = APIRouter()


@mechanism_diagnostics_router.get("/initiative/mechanism-diagnostics")
async def get_mechanism_diagnostics(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """P4 (`MEME-IIC-DIAG-UI`): диагностика двух механизмов инициативы.

    Отдаёт ответ сборщика байт-в-байт (без переименований и склейки):
    ``schema_version``/``generated_at``/``chat_id``, два блока механизмов и
    список ``degraded``. Отсутствующая БД — честные блоки ``no_data``, а не
    500: guard принадлежит сборщику, как и у соседнего GET meme-settings.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    await _require_chat_access(request, user, chat_id)
    from services import initiative_diagnostics as diag
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    return await diag.collect_mechanism_diagnostics(db, chat_id)
