"""CSP violation reporting endpoint (SOK-337).

Browsers POST application/csp-report JSON here whenever the site's
Content-Security-Policy is violated.  We log the key fields and return
204 so the browser doesn't retry.  The endpoint intentionally bypasses
the Caddy proxy-secret guard (see ProxySecretMiddleware exclusion in
server.py) because reports arrive directly from end-user browsers, not
through our reverse proxy.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

from emergent_atelier.api.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["security"])


@router.post("/api/csp-report", status_code=204, include_in_schema=False)
@limiter.limit("60/minute")
async def csp_report(request: Request) -> Response:
    """Accept CSP violation reports and log them for visibility."""
    try:
        body = await request.json()
        # Both report-uri (legacy) and report-to (modern) formats
        report = body.get("csp-report", body)
        logger.warning(
            "CSP violation | blocked-uri=%s violated-directive=%s document-uri=%s source-file=%s",
            report.get("blocked-uri") or report.get("blockedURL", "unknown"),
            report.get("violated-directive") or report.get("effectiveDirective", "unknown"),
            report.get("document-uri") or report.get("documentURL", "unknown"),
            report.get("source-file") or report.get("sourceFile", "unknown"),
        )
    except Exception:
        pass  # Never fail on malformed/empty reports
    return Response(status_code=204)
