"""
Pure-ASGI replacement for the BaseHTTPMiddleware `dispatch` in main.py (line ~62).

Why: BaseHTTPMiddleware re-raises downstream errors inside an anyio TaskGroup,
producing the ExceptionGroup seen in the logs, and it cannot recover once
response headers have started. This middleware:
  - assigns a request_id
  - logs method/path/status/duration
  - converts ANY escaped exception into a 500 JSON (if headers not yet sent)
  - never lets an exception reach Passenger / the server
Usage in main.py:
    from app.core.exceptions.asgi_middleware import SafeRequestMiddleware
    app.add_middleware(SafeRequestMiddleware)     # remove the old @app.middleware("http")
"""
import json
import logging
import time
import uuid

log = logging.getLogger("app.request")


class SafeRequestMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = uuid.uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = rid
        started = {"v": False, "status": 0}
        t0 = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                started["v"] = True
                started["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("Unhandled exception [%s] %s %s", rid, scope.get("method"), scope.get("path"))
            if not started["v"]:
                body = json.dumps({"success": False, "message": "Internal server error",
                                   "error_code": "INTERNAL_ERROR", "request_id": rid}).encode()
                try:
                    await send({"type": "http.response.start", "status": 500,
                                "headers": [(b"content-type", b"application/json"),
                                            (b"content-length", str(len(body)).encode()),
                                            (b"x-request-id", rid.encode())]})
                    await send({"type": "http.response.body", "body": body})
                except Exception:
                    log.exception("could not send fallback 500 [%s]", rid)
        finally:
            log.info("%s %s -> %s %.1fms [%s]", scope.get("method"), scope.get("path"),
                     started["status"], (time.perf_counter() - t0) * 1000, rid)
