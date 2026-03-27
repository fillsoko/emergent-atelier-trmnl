"""TRMNL Third-Party Plugin marketplace endpoints.

Implements the OAuth2 installation flow and screen-generation protocol
required to list Emergent Atelier in the official TRMNL marketplace.

Required environment variables (set in docker-compose.yml or .env):
  TRMNL_CLIENT_ID      — Client ID from trmnl.com/plugins/my/<id>/edit
  TRMNL_CLIENT_SECRET  — Client secret from the same page
  TRMNL_PUBLIC_URL     — Public base URL of this server (no trailing slash)
                         e.g. https://emergent-atelier.example.com

Reference: https://docs.trmnl.com/go/plugin-marketplace
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from urllib.parse import urlparse

from emergent_atelier.api.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------

_CLIENT_ID = os.getenv("TRMNL_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("TRMNL_CLIENT_SECRET", "")
_PUBLIC_URL = os.getenv("TRMNL_PUBLIC_URL", "").rstrip("/")

TRMNL_TOKEN_URL = "https://trmnl.com/oauth/token"

_ALLOWED_REDIRECT_HOSTS = {"trmnl.com", "usetrmnl.com"}

# Token TTL: reject access tokens older than this many days (SOK-159)
TOKEN_TTL_DAYS = 90


def _is_valid_callback(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return bool(parsed.hostname) and any(
            parsed.hostname == h or parsed.hostname.endswith(f".{h}")
            for h in _ALLOWED_REDIRECT_HOSTS
        )
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Simple JSON-file installation store
# ---------------------------------------------------------------------------

_STORE_PATH = Path(os.getenv("TRMNL_STORE_PATH", "/app/data/trmnl_installs.json"))


def _load_store() -> dict[str, Any]:
    if _STORE_PATH.exists():
        try:
            return json.loads(_STORE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_store(data: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# HMAC-SHA256 signature verification
# ---------------------------------------------------------------------------

def validate_marketplace_config() -> None:
    """Raise at startup if TRMNL_CLIENT_SECRET is not configured.

    Called by the server's init_app to fail fast before accepting traffic.
    """
    if not _CLIENT_SECRET:
        raise RuntimeError(
            "TRMNL_CLIENT_SECRET is not set. "
            "This secret is required for webhook signature verification. "
            "Set it in docker-compose.yml or .env before starting the server."
        )


def _verify_trmnl_signature(body: bytes, signature_header: str) -> bool:
    """Verify the HMAC-SHA256 webhook signature sent by TRMNL.

    TRMNL signs each webhook request with CLIENT_SECRET using HMAC-SHA256
    and sends the hex digest in the X-Trmnl-Signature header.
    Raises RuntimeError (→ HTTP 500) if CLIENT_SECRET is not configured,
    rather than silently bypassing verification.
    """
    if not _CLIENT_SECRET:
        raise RuntimeError(
            "TRMNL_CLIENT_SECRET is not configured; cannot verify webhook signature"
        )
    expected = hmac.new(_CLIENT_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Pydantic request models (SOK-148: field length constraints)
# ---------------------------------------------------------------------------

class _UserPayload(BaseModel):
    name: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=255)
    time_zone: str = Field(default="UTC", max_length=100)


class _InstallSuccessPayload(BaseModel):
    plugin_setting_id: str = Field(default="", max_length=255)
    uuid: str = Field(default="", max_length=255)
    user: _UserPayload = Field(default_factory=_UserPayload)


class _UninstallPayload(BaseModel):
    plugin_setting_id: str = Field(default="", max_length=255)
    uuid: str = Field(default="", max_length=255)


# ---------------------------------------------------------------------------
# Install — OAuth2 start
# ---------------------------------------------------------------------------

@router.get("/install", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def install_start(
    request: Request,
    token: str = "",
    installation_callback_url: str = "",
) -> Response:
    """Step 1: TRMNL sends user here to begin plugin installation.

    Exchanges the one-time token for an access_token via TRMNL's OAuth2
    endpoint, then redirects the user back to TRMNL.
    """
    if not token or not installation_callback_url:
        raise HTTPException(status_code=400, detail="Missing token or installation_callback_url")

    if not _is_valid_callback(installation_callback_url):
        logger.warning("install: rejected invalid callback URL: %s", installation_callback_url)
        raise HTTPException(status_code=400, detail="Invalid callback URL")

    if not _CLIENT_ID or not _CLIENT_SECRET:
        logger.warning("TRMNL_CLIENT_ID / TRMNL_CLIENT_SECRET not configured")
        raise HTTPException(status_code=503, detail="Plugin not yet configured with TRMNL credentials")

    # Exchange token for access_token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                TRMNL_TOKEN_URL,
                json={
                    "code": token,
                    "client_id": _CLIENT_ID,
                    "client_secret": _CLIENT_SECRET,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="Token exchange with TRMNL failed") from exc

    access_token = payload.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in TRMNL response")

    # Persist pending install (success webhook will enrich with user data)
    store = _load_store()
    store[access_token] = {
        "access_token": access_token,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_store(store)

    logger.info("Installation started; redirecting to %s", installation_callback_url)
    return RedirectResponse(url=installation_callback_url)


# ---------------------------------------------------------------------------
# Install success webhook
# ---------------------------------------------------------------------------

@router.post("/install/success", status_code=200)
@limiter.limit("20/minute")
async def install_success(
    request: Request,
    x_trmnl_signature: str = Header(default=""),
) -> dict[str, str]:
    """Step 2: TRMNL posts user profile here after install completes."""
    raw_body = await request.body()

    if not _verify_trmnl_signature(raw_body, x_trmnl_signature):
        logger.warning("install/success: HMAC signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid request signature")

    try:
        payload = _InstallSuccessPayload.model_validate_json(raw_body)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid request body")

    # Extract access_token from Authorization header
    auth = request.headers.get("authorization", "")
    access_token = auth.removeprefix("Bearer ").strip()

    # Validate: token must have been legitimately issued by our OAuth2 flow
    store = _load_store()
    if not access_token or access_token not in store or store[access_token].get("status") != "pending":
        logger.warning("install/success: unknown or already-processed token")
        raise HTTPException(status_code=401, detail="Invalid or already-processed installation token")

    store[access_token] = {
        "access_token": access_token,
        "plugin_setting_id": payload.plugin_setting_id,
        "uuid": payload.uuid,
        "user": {
            "name": payload.user.name,
            "email": payload.user.email,
            "timezone": payload.user.time_zone,
        },
        "status": "active",
        # Preserve created_at from pending record; fall back to now if missing
        "created_at": store[access_token].get(
            "created_at", datetime.now(timezone.utc).isoformat()
        ),
    }
    _save_store(store)
    logger.info("Installation confirmed for uuid=%s", payload.uuid)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Manage — plugin management page
# ---------------------------------------------------------------------------

@router.get("/manage", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def manage(request: Request) -> HTMLResponse:
    """Plugin management page shown to installed users."""
    public_url = _PUBLIC_URL or "http://localhost:8000"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Emergent Atelier — Settings</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
    p  {{ color: #555; line-height: 1.6; }}
    .preview {{ border: 1px solid #ddd; border-radius: 8px; overflow: hidden; max-width: 400px; margin: 1.5rem 0; }}
    .preview img {{ width: 100%; display: block; }}
    a  {{ color: #2563eb; }}
  </style>
</head>
<body>
  <h1>Emergent Atelier</h1>
  <p>Multi-agent generative art that quietly evolves on your TRMNL eInk display.
     A new composition is produced every 15 minutes — no two refreshes are ever the same.</p>
  <div class="preview">
    <img src="{public_url}/image.png" alt="Current canvas" />
  </div>
  <p>
    <strong>Live preview above</strong> — the image you see is exactly what your TRMNL device is displaying right now.
  </p>
  <p>
    <a href="https://github.com/fillsoko/emergent-atelier-trmnl" target="_blank">View source on GitHub</a> ·
    <a href="{public_url}/" target="_blank">Open full dashboard</a>
  </p>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Markup — TRMNL polls this every 15 min for fresh HTML content
# ---------------------------------------------------------------------------

@router.post("/markup")
@limiter.limit("20/minute")
async def get_markup(
    request: Request,
    authorization: str = Header(default=""),
    x_trmnl_signature: str = Header(default=""),
) -> JSONResponse:
    """Return current canvas embedded in TRMNL-compatible HTML markup.

    TRMNL renders the returned HTML to a PNG and pushes it to the device.
    We embed the canvas as a base64 PNG inside a full-bleed <img>.
    """
    raw_body = await request.body()

    if not _verify_trmnl_signature(raw_body, x_trmnl_signature):
        logger.warning("markup: HMAC signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid request signature")

    # Validate the caller is an active installed plugin user (SOK-142)
    access_token = authorization.removeprefix("Bearer ").strip()
    store = _load_store()
    record = store.get(access_token, {})
    if not access_token or record.get("status") != "active":
        logger.warning("markup: unauthorized access_token")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Enforce token TTL (SOK-159): reject tokens older than TOKEN_TTL_DAYS
    created_at_str = record.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
            age_days = (datetime.now(timezone.utc) - created_at).days
            if age_days > TOKEN_TTL_DAYS:
                logger.warning(
                    "markup: access_token expired (age=%d days, ttl=%d days)",
                    age_days,
                    TOKEN_TTL_DAYS,
                )
                raise HTTPException(status_code=401, detail="Access token expired")
        except HTTPException:
            raise
        except Exception:
            logger.warning("markup: could not parse created_at, denying request")
            raise HTTPException(status_code=401, detail="Unauthorized")

    from emergent_atelier.api.server import _store  # avoid circular import

    if _store is None:
        raise HTTPException(status_code=503, detail="Canvas store not initialised")

    version = _store.current()
    png_bytes = version.to_png_bytes(dither=False)
    b64 = base64.b64encode(png_bytes).decode()

    markup = f"""<div class="layout layout--col" style="padding:0;margin:0;">
  <img src="data:image/png;base64,{b64}"
       style="width:800px;height:480px;display:block;image-rendering:pixelated;" />
</div>"""

    return JSONResponse(content={"markup": markup})


# ---------------------------------------------------------------------------
# Uninstall webhook
# ---------------------------------------------------------------------------

@router.post("/uninstall", status_code=200)
@limiter.limit("20/minute")
async def uninstall(
    request: Request,
    x_trmnl_signature: str = Header(default=""),
) -> dict[str, str]:
    """TRMNL notifies us when a user uninstalls the plugin."""
    raw_body = await request.body()

    if not _verify_trmnl_signature(raw_body, x_trmnl_signature):
        logger.warning("uninstall: HMAC signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid request signature")

    auth = request.headers.get("authorization", "")
    access_token = auth.removeprefix("Bearer ").strip()

    if not access_token:
        logger.warning("uninstall: missing Authorization header")
        raise HTTPException(status_code=401, detail="Missing authorization token")

    store = _load_store()
    if access_token in store:
        del store[access_token]
        _save_store(store)
        logger.info("User uninstalled; removed access_token from store")
    else:
        logger.warning("uninstall: unknown access_token, ignoring")

    return {"status": "ok"}
