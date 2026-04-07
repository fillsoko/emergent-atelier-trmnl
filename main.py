"""Emergent Atelier entry point.

Usage:
  python main.py [--config-dir configs] [--seed path/to/seed.png]
                 [--host 0.0.0.0] [--port 8000]
                 [--refresh 900] [--history-depth 10]
                 [--data-dir data/canvas]

Or via Docker:
  docker compose up
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import uvicorn

from emergent_atelier.agents.registry import create_agent
from emergent_atelier.api.server import app, init_app, cycle_runner
from emergent_atelier.canvas.coordinator import Coordinator
from emergent_atelier.canvas.state import CanvasStateStore
from emergent_atelier.config.loader import load_all_configs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Emergent Atelier")
    p.add_argument("--config-dir", default="configs", help="Agent config directory")
    p.add_argument("--seed", default=None, help="Seed image path")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--refresh", type=int, default=900, help="Cycle interval in seconds")
    p.add_argument("--history-depth", type=int, default=10)
    p.add_argument("--data-dir", default="data/canvas")
    return p.parse_args()


def _check_required_env() -> None:
    # Restrict file creation permissions to owner-only for all files written by
    # this process (SQLite databases, data files, etc.).
    os.umask(0o077)

    # Core secrets — the engine cannot function without these.
    required = ["CYCLE_SECRET", "TRMNL_STORE_KEY", "VOTE_IP_SALT"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("FATAL: Missing required environment variables: %s", missing)
        sys.exit(1)

    # Proxy secret enforcement — when REQUIRE_PROXY_SECRET=true, CADDY_PROXY_SECRET
    # must also be set, otherwise every request would be rejected with 403.
    if os.getenv("REQUIRE_PROXY_SECRET", "true").lower() == "true":
        if not os.getenv("CADDY_PROXY_SECRET"):
            logger.error(
                "FATAL: REQUIRE_PROXY_SECRET=true but CADDY_PROXY_SECRET is not set. "
                "Generate with: openssl rand -hex 32 and configure in Caddy."
            )
            sys.exit(1)

    # Dashboard auth — strongly recommended in production (SOK-232).
    # Without DASHBOARD_SECRET, /api/status, /api/history, /api/agents, and the
    # dashboard are accessible to anyone who reaches the app (bypassing the proxy
    # secret guard for read endpoints). Warn loudly in production mode.
    if not os.getenv("DASHBOARD_SECRET"):
        if os.getenv("REQUIRE_PROXY_SECRET", "true").lower() == "true":
            logger.warning(
                "DASHBOARD_SECRET is not set. Internal API endpoints (/api/status, "
                "/api/history, /api/agents) and the dashboard are unprotected beyond "
                "the proxy secret. Set DASHBOARD_SECRET in production: "
                "openssl rand -hex 32"
            )

    # Marketplace credentials — only needed for the TRMNL OAuth install flow.
    # The engine can start and serve /image.png without them; the marketplace
    # endpoints will return 503 until these are configured.
    marketplace_vars = ["TRMNL_CLIENT_ID", "TRMNL_CLIENT_SECRET"]
    missing_marketplace = [k for k in marketplace_vars if not os.getenv(k)]
    if missing_marketplace:
        logger.warning(
            "Marketplace credentials not set (%s). "
            "Core image serving is operational; TRMNL OAuth endpoints will return 503 "
            "until these are configured.",
            ", ".join(missing_marketplace),
        )


async def main() -> None:
    _check_required_env()
    args = parse_args()

    # Initialise canvas store
    store = CanvasStateStore(
        seed_path=args.seed,
        history_depth=args.history_depth,
        data_dir=args.data_dir,
    )
    coordinator = Coordinator(store)

    # Load and register agents
    configs = load_all_configs(args.config_dir)
    if not configs:
        logger.warning("No agent configs found in '%s' — system will run with no agents.", args.config_dir)
    for cfg in configs:
        try:
            agent = create_agent(cfg)
            coordinator.register_agent(agent)
            logger.info("Registered agent: %s (%s)", cfg.name, cfg.algorithm)
        except Exception as exc:
            logger.error("Failed to create agent from config '%s': %s", cfg.name, exc)

    # Wire up FastAPI app
    init_app(store, coordinator, refresh_interval_sec=args.refresh)

    # Start cycle runner as background task
    loop = asyncio.get_event_loop()
    loop.create_task(cycle_runner(args.refresh))

    # Start uvicorn — proxy_headers=True so SlowAPI sees real client IPs
    # when running behind Caddy (which proxies from localhost:8001).
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
