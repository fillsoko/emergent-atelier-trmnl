"""Canvas state store with versioning.

FR-05: Canvas history retained (configurable depth, default 10).
FR-06: State stored as versioned PNG (800x480, 1-bit depth).
FR-07: Each version tagged with cycle number, agents, timestamp, delta.
FR-08: Seed image support; default is blank canvas.
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image


CANVAS_WIDTH = 800
CANVAS_HEIGHT = 480


@dataclass
class CanvasVersion:
    cycle: int
    timestamp: float
    contributing_agents: list[str]
    delta_pct: float          # % pixels changed from previous version
    image: Image.Image

    def to_png_bytes(self, dither: bool = False) -> bytes:
        """Encode canvas to PNG bytes. Optionally apply Floyd-Steinberg dither for grayscale."""
        buf = io.BytesIO()
        if dither:
            img = self.image.convert("L").convert("1", dither=Image.FLOYDSTEINBERG)
        else:
            img = self.image
        img.save(buf, format="PNG")
        return buf.getvalue()


class CanvasStateStore:
    """Thread-safe versioned canvas state store.

    FR-01 through FR-09 implementation.
    """

    def __init__(
        self,
        seed_path: Optional[str] = None,
        history_depth: int = 10,
        data_dir: str = "data/canvas",
    ) -> None:
        self._lock = threading.Lock()
        self._history: list[CanvasVersion] = []
        self._history_depth = history_depth
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._cycle = 0

        # Initialise from seed or blank
        if seed_path and Path(seed_path).exists():
            seed = Image.open(seed_path).convert("1")
            seed = seed.resize((CANVAS_WIDTH, CANVAS_HEIGHT))
        else:
            seed = Image.new("1", (CANVAS_WIDTH, CANVAS_HEIGHT), 0)

        initial = CanvasVersion(
            cycle=0,
            timestamp=time.time(),
            contributing_agents=[],
            delta_pct=0.0,
            image=seed,
        )
        self._history.append(initial)

    # ------------------------------------------------------------------
    # Public read API (safe for agents to call concurrently)
    # ------------------------------------------------------------------

    def current(self) -> CanvasVersion:
        with self._lock:
            return self._history[-1]

    def history(self) -> list[CanvasVersion]:
        with self._lock:
            return list(self._history)

    def current_cycle(self) -> int:
        with self._lock:
            return self._cycle

    # ------------------------------------------------------------------
    # Write API (coordinator-only — agents write to staging buffers)
    # ------------------------------------------------------------------

    def commit(self, new_image: Image.Image, contributing_agents: list[str]) -> CanvasVersion:
        """Commit a new canvas state. Returns the committed version."""
        with self._lock:
            prev = self._history[-1].image
            delta_pct = self._compute_delta(prev, new_image)
            self._cycle += 1
            version = CanvasVersion(
                cycle=self._cycle,
                timestamp=time.time(),
                contributing_agents=list(contributing_agents),
                delta_pct=delta_pct,
                image=new_image.copy(),
            )
            self._history.append(version)
            if len(self._history) > self._history_depth:
                self._history.pop(0)
            # Persist to disk
            self._persist(version)
            return version

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_delta(prev: Image.Image, curr: Image.Image) -> float:
        import numpy as np
        a = np.array(prev, dtype=bool)
        b = np.array(curr, dtype=bool)
        changed = int((a != b).sum())
        total = a.size
        return round(changed / total * 100, 4) if total else 0.0

    def _persist(self, version: CanvasVersion) -> None:
        path = self._data_dir / f"cycle_{version.cycle:06d}.png"
        version.image.save(str(path), format="PNG")
