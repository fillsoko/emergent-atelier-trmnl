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

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from emergent_atelier.canvas.coordinator import Coordinator
from emergent_atelier.canvas.state import CanvasStateStore
from emergent_atelier.api.marketplace import router as marketplace_router
from emergent_atelier.api.votes import router as votes_router

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Emergent Atelier", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://emergentatelier.dev",
        "https://www.emergentatelier.dev",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
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
    assert _store is not None
    version = _store.current()
    data = version.to_png_bytes(dither=dither)
    return Response(content=data, media_type="image/png")


@app.get("/plugin.json")
def get_plugin_manifest() -> JSONResponse:
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
def get_status(request: Request) -> dict[str, Any]:
    assert _store is not None and _coordinator is not None
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
def get_history(request: Request, limit: int = Query(10, le=50)) -> list[dict[str, Any]]:
    assert _store is not None
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
def get_agents(request: Request) -> list[dict[str, Any]]:
    assert _coordinator is not None
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
    assert _coordinator is not None
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
async def dashboard() -> HTMLResponse:
    html_path = _templates_dir / "index.html"
    return HTMLResponse(content=html_path.read_text())


# ------------------------------------------------------------------
# Background cycle runner
# ------------------------------------------------------------------

async def cycle_runner(interval_sec: int) -> None:
    """Runs canvas cycles on the configured interval."""
    assert _coordinator is not None
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
