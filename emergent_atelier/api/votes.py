"""Roadmap voting API — IP-throttled upvote/downvote for public roadmap items.

POST /api/votes/{issue_identifier}  body: {"action": "up" | "down"}
GET  /api/votes/{issue_identifier}  returns: {"up": int, "down": int, "userVote": "up"|"down"|null}

Storage: SQLite at data/votes.db (persists via Docker volume).
Privacy:  IPs are hashed with SHA-256 before storage.
Throttle: 1 vote per IP per issue (changeable); max 20 votes per IP per hour.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, HTTPException, Path as PathParam, Request

from emergent_atelier.api.limiter import limiter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/votes", tags=["votes"])

_DB_PATH = Path("data/votes.db")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Set restrictive umask so the DB file is created 0o600 (not world-readable).
    _old_umask = os.umask(0o077)
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10.0, check_same_thread=False)
    finally:
        os.umask(_old_umask)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS votes (
            issue_identifier TEXT NOT NULL,
            ip_hash          TEXT NOT NULL,
            action           TEXT NOT NULL CHECK(action IN ('up','down')),
            voted_at         INTEGER NOT NULL,
            PRIMARY KEY (issue_identifier, ip_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_votes_ip_hash ON votes(ip_hash);
        CREATE INDEX IF NOT EXISTS idx_votes_voted_at ON votes(voted_at);
    """)
    conn.commit()


# Initialise schema on module import so it's ready before first request.
try:
    with _get_db() as _init_conn:
        _ensure_schema(_init_conn)
except Exception as _e:
    logger.warning("Could not pre-init votes DB: %s", _e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VOTE_IP_SALT = os.environ.get("VOTE_IP_SALT", "")


def _hash_ip(ip: str) -> str:
    return hashlib.sha256((_VOTE_IP_SALT + ip).encode()).hexdigest()


def _client_ip(request: Request) -> str:
    # Caddy is the only ingress; request.client.host is always the real client IP.
    # We do NOT trust X-Forwarded-For to prevent rate-limit bypass via header spoofing.
    return request.client.host if request.client else "unknown"


def _rate_limit_ok(conn: sqlite3.Connection, ip_hash: str) -> bool:
    """Return True if this IP hasn't exceeded 20 votes in the last hour."""
    one_hour_ago = int(time.time()) - 3600
    row = conn.execute(
        "SELECT COUNT(*) FROM votes WHERE ip_hash = ? AND voted_at >= ?",
        (ip_hash, one_hour_ago),
    ).fetchone()
    return row[0] < 20


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VoteRequest(BaseModel):
    action: Literal["up", "down"]


class VoteResponse(BaseModel):
    up: int
    down: int
    userVote: Optional[Literal["up", "down"]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_IssueId = Annotated[str, PathParam(max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")]


@router.post("/{issue_identifier}", response_model=VoteResponse)
@limiter.limit("20/minute")
def cast_vote(issue_identifier: _IssueId, body: VoteRequest, request: Request) -> VoteResponse:
    """Cast or change a vote on a roadmap item."""
    ip = _client_ip(request)
    ip_hash = _hash_ip(ip)
    now = int(time.time())

    conn = _get_db()
    try:
        _ensure_schema(conn)

        # Rate-limit check (count new votes; updating an existing row doesn't count anew)
        existing = conn.execute(
            "SELECT action FROM votes WHERE issue_identifier = ? AND ip_hash = ?",
            (issue_identifier, ip_hash),
        ).fetchone()

        if existing is None:
            # New vote — check hourly rate limit
            if not _rate_limit_ok(conn, ip_hash):
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded: max 20 votes per hour.",
                )
            conn.execute(
                "INSERT INTO votes (issue_identifier, ip_hash, action, voted_at) VALUES (?, ?, ?, ?)",
                (issue_identifier, ip_hash, body.action, now),
            )
        else:
            # Update existing vote (no new rate-limit charge for changing vote)
            conn.execute(
                "UPDATE votes SET action = ?, voted_at = ? WHERE issue_identifier = ? AND ip_hash = ?",
                (body.action, now, issue_identifier, ip_hash),
            )

        conn.commit()
        return _fetch_counts(conn, issue_identifier, ip_hash)
    finally:
        conn.close()


@router.get("/{issue_identifier}", response_model=VoteResponse)
@limiter.limit("30/minute")
def get_votes(issue_identifier: _IssueId, request: Request) -> VoteResponse:
    """Get vote counts and the caller's own vote for a roadmap item."""
    ip = _client_ip(request)
    ip_hash = _hash_ip(ip)

    conn = _get_db()
    try:
        _ensure_schema(conn)
        return _fetch_counts(conn, issue_identifier, ip_hash)
    finally:
        conn.close()


def _fetch_counts(
    conn: sqlite3.Connection, issue_identifier: str, ip_hash: str
) -> VoteResponse:
    rows = conn.execute(
        "SELECT action, COUNT(*) as cnt FROM votes WHERE issue_identifier = ? GROUP BY action",
        (issue_identifier,),
    ).fetchall()
    counts: dict[str, int] = {"up": 0, "down": 0}
    for row in rows:
        counts[row["action"]] = row["cnt"]

    user_row = conn.execute(
        "SELECT action FROM votes WHERE issue_identifier = ? AND ip_hash = ?",
        (issue_identifier, ip_hash),
    ).fetchone()
    user_vote = user_row["action"] if user_row else None

    return VoteResponse(up=counts["up"], down=counts["down"], userVote=user_vote)
