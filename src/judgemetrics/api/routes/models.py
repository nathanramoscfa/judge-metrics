# src/judgemetrics/api/routes/models.py
"""``/api/v1/models``: the model card of a fitted expected-outcome model.

Every adjusted observation names its model (``ModelRef.url``); the card is
served from the catalogue row alone (``services.metrics.model_card``: one
statement, no artifact read) and never carries the artifact's storage URI.
A model of a snapshot no current observation cites is a 404, as is an
unknown id; a malformed id is a 422.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from judgemetrics.api.deps import SessionDep, SettingsDep, StrictQuery, cache_public
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.schemas.metrics import ModelCard
from judgemetrics.services.metrics import model_card

router = APIRouter(prefix="/models", tags=["models"], dependencies=[Depends(cache_public)])


@router.get(
    "/{model_id}",
    response_model=ModelCard,
    responses=error_responses(404, 422),
    summary="The model card of an expected-outcome model an adjusted observation cites",
    dependencies=[Depends(StrictQuery())],
)
def get_model(model_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> ModelCard:
    found = model_card(session, settings, model_id)
    if found is None:
        raise ApiError(status_code=404, code="not_found", message=f"model {model_id} not found")
    return found
