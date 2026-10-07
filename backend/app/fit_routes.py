"""The "Rower na Twoją miarę" tab's frame-size calculator: POST /v1/fit/frame-size.

A pure calculation (app/frame_size.py): no AI, no database, no generic cache, nothing
stored. The frontend calls it while the rider types, so it must stay instant.
"""
import logging
from typing import Callable

from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .frame_size import compute_frame_size
from .schemas import FrameSizeRequest, FrameSizeResponse

logger = logging.getLogger("biker.search")


class _FiniteSafeRoute(APIRoute):
    """422 bodies without the offending `input`.

    A JSON `NaN` / `Infinity` is rejected by the model, but FastAPI echoes the value back
    in the error and Starlette cannot serialise it, so the 422 would turn into a 500.
    """

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                errors = [{k: v for k, v in err.items() if k != "input"} for err in exc.errors()]
                return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

        return route_handler


router = APIRouter(route_class=_FiniteSafeRoute)


@router.post("/v1/fit/frame-size", response_model=FrameSizeResponse)
async def frame_size(req: FrameSizeRequest) -> FrameSizeResponse:
    """Recommended frame size (number, range, letters) for a height, inseam and bike type. 422 for a bad field."""
    result = compute_frame_size(req.height_cm, req.inseam_cm, req.bike_type)
    # Only the numbers the rider typed and the answer — nothing that identifies anyone.
    logger.info(
        "frame size | type=%s height=%.1f inseam=%.1f -> size=%.1f %s range=%.1f-%.1f letters=%s warning=%s",
        result.bike_type, req.height_cm, req.inseam_cm, result.size, result.unit,
        result.range_min, result.range_max, "/".join(result.letters), result.measurement_warning,
    )
    return result
