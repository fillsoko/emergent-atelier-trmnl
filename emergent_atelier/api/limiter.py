"""Shared SlowAPI rate limiter instance.

Defined here (not in server.py) so that routers like marketplace.py
can import it without creating a circular dependency.
"""

from fastapi import Request
from slowapi import Limiter


def _client_host(request: Request) -> str:
    # Always use request.client.host rather than X-Forwarded-For headers.
    # Caddy is the only ingress; request.client.host is the real client IP
    # (resolved by uvicorn from Caddy's X-Forwarded-For, which Caddy sets to
    # {remote_host} so spoofed X-Forwarded-For from clients is stripped).
    # We do NOT read raw forwarded headers to prevent rate-limit bypass.
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_host)
