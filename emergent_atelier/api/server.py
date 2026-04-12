"""FastAPI server — HTTP image endpoint + dashboard API.

FR-10: HTTP endpoint returning current canvas PNG.
FR-11: Optional dithering for TRMNL X (grayscale).
FR-12: TRMNL plugin manifest endpoint.
FR-13: Configurable refresh cycle.
FR-17/18: Dashboard data endpoints.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import time
from hmac import compare_digest
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from emergent_atelier.canvas.coordinator import Coordinator
from emergent_atelier.canvas.state import CanvasStateStore
from emergent_atelier.api.csp import router as csp_router
from emergent_atelier.api.limiter import limiter
from emergent_atelier.api.marketplace import router as marketplace_router, validate_marketplace_config
from emergent_atelier.api.votes import router as votes_router

logger = logging.getLogger(__name__)

_DEFAULT_CORS_ORIGINS = "https://emergentatelier.dev,https://www.emergentatelier.dev"
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if o.strip()
]
if "*" in _cors_origins:
    raise RuntimeError(
        "CORS_ORIGINS must not include wildcard '*' — this would allow any origin "
        "to call the API. Set explicit allowed origins instead."
    )
if any(o in ("http://localhost", "http://127.0.0.1") for o in _cors_origins):
    logger.warning(
        "CORS_ORIGINS includes a localhost origin (%s). "
        "Ensure this is intentional and not a production misconfiguration.",
        [o for o in _cors_origins if o.startswith("http://localhost") or o.startswith("http://127.0.0.1")],
    )

# ---------------------------------------------------------------------------
# Proxy-secret guard (SOK-202)
#
# When REQUIRE_PROXY_SECRET=true, every request must carry the header
# X-Proxy-Secret matching CADDY_PROXY_SECRET.  This ensures the app only
# serves traffic that arrived through the Caddy reverse proxy.
#
# Caddy config snippet to inject the header:
#   header_up X-Proxy-Secret {$CADDY_PROXY_SECRET}
# ---------------------------------------------------------------------------

_CADDY_PROXY_SECRET = os.getenv("CADDY_PROXY_SECRET", "")
_REQUIRE_PROXY_SECRET = os.getenv("REQUIRE_PROXY_SECRET", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Dashboard auth (SOK-221, SOK-288)
#
# DASHBOARD_SECRET is required. The dashboard and internal read API endpoints
# (GET /api/status, GET /api/history, GET /api/agents) require HTTP Basic Auth.
# Any username is accepted; the password must equal DASHBOARD_SECRET.
#
# Example:
#   DASHBOARD_SECRET=$(openssl rand -hex 32)
# ---------------------------------------------------------------------------

_DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")
if not _DASHBOARD_SECRET:
    raise RuntimeError(
        "DASHBOARD_SECRET is required but not set. "
        "Generate one with: openssl rand -hex 32"
    )


def _require_dashboard_auth(request: Request) -> None:
    """Raise 401 if the request lacks valid Basic Auth matching DASHBOARD_SECRET."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
            _username, _, password = decoded.partition(":")
            if compare_digest(password, _DASHBOARD_SECRET):
                return
        except Exception:
            pass
    raise HTTPException(
        status_code=401,
        detail="Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="Emergent Atelier"'},
    )


class ProxySecretMiddleware(BaseHTTPMiddleware):
    # Paths that bypass the proxy-secret check because they receive direct
    # browser-initiated requests (not routed through Caddy).
    _PROXY_EXEMPT_PATHS: frozenset[str] = frozenset({"/api/csp-report"})

    async def dispatch(self, request: Request, call_next):
        if _REQUIRE_PROXY_SECRET and request.url.path not in self._PROXY_EXEMPT_PATHS:
            incoming = request.headers.get("x-proxy-secret", "")
            if not _CADDY_PROXY_SECRET or not compare_digest(incoming, _CADDY_PROXY_SECRET):
                return Response(status_code=403, content="Forbidden")
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "script-src 'self'"
        )
        return response


app = FastAPI(title="Emergent Atelier", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ProxySecretMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(csp_router)
app.include_router(marketplace_router)
app.include_router(votes_router)

# These are set by main.py before uvicorn starts
_store: CanvasStateStore | None = None
_coordinator: Coordinator | None = None
_refresh_interval_sec: int = 900  # 15 min default


def init_app(
    store: CanvasStateStore,
    coordinator: Coordinator,
    refresh_interval_sec: int = 900,
) -> None:
    global _store, _coordinator, _refresh_interval_sec
    validate_marketplace_config()
    _store = store
    _coordinator = coordinator
    _refresh_interval_sec = refresh_interval_sec


# ------------------------------------------------------------------
# TRMNL plugin endpoint
# ------------------------------------------------------------------

@app.get("/image.png", response_class=Response)
@limiter.limit("30/minute")
def get_canvas_png(request: Request, dither: bool = Query(False, description="Apply Floyd-Steinberg dithering")) -> Response:
    """Current canvas as 1-bit PNG. Consumed by TRMNL plugin."""
    if _store is None:
        raise HTTPException(status_code=503, detail="Service not available")
    version = _store.current()
    data = version.to_png_bytes(dither=dither)
    return Response(content=data, media_type="image/png")


@app.get("/plugin.json")
@limiter.limit("30/minute")
def get_plugin_manifest(request: Request) -> JSONResponse:
    """TRMNL-compatible plugin manifest."""
    manifest_path = Path(__file__).parent.parent.parent / "trmnl" / "plugin_manifest.json"
    with manifest_path.open() as f:
        manifest = json.load(f)
    return JSONResponse(content=manifest)


# ------------------------------------------------------------------
# Status / API
# ------------------------------------------------------------------

@app.get("/api/status")
@limiter.limit("30/minute")
def get_status(request: Request, _auth: None = Depends(_require_dashboard_auth)) -> dict[str, Any]:
    if _store is None or _coordinator is None:
        raise HTTPException(status_code=503, detail="Service not available")
    current = _store.current()
    agents = _coordinator.registered_agents()
    return {
        "cycle": current.cycle,
        "timestamp": current.timestamp,
        "refresh_interval_sec": _refresh_interval_sec,
        "agents": [
            {
                "name": a.config.name,
                "role": a.config.role,
                "algorithm": a.config.algorithm,
                "enabled": a.config.enabled,
                "influence_radius": a.config.influence_radius,
                "pixel_budget": a.config.pixel_budget,
            }
            for a in agents
        ],
    }


@app.get("/api/history")
@limiter.limit("20/minute")
def get_history(request: Request, limit: int = Query(10, le=50), _auth: None = Depends(_require_dashboard_auth)) -> list[dict[str, Any]]:
    if _store is None:
        raise HTTPException(status_code=503, detail="Service not available")
    versions = _store.history()[-limit:]
    result = []
    for v in reversed(versions):
        thumb = _version_thumbnail_b64(v)
        result.append({
            "cycle": v.cycle,
            "timestamp": v.timestamp,
            "contributing_agents": v.contributing_agents,
            "delta_pct": v.delta_pct,
            "thumbnail_b64": thumb,
        })
    return result


@app.get("/api/agents")
@limiter.limit("20/minute")
def get_agents(request: Request, _auth: None = Depends(_require_dashboard_auth)) -> list[dict[str, Any]]:
    if _coordinator is None:
        raise HTTPException(status_code=503, detail="Service not available")
    return [
        {
            "name": a.config.name,
            "role": a.config.role,
            "algorithm": a.config.algorithm,
            "enabled": a.config.enabled,
        }
        for a in _coordinator.registered_agents()
    ]


_CYCLE_SECRET = os.getenv("CYCLE_SECRET", "")


@app.post("/api/cycle")
@limiter.limit("5/minute")
async def trigger_cycle(request: Request, authorization: str = Header(default="")) -> dict[str, str]:
    """Manually trigger a canvas evolution cycle. Requires Authorization: Bearer <CYCLE_SECRET>. CYCLE_SECRET must be set."""
    if not _CYCLE_SECRET:
        raise HTTPException(status_code=503, detail="Cycle endpoint not configured")
    token = authorization.removeprefix("Bearer ").strip()
    if not compare_digest(token, _CYCLE_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if _coordinator is None:
        raise HTTPException(status_code=503, detail="Service not available")
    asyncio.create_task(_coordinator.run_cycle())
    return {"status": "cycle_triggered"}


# ------------------------------------------------------------------
# Dashboard HTML
# ------------------------------------------------------------------

_templates_dir = Path(__file__).parent.parent / "dashboard" / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

_static_dir = Path(__file__).parent.parent / "dashboard" / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def dashboard(request: Request, _auth: None = Depends(_require_dashboard_auth)) -> HTMLResponse:
    html_path = _templates_dir / "index.html"
    return HTMLResponse(content=html_path.read_text())


# ------------------------------------------------------------------
# Background cycle runner
# ------------------------------------------------------------------

async def cycle_runner(interval_sec: int) -> None:
    """Runs canvas cycles on the configured interval."""
    if _coordinator is None:
        raise RuntimeError("cycle_runner called before init_app")
    while True:
        try:
            await _coordinator.run_cycle()
        except Exception:
            logger.exception("Cycle runner error")
        await asyncio.sleep(interval_sec)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _version_thumbnail_b64(version: Any) -> str:
    thumb = version.image.convert("L").resize((160, 96))
    buf = io.BytesIO()
    thumb.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
