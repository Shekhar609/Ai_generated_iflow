from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..services.tracing import new_request_id, set_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id")
        rid = incoming or new_request_id()
        set_request_id(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        set_request_id(None)
        return response
